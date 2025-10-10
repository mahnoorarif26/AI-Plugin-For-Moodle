import os
import re
import json
import uuid
from datetime import datetime
from typing import Dict, List, Any

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS

# === FIREBASE IMPORTS ===
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin.firestore import Query

# === UTILS IMPORTS ===
# IMPORTANT: Assumes these utilities exist and are correctly implemented in 'utils' folder.
from utils import (
    extract_pdf_text,
    split_into_chunks,
    build_user_prompt,
    SYSTEM_PROMPT,
    call_groq_json,
)
from utils.groq_utils import (
    _allocate_counts,
    filter_and_trim_questions,
    extract_subtopics_llm,
    generate_quiz_from_subtopics_llm,
)

# ===============================
# LOAD ENVIRONMENT VARIABLES
# ===============================
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "./serviceAccountKey.json")

if not GROQ_API_KEY:
    raise RuntimeError("❌ GROQ_API_KEY is missing in environment (.env).")

# ===============================
# FIREBASE INITIALIZATION
# ===============================
db = None
try:
    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase App Initialized successfully.")
except Exception as e:
    print(f"⚠️ WARNING: Firebase failed to initialize. Error: {e}")
    db = None

# ===============================
# GLOBAL MEMORY STORE & DUMMY USERS
# ===============================
# Stores the raw text and metadata of uploaded files, keyed by a unique upload_id
# Format: {upload_id: {'text': raw_text, 'file_name': file_name}}
_SUBTOPIC_UPLOADS: Dict[str, Dict[str, str]] = {}

# Dummy user list for simple login simulation (bsdsf22a001 to bsdsf22a050)
_DUMMY_USERS = {
    **{f"bsdsf22a{i:03d}@pucit.edu.pk": {"name": f"Student {i:03d}", "role": "student"} for i in range(1, 51)},
    "abdullah@pucit.edu.pk": {"name": "Abdullah Teacher", "role": "teacher"},
}

# ===============================
# QUIZ GENERATION HELPERS
# ===============================

def enforce_flag_targets(questions: List[Dict[str, Any]], scenario_target: int, code_target: int) -> List[Dict[str, Any]]:
    """
    Ensures that the number of scenario-based and code snippet questions matches the requested targets.
    If there are fewer than requested, it sets the flags on additional questions.
    """
    scenario_count = sum(1 for q in questions if q.get("scenario_based", False))
    code_count = sum(1 for q in questions if q.get("code_snippet", False))

    # Enforce scenario_based flag
    if scenario_count < scenario_target:
        for q in questions:
            if not q.get("scenario_based", False):
                q["scenario_based"] = True
                scenario_count += 1
                if scenario_count >= scenario_target:
                    break

    # Enforce code_snippet flag
    if code_count < code_target:
        for q in questions:
            if not q.get("code_snippet", False):
                q["code_snippet"] = True
                code_count += 1
                if code_count >= code_target:
                    break

    return questions

# ===============================
# FIREBASE FUNCTIONS
# ===============================
def save_quiz_to_firestore(quiz_data: dict):
    """Save generated quiz to Firestore."""
    if db is None:
        print("⚠️ Firestore client not available. Skipping save.")
        return None

    if "questions" in quiz_data:
        # Assign a unique ID to each question if it doesn't have one
        for q in quiz_data["questions"]:
            if "id" not in q:
                q["id"] = str(uuid.uuid4())
            # Ensure question text/prompt is set for display
            if not q.get('prompt') and q.get('question_text'):
                q['prompt'] = q['question_text']

    try:
        # Use a transaction to ensure unique ID is handled (though .add() is usually fine)
        # Note: doc_ref is a tuple (WriteTime, DocumentReference)
        doc_ref_tuple = db.collection('AIquizzes').add({
            **quiz_data,
            "created_at": datetime.now(),
        })
        return doc_ref_tuple[1].id
    except Exception as e:
        print(f"❌ Error saving quiz to Firestore: {e}")
        return None


