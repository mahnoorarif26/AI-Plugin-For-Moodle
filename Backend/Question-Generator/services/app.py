import os
import re
import json
import uuid
from datetime import datetime
from typing import Dict, List, Any
import time

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
try:
    from firebase_admin.firestore import Query  # optional; used for ordering
except Exception:
    Query = None  # type: ignore

import sys
from services.db import (
    save_quiz as save_quiz_to_store,
    get_quiz_by_id,
    list_quizzes,
    save_submission as save_submission_to_store,  # Singular - save_submission
    get_submitted_quiz_ids  # This was missing from your db.py
)
from services import db as _db_mod

# ====== LLM / UTILS ======
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
# -----------------------------------imports for quiz grading-----------------------------------
import os
import sys
import importlib.util

from dotenv import load_dotenv

load_dotenv()

# ---- Find the nearest 'Question-Generator' directory above this file ----
HERE = os.path.dirname(__file__)  # e.g. .../Backend/Question-Generator/services
qg_dir = HERE

while qg_dir and os.path.basename(qg_dir) != "Question-Generator":
    parent = os.path.dirname(qg_dir)
    if parent == qg_dir:
        # We walked all the way up and never found it
        raise FileNotFoundError(
            "Could not locate 'Question-Generator' directory from " + HERE
        )
    qg_dir = parent

QG_ROOT = qg_dir
GRADER_FILE = os.path.join(QG_ROOT, "quiz grading", "grader.py")

# ---- Make sure grader.py's folder is importable (for llm.py, prompts.py, etc.) ----
QUIZ_GRADING_DIR = os.path.dirname(GRADER_FILE)
if QUIZ_GRADING_DIR not in sys.path:
    sys.path.insert(0, QUIZ_GRADING_DIR)

# Optional: one-time sanity check while wiring this up
print("Grader at:", GRADER_FILE, "exists:", os.path.exists(GRADER_FILE))

if not os.path.exists(GRADER_FILE):
    raise FileNotFoundError(f"grader.py not found at {GRADER_FILE}")

# ---- Dynamic import of quiz grading/grader.py ----
spec = importlib.util.spec_from_file_location("quizgrading.grader", GRADER_FILE)
grader_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grader_mod)

QuizGrader = grader_mod.QuizGrader

grader = QuizGrader(
    api_key=os.getenv("GROQ_API_KEY"),
    model=os.getenv("GROQ_MODEL"),
    default_policy=os.getenv("GRADING_POLICY", "balanced"),
)


# --- Configuration Section ---

# Correctly point to the 'data' folder
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'data', 'assignments_data.json')

# Re-run your load function:
def load_assignments_data():
    """Loads all assignment data from the local JSON file."""
    if not os.path.exists(DATA_FILE_PATH):
        # This print statement should now show the correct path if it still fails
        print(f"Error: Assignment data file not found at {DATA_FILE_PATH}")
        return {}
    try:
        with open(DATA_FILE_PATH, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON data: {e}")
        return {}

ALL_ASSIGNMENTS = load_assignments_data()





# --- End Configuration Section ---
# ===============================
# APP CONFIGURATION
# ===============================
app = Flask(__name__)
# CRITICAL: Set a secret key for session management for time tracking
app.secret_key = os.getenv("FLASK_SECRET_KEY", "a_very_secret_dev_key_that_should_be_changed_12345")
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- FILE UPLOAD CONFIGURATION (For Assignments) ---
UPLOAD_FOLDER = 'student_uploads'  # Define an upload folder
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# ---------------------------------------------------


# ===============================
# AUTH ROUTES (Simple logout)
# ===============================
@app.route('/logout')
def logout():
    """Simple logout route that clears session and redirects to home."""
    session.clear()
    return redirect(url_for('teacher_generate'))

# ===============================
# GLOBAL MEMORY STORE
# ===============================
_SUBTOPIC_UPLOADS: Dict[str, Dict[str, str]] = {}

load_dotenv()  # Load variables from .env file

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("❌ GROQ_API_KEY not found in environment variables. Please check your .env file.")

# ===============================
# LANDING (always open teacher/generate)
# ===============================
@app.route('/', methods=['GET'])
def root_redirect():
    """Always land on the teacher generation page."""
    return redirect(url_for('teacher_generate'))


# ===============================
# STUDENT ROUTES (CORE)
# ===============================
@app.route('/student')
def student_index():
    """List all available items for students - SHOW EVERYTHING"""
    try:
        student_email = "student@example.com"
        submitted_quiz_ids = set(get_submitted_quiz_ids(student_email) or [])

        all_items = list_quizzes(kind=None) or []

        # SHOW ALL ITEMS AS BOTH QUIZZES AND ASSIGNMENTS
        display_items = []
        
        for it in all_items:
            item_id = it.get("id")
            if not item_id:
                continue

            # Skip if submitted
            is_submitted = item_id in submitted_quiz_ids
            if is_submitted:
                continue

            questions_count = len(it.get("questions", []))

            item_data = {
                "id": item_id,
                "title": it.get("title") or "Generated Content",
                "time_limit_min": it.get('time_limit_min', 60),
                "questions_count": questions_count,
                "created_at": it.get("created_at"),
                "actual_kind": it.get('metadata', {}).get('kind', 'not_set')
            }

            display_items.append(item_data)
            print(f"📋 Adding item: {item_data['title']} (Kind: {item_data['actual_kind']})")

        # FOR NOW: Show ALL items in BOTH quizzes and assignments sections
        print(f"🎯 Displaying {len(display_items)} items to student")
        
        return render_template('student_index.html',
                               quizzes=display_items,  # Show everything as quizzes
                               assignments=display_items,  # Show everything as assignments
                               error=None,
                               student_name="Student")

    except Exception as e:
        print(f"❌ Error in student_index: {e}")
        return render_template('student_index.html',
                               quizzes=[],
                               assignments=[],
                               error=f"Failed to load items: {e}",
                               student_name="Student")
    

@app.route('/student/submit', methods=['POST'])
def submit_quiz():
    """Handle student quiz submission."""
    form_data = request.form
    quiz_id = form_data.get('quiz_id')
    student_email = "student@example.com"
    student_name = "Student"

    if not quiz_id:
        return jsonify({"error": "Missing quiz ID"}), 400

    correct_quiz_data = get_quiz_by_id(quiz_id)
    if not correct_quiz_data:
        return jsonify({"error": "Quiz not found"}), 404

    # Collect student answers from form: names are the question IDs
    total_questions = len(correct_quiz_data.get('questions', []))
    student_answers: Dict[str, Any] = {}
    for q in correct_quiz_data.get('questions', []):
        q_id = q.get('id')
        if not q_id:
            continue
        student_answers[q_id] = (form_data.get(q_id) or '').strip()

    # === Quiz Grading Integration (uses quiz_grading module) ===
    # Normalize quiz object: if questions used 'correct_answer', map it to expected 'answer'
    quiz_for_grader = dict(correct_quiz_data)
    qlist = []
    for q in (correct_quiz_data.get('questions') or []):
        qq = dict(q)
        if 'answer' not in qq:
            for key in ['correct_answer','reference_answer','expected_answer','ideal_answer']:
                if qq.get(key) is not None:
                    qq['answer'] = qq.get(key)
                    break
        qlist.append(qq)
    quiz_for_grader['questions'] = qlist

    try:
        result = grader.grade_quiz(
            quiz=quiz_for_grader,
            responses=student_answers,
            policy=os.getenv("GRADING_POLICY", "balanced"),
        )
        score = result.get('total_score', 0)
        grading_items = result.get('items') or []
        max_total_calc = result.get('max_total')
    except Exception as e:
        # Fallback: if grader fails for any reason, keep score at 0
        print(f"[quiz_grading] grading failed: {e}")
        score = 0
        grading_items = []
        max_total_calc = None

    submission_data = {
        "email": student_email,
        "name": student_name,
        "answers": student_answers,
        "score": score,
        "total_questions": total_questions,
        "grading_items": grading_items if 'grading_items' in locals() else [],
        "max_total": max_total_calc if 'max_total_calc' in locals() else None,
    }
    submission_id = save_submission_to_store(quiz_id, submission_data)

    # Redirect to a confirmation page after submission
    return redirect(url_for('submission_confirmation', quiz_id=quiz_id, score=score, total=total_questions, submission_id=submission_id))

@app.route('/student/confirmation/<quiz_id>', methods=['GET'])
def submission_confirmation(quiz_id):
    """Display submission confirmation and score."""
    score = request.args.get('score', 'N/A')
    total = request.args.get('total', 'N/A')
    submission_id = request.args.get('submission_id', 'N/A')
    
    quiz_data = get_quiz_by_id(quiz_id)
    quiz_title = quiz_data.get("metadata", {}).get("source_file", f"Submitted Quiz") if quiz_data else "Submitted Quiz"

    is_assignment = request.args.get('is_assignment') in ('1','true','True','yes')
    return render_template(
        'submission_confirmation.html', 
        quiz_title=quiz_title, 
        score=score, 
        total=total, 
        submission_id=submission_id,
        student_name="Student",
        quiz_id=quiz_id,
        is_assignment=is_assignment
    )

# ===============================
# GRADES API (for frontend grades panel)
# ===============================
@app.get('/api/grades')
def api_grades():
    """Return student's graded submissions. Requires Firestore.
    Shape: {success:true, items:[{id,title,date,score,max_score}]}"""
    email = request.args.get('email') or 'student@example.com'
    items = []
    try:
        fs = getattr(_db_mod, '_db', None)
        if fs is None:
            return jsonify({"success": True, "items": []})
        # Iterate both collections (quizzes + assignments) and collect this student's submissions
        for collection_name in ['AIquizzes', 'assignments']:
            qdocs = fs.collection(collection_name).stream()
            for qdoc in qdocs:
                qid = qdoc.id
                q = qdoc.to_dict() or {}
                title = (
                    q.get('title')
                    or q.get('metadata', {}).get('source_file')
                    or ('Assignment' if collection_name == 'assignments' else 'AI Generated Quiz')
                )

                def _default_max(t):
                    t = (t or '').lower()
                    return 1 if t in ('mcq', 'true_false') else (3 if t == 'short' else (5 if t == 'long' else 1))

                max_total = 0
                for qq in q.get('questions', []) or []:
                    max_total += float(qq.get('max_score') or _default_max(qq.get('type')))

                subs = (
                    fs.collection(collection_name)
                      .document(qid)
                      .collection('submissions')
                      .where('student_email', '==', email)
                      .stream()
                )
                for sd in subs:
                    s = sd.to_dict() or {}
                    # Auto-refresh stale submissions (no grading_items)
                    if grader is not None and not (s.get('grading_items') or []):
                        try:
                            answers = s.get('answers') or {}
                            quiz_for_grader = dict(q)
                            qlist = []
                            for qq in (q.get('questions') or []):
                                d = dict(qq)
                                if 'answer' not in d:
                                    for key in ['answer','correct_answer','reference_answer','expected_answer','ideal_answer','solution','model_answer']:
                                        if d.get(key) is not None:
                                            d['answer'] = d.get(key)
                                            break
                                if 'max_score' not in d or d.get('max_score') is None:
                                    d['max_score'] = _default_max(d.get('type'))
                                qlist.append(d)
                            quiz_for_grader['questions'] = qlist
                            result = grader.grade_quiz(quiz=quiz_for_grader, responses=answers, policy=os.getenv('GRADING_POLICY','balanced'))
                            fs.collection(collection_name).document(qid).collection('submissions').document(sd.id).update({
                                'score': result.get('total_score', 0),
                                'max_total': result.get('max_total'),
                                'grading_items': result.get('items') or [],
                            })
                            s['score'] = result.get('total_score', 0)
                            s['max_total'] = result.get('max_total')
                            s['grading_items'] = result.get('items') or []
                        except Exception:
                            pass

                    gitems = s.get('grading_items') or []
                    if gitems:
                        try:
                            calc_score = sum(float(it.get('score') or 0) for it in gitems)
                            calc_max   = sum(float((it.get('max_score') if it.get('max_score') is not None else it.get('max')) or 0) for it in gitems)
                        except Exception:
                            calc_score, calc_max = float(s.get('score', 0) or 0), float(s.get('max_total') or 0)
                    else:
                        answers = s.get('answers') or {}
                        calc_score = 0.0
                        for qq in (q.get('questions') or []):
                            qid2 = qq.get('id')
                            t = (qq.get('type') or '').lower()
                            expected = qq.get('answer')
                            if expected is None:
                                expected = qq.get('correct_answer')
                            if t in ('mcq','true_false') and expected is not None and qid2 in answers:
                                if str(answers.get(qid2) or '').strip().lower() == str(expected).strip().lower():
                                    ms = float(qq.get('max_score') or (1 if t in ('mcq','true_false') else 0))
                                    calc_score += ms
                        calc_max = float(s.get('max_total') or 0) or float(max_total or s.get('total_questions') or 0)

                    items.append({
                        'id': sd.id,
                        'quiz_id': qid,
                        'title': title,
                        'date': str(s.get('submitted_at') or ''),
                        'score': float(calc_score),
                        'max_score': float(calc_max),
                        'kind': 'assignment' if collection_name == 'assignments' else 'quiz',
                    })

        items.sort(key=lambda x: str(x.get('date') or ''), reverse=True)
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": f"grades_list_failed: {e}"}), 500


# ===============================
# SUBMISSION STATUS API (single submission)
# ===============================
@app.get('/api/submissions/<submission_id>')
def api_get_submission(submission_id: str):
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": False, "error": "firestore_disabled"}), 400
    try:
        refresh = request.args.get('refresh') in ('1','true','yes')
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                subref = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id)
                sub = subref.get()
                if not sub.exists:
                    continue
                q = qdoc.to_dict() or {}
                s = sub.to_dict() or {}
                title = q.get('title') or q.get('metadata', {}).get('source_file') or ('Assignment' if collection_name=='assignments' else 'AI Generated Quiz')

                if refresh and grader is not None and not (s.get('grading_items') or []):
                    try:
                        def _default_max(t):
                            t = (t or '').lower()
                            return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))
                        quiz_for_grader = dict(q)
                        qlist = []
                        for qq in (q.get('questions') or []):
                            d = dict(qq)
                            if 'answer' not in d:
                                for key in ['answer','correct_answer','reference_answer','expected_answer','ideal_answer','solution','model_answer']:
                                    if d.get(key) is not None:
                                        d['answer'] = d.get(key)
                                        break
                            if 'max_score' not in d or d.get('max_score') is None:
                                d['max_score'] = _default_max(d.get('type'))
                            qlist.append(d)
                        quiz_for_grader['questions'] = qlist
                        result = grader.grade_quiz(quiz=quiz_for_grader, responses=s.get('answers') or {}, policy=os.getenv('GRADING_POLICY','balanced'))
                        fs.collection(collection_name).document(qid).collection('submissions').document(submission_id).update({
                            'score': result.get('total_score', 0),
                            'max_total': result.get('max_total'),
                            'grading_items': result.get('items') or [],
                        })
                        s['score'] = result.get('total_score', 0)
                        s['max_total'] = result.get('max_total')
                        s['grading_items'] = result.get('items') or []
                    except Exception:
                        pass

                items = s.get('grading_items') or []
                if items:
                    try:
                        score = sum(float(it.get('score') or 0) for it in items)
                        max_total = sum(float((it.get('max_score') if it.get('max_score') is not None else it.get('max')) or 0) for it in items)
                    except Exception:
                        score = float(s.get('score') or 0)
                        max_total = float(s.get('max_total') or 0)
                else:
                    score = float(s.get('score') or 0)
                    max_total = float(s.get('max_total') or 0)

                return jsonify({
                    'success': True,
                    'submission': {
                        'id': submission_id,
                        'score': score,
                        'max_total': max_total,
                        'grading_items': items,
                        'kind': 'assignment' if collection_name=='assignments' else 'quiz',
                    },
                    'quiz_title': title,
                })
        return jsonify({'success': False, 'error': 'submission_not_found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
# --------------------------------------------------------------------------------------------------
# QUIZ ROUTE
# --------------------------------------------------------------------------------------------------

@app.route('/student/quiz/<string:quiz_id>', methods=['GET'])
def student_quiz(quiz_id):
    """Display quiz for student with a timer AND STARTS SERVER-SIDE TIMER."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        abort(404)

    session['quiz_start_time_' + quiz_id] = time.time()

    questions_for_student = [{
        'id': q.get('id'),
        'type': q.get('type'),
        'prompt': q.get('prompt') or q.get('question_text'),
        'options': q.get('options') if q.get('type') in ['mcq', 'true_false'] else None,
        'difficulty': q.get('difficulty'),
    } for q in quiz_data.get('questions', [])]

    title = quiz_data.get("title") or quiz_data.get("metadata", {}).get("source_file", f"Quiz #{quiz_id}")
    time_limit_min = quiz_data.get('time_limit_min', 60)

    return render_template(
        'student_quiz.html',
        quiz_id=quiz_id,
        title=title,
        questions=questions_for_student,
        time_limit_min=time_limit_min,
        student_email="student@example.com",
        student_name="Student"
    )


@app.route('/student/submit', methods=['POST'])
def student_submit_quiz():
    """Handle student quiz submission AND VALIDATE SERVER-SIDE TIMER."""
    form_data = request.form
    quiz_id = form_data.get('quiz_id')

    if not quiz_id:
        return jsonify({"error": "Missing quiz ID"}), 400

    correct_quiz_data = get_quiz_by_id(quiz_id)
    if not correct_quiz_data:
        return jsonify({"error": "Quiz not found"}), 404

    start_time_key = 'quiz_start_time_' + quiz_id
    start_time_server = session.pop(start_time_key, 0)

    time_limit_min = correct_quiz_data.get('time_limit_min', 60)
    allowed_seconds = time_limit_min * 60 + 5

    score = 0
    time_exceeded = False

    if start_time_server == 0:
        time_exceeded = True
        message = "Submission failed: Quiz session expired or invalid."
        time_taken_sec = 0
    elif (time.time() - start_time_server) > allowed_seconds:
        time_exceeded = True
        message = "Submission failed: Time limit exceeded."
        time_taken_sec = round(time.time() - start_time_server)
    else:
        time_taken_sec = round(time.time() - start_time_server)

    total_questions = len(correct_quiz_data.get('questions', []))
    student_answers: Dict[str, str] = {}

    if not time_exceeded:
        for q in correct_quiz_data.get('questions', []):
            q_id = q.get('id')
            if not q_id:
                continue
            correct_answer = q.get('correct_answer')
            student_response = (form_data.get(q_id) or '').strip()
            student_answers[q_id] = student_response

            if q.get('type') in ['mcq', 'true_false'] and correct_answer is not None:
                if str(student_response).lower() == str(correct_answer).lower():
                    score += 1

    submission_data = {
        "email": "student@example.com",
        "name": "Student",
        "answers": student_answers,
        "score": score,
        "total_questions": total_questions,
        "status": "Timeout" if time_exceeded else "Completed",
        "time_taken_sec": time_taken_sec,
        "kind": "quiz_submission"
    }
    submission_id = save_submission_to_store(quiz_id, submission_data)

    return redirect(url_for('submission_confirmation',
                             quiz_id=quiz_id,
                             score=score,
                             total=total_questions,
                             submission_id=submission_id,
                             is_assignment=False,
                             time_exceeded=time_exceeded))


# --------------------------------------------------------------------------------------------------
# ASSIGNMENT ROUTES
# --------------------------------------------------------------------------------------------------




@app.route("/api/test/create-sample-assignment")
def create_sample_assignment():
    """Create a sample assignment for testing"""
    try:
        sample_assignment = {
            "title": "Sample Programming Assignment",
            "questions": [
                {
                    "id": "q1",
                    "type": "short",
                    "prompt": "Write a Python function to calculate factorial.",
                    "difficulty": "medium"
                },
                {
                    "id": "q2", 
                    "type": "short",
                    "prompt": "Explain the time complexity of your solution.",
                    "difficulty": "easy"
                }
            ],
            "metadata": {
                "kind": "assignment",
                "source": "test",
                "created_at": datetime.utcnow().isoformat()
            }
        }
        
        assignment_id = save_quiz_to_store(sample_assignment)
        return jsonify({
            "success": True,
            "assignment_id": assignment_id,
            "message": "Sample assignment created successfully"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

    #?????????????????????????????????????????????????????????????????????????????

# Make the assignment view robust to both old `quiz_id` route variable and new `assignment_id`.
@app.route('/student/assignment/<string:assignment_id>', methods=['GET'])
@app.route('/student/assignment/<string:quiz_id>', methods=['GET'])
def student_assignment(**kwargs):
    """
    Display assignment for student (open-ended response/file upload).
    This accepts either /student/assignment/<assignment_id> (preferred)
    or the legacy /student/assignment/<quiz_id>.
    """
    # pick whichever path variable is provided
    assignment_id = kwargs.get('assignment_id') or kwargs.get('quiz_id')
    if not assignment_id:
        abort(404)

    assignment_data = get_quiz_by_id(assignment_id)

    if not assignment_data:
        abort(404)

    questions_for_student = [{
        'id': q.get('id'),
        'prompt': q.get('prompt') or q.get('question_text'),
        'type': q.get('type')
    } for q in assignment_data.get('questions', [])]

    title = assignment_data.get("title") or f"Assignment #{assignment_id}"

    # Provide both identifiers to the template for backward compatibility
    return render_template(
        'student_assignment.html',
        quiz_id=assignment_id,       # legacy templates expecting quiz_id still work
        assignment_id=assignment_id, # preferred variable name
        title=title,
        questions=questions_for_student,
        student_email="student@example.com",
        student_name="Student"
    )


@app.route('/student/submit_assignment', methods=['POST'])
def student_submit_assignment():
    """Handle student assignment submission (text/files)."""

    # Accept both 'assignment_id' (preferred) and legacy 'quiz_id'
    assignment_id = request.form.get('assignment_id') or request.form.get('quiz_id')
    student_email = "student@example.com"
    student_name = "Student"

    if not assignment_id:
        return jsonify({"error": "Missing assignment ID"}), 400

    assignment_data = get_quiz_by_id(assignment_id)
    if not assignment_data:
        return jsonify({"error": "Assignment not found"}), 404

    student_answers: Dict[str, str] = {}
    uploaded_files_map = {}
    total_questions = len(assignment_data.get('questions', []))

    for q in assignment_data.get('questions', []):
        q_id = q.get('id')
        if q_id:
            student_response = (request.form.get(q_id) or '').strip()
            student_answers[q_id] = student_response

    uploaded_file = request.files.get('assignment_file_final')
    if uploaded_file and uploaded_file.filename != '':
        filename = secure_filename(uploaded_file.filename)
        file_uuid = str(uuid.uuid4())[:8]
        safe_filename = f"{assignment_id}_{student_email.split('@')[0]}_{file_uuid}_{filename}"

        if 'UPLOAD_FOLDER' not in app.config:
            print("⚠️ UPLOAD_FOLDER is not configured. File will not be saved.")
            uploaded_files_map['assignment_file_final'] = f"Error: UPLOAD_FOLDER not set"
        else:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
            try:
                uploaded_file.save(file_path)
                uploaded_files_map['assignment_file_final'] = safe_filename
            except Exception as e:
                print(f"File upload failed for {filename}: {e}")
                uploaded_files_map['assignment_file_final'] = f"Error: {e}"

    # Grade assignment with embedded grader
    grading_items = []
    max_total_calc = None
    score_total = 0
    if grader is not None:
        def _default_max(t):
            t = (t or '').lower()
            return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))
        quiz_for_grader = dict(assignment_data)
        qlist = []
        for q in (assignment_data.get('questions') or []):
            d = dict(q)
            if 'answer' not in d:
                for key in ['answer','correct_answer','reference_answer','expected_answer','ideal_answer','solution','model_answer']:
                    if d.get(key) is not None:
                        d['answer'] = d.get(key)
                        break
            if 'max_score' not in d or d.get('max_score') is None:
                d['max_score'] = _default_max(d.get('type'))
            qlist.append(d)
        quiz_for_grader['questions'] = qlist
        try:
            result = grader.grade_quiz(
                quiz=quiz_for_grader,
                responses=student_answers,
                policy=os.getenv('GRADING_POLICY','balanced'),
            )
            score_total = result.get('total_score', 0) or sum(float(x.get('score') or 0) for x in (result.get('items') or []))
            grading_items = result.get('items') or []
            max_total_calc = result.get('max_total')
        except Exception as e:
            print(f"[assignment_grading] grading failed: {e}")

    submission_data = {
        "email": student_email,
        "name": student_name,
        "answers": student_answers,
        "files": uploaded_files_map,
        "score": score_total,
        "total_questions": total_questions,
        "kind": "assignment_submission",
        "submitted_at": datetime.utcnow().isoformat(),
        "grading_items": grading_items,
        "max_total": max_total_calc,
    }

    submission_id = save_submission_to_store(assignment_id, submission_data)

    if not max_total_calc:
        max_total_calc = sum(float((q.get('max_score') if q.get('max_score') is not None else _default_max(q.get('type')))) for q in (assignment_data.get('questions') or []))

    return redirect(url_for('submission_confirmation',
                             quiz_id=assignment_id,
                             score=score_total,
                             total=max_total_calc,
                             submission_id=submission_id,
                             is_assignment=True))

#?>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>123

@app.route("/api/debug/quizzes")
def debug_quizzes():
    """Debug endpoint to see all stored quizzes and their metadata"""
    try:
        quizzes = list_quizzes(kind=None) or []
        debug_info = []
        
        for quiz in quizzes:
            debug_info.append({
                "id": quiz.get("id"),
                "title": quiz.get("title"),
                "metadata": quiz.get("metadata", {}),
                "kind": quiz.get("metadata", {}).get("kind", "NOT SET"),
                "questions_count": len(quiz.get("questions", [])),
                "has_questions": bool(quiz.get("questions"))
            })
        
        return jsonify({
            "total_quizzes": len(quizzes),
            "quizzes": debug_info
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================
# TEACHER ROUTES (no auth)
# ===============================

@app.route('/teacher/generate')
def teacher_generate():
    """Quiz generation page (no auth) — this is the landing page from '/'."""
    return render_template('index.html', teacher_name="Teacher")

@app.route('/teacher')
def teacher_index():
    """List all quizzes/assignments with submission counts for teachers."""
    try:
        fs = getattr(_db_mod, '_db', None)
        items = list_quizzes(kind=None) or []
        enriched = []
        for it in items:
            qid = it.get('id')
            if not qid:
                continue
            collection_name = 'assignments' if (it.get('kind') == 'assignment' or it.get('metadata', {}).get('kind') == 'assignment') else 'AIquizzes'
            subs_count = 0
            try:
                if fs is not None:
                    subs_count = sum(1 for _ in fs.collection(collection_name).document(qid).collection('submissions').stream())
            except Exception:
                subs_count = 0
            enriched.append({
                'id': qid,
                'title': it.get('title') or it.get('metadata', {}).get('source_file') or 'Untitled',
                'kind': it.get('kind') or it.get('metadata', {}).get('kind') or 'quiz',
                'questions_count': len(it.get('questions', []) or []),
                'submissions_count': subs_count,
            })
        return render_template('teacher_index.html', items=enriched, teacher_name='Teacher')
    except Exception as e:
        print('[teacher_index] error:', e)
        return render_template('teacher_index.html', items=[], teacher_name='Teacher', error=str(e))

@app.route('/teacher/manual', methods=['GET'])
def teacher_manual():
    return render_template('manual_create.html')

@app.route('/teacher/submissions/<quiz_id>', methods=['GET'])
def teacher_submissions(quiz_id):
    """View student submissions for a specific quiz (UI shell; wire your data in template)."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return ("Quiz not found.", 404)
    quiz_title = quiz_data.get("title") or quiz_data.get("metadata", {}).get("source_file", f"Quiz #{quiz_id}")
    try:
        fs = getattr(_db_mod, '_db', None)
        if fs is None:
            return ("Firestore connection failed.", 500)

        collection_name = 'assignments' if quiz_data.get('metadata', {}).get('kind') == 'assignment' else 'AIquizzes'
        submissions_ref = fs.collection(collection_name).document(quiz_id).collection('submissions')
        try:
            if Query is not None:
                docs = submissions_ref.order_by('submitted_at', direction=Query.DESCENDING).stream()
            else:
                docs = submissions_ref.stream()
        except Exception:
            docs = submissions_ref.stream()

        questions_map = {q.get('id'): q for q in (quiz_data.get('questions') or []) if q.get('id')}
        submissions_list = []
        for doc in docs:
            submission = doc.to_dict() or {}
            processed_answers = {}
            grading_items = submission.get('grading_items') or []
            grade_map = {}
            try:
                for gi in grading_items:
                    qid = gi.get('question_id') or gi.get('id')
                    if qid:
                        grade_map[str(qid)] = gi
            except Exception:
                grade_map = {}
            for q_id, student_response in (submission.get('answers') or {}).items():
                q_data = questions_map.get(q_id)
                if not q_data:
                    continue
                correct_answer = (
                    q_data.get('answer')
                    or q_data.get('correct_answer')
                    or q_data.get('reference_answer')
                    or q_data.get('expected_answer')
                    or q_data.get('ideal_answer')
                )
                is_correct = None
                if (q_data.get('type') or '').lower() in ['mcq','true_false'] and correct_answer is not None:
                    is_correct = str(student_response).strip().lower() == str(correct_answer).strip().lower()
                # compute per-question score/max
                def _default_max(t):
                    t = (t or '').lower()
                    return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))
                gi = grade_map.get(str(q_id)) or {}
                q_max = gi.get('max_score') if gi.get('max_score') is not None else gi.get('max')
                if q_max is None:
                    q_max = q_data.get('max_score') if q_data.get('max_score') is not None else _default_max(q_data.get('type'))
                q_score = gi.get('score')
                if q_score is None and is_correct is not None:
                    q_score = q_max if is_correct else 0
                processed_answers[q_id] = {
                    'prompt': q_data.get('prompt') or q_data.get('question_text'),
                    'type': q_data.get('type'),
                    'response': student_response,
                    'correct_answer': correct_answer,
                    'is_correct': is_correct,
                    'score': q_score,
                    'max_score': q_max,
                    'feedback': gi.get('feedback') if isinstance(gi, dict) else None,
                }
            # compute display max_total for teacher view
            computed_max_total = submission.get('max_total')
            if computed_max_total is None:
                def _default_max(t):
                    t = (t or '').lower()
                    return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))
                try:
                    computed_max_total = sum(float((qq.get('max_score') if qq.get('max_score') is not None else _default_max(qq.get('type')))) for qq in (quiz_data.get('questions') or []))
                except Exception:
                    computed_max_total = len(questions_map)

            # compute display score from processed answers if possible
            try:
                display_score = sum(float((v.get('score') or 0)) for v in processed_answers.values() if isinstance(v, dict))
            except Exception:
                display_score = float(submission.get('score') or 0)

            submissions_list.append({
                'id': doc.id,
                'student_name': submission.get('student_name') or submission.get('name') or 'Anonymous',
                'student_email': submission.get('student_email') or submission.get('email') or 'N/A',
                'score': display_score,
                'total_questions': computed_max_total,
                'submitted_at_str': submission.get('submitted_at').strftime('%Y-%m-%d %H:%M') if hasattr(submission.get('submitted_at'), 'strftime') else str(submission.get('submitted_at') or ''),
                'answers': processed_answers,
            })

        return render_template('teacher_submissions.html', quiz_title=quiz_title, quiz_id=quiz_id, submissions=submissions_list)
    except Exception as e:
        print(f"❌ Error fetching submissions: {e}")
        return ("Failed to load submissions.", 500)