def get_quiz_by_id(quiz_id: str):
    """Fetch quiz by ID."""
    if db is None:
        return None
    try:
        doc_ref = db.collection('AIquizzes').document(quiz_id)
        doc = doc_ref.get()
        if doc.exists:
            return {"id": doc.id, **doc.to_dict()}
        return None
    except Exception as e:
        print(f"❌ Error fetching quiz {quiz_id}: {e}")
        return None


def save_submission_to_firestore(quiz_id: str, student_data: dict):
    """Save student submission to Firestore."""
    if db is None:
        print("⚠️ Firestore client not available. Skipping save.")
        return None
    try:
        submission_data = {
            "quiz_id": quiz_id,
            "student_email": student_data.get("email", "anonymous@pucit.edu.pk"),
            "student_name": student_data.get("name", "Anonymous"),
            "answers": student_data.get("answers", {}),
            "score": student_data.get("score", 0),
            "total_questions": student_data.get("total_questions", 0),
            "submitted_at": datetime.now(),
        }

        # Note: doc_ref is a tuple (WriteTime, DocumentReference)
        doc_ref_tuple = db.collection('AIquizzes').document(quiz_id).collection('submissions').add(submission_data)
        return doc_ref_tuple[1].id
    except Exception as e:
        print(f"❌ Error saving submission for quiz {quiz_id}: {e}")
        return None

def get_submitted_quiz_ids(student_email: str) -> List[str]:
    """Fetch IDs of quizzes already submitted by a student."""
    if db is None:
        return []
    try:
        submitted_ids = set()
        
        # 1. Fetch all quiz references
        # In a real app, optimize this by using a top-level 'submissions' collection
        quiz_refs = db.collection('AIquizzes').select([]).stream()
        
        # 2. For each quiz, check for the student's submission
        for quiz_doc in quiz_refs:
            submission_query = db.collection('AIquizzes').document(quiz_doc.id).collection('submissions') \
                .where('student_email', '==', student_email).limit(1)
            
            if len(list(submission_query.stream())) > 0:
                submitted_ids.add(quiz_doc.id)
                
        return list(submitted_ids)
        
    except Exception as e:
        print(f"❌ Error fetching submitted quiz IDs for {student_email}: {e}")
        return []