# ===============================
# TEACHER JSON APIs (for index.html Grades tab)
# ===============================

@app.get('/api/teacher/quizzes')
def api_teacher_quizzes():
    fs = getattr(_db_mod, '_db', None)
    items = []
    try:
        quizzes = list_quizzes(kind=None) or []
        for q in quizzes:
            qid = q.get('id')
            if not qid:
                continue
            collection_name = 'assignments' if (q.get('kind') == 'assignment' or q.get('metadata', {}).get('kind') == 'assignment') else 'AIquizzes'
            subs_count = 0
            total_scores = 0.0
            total_max = 0.0
            try:
                if fs is not None:
                    subs = list(fs.collection(collection_name).document(qid).collection('submissions').stream())
                    subs_count = len(subs)
                    for sdoc in subs:
                        s = sdoc.to_dict() or {}
                        total_scores += float(s.get('score') or 0)
                        if s.get('max_total') is not None:
                            total_max += float(s.get('max_total') or 0)
                        else:
                            def _default_max(t):
                                t = (t or '').lower()
                                return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))
                            total_max += sum(float(qq.get('max_score') or _default_max(qq.get('type'))) for qq in (q.get('questions') or []))
            except Exception:
                pass
            avg_pct = (total_scores / total_max * 100.0) if total_max > 0 else None
            items.append({
                'id': qid,
                'title': q.get('title') or q.get('metadata', {}).get('source_file') or 'Untitled',
                'kind': q.get('kind') or q.get('metadata', {}).get('kind') or 'quiz',
                'created_at': str(q.get('created_at') or ''),
                'questions_count': len(q.get('questions', []) or []),
                'submissions_count': subs_count,
                'average_percent': avg_pct,
            })
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'items': []}), 500