# ===============================
# FLASK APP SETUP
# ===============================
app = Flask(__name__)
# !! CRITICAL: Set a secret key for session management !!
app.secret_key = os.getenv("FLASK_SECRET_KEY", "a_very_secret_dev_key_that_should_be_changed_12345")
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ===============================
# LOGIN/LOGOUT ROUTES
# ===============================
@app.route('/', methods=['GET', 'POST'])
def login():
    """Simple login page."""
    if request.method == 'POST':
        user_email = request.form.get('email', '').lower()
        
        user = _DUMMY_USERS.get(user_email)
        
        if user:
            session['logged_in'] = True
            session['email'] = user_email
            session['role'] = user['role']
            session['name'] = user['name']
            
            if user['role'] == 'teacher':
                return redirect(url_for('teacher_index'))
            else:
                return redirect(url_for('student_index'))
        else:
            # We don't use flash here, we pass the error directly to template
            return render_template('login.html', error="Invalid email. Try one of the dummy users.")
    
    # If already logged in, redirect to respective dashboard
    if session.get('logged_in'):
        if session.get('role') == 'teacher':
            return redirect(url_for('teacher_index'))
        else:
            return redirect(url_for('student_index'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('email', None)
    session.pop('role', None)
    session.pop('name', None)
    return redirect(url_for('login'))

# ===============================
# STUDENT ROUTES
# ===============================
@app.route('/student')
def student_index():
    """List all available quizzes for students, filtering submitted ones."""
    if not session.get('logged_in') or session.get('role') != 'student':
        return redirect(url_for('login'))
        
    student_email = session.get('email')

    if db is None:
        return render_template('student_index.html', quizzes=[], error="Firestore connection failed.", student_name=session.get('name'))
    try:
        # 1. Get IDs of quizzes the student has submitted (for quiz disappearance)
        submitted_quiz_ids = get_submitted_quiz_ids(student_email)
        
        # 2. Fetch all quizzes and filter
        quizzes = []
        docs = db.collection('AIquizzes').order_by("created_at", direction=Query.DESCENDING).stream()
        for doc in docs:
            # Quiz disappears if student has submitted it
            if doc.id in submitted_quiz_ids:
                continue 
            
            data = doc.to_dict()
            title = data.get("metadata", {}).get("source_file", "AI Generated Quiz")
            q_count = len(data.get("questions", []))
            
            if not title or title == "AI Generated Quiz":
                created_date = data.get('created_at')
                date_str = created_date.strftime('%Y-%m-%d %H:%M') if isinstance(created_date, datetime) else 'Unknown Date'
                title = f"Quiz ({q_count} Q) from {date_str}"
            
            quizzes.append({
                "id": doc.id,
                "title": title,
                "questions_count": q_count,
                "created_at": data.get("created_at", datetime.now()),
            })
            
        return render_template('student_index.html', quizzes=quizzes, error=None, student_name=session.get('name'))
    except Exception as e:
        print(f"❌ Error fetching student quiz list: {e}")
        return render_template('student_index.html', quizzes=[], error=f"Failed to load quizzes: {e}", student_name=session.get('name'))


@app.route('/student/quiz/<quiz_id>', methods=['GET'])
def student_quiz(quiz_id):
    """Display quiz for student with a timer."""
    if not session.get('logged_in') or session.get('role') != 'student':
        return redirect(url_for('login'))
        
    # Check submission status before displaying quiz
    submitted_ids = get_submitted_quiz_ids(session.get('email'))
    if quiz_id in submitted_ids:
        # Redirect if already submitted (real-time check)
        return redirect(url_for('student_index'))

    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return ("Quiz not found", 404)

    questions_for_student = [{
        'id': q.get('id'),
        'type': q.get('type'),
        # Prioritize 'prompt' but fall back to 'question_text'
        'prompt': q.get('prompt') or q.get('question_text'),
        # Only include options for mcq/true_false. Filter out correct_answer.
        'options': q.get('options') if q.get('type') in ['mcq', 'true_false'] else None,
        'difficulty': q.get('difficulty'),
    } for q in quiz_data.get('questions', [])]

    title = quiz_data.get("metadata", {}).get("source_file", f"Quiz #{quiz_id}")
    return render_template('student_quiz.html', 
        quiz_id=quiz_id, 
        title=title, 
        questions=questions_for_student,
        student_email=session.get('email'),
        student_name=session.get('name')
    )


@app.route('/student/submit', methods=['POST'])
def submit_quiz():
    """Handle student quiz submission."""
    if not session.get('logged_in') or session.get('role') != 'student':
        return jsonify({"error": "Unauthorized"}), 401
        
    form_data = request.form
    quiz_id = form_data.get('quiz_id')
    student_email = session.get('email')
    student_name = session.get('name')

    if not quiz_id:
        return jsonify({"error": "Missing quiz ID"}), 400

    correct_quiz_data = get_quiz_by_id(quiz_id)
    if not correct_quiz_data:
        return jsonify({"error": "Quiz not found"}), 404

    # Submission logic: calculate score for auto-graded Qs
    score = 0
    total_questions = len(correct_quiz_data.get('questions', []))
    student_answers = {}

    for q in correct_quiz_data.get('questions', []):
        q_id = q.get('id')
        if not q_id:
            continue
        correct_answer = q.get('correct_answer')
        student_response = form_data.get(q_id, '').strip()
        
        # Store all answers for submission
        student_answers[q_id] = student_response

        if q.get('type') in ['mcq', 'true_false'] and correct_answer is not None:
            # For auto-graded questions, perform case-insensitive comparison
            if str(student_response).lower() == str(correct_answer).lower():
                score += 1

    submission_data = {
        "email": student_email,
        "name": student_name,
        "answers": student_answers,
        "score": score,
        "total_questions": total_questions,
    }
    submission_id = save_submission_to_firestore(quiz_id, submission_data)

    # Redirect to a confirmation page after submission
    return redirect(url_for('submission_confirmation', quiz_id=quiz_id, score=score, total=total_questions, submission_id=submission_id))

@app.route('/student/confirmation/<quiz_id>', methods=['GET'])
def submission_confirmation(quiz_id):
    """Display submission confirmation and score."""
    if not session.get('logged_in') or session.get('role') != 'student':
        return redirect(url_for('login'))
        
    score = request.args.get('score', 'N/A')
    total = request.args.get('total', 'N/A')
    submission_id = request.args.get('submission_id', 'N/A')
    
    quiz_data = get_quiz_by_id(quiz_id)
    quiz_title = quiz_data.get("metadata", {}).get("source_file", f"Submitted Quiz") if quiz_data else "Submitted Quiz"

    return render_template(
        'submission_confirmation.html', 
        quiz_title=quiz_title, 
        score=score, 
        total=total, 
        submission_id=submission_id,
        student_name=session.get('name')
    )

# ===============================
# TEACHER ROUTES
# ===============================
@app.route('/teacher')
def teacher_index():
    """Teacher Dashboard: List of Created Quizzes."""
    if not session.get('logged_in') or session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    if db is None:
        return render_template('teacher_index.html', quizzes=[], error="Firestore connection failed.", teacher_name=session.get('name'))
    try:
        quizzes = []
        docs = db.collection('AIquizzes').order_by("created_at", direction=Query.DESCENDING).stream()
        for doc in docs:
            data = doc.to_dict()
            title = data.get("metadata", {}).get("source_file", "AI Generated Quiz")
            q_count = len(data.get("questions", []))
            created_date = data.get('created_at')
            
            if not title or title == "AI Generated Quiz":
                date_str = created_date.strftime('%Y-%m-%d %H:%M') if isinstance(created_date, datetime) else 'Unknown Date'
                title = f"Quiz ({q_count} Q) from {date_str}"

            quizzes.append({
                "id": doc.id,
                "title": title,
                "questions_count": q_count,
                "created_at": created_date,
            })
        
        return render_template('teacher_index.html', quizzes=quizzes, error=None, teacher_name=session.get('name'))
    except Exception as e:
        print(f"❌ Error fetching quiz list for teacher: {e}")
        return render_template('teacher_index.html', quizzes=[], error=f"Failed to load quizzes: {e}", teacher_name=session.get('name'))


@app.route('/teacher/generate')
def teacher_generate():
    """Quiz generation page (uses index.html content)."""
    if not session.get('logged_in') or session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    return render_template('index.html', teacher_name=session.get('name'))


@app.route('/teacher/submissions/<quiz_id>', methods=['GET'])
def teacher_submissions(quiz_id):
    """View student submissions for a specific quiz (The Solved Quiz Fetch)."""
    if not session.get('logged_in') or session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    if db is None:
        return ("Firestore connection failed.", 500)

    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return ("Quiz not found.", 404)

    # Create a map for quick question lookup
    questions_map = {q.get('id'): q for q in quiz_data.get('questions', []) if q.get('id')}
    quiz_title = quiz_data.get("metadata", {}).get("source_file", f"Quiz #{quiz_id}")

    try:
        submissions_ref = db.collection('AIquizzes').document(quiz_id).collection('submissions')
        # Fetch submissions
        docs = submissions_ref.order_by("submitted_at", direction=Query.DESCENDING).stream()

        submissions_list = []
        for doc in docs:
            submission = doc.to_dict()
            processed_answers = {}
            for q_id, student_response in submission.get('answers', {}).items():
                q_data = questions_map.get(q_id)
                if not q_data:
                    continue
                correct_answer = q_data.get('correct_answer', 'N/A')
                
                # Check correctness only for auto-graded types (mcq, true_false)
                is_correct = None
                if q_data.get('type') in ['mcq', 'true_false']:
                    is_correct = str(student_response).strip().lower() == str(correct_answer).strip().lower()
                
                processed_answers[q_id] = {
                    'prompt': q_data.get('prompt') or q_data.get('question_text'),
                    'type': q_data.get('type'),
                    'response': student_response,
                    'correct_answer': correct_answer,
                    'is_correct': is_correct # True/False/None (for manual)
                }

            submissions_list.append({
                "id": doc.id,
                "student_name": submission.get("student_name", "Anonymous"),
                "student_email": submission.get("student_email", "N/A"),
                "score": submission.get("score", 0),
                "total_questions": submission.get("total_questions", len(questions_map)),
                "submitted_at_str": submission.get('submitted_at').strftime('%Y-%m-%d %H:%M') if submission.get('submitted_at') and isinstance(submission.get('submitted_at'), datetime) else 'Unknown Date',
                "answers": processed_answers,
            })

        return render_template('teacher_submissions.html', quiz_title=quiz_title, quiz_id=quiz_id, submissions=submissions_list)

    except Exception as e:
        print(f"❌ Error fetching submissions: {e}")
        return ("Failed to load submissions.", 500)


# ===============================
# API ROUTES (Restricted to Teacher)
# ===============================
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


# ---- Re-introduced: /api/quiz/from-pdf route (was missing and caused 404)
@app.route("/api/quiz/from-pdf", methods=["POST"])
def quiz_from_pdf():
    """
    Generate quiz from uploaded PDF. Returns the quiz JSON and also saves to Firestore.
    """
    if not session.get('logged_in') or session.get('role') != 'teacher':
        # Allow only teacher to call this API (consistent with other APIs)
        return jsonify({"error": "Unauthorized"}), 401

    try:
        # ---- file (PDF) ----
        if "file" not in request.files:
            return ("Missing file (multipart field 'file')", 400)

        file = request.files["file"]
        if not file or file.filename == "":
            return ("Empty file", 400)

        if not (file.mimetype == "application/pdf" or file.filename.lower().endswith(".pdf")):
            return ("Only PDF accepted (.pdf)", 400)

        # ---- options (JSON) ----
        options_raw = request.form.get("options")
        if not options_raw:
            # Some clients may send 'options' as a file part
            opt_file = request.files.get("options")
            if opt_file:
                try:
                    options_raw = opt_file.read().decode("utf-8", "ignore")
                except Exception:
                    options_raw = None

        if not options_raw:
            return ("Missing options (multipart field 'options')", 400)

        try:
            options = json.loads(options_raw)
        except Exception:
            return ("Invalid JSON in 'options'", 400)

        num_questions = options.get("num_questions", 8)
        qtypes = options.get("question_types", ["mcq", "short"])
        diff = options.get("difficulty", {"mode": "auto"})
        diff_mode = diff.get("mode", "auto")

        # ---- PDF -> text ----
        text = extract_pdf_text(file)
        if not text or not text.strip():
            return ("Could not extract text from PDF", 400)

        chunks = split_into_chunks(text)

        # ---- difficulty mix (default custom mix if "custom" mode is selected) ----
        mix_counts = {}
        if diff_mode == "custom":
            mix_counts = _allocate_counts(
                total=num_questions if num_questions is not None else 0,
                easy=int(diff.get("easy", 30)),
                med=int(diff.get("medium", 50)),
                hard=int(diff.get("hard", 20)),
            )

        # ---- LLM call ----
        user_prompt = build_user_prompt(
            pdf_chunks=chunks,
            num_questions=num_questions,
            qtypes=qtypes,
            difficulty_mode=diff_mode,
            mix_counts=mix_counts,
        )

        llm_json = call_groq_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=GROQ_API_KEY,
        )

        questions = llm_json.get("questions", [])
        questions = filter_and_trim_questions(
            questions=questions,
            allowed_types=qtypes,
            difficulty_mode=diff_mode,
            mix_counts=mix_counts,
            num_questions=num_questions,
        )

        # Safely try to extract the original file name for the title
        source_file = file.filename if file and file.filename else "PDF Upload"

        result = {
            "questions": questions,
            "metadata": {
                "model": "llama-3.3-70b-versatile",
                "difficulty_mode": diff_mode,
                "counts_requested": {
                    "total": num_questions,
                    **({
                        "easy":   mix_counts.get("easy"),
                        "medium": mix_counts.get("medium"),
                        "hard":   mix_counts.get("hard"),
                    } if diff_mode == "custom" else {})
                },
                "source_note": llm_json.get("source_note", ""),
                "source_file": source_file, # Add source file to metadata for listing
            }
        }

        # Save to Firestore if available
        firebase_id = save_quiz_to_firestore(result)
        if firebase_id:
            result["metadata"]["firebase_quiz_id"] = firebase_id

        return jsonify(result), 200

    except json.JSONDecodeError:
        return ("Model returned invalid JSON. Try reducing PDF length or rephrasing.", 502)
    except Exception as e:
        return (f"Server error: {str(e)}", 500)


@app.route("/api/custom/extract-subtopics", methods=["POST"])
def extract_subtopics():
    """
    Extract subtopics from uploaded PDF/text file.
    Note: This route is teacher-restricted like other custom endpoints.
    """
    if not session.get('logged_in') or session.get('role') != 'teacher':
        return jsonify({"error": "Unauthorized"}), 401

    if "file" not in request.files:
        return jsonify({"error": "Missing file (multipart field 'file')"}), 400

    uploaded_file = request.files['file']
    file_name = uploaded_file.filename or "uploaded_content.txt"

    try:
        # 1. Extract Text
        raw_text = extract_pdf_text(uploaded_file)
        if not raw_text or len(raw_text.strip()) < 50:
            return jsonify({"error": "Could not extract sufficient text from file. Please ensure it's a valid PDF/Text document."}), 400

        # 2. Store full text and file name for later quiz generation
        upload_id = str(uuid.uuid4())
        _SUBTOPIC_UPLOADS[upload_id] = {'text': raw_text, 'file_name': file_name}

        # 3. Get Subtopics using LLM (Use only the first few chunks for topic extraction to save latency/tokens)
        text_chunks = split_into_chunks(raw_text)
        sample_text = "\n\n".join(text_chunks[:2]) if len(text_chunks) > 0 else raw_text[:4000]

        # CALL the helper using positional arguments to avoid keyword mismatch
        # Many helper implementations accept (text, api_key) or (doc_text, api_key) as positional args.
        # Using positional args is robust against keyword name mismatches.
        try:
            subtopics_llm_output = extract_subtopics_llm(sample_text, GROQ_API_KEY)
        except TypeError:
            # Fallback: try single-argument call (some variants accept just the text)
            subtopics_llm_output = extract_subtopics_llm(sample_text)

        # normalize LLM output expectations
        if isinstance(subtopics_llm_output, dict) and subtopics_llm_output.get("subtopics"):
            return jsonify({
                "success": True,
                "upload_id": upload_id,
                "subtopics": subtopics_llm_output["subtopics"],
                "source_file": file_name,
            })
        elif isinstance(subtopics_llm_output, list):
            # if helper returned a raw list
            return jsonify({
                "success": True,
                "upload_id": upload_id,
                "subtopics": subtopics_llm_output,
                "source_file": file_name,
            })
        else:
            error_message = subtopics_llm_output.get('error', "Unknown LLM error occurred.") if isinstance(subtopics_llm_output, dict) else "LLM returned unexpected format."
            return jsonify({"error": f"LLM failed to extract subtopics. Error: {error_message}"}), 500

    except Exception as e:
        print(f"❌ Error in extract_subtopics: {e}")
        return jsonify({"error": f"Server error during subtopic extraction: {str(e)}"}), 500


@app.route("/api/custom/quiz-from-subtopics", methods=["POST"])
def quiz_from_subtopics():
    """
    Generate quiz based on chosen subtopics and save to Firestore.
    """
    if not session.get('logged_in') or session.get('role') != 'teacher':
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        payload = request.get_json()
        upload_id = payload.get("upload_id")
        chosen = payload.get("subtopics", []) 
        totals = payload.get("totals", {})
        
        # Difficulty settings
        difficulty = payload.get("difficulty", {})
        difficulty_mode = difficulty.get('mode', 'auto') if isinstance(difficulty, dict) else difficulty
        
        scenario_based_target = int(payload.get("scenario_based", 0))
        code_snippet_target = int(payload.get("code_snippet", 0))

        if not upload_id or upload_id not in _SUBTOPIC_UPLOADS:
            return jsonify({"error": "Invalid or expired upload_id; run subtopic detection again."}), 400
        if not chosen:
            return jsonify({"error": "No subtopics provided"}), 400

        total_requested = sum(int(v) for v in totals.values()) if isinstance(totals, dict) else 0
        if total_requested <= 0:
            return jsonify({"error": "Totals must request at least 1 question across types."}), 400

        # Retrieve data from the new structure
        uploaded_data = _SUBTOPIC_UPLOADS[upload_id]
        full_text = uploaded_data['text']
        source_file = uploaded_data['file_name']
        
        # 1. Call LLM to generate quiz
        out = generate_quiz_from_subtopics_llm(
            full_text=full_text,
            chosen_subtopics=chosen,
            totals={k: int(v) for k, v in totals.items()},
            difficulty=difficulty,
            scenario_based=scenario_based_target,
            code_snippet=code_snippet_target,
            api_key=GROQ_API_KEY
        )

        # 2. Process, enforce flags, and save result
        questions = out.get("questions", [])
        if not questions:
            error_message = out.get('error', "LLM generated an empty or invalid quiz structure.")
            return jsonify({"error": f"Quiz generation failed: {error_message}"}), 500
            
        # Apply flag enforcement after LLM call (crucial step!)
        questions = enforce_flag_targets(questions, scenario_based_target, code_snippet_target)

        quiz_data = {
            "questions": questions,
            "metadata": {
                "source": "subtopics",
                "upload_id": upload_id,
                "source_file": source_file, 
                "selected_subtopics": chosen,
                "totals_requested": totals,
                "difficulty": difficulty,
                "flags": {"scenario_based": scenario_based_target, "code_snippet": code_snippet_target},
                "total_questions": len(questions)
            }
        }

        quiz_id = save_quiz_to_firestore(quiz_data)

        if quiz_id:
            # Clean up the large text from memory after successful save
            if upload_id in _SUBTOPIC_UPLOADS:
                del _SUBTOPIC_UPLOADS[upload_id] 
                
            return jsonify({"success": True, "quiz_id": quiz_id, "questions_count": len(questions), "questions": questions})
        else:
            return jsonify({"error": "Failed to save the generated quiz to the database."}), 500

    except Exception as e:
        print(f"❌ Error in quiz_from_subtopics: {e}")
        return jsonify({"error": f"Server error during quiz generation: {str(e)}"}), 500


@app.route("/generate-question", methods=["POST"])
def auto_generate_quiz():
    """
    Generate a simple AI-Powered quiz based on a topic text (no PDF/subtopic workflow).
    """
    if not session.get('logged_in') or session.get('role') != 'teacher':
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        payload = request.get_json()
        topic_text = payload.get("topic_text", "").strip()
        totals = payload.get("totals", {})
        
        if not topic_text:
            return jsonify({"error": "Please enter a topic or text to generate a quiz."}), 400
        
        total_requested = sum(int(v) for v in totals.values()) if isinstance(totals, dict) else 0
        if total_requested <= 0:
            return jsonify({"error": "Totals must request at least 1 question across types."}), 400

        # 1. Call LLM to generate quiz by reusing the subtopic generation function
        out = generate_quiz_from_subtopics_llm(
            full_text=topic_text, # Pass the topic text as the context
            chosen_subtopics=[topic_text[:50] + "..."], # Use a snippet for metadata display
            totals={k: int(v) for k, v in totals.items()},
            difficulty="auto", # Simplified mode is always auto difficulty
            scenario_based=0,
            code_snippet=0,
            api_key=GROQ_API_KEY
        )

        # 2. Process and Save Result
        questions = out.get("questions", [])
        if not questions:
            error_message = out.get('error', "LLM generated an empty or invalid quiz structure.")
            return jsonify({"error": f"AI-Powered Quiz generation failed: {error_message}"}), 500
        
        quiz_data = {
            "questions": questions,
            "metadata": {
                "source": "auto-topic",
                "source_file": topic_text, # Use the topic as the quiz title
                "totals_requested": totals,
                "difficulty": "auto",
                "flags": {"scenario_based": False, "code_snippet": False},
                "total_questions": len(questions)
            }
        }

        quiz_id = save_quiz_to_firestore(quiz_data)

        if quiz_id:
            return jsonify({"success": True, "quiz_id": quiz_id, "questions_count": len(questions)})
        else:
            return jsonify({"error": "Failed to save the generated quiz to the database."}), 500

    except Exception as e:
        print(f"❌ Error in auto_generate_quiz: {e}")
        return jsonify({"error": f"Server error during quiz generation: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