@app.get('/api/teacher/quizzes/<quiz_id>/submissions')
def api_teacher_quiz_submissions(quiz_id: str):
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({'success': True, 'submissions': []})
    try:
        quiz = get_quiz_by_id(quiz_id)
        if not quiz:
            return jsonify({'success': False, 'error': 'quiz_not_found'}), 404
        questions_map = {q.get('id'): q for q in (quiz.get('questions') or []) if q.get('id')}
        collection_name = 'assignments' if quiz.get('metadata', {}).get('kind') == 'assignment' else 'AIquizzes'
        ref = fs.collection(collection_name).document(quiz_id).collection('submissions')
        try:
            if Query is not None:
                docs = ref.order_by('submitted_at', direction=Query.DESCENDING).stream()
            else:
                docs = ref.stream()
        except Exception:
            docs = ref.stream()
        out = []
        for doc in docs:
            s = doc.to_dict() or {}
            grading_items = s.get('grading_items') or []
            grade_map = {}
            try:
                for gi in grading_items:
                    qid0 = gi.get('question_id') or gi.get('id')
                    if qid0:
                        grade_map[str(qid0)] = gi
            except Exception:
                grade_map = {}
            answers = []
            for qid, resp in (s.get('answers') or {}).items():
                qd = questions_map.get(qid) or {}
                correct = (
                    qd.get('answer')
                    or qd.get('correct_answer')
                    or qd.get('reference_answer')
                    or qd.get('expected_answer')
                    or qd.get('ideal_answer')
                )
                is_correct = None
                if (qd.get('type') or '').lower() in ('mcq','true_false') and correct is not None:
                    is_correct = str(resp).strip().lower() == str(correct).strip().lower()
                def _default_max(t):
                    t = (t or '').lower()
                    return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))
                gi = grade_map.get(str(qid)) or {}
                q_max = gi.get('max_score') if gi.get('max_score') is not None else gi.get('max')
                if q_max is None:
                    q_max = qd.get('max_score') if qd.get('max_score') is not None else _default_max(qd.get('type'))
                q_score = gi.get('score')
                if q_score is None and is_correct is not None:
                    q_score = q_max if is_correct else 0
                answers.append({
                    'question_id': qid,
                    'prompt': qd.get('prompt') or qd.get('question_text'),
                    'type': qd.get('type'),
                    'response': resp,
                    'correct_answer': correct,
                    'is_correct': is_correct,
                    'score': q_score,
                    'max_score': q_max,
                    'feedback': gi.get('feedback') if isinstance(gi, dict) else None,
                })
            out.append({
                'id': doc.id,
                'student_name': s.get('student_name') or s.get('name') or 'Anonymous',
                'student_email': s.get('student_email') or s.get('email') or 'N/A',
                'score': s.get('score', 0),
                'max_total': s.get('max_total'),
                'total_questions': s.get('total_questions', len(questions_map)),
                'submitted_at': str(s.get('submitted_at') or ''),
                'answers': answers,
                'grading_items': grading_items,
            })
        return jsonify({'success': True, 'quiz_id': quiz_id, 'submissions': out})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===============================
# HEALTH
# ===============================
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

# ===============================
# QUIZ GEN API (unchanged)
# ===============================
@app.route("/api/quiz/from-pdf", methods=["POST"])
def quiz_from_pdf():
    """
    Generate quiz from uploaded PDF. Returns quiz JSON and saves via services/db.py.
    """
    try:
        if "file" not in request.files:
            return ("Missing file (multipart field 'file')", 400)

        file = request.files["file"]
        if not file or file.filename == "":
            return ("Empty file", 400)

        if not (file.mimetype == "application/pdf" or file.filename.lower().endswith(".pdf")):
            return ("Only PDF accepted (.pdf)", 400)

        options_raw = request.form.get("options")
        if not options_raw:
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

        dist = options.get("distribution", {})
        
        # CRITICAL FIX: Get the kind from options (assignment or quiz)
        kind = options.get("kind", "quiz")  # Default to quiz if not specified
        print(f"📝 Generating {kind} from PDF")

        text = extract_pdf_text(file)
        if not text or not text.strip():
            return ("Could not extract text from PDF", 400)

        chunks = split_into_chunks(text)

        mix_counts = {}
        if diff_mode == "custom":
            mix_counts = _allocate_counts(
                total=num_questions,
                easy=int(diff.get("easy", 30)),
                med=int(diff.get("medium", 50)),
                hard=int(diff.get("hard", 20)),
            )

        user_prompt = build_user_prompt(
            pdf_chunks=chunks,
            num_questions=num_questions,
            qtypes=qtypes,
            difficulty_mode=diff_mode,
            mix_counts=mix_counts,
            type_targets=dist
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

        source_file = file.filename if file and file.filename else "PDF Upload"

        result = {
            "title": source_file,
            "questions": questions,
            "metadata": {
                "model": "llama-3.3-70b-versatile",
                "difficulty_mode": diff_mode,
                "counts_requested": {
                    "total": num_questions,
                    **({
                        "easy": mix_counts.get("easy"),
                        "medium": mix_counts.get("medium"),
                        "hard": mix_counts.get("hard"),
                    } if diff_mode == "custom" else {})
                },
                "source_note": llm_json.get("source_note", ""),
                "source_file": source_file,
                "kind": kind  # CRITICAL: Set the kind from the options
            }
        }

        quiz_id = save_quiz_to_store(result)
        result["metadata"]["quiz_id"] = quiz_id

        print(f"✅ Saved {kind} with ID: {quiz_id}")
        return jsonify(result), 200

    except Exception as e:
        print(f"❌ Error in quiz_from_pdf: {e}")
        return (f"Server error: {str(e)}", 500)

# ===============================
# SUBTOPICS API (unchanged)
# ===============================
@app.route("/api/custom/extract-subtopics", methods=["POST"])
def extract_subtopics():
    if "file" not in request.files:
        return jsonify({"error": "Missing file (multipart field 'file')"}), 400

    uploaded_file = request.files['file']
    file_name = uploaded_file.filename or "uploaded_content.txt"

    try:
        raw_text = extract_pdf_text(uploaded_file)
        if not raw_text or len(raw_text.strip()) < 50:
            return jsonify({"error": "Could not extract sufficient text from file. Please ensure it's a valid PDF/Text document."}), 400

        upload_id = str(uuid.uuid4())
        _SUBTOPIC_UPLOADS[upload_id] = {'text': raw_text, 'file_name': file_name}

        text_chunks = split_into_chunks(raw_text)
        sample_text = "\n\n".join(text_chunks[:2]) if len(text_chunks) > 0 else raw_text[:4000]

        try:
            subtopics_llm_output = extract_subtopics_llm(
                doc_text=sample_text,
                api_key=GROQ_API_KEY,
                n=10
            )
        except Exception as e:
            print(f"❌ Error in extract_subtopics_llm: {e}")
            lines = [ln.strip() for ln in sample_text.splitlines() if ln.strip()]
            heads = [ln for ln in lines if re.match(r"^\s*\d+[\.\)]\s+\w+", ln) or len(ln.split()) <= 6]
            subtopics_llm_output = list(dict.fromkeys(heads))[:10]

        if isinstance(subtopics_llm_output, dict) and subtopics_llm_output.get("subtopics"):
            subs = subtopics_llm_output["subtopics"]
        elif isinstance(subtopics_llm_output, list):
            subs = subtopics_llm_output
        else:
            subs = []
            if isinstance(subtopics_llm_output, dict):
                for key in ["items", "list", "topics", "subtopics"]:
                    if key in subtopics_llm_output and isinstance(subtopics_llm_output[key], list):
                        subs = [str(x).strip() for x in subtopics_llm_output[key] if str(x).strip()]
                        break
            if not subs:
                lines = [ln.strip() for ln in sample_text.splitlines() if ln.strip()]
                heads = [ln for ln in lines if re.match(r"^\s*\d+[\.\)]\s+\w+", ln) or len(ln.split()) <= 6]
                subs = list(dict.fromkeys(heads))[:10]

        return jsonify({
            "success": True,
            "upload_id": upload_id,
            "subtopics": subs,
            "source_file": file_name,
        }), 200

    except Exception as e:
        print(f"❌ Error in extract_subtopics: {e}")
        return jsonify({"error": f"Server error during subtopic extraction: {str(e)}"}), 500


@app.route("/api/custom/quiz-from-subtopics", methods=["POST"])
def quiz_from_subtopics():
    try:
        payload = request.get_json() or {}
        upload_id = payload.get("upload_id")
        chosen = payload.get("subtopics", [])
        totals = payload.get("totals", {})
        is_assignment = bool(payload.get("is_assignment"))

        difficulty = payload.get("difficulty", {})
        difficulty_mode = difficulty.get('mode', 'auto') if isinstance(difficulty, dict) else difficulty

        if not upload_id or upload_id not in _SUBTOPIC_UPLOADS:
            return jsonify({"error": "Invalid or expired upload_id; run subtopic detection again."}), 400
        if not chosen:
            return jsonify({"error": "No subtopics provided"}), 400

        total_requested = sum(int(v) for v in totals.values()) if isinstance(totals, dict) else 0
        if total_requested <= 0:
            return jsonify({"error": "Totals must request at least 1 question across types."}), 400

        uploaded_data = _SUBTOPIC_UPLOADS[upload_id]
        full_text = uploaded_data['text']
        source_file = uploaded_data['file_name']

        out = generate_quiz_from_subtopics_llm(
            full_text=full_text,
            chosen_subtopics=chosen,
            totals={k: int(v) for k, v in totals.items()},
            difficulty=difficulty,
            api_key=GROQ_API_KEY
        )

        questions = out.get("questions", [])
        if not questions:
            error_message = out.get('error', "LLM generated an empty or invalid quiz structure.")
            return jsonify({"error": f"Quiz generation failed: {error_message}"}), 500

        quiz_data = {
            "title": source_file,
            "questions": questions,
            "metadata": {
                "source": "subtopics",
                "upload_id": upload_id,
                "source_file": source_file,
                "selected_subtopics": chosen,
                "totals_requested": totals,
                "difficulty": difficulty,
                "kind": "assignment" if is_assignment else "quiz",
                "total_questions": len(questions)
            }
        }

        quiz_id = save_quiz_to_store(quiz_data)

        resp = {
            "success": True,
            "quiz_id": quiz_id,
            "title": source_file,
            "questions": questions,
            "metadata": quiz_data["metadata"],
            "message": "Quiz generated successfully."
        }

        if upload_id in _SUBTOPIC_UPLOADS:
            del _SUBTOPIC_UPLOADS[upload_id]

        return jsonify(resp), 200

    except Exception as e:
        print(f"❌ Error in quiz_from_subtopics: {e}")
        return jsonify({"error": f"Server error during quiz generation: {str(e)}"}), 500


@app.route("/generate-question", methods=["POST"])
def auto_generate_quiz():
    try:
        payload = request.get_json() or {}
        topic_text = (payload.get("topic_text") or "").strip()
        totals = payload.get("totals", {})
        is_assignment = bool((payload or {}).get("is_assignment"))

        if not topic_text:
            return jsonify({"error": "Please enter a topic or text to generate a quiz."}), 400

        total_requested = sum(int(v) for v in totals.values()) if isinstance(totals, dict) else 0
        if total_requested <= 0:
            return jsonify({"error": "Totals must request at least 1 question across types."}), 400

        out = generate_quiz_from_subtopics_llm(
            full_text=topic_text,
            chosen_subtopics=[topic_text[:50] + "..."],
            totals={k: int(v) for k, v in totals.items()},
            difficulty="auto",
            api_key=GROQ_API_KEY
        )

        questions = out.get("questions", [])
        if not questions:
            error_message = out.get('error', "LLM generated an empty or invalid quiz structure.")
            return jsonify({"error": f"AI-Powered Quiz generation failed: {error_message}"}), 500

        quiz_data = {
            "title": topic_text,
            "questions": questions,
            "metadata": {
                "source": "auto-topic",
                "source_file": topic_text,
                "totals_requested": totals,
                "difficulty": "auto",
                "kind": "assignment" if is_assignment else "quiz",
                "total_questions": len(questions)
            }
        }

        quiz_id = save_quiz_to_store(quiz_data)
        return jsonify({"success": True, "quiz_id": quiz_id, "questions_count": len(questions)}), 200

    except Exception as e:
        print(f"❌ Error in auto_generate_quiz: {e}")
        return jsonify({"error": f"Server error during quiz generation: {str(e)}"}), 500


# ===============================
# PUBLISH / VIEW API (for UI flow)
# ===============================
@app.route("/api/quizzes/<quiz_id>/publish", methods=["POST"])
def publish_quiz(quiz_id):
    quiz = get_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({"ok": False, "error": "Quiz not found"}), 404

    quiz["published"] = True
    quiz["published_at"] = datetime.utcnow().isoformat() + "Z"
    quiz["publish_url"] = f"/quiz/{quiz_id}"

    save_quiz_to_store(quiz)

    return jsonify({
        "ok": True,
        "quiz_id": quiz_id,
        "publish_url": quiz["publish_url"],
        "published_at": quiz["published_at"]
    }), 200


@app.post("/api/quizzes")
def api_create_quiz():
    data = request.get_json(force=True) or {}
    items = data.get("items") or []

    questions = []
    for i, it in enumerate(items):
        qtype = (it.get("type") or "").strip().lower()
        if qtype in ("tf", "truefalse", "true_false"):
            qtype = "true_false"
        elif qtype in ("mcq", "multiple_choice"):
            qtype = "mcq"
        elif qtype in ("short", "short_answer", "saq"):
            qtype = "short"
        else:
            qtype = "mcq"

        q = {
            "type": qtype,
            "prompt": it.get("prompt") or it.get("question_text") or "",
            "difficulty": it.get("difficulty"),
            "order": i
        }
        if qtype in ("mcq", "true_false"):
            q["options"] = it.get("options") or []
            q["answer"] = it.get("answer")
        else:
            q["answer"] = it.get("answer")

        questions.append(q)

    quiz_dict = {
        "title": data.get("title") or "Untitled Quiz",
        "questions": questions,
        "metadata": data.get("metadata") or {},
        "created_at": datetime.utcnow()
    }

    quiz_id = save_quiz_to_store(quiz_dict)
    return jsonify({"id": quiz_id, "title": quiz_dict["title"]}), 201


@app.route("/api/quizzes", methods=["GET"])
def api_list_quizzes():
    kind = request.args.get("kind")
    quizzes = list_quizzes(kind=kind)
    return jsonify({
        "success": True,
        "items": quizzes,
        "kind": kind or "all",
    })


@app.post("/api/quizzes/<quiz_id>/publish")
def api_publish_quiz(quiz_id):
    return jsonify({"quiz_id": quiz_id, "status": "published"}), 200



#>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
@app.route('/student-test')
def student_test():
    """Test version that shows ALL items as potential assignments"""
    try:
        all_items = list_quizzes(kind=None) or []
        
        # Show everything as assignments for testing
        assignments = []
        for it in all_items:
            item_id = it.get("id")
            if item_id:
                assignments.append({
                    "id": item_id,
                    "title": it.get("title") or "Untitled Item",
                    "questions_count": len(it.get("questions", [])),
                    "actual_kind": it.get('metadata', {}).get('kind', 'missing')
                })

        return render_template('student_index.html',
                               quizzes=[],
                               assignments=assignments,
                               error=None,
                               student_name="Student")

    except Exception as e:
        return render_template('student_index.html',
                               quizzes=[],
                               assignments=[],
                               error=f"Failed to load items: {e}",
                               student_name="Student")





@app.route("/api/create-test-assignment")
def create_test_assignment():
    """Create a test assignment with proper kind metadata"""
    try:
        test_assignment = {
            "title": "Test Programming Assignment - Python Functions",
            "questions": [
                {
                    "id": "q1",
                    "type": "short",
                    "prompt": "Write a Python function that reverses a string without using built-in reverse functions.",
                    "difficulty": "medium"
                },
                {
                    "id": "q2", 
                    "type": "short",
                    "prompt": "Explain the time and space complexity of your solution.",
                    "difficulty": "hard"
                }
            ],
            "metadata": {
                "kind": "assignment",  # THIS IS CRITICAL
                "source": "test",
                "created_at": datetime.utcnow().isoformat(),
                "total_questions": 2
            }
        }
        
        assignment_id = save_quiz_to_store(test_assignment)
        return jsonify({
            "success": True,
            "assignment_id": assignment_id,
            "message": "Test assignment created with proper kind='assignment'"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    




@app.route("/api/fix-missing-assignments")
def fix_missing_assignments():
    """Temporary fix: Find items that should be assignments and update their kind"""
    try:
        all_items = list_quizzes(kind=None) or []
        fixed_count = 0
        
        for item in all_items:
            item_id = item.get("id")
            current_kind = item.get('metadata', {}).get('kind', 'quiz')
            
            # If kind is missing or quiz, but it has assignment-like content
            if current_kind == 'quiz':
                title = item.get("title", "").lower()
                questions = item.get("questions", [])
                
                # Check if it should be an assignment
                should_be_assignment = (
                    'assignment' in title or
                    any(q.get('type') in ['short', 'essay', 'code'] for q in questions)
                )
                
                if should_be_assignment:
                    # Update the kind to assignment
                    item['metadata']['kind'] = 'assignment'
                    save_quiz_to_store(item)  # This should update the item
                    fixed_count += 1
                    print(f"✅ Fixed: {item_id} -> assignment")
        
        return jsonify({
            "success": True,
            "fixed_count": fixed_count,
            "message": f"Fixed {fixed_count} items to be assignments"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    






@app.route("/api/debug/all-items")
def debug_all_items():
    """See EVERYTHING in the database and their kinds"""
    try:
        all_items = list_quizzes(kind=None) or []
        items_info = []
        
        for item in all_items:
            items_info.append({
                "id": item.get("id"),
                "title": item.get("title", "No Title"),
                "kind": item.get('metadata', {}).get('kind', 'MISSING KIND'),
                "questions_count": len(item.get("questions", [])),
                "metadata": item.get("metadata", {})
            })
        
        return jsonify({
            "total_items": len(all_items),
            "items": items_info
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================
# STUDENT GRADE DETAIL (quizzes + assignments)
# ===============================
@app.get('/student/grade/<submission_id>')
def student_grade_detail(submission_id: str):
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return redirect(url_for('student_index'))
    try:
        found = None
        quiz_title = 'Submitted Grade'
        total = 0.0
        rows = []
        max_total = None
        q = None
        s = None
        collection_name = None

        # Fast path via quiz_id hint
        quiz_id_hint = request.args.get('quiz_id')
        if quiz_id_hint:
            quiz_obj = get_quiz_by_id(quiz_id_hint)
            if quiz_obj:
                q = quiz_obj
                collection_name = 'assignments' if quiz_obj.get('metadata', {}).get('kind') == 'assignment' else 'AIquizzes'
                quiz_title = quiz_obj.get('title') or quiz_obj.get('metadata', {}).get('source_file') or quiz_title
                subref = fs.collection(collection_name).document(quiz_id_hint).collection('submissions').document(submission_id)
                sub = subref.get()
                if sub.exists:
                    s = sub.to_dict() or {}
                    found = s

        # Look for submission across AIquizzes and assignments (fallback)
        if not found:
            for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                q = qdoc.to_dict() or {}
                title = (
                    q.get('title')
                    or q.get('metadata', {}).get('source_file')
                    or ('Assignment' if collection_name == 'assignments' else 'AI Generated Quiz')
                )
                subref = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id)
                sub = subref.get()
                if not sub.exists:
                    continue
                s = sub.to_dict() or {}

                # Auto-refresh this submission if it has no grading_items yet
                if grader is not None and not (s.get('grading_items') or []):
                    try:
                        answers = s.get('answers') or {}
                        def _default_max(t):
                            t = (t or '').lower()
                            return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))
                        quiz_for_grader = dict(q)
                        qlist = []
                        for qq in (q.get('questions') or []):
                            d = dict(qq)
                            if 'answer' not in d:
                                for key in ['answer','correct_answer','reference_answer','expected_answer','ideal_answer','solution','model_answer']:
                                    if d.get(key) is not None:
                                        d['answer'] = d.get(key)
                                        break
                            if 'max_score' not in d or d.get('max_score') is None:
                                d['max_score'] = _default_max(d.get('type'))
                            qlist.append(d)
                        quiz_for_grader['questions'] = qlist
                        result = grader.grade_quiz(quiz=quiz_for_grader, responses=answers, policy=os.getenv('GRADING_POLICY','balanced'))
                        fs.collection(collection_name).document(qid).collection('submissions').document(submission_id).update({
                            'score': result.get('total_score', 0),
                            'max_total': result.get('max_total'),
                            'grading_items': result.get('items') or [],
                        })
                        s['score'] = result.get('total_score', 0)
                        s['max_total'] = result.get('max_total')
                        s['grading_items'] = result.get('items') or []
                    except Exception:
                        pass

                found = s
                quiz_title = title

                # Build rows from stored grading if present
                items = s.get('grading_items') or []
                answers = s.get('answers') or {}
                def _default_max(t):
                    t = (t or '').lower()
                    return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))
                # compute total if needed
                total = 0.0
                for qq in (q.get('questions') or []):
                    total += float(qq.get('max_score') or _default_max(qq.get('type')))
                max_total = s.get('max_total') or total

                if items:
                    # join items with quiz prompts
                    by_id = {qq.get('id'): qq for qq in (q.get('questions') or [])}
                    for it in items:
                        qq = by_id.get(it.get('question_id')) or {}
                        expected_val = ''
                        qtype_low = (qq.get('type') or '').lower()
                        if qtype_low in ('mcq','true_false'):
                            ans = qq.get('answer') if qq.get('answer') is not None else qq.get('correct_answer')
                            opts = qq.get('options') or []
                            if isinstance(ans, str) and len(ans) == 1 and ans.upper() in ('A','B','C','D') and opts:
                                idx_map = {'A':0,'B':1,'C':2,'D':3}
                                i = idx_map.get(ans.upper())
                                if i is not None and i < len(opts):
                                    expected_val = f"{ans.upper()}) {opts[i]}"
                                else:
                                    expected_val = str(ans)
                            elif (isinstance(ans, int) or (isinstance(ans, str) and ans.isdigit())) and opts:
                                try:
                                    n = int(ans)
                                    i = n-1 if 1 <= n <= len(opts) else (n if 0 <= n < len(opts) else None)
                                    if i is not None:
                                        letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                                        letter = letters[i] if i < len(letters) else ''
                                        expected_val = f"{letter}) {opts[i]}" if letter else str(opts[i])
                                    else:
                                        expected_val = str(ans)
                                except Exception:
                                    expected_val = str(ans)
                            else:
                                expected_val = str(ans or '')
                        else:
                            for key in ['answer','reference_answer','expected_answer','ideal_answer','solution','model_answer']:
                                if qq.get(key):
                                    expected_val = str(qq.get(key))
                                    break
                            if not expected_val and it.get('expected'):
                                expected_val = str(it.get('expected'))

                        student_val = answers.get(it.get('question_id'))
                        if qtype_low in ('mcq','true_false') and qq.get('options'):
                            opts = qq.get('options')
                            if isinstance(student_val, str) and len(student_val)==1 and student_val.upper() in ('A','B','C','D'):
                                idx_map = {'A':0,'B':1,'C':2,'D':3}
                                j = idx_map.get(student_val.upper())
                                if j is not None and j < len(opts):
                                    student_val = f"{student_val.upper()}) {opts[j]}"
                            elif isinstance(student_val, int) or (isinstance(student_val, str) and student_val.isdigit()):
                                try:
                                    n = int(student_val)
                                    j = n-1 if 1 <= n <= len(opts) else (n if 0 <= n < len(opts) else None)
                                    if j is not None:
                                        letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                                        letter = letters[j] if j < len(letters) else ''
                                        student_val = f"{letter}) {opts[j]}" if letter else str(opts[j])
                                except Exception:
                                    pass
                        rows.append({
                            'prompt': qq.get('prompt') or qq.get('question_text') or '(no prompt)',
                            'student_answer': student_val,
                            'expected': expected_val,
                            'verdict': it.get('verdict'),
                            'is_correct': it.get('is_correct'),
                            'score': it.get('score'),
                            'max_score': it.get('max_score'),
                        })
                else:
                    # fallback rows from answers and quiz
                    for qq in (q.get('questions') or []):
                        qid2 = qq.get('id')
                        student_ans = answers.get(qid2)
                        expected = qq.get('answer') if qq.get('type') in ('mcq','true_false') else ''
                        verdict = None
                        is_correct = None
                        score = 0
                        maxs = float(qq.get('max_score') or _default_max(qq.get('type')))
                        if qq.get('type') in ('mcq','true_false') and expected is not None:
                            is_correct = str(student_ans).strip().lower() == str(expected).strip().lower()
                            verdict = 'correct' if is_correct else 'incorrect'
                            score = maxs if is_correct else 0
                        if (qq.get('type') or '').lower()=='mcq' and qq.get('options'):
                            opts = qq.get('options')
                            idx_map = {'A':0,'B':1,'C':2,'D':3}
                            if isinstance(expected, str) and len(expected)==1 and expected.upper() in idx_map:
                                i = idx_map.get(expected.upper())
                                if i is not None and i < len(opts):
                                    expected = f"{expected.upper()}) {opts[i]}"
                            elif isinstance(expected, int) or (isinstance(expected, str) and expected.isdigit()):
                                try:
                                    n = int(expected)
                                    i = n-1 if 1 <= n <= len(opts) else (n if 0 <= n < len(opts) else None)
                                    if i is not None:
                                        letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                                        letter = letters[i] if i < len(letters) else ''
                                        expected = f"{letter}) {opts[i]}" if letter else str(opts[i])
                                except Exception:
                                    pass
                            if isinstance(student_ans, str) and len(student_ans)==1 and student_ans.upper() in idx_map:
                                j = idx_map.get(student_ans.upper())
                                if j is not None and j < len(opts):
                                    student_ans = f"{student_ans.upper()}) {opts[j]}"
                            elif isinstance(student_ans, int) or (isinstance(student_ans, str) and student_ans.isdigit()):
                                try:
                                    n = int(student_ans)
                                    j = n-1 if 1 <= n <= len(opts) else (n if 0 <= n < len(opts) else None)
                                    if j is not None:
                                        letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                                        letter = letters[j] if j < len(letters) else ''
                                        student_ans = f"{letter}) {opts[j]}" if letter else str(opts[j])
                                except Exception:
                                    pass
                        rows.append({
                            'prompt': qq.get('prompt') or qq.get('question_text') or '(no prompt)',
                            'student_answer': student_ans,
                            'expected': expected,
                            'verdict': verdict,
                            'is_correct': is_correct,
                            'score': score,
                            'max_score': maxs,
                        })
                break
            if found:
                break

        if not found:
            return redirect(url_for('student_index'))

        # Compute display score from rows if available
        try:
            display_score = sum(float(r.get('score') or 0) for r in rows)
        except Exception:
            display_score = float(found.get('score', 0) or 0)

        return render_template(
            'grade_detail.html',
            quiz_title=quiz_title,
            score=display_score,
            total=total,
            max_total=max_total,
            submission_id=submission_id,
            submitted_at=str(found.get('submitted_at') or ''),
            rows=rows,
        )
    except Exception:
        return redirect(url_for('student_index'))


# ===============================
# RE-GRADE API (quizzes + assignments)
# ===============================
@app.post('/api/submissions/<submission_id>/regrade')
def api_regrade_submission(submission_id: str):
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": False, "error": "firestore_disabled"}), 400
    try:
        target = None
        qdoc_match = None
        collection_match = None
        # find submission and its parent
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                sub = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id).get()
                if sub.exists:
                    target = sub.to_dict() or {}
                    qdoc_match = qdoc
                    collection_match = collection_name
                    break
            if target:
                break

        if not target or not qdoc_match or not collection_match:
            return jsonify({"success": False, "error": "submission_not_found"}), 404

        quiz = qdoc_match.to_dict() or {}
        answers = target.get('answers') or {}

        def _default_max(t):
            t = (t or '').lower()
            return 1 if t in ('mcq','true_false') else (3 if t=='short' else (5 if t=='long' else 1))

        quiz_for_grader = dict(quiz)
        qlist = []
        for q in (quiz.get('questions') or []):
            qq = dict(q)
            if 'answer' not in qq:
                for key in ['answer','correct_answer','reference_answer','expected_answer','ideal_answer','solution','model_answer']:
                    if qq.get(key) is not None:
                        qq['answer'] = qq.get(key)
                        break
            if 'max_score' not in qq or qq.get('max_score') is None:
                qq['max_score'] = _default_max(qq.get('type'))
            qlist.append(qq)
        quiz_for_grader['questions'] = qlist

        if grader is None:
            return jsonify({"success": False, "error": "grader_unavailable"}), 500

        result = grader.grade_quiz(
            quiz=quiz_for_grader,
            responses=answers,
            policy=os.getenv('GRADING_POLICY','balanced'),
        )

        fs.collection(collection_match).document(qdoc_match.id).collection('submissions').document(submission_id).update({
            'score': result.get('total_score', 0),
            'max_total': result.get('max_total'),
            'grading_items': result.get('items') or [],
        })

        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
