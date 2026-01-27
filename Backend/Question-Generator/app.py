import os
import re
import sys
import json
import uuid
import math
from datetime import datetime, timezone
from typing import Dict, List, Any
import importlib.util

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, redirect, url_for,session 
from flask_cors import CORS
# Add this after the groq_utils imports
from utils.assignment_utils import generate_advanced_assignments_llm
from utils.pdf_utils import SmartPDFProcessor
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import base64
from cryptography.hazmat.backends import default_backend


from services.db import (
    save_quiz as save_quiz_to_store,
    get_quiz_by_id,
    list_quizzes,
    save_submission as save_submission_to_store,
    get_submitted_quiz_ids,
    get_submissions_for_quiz
    # ADD THIS LINE:,# Assuming this function exists in services.db
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

# ===============================
# ENV / CONFIG
# ===============================
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("❌ GROQ_API_KEY is missing in environment (.env).")

# ===============================
# QUIZ GRADER (from quiz grading/)
# ===============================
GRADER_FILE = os.path.join(os.path.dirname(__file__), "quiz grading", "grader.py")
QUIZ_GRADING_DIR = os.path.dirname(GRADER_FILE)
if QUIZ_GRADING_DIR not in sys.path:
    sys.path.insert(0, QUIZ_GRADING_DIR)

grader = None
if os.path.exists(GRADER_FILE):
    try:
        spec = importlib.util.spec_from_file_location("quizgrading.grader", GRADER_FILE)
        grader_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grader_mod)
        QuizGrader = grader_mod.QuizGrader
        grader = QuizGrader(
            api_key=os.getenv("GROQ_API_KEY"),
            model=os.getenv("GROQ_MODEL"),
            default_policy=os.getenv("GRADING_POLICY", "balanced"),
        )
        print(f"✅ Quiz grader loaded from {GRADER_FILE}")
    except Exception as e:
        print(f"⚠️ Quiz grader failed to load: {e}")
else:
    print(f"⚠️ Grader file not found at {GRADER_FILE}; grading disabled.")

# ===============================
# APP
# ===============================
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_only_secret_change_me")
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ===============================
# GLOBAL MEMORY STORE
# ===============================
# Stores the raw text and metadata of uploaded files, keyed by a unique upload_id
# Format: {upload_id: {'text': raw_text, 'file_name': file_name}}
_SUBTOPIC_UPLOADS: Dict[str, Dict[str, str]] = {}

# ===============================
# HELPER FUNCTIONS
# ===============================
def _get_chunk_types_distribution(chunks_with_metadata: List[Dict[str, Any]]) -> Dict[str, int]:
    """Helper method to analyze chunk type distribution for FYP analysis."""
    distribution = {}
    for chunk in chunks_with_metadata:
        chunk_type = chunk.get('chunk_type', 'unknown')
        distribution[chunk_type] = distribution.get(chunk_type, 0) + 1
    return distribution

def _get_enhanced_fallback_subtopics(raw_text: str, document_analysis: Dict[str, Any]) -> List[str]:
    """
    Enhanced fallback subtopic extraction using document structure analysis.
    """
    subtopics = []
    
    # Method 1: Extract from page analysis
    for page in document_analysis.get('pages', []):
        if page.get('has_headings') and page.get('text'):
            lines = [line.strip() for line in page['text'].split('\n') if line.strip()]
            for line in lines:
                if _is_likely_heading(line) and line not in subtopics:
                    subtopics.append(line)
    
    # Method 2: Extract numbered sections
    numbered_sections = re.findall(r'\n\s*(\d+[\.\)]\s+[^\n]{5,50})', raw_text)
    subtopics.extend(numbered_sections[:5])
    
    # Method 3: Extract ALL CAPS headings
    all_caps_headings = re.findall(r'\n\s*([A-Z][A-Z\s]{5,30}[A-Z])\s*\n', raw_text)
    subtopics.extend(all_caps_headings[:3])
    
    # Method 4: Extract title case lines (potential section headers)
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    for line in lines[:50]:  # Check first 50 lines
        words = line.split()
        if 2 <= len(words) <= 8 and len(line) < 80:
            # Check if it's title case or has other heading characteristics
            if (any(word.istitle() for word in words if len(word) > 3) or 
                re.match(r'^\d+[\.\)]', line)):
                if line not in subtopics:
                    subtopics.append(line)
    
    # Remove duplicates and clean up
    unique_subtopics = list(dict.fromkeys([s.strip() for s in subtopics if s.strip()]))
    
    # Ensure we have some subtopics
    if not unique_subtopics:
        # Final fallback: use first sentences from important paragraphs
        paragraphs = [p.strip() for p in raw_text.split('\n\n') if len(p.strip()) > 50]
        for para in paragraphs[:5]:
            first_sentence = para.split('.')[0] + '.'
            if len(first_sentence) > 20 and len(first_sentence) < 100:
                unique_subtopics.append(first_sentence)
    
    return unique_subtopics[:10]

def _is_likely_heading(line: str) -> bool:
    """Helper function to detect likely headings."""
    line = line.strip()
    if len(line) < 80:
        patterns = [
            r'^\d+[\.\)]\s+\w+',
            r'^\b(?:CHAPTER|SECTION|ABSTRACT|INTRODUCTION|METHODOLOGY|RESULTS|CONCLUSION|REFERENCES)\b',
            r'^[A-Z][A-Z\s]{2,}[A-Z]$',
            r'^\s*\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*$',
        ]
        for pattern in patterns:
            if re.match(pattern, line, re.IGNORECASE):
                return True
        words = line.split()
        if 2 <= len(words) <= 8 and len(line) < 60:
            return True
    return False

def _default_max_score(qtype: str) -> float:
    q = (qtype or "").lower()
    if q in ("mcq", "true_false", "tf", "truefalse"):
        return 1.0
    if q == "short":
        return 3.0
    if q in ("long", "conceptual"):
        return 5.0
    return 1.0

def _prepare_quiz_for_grading(quiz: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize quiz structure for the grader: ensure answers/max_score are present."""
    quiz_for_grader = dict(quiz or {})
    normalized_questions: List[Dict[str, Any]] = []
    for q in quiz_for_grader.get("questions", []) or []:
        qq = dict(q)
        # Normalize answer field
        if qq.get("answer") is None:
            for key in ["correct_answer", "reference_answer", "expected_answer", "ideal_answer", "solution", "model_answer"]:
                if qq.get(key) is not None:
                    qq["answer"] = qq.get(key)
                    break
        # Default max_score when missing
        if qq.get("max_score") is None:
            qq["max_score"] = _default_max_score(qq.get("type"))
        normalized_questions.append(qq)
    quiz_for_grader["questions"] = normalized_questions
    return quiz_for_grader

def _ceil_score(val: Any) -> int:
    try:
        return int(math.ceil(float(val)))
    except Exception:
        return 0

def _humanize_datetime(val: Any) -> str:
    """Return a consistent, human-readable UTC timestamp string."""
    try:
        if isinstance(val, datetime):
            dt = val
        elif isinstance(val, str):
            # Normalize "Z" suffix to +00:00 for fromisoformat
            if val.endswith("Z"):
                val = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(val)
        else:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return ""

# ===============================
# LANDING (always open teacher/generate)
# ===============================
@app.route('/', methods=['GET'])
def root_redirect():
    """Always land on the teacher generation page."""
    return redirect(url_for('teacher_generate'))



#??????????????????????????????????????????????????????

def get_submissions_by_quiz_id(quiz_id: str) -> list:
    """
    Fetches all student submissions for a given quiz ID.
    (You need to implement the actual database logic here)
    """
    # Example placeholder return:
    # submissions = db.collection('submissions').where('quiz_id', '==', quiz_id).get()
    # return [doc.to_dict() for doc in submissions]
    return []
#????????????????????????????????????????????????????/
# LTI Launch Endpoint (MAIN)
# ===============================
# LTI CONFIGURATION (CLEAN VERSION)
# ===============================

# Generate RSA keys for LTI
def generate_rsa_keys():
    """Generate RSA key pair for LTI 1.3"""
    try:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        
        public_numbers = private_key.public_key().public_numbers()
        n_b64 = base64.urlsafe_b64encode(
            public_numbers.n.to_bytes(256, byteorder='big')
        ).decode('utf-8').rstrip('=')
        e_b64 = base64.urlsafe_b64encode(
            public_numbers.e.to_bytes(4, byteorder='big')
        ).decode('utf-8').rstrip('=')
        
        jwks_data = {
            "keys": [
                {
                    "kty": "RSA",
                    "alg": "RS256", 
                    "use": "sig",
                    "kid": "lti-key-1",
                    "n": n_b64,
                    "e": e_b64
                }
            ]
        }
        
        print("✅ LTI RSA keys generated")
        return jwks_data
        
    except Exception as e:
        print(f"⚠️ Using placeholder keys: {e}")
        return {
            "keys": [{
                "kty": "RSA",
                "alg": "RS256", 
                "use": "sig",
                "kid": "test-key",
                "n": "placeholder_n",
                "e": "AQAB"
            }]
        }

# Initialize LTI keys
LTI_JWKS = generate_rsa_keys()

# ===============================
# LTI ENDPOINTS (ONLY ONE OF EACH)
# ===============================

@app.route('/lti/login', methods=['GET', 'POST'])
def lti_login():
    """LTI Login Endpoint - ONLY ONE"""
    return """
    <h1>LTI Login</h1>
    <p>Ready for Moodle LTI 1.1</p>
    <p>Test: <a href="/lti/launch">Launch Endpoint</a></p>
    """

@app.route('/lti/launch', methods=['GET', 'POST'])
def lti_launch():
    """Main LTI Launch Endpoint - ONLY ONE"""
    try:
        if request.method == 'GET':
            return """
            <h1>AI Quiz Generator - LTI Ready</h1>
            <p><strong>Status:</strong> ✅ Active</p>
            <p><strong>Consumer Key:</strong> test_key</p>
            <p><strong>Shared Secret:</strong> test_secret</p>
            <p><a href="/teacher">Teacher Dashboard</a> | <a href="/student">Student Dashboard</a></p>
            """
        
        print("=" * 50)
        print("🎯 LTI LAUNCH FROM MOODLE")
        print("=" * 50)
        
        # Get LTI data
        lti_data = request.form
        
        # Store in session
        session['lti_user_id'] = lti_data.get('user_id', 'unknown')
        session['lti_roles'] = lti_data.get('roles', '')
        session['lti_course_id'] = lti_data.get('context_id', '')
        session['lti_context_title'] = lti_data.get('context_title', '')
        
        # Debug print
        print(f"👤 User: {session['lti_user_id']}")
        print(f"🎭 Roles: {session['lti_roles']}")
        print(f"📚 Course: {session['lti_course_id']}")
        
        # Print all parameters (for debugging)
        for key, value in lti_data.items():
            if value:
                print(f"   {key}: {value[:100]}{'...' if len(str(value)) > 100 else ''}")
        
        # Redirect based on role
                # Redirect based on role
        roles = session['lti_roles'].lower()
        if any(role in roles for role in ['instructor', 'teachingassistant', 'teacher', 'admin']):
            print("➡️ Redirecting to Teacher Interface")
            return redirect('/teacher/generate')  # Go DIRECTLY to teacher interface
        else:
            print("➡️ Redirecting to Student Dashboard")
            return redirect('/student')
            
    except Exception as e:
        print(f"❌ LTI Error: {str(e)}")
        return f"LTI Launch Error: {str(e)}", 400

@app.route('/.well-known/jwks.json', methods=['GET'])
def jwks():
    """Public JWKS endpoint for LTI 1.3 - ONLY ONE"""
    return jsonify(LTI_JWKS)



# ===============================
# BASIC HOME ROUTE
# ===============================
@app.route('/home')
def home():
    return '''
    <h1>AI Quiz Generator</h1>
    <p><strong>Status:</strong> ✅ Running</p>
    <p><a href="/teacher">Go to Teacher Dashboard</a></p>
    <p><a href="/student">Go to Student Dashboard</a></p>
    <p><a href="/lti/launch">Test LTI Launch</a></p>
    <p><a href="/.well-known/jwks.json">View JWKS</a></p>
    '''

# ===============================
# TEACHER DASHBOARD (Main Teacher Page)
# ===============================
# ===============================
# TEACHER DASHBOARD (Main Teacher Page)
# ===============================
@app.route('/teacher')
def teacher_index():
    """Main teacher dashboard - ALWAYS show teacher interface"""
    
    # Get user info from session or use defaults
    user_id = session.get('lti_user_id', 'Teacher')
    roles = session.get('lti_roles', 'Instructor')
    course = session.get('lti_context_title', 'Default Course')
    
    # Always redirect to the actual teacher interface
    return redirect(url_for('teacher_generate'))

# ===============================
# STUDENT ROUTES (no auth)
# ===============================
@app.route('/student')
def student_index():
    """Student dashboard - shows available quizzes"""
    
    # Get user info from session
    user_id = session.get('lti_user_id', 'Student')
    
    try:
        # Use LTI user ID for email if available
        student_email = f"{user_id}@example.com" if user_id != 'Student' else "student@example.com"
        submitted_quiz_ids = set(get_submitted_quiz_ids(student_email) or [])
        items = list_quizzes() or []
        quizzes = []
        for it in items:
            if it["id"] in submitted_quiz_ids:
                continue
            quizzes.append({
                "id": it["id"],
                "title": it.get("title") or "AI Generated Quiz",
                "questions_count": sum((it.get("counts") or {}).values()) if it.get("counts") else len(it.get("questions", [])),
                "created_at": it.get("created_at"),
            })
        return render_template('student_index.html', quizzes=quizzes, error=None, student_name=user_id)
    except Exception as e:
        print(f"❌ Error fetching student quiz list: {e}")
        return render_template('student_index.html', quizzes=[], error=f"Failed to load quizzes: {e}", student_name=user_id)


@app.route('/student/quiz/<quiz_id>', methods=['GET'])
def student_quiz(quiz_id):
    """Display quiz for student with a timer (no auth)."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return ("Quiz not found", 404)

    questions_for_student = [{
        'id': q.get('id'),
        'type': q.get('type'),
        'prompt': q.get('prompt') or q.get('question_text'),
        'options': q.get('options') if q.get('type') in ['mcq', 'true_false'] else None,
        'difficulty': q.get('difficulty'),
    } for q in quiz_data.get('questions', [])]

    title = quiz_data.get("title") or quiz_data.get("metadata", {}).get("source_file", f"Quiz #{quiz_id}")
    return render_template(
        'student_quiz.html',
        quiz_id=quiz_id,
        title=title,
        questions=questions_for_student,
        student_email="student@example.com",
        student_name="Student"
    )


@app.route('/student/submit', methods=['POST'])
def submit_quiz():
    """Handle student quiz submission (no auth)."""
    form_data = request.form
    quiz_id = form_data.get('quiz_id')

    if not quiz_id:
        return jsonify({"error": "Missing quiz ID"}), 400

    correct_quiz_data = get_quiz_by_id(quiz_id)
    if not correct_quiz_data:
        return jsonify({"error": "Quiz not found"}), 404

    total_questions = len(correct_quiz_data.get('questions', []))
    student_answers: Dict[str, str] = {}

    for q in correct_quiz_data.get('questions', []):
        q_id = q.get('id')
        if not q_id:
            continue
        student_answers[q_id] = (form_data.get(q_id) or '').strip()

    # Prefer AI grading when available; fallback to basic MCQ/TF scoring
    grading_items: List[Dict[str, Any]] = []
    max_total_calc = None
    score = 0
    if grader is not None:
        try:
            quiz_for_grader = _prepare_quiz_for_grading(correct_quiz_data)
            result = grader.grade_quiz(
                quiz=quiz_for_grader,
                responses=student_answers,
                policy=os.getenv("GRADING_POLICY", "balanced"),
            )
            score = _ceil_score(result.get('total_score', 0))
            grading_items = result.get('items') or []
            max_total_calc = result.get('max_total')
        except Exception as e:
            print(f"[quiz_grading] grading failed: {e}")
    else:
        for q in correct_quiz_data.get('questions', []):
            if q.get('type') in ['mcq', 'true_false'] and q.get('correct_answer') is not None:
                qid = q.get('id')
                if qid and str(student_answers.get(qid, "")).lower() == str(q.get('correct_answer')).lower():
                    score += 1
        score = _ceil_score(score)

    # In no-auth mode, use fixed student identity
    submission_data = {
        "email": "student@example.com",
        "name": "Student",
        "answers": student_answers,
        "score": score,
        "total_questions": total_questions,
        "grading_items": grading_items,
        "max_total": max_total_calc,
        "kind": "quiz_submission",
        "submitted_at": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
    }
    submission_id = save_submission_to_store(quiz_id, submission_data)

    return redirect(url_for('submission_confirmation', quiz_id=quiz_id, score=score, total=total_questions, submission_id=submission_id))


@app.route('/student/confirmation/<quiz_id>', methods=['GET'])
def submission_confirmation(quiz_id):
    """Display submission confirmation and score."""
    score_raw = request.args.get('score', 'N/A')
    total_raw = request.args.get('total', 'N/A')
    try:
        score = _ceil_score(score_raw)
        total = _ceil_score(total_raw)
    except Exception:
        score, total = score_raw, total_raw
    submission_id = request.args.get('submission_id', 'N/A')

    quiz_data = get_quiz_by_id(quiz_id)
    quiz_title = (quiz_data.get("title") if quiz_data else None) or \
                 (quiz_data.get("metadata", {}).get("source_file") if quiz_data else None) or \
                 "Submitted Quiz"

    return render_template(
        'submission_confirmation.html',
        quiz_title=quiz_title,
        score=score,
        total=total,
        submission_id=submission_id,
        student_name="Student"
    )

# ===============================
# GRADES + SUBMISSION APIs
# ===============================
@app.get('/api/grades')
def api_grades():
    """Return graded submissions for a student (requires Firestore)."""
    email_filter = (request.args.get('email') or '').strip()
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": True, "items": []})

    items = []
    try:
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                quiz = qdoc.to_dict() or {}
                title = (
                    quiz.get('title')
                    or quiz.get('metadata', {}).get('source_file')
                    or ('Assignment' if collection_name == 'assignments' else 'AI Generated Quiz')
                )

                # Pre-compute max score in case submissions are missing it
                max_total_default = 0.0
                for qq in quiz.get('questions', []) or []:
                    max_total_default += float(qq.get('max_score') or _default_max_score(qq.get('type')))

                subs_ref = (
                    fs.collection(collection_name)
                      .document(qid)
                      .collection('submissions')
                )
                if email_filter:
                    subs_ref = subs_ref.where('student_email', '==', email_filter)
                subs = subs_ref.stream()
                for sd in subs:
                    s = sd.to_dict() or {}

                    # Auto-grade if grader is available but submission lacks grading_items
                    if grader is not None and not (s.get('grading_items') or []):
                        try:
                            quiz_for_grader = _prepare_quiz_for_grading(quiz)
                            result = grader.grade_quiz(
                                quiz=quiz_for_grader,
                                responses=s.get('answers') or {},
                                policy=os.getenv("GRADING_POLICY", "balanced"),
                            )
                            fs.collection(collection_name).document(qid).collection('submissions').document(sd.id).update({
                                'score': _ceil_score(result.get('total_score', 0)),
                                'max_total': _ceil_score(result.get('max_total')) if result.get('max_total') is not None else None,
                                'grading_items': result.get('items') or [],
                            })
                            s['score'] = _ceil_score(result.get('total_score', 0))
                            s['max_total'] = _ceil_score(result.get('max_total')) if result.get('max_total') is not None else None
                            s['grading_items'] = result.get('items') or []
                        except Exception as e:
                            print(f"[api/grades] auto-grade failed: {e}")

                    items.append({
                        'id': sd.id,
                        'title': title,
                        'date': str(s.get('submitted_at') or ''),
                        'date_human': _humanize_datetime(s.get('submitted_at') or ''),
                        'score': _ceil_score(s.get('score') or 0),
                        'max_score': _ceil_score(s.get('max_total') or max_total_default),
                        'quiz_id': qid,
                        'student_email': s.get('student_email') or s.get('email') or '',
                        'student_name': s.get('student_name') or s.get('name') or '',
                        'kind': 'assignment' if collection_name == 'assignments' else 'quiz',
                    })
        items.sort(key=lambda x: str(x.get('date') or ''), reverse=True)
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": f"grades_list_failed: {e}"}), 500


@app.get('/api/submissions/<submission_id>')
def api_get_submission(submission_id: str):
    """Fetch a specific submission by ID (Firestore required)."""
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": False, "error": "firestore_disabled"}), 400
    try:
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                subref = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id)
                sub = subref.get()
                if not sub.exists:
                    continue
                s = sub.to_dict() or {}
                s["score"] = _ceil_score(s.get("score") or 0)
                s["max_total"] = _ceil_score(s.get("max_total") or 0)
                s["submitted_at_human"] = _humanize_datetime(s.get("submitted_at") or '')
                s["student_email"] = s.get("student_email") or s.get("email")
                s["student_name"] = s.get("student_name") or s.get("name")
                return jsonify({
                    "success": True,
                    "submission": s,
                    "quiz_id": qid,
                    "collection": collection_name,
                })
        return jsonify({"success": False, "error": "submission_not_found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.post('/api/submissions/<submission_id>/regrade')
def api_regrade_submission(submission_id: str):
    """Force regrading of a submission (Firestore required)."""
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": False, "error": "firestore_disabled"}), 400
    if grader is None:
        return jsonify({"success": False, "error": "grader_unavailable"}), 500
    try:
        target = None
        quiz = None
        collection_match = None
        quiz_id = None
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                sub = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id).get()
                if sub.exists:
                    target = sub.to_dict() or {}
                    quiz = qdoc.to_dict() or {}
                    collection_match = collection_name
                    quiz_id = qid
                    break
            if target:
                break

        if not target or not quiz or not collection_match:
            return jsonify({"success": False, "error": "submission_not_found"}), 404

        quiz_for_grader = _prepare_quiz_for_grading(quiz)
        result = grader.grade_quiz(
            quiz=quiz_for_grader,
            responses=target.get('answers') or {},
            policy=os.getenv('GRADING_POLICY', 'balanced'),
        )
        fs.collection(collection_match).document(quiz_id).collection('submissions').document(submission_id).update({
            'score': _ceil_score(result.get('total_score', 0)),
            'max_total': _ceil_score(result.get('max_total')) if result.get('max_total') is not None else None,
            'grading_items': result.get('items') or [],
        })

        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.get('/student/grade/<submission_id>')
def student_grade_detail(submission_id: str):
    """Render grade details page for a submission (Firestore required)."""
    origin = request.args.get('origin') or 'student'
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return redirect(url_for('student_index'))
    try:
        found = None
        quiz_data = None
        collection_match = None
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                subref = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id)
                sub = subref.get()
                if not sub.exists:
                    continue
                found = sub.to_dict() or {}
                quiz_data = qdoc.to_dict() or {}
                collection_match = collection_name
                quiz_data["id"] = qid
                break
            if found:
                break

        if not found or not quiz_data:
            return redirect(url_for('student_index'))

        # Auto-grade if missing
        if grader is not None and not (found.get('grading_items') or []):
            try:
                quiz_for_grader = _prepare_quiz_for_grading(quiz_data)
                result = grader.grade_quiz(
                    quiz=quiz_for_grader,
                    responses=found.get('answers') or {},
                    policy=os.getenv("GRADING_POLICY", "balanced"),
                )
                fs.collection(collection_match).document(quiz_data["id"]).collection('submissions').document(submission_id).update({
                    'score': _ceil_score(result.get('total_score', 0)),
                    'max_total': _ceil_score(result.get('max_total')) if result.get('max_total') is not None else None,
                    'grading_items': result.get('items') or [],
                })
                found['score'] = _ceil_score(result.get('total_score', 0))
                found['max_total'] = _ceil_score(result.get('max_total')) if result.get('max_total') is not None else None
                found['grading_items'] = result.get('items') or []
            except Exception as e:
                print(f"[student/grade] auto-grade failed: {e}")

        rows = []
        total_max = 0.0
        by_id = {q.get('id'): q for q in (quiz_data.get('questions') or [])}
        for q in quiz_data.get('questions', []) or []:
            total_max += float(q.get('max_score') or _default_max_score(q.get('type')))
        total_max = _ceil_score(total_max)
        for item in found.get('grading_items') or []:
            qq = by_id.get(item.get('question_id')) or {}
            expected_val = ""
            if (qq.get('type') or '').lower() in ('mcq', 'true_false'):
                expected_val = qq.get('answer') if qq.get('answer') is not None else qq.get('correct_answer')
            else:
                for key in ["answer", "reference_answer", "expected_answer", "ideal_answer", "solution", "model_answer"]:
                    if qq.get(key):
                        expected_val = str(qq.get(key))
                        break
            rows.append({
                "prompt": qq.get('prompt') or qq.get('question_text') or '(no prompt)',
                "student_answer": (found.get('answers') or {}).get(item.get('question_id')),
                "expected": expected_val,
                "verdict": item.get('verdict'),
                "is_correct": item.get('is_correct'),
                "score": item.get('score'),
                "max_score": item.get('max_score'),
            })

        if rows:
            try:
                display_score = _ceil_score(sum(float(r.get('score') or 0) for r in rows))
            except Exception:
                display_score = found.get('score', 0)
        else:
            display_score = _ceil_score(found.get('score', 0))
        max_total_display = _ceil_score(found.get('max_total') or total_max)
        back_url = '/teacher/generate' if origin == 'teacher' else url_for('student_index')
        return render_template(
            'grade_detail.html',
            quiz_title=quiz_data.get('title') or quiz_data.get('metadata', {}).get('source_file') or "Submitted Grade",
            score=display_score,
            total=total_max,
            max_total=max_total_display,
            submission_id=submission_id,
            submitted_at=_humanize_datetime(found.get('submitted_at') or ''),
            student_email=found.get('student_email') or found.get('email') or '',
            student_name=found.get('student_name') or found.get('name') or '',
            back_url=back_url,
            rows=rows,
        )
    except Exception as e:
        print(f"[student/grade] failed: {e}")
        return redirect(url_for('student_index'))

# ===============================
# TEACHER ROUTES (no auth)
# ===============================


@app.route('/teacher/generate')
def teacher_generate():
    """Quiz generation page (no auth) — this is the landing page from '/'."""
    return render_template('index.html', teacher_name="Teacher")

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
        subs_raw = get_submissions_for_quiz(quiz_id) or []
        submissions = []
        graded_count = 0
        for s in subs_raw:
            score = _ceil_score(s.get("score") or 0)
            max_total = _ceil_score(s.get("max_total") or s.get("total_questions") or 0)
            graded = bool(s.get("grading_items")) or score > 0
            if graded:
                graded_count += 1
            submissions.append({
                "id": s.get("id"),
                "student_email": s.get("student_email") or s.get("email") or "N/A",
                "student_name": s.get("student_name") or s.get("name") or "",
                "score": score,
                "max_total": max_total,
                "status": s.get("status") or ("Graded" if graded else "Pending"),
                "submitted_at": _humanize_datetime(s.get("submitted_at") or ""),
                "is_graded": graded,
            })
        return render_template(
            'teacher_submissions.html',
            quiz_title=quiz_title,
            quiz_id=quiz_id,
            submissions=submissions,
            total_submissions=len(submissions),
            graded_count=graded_count,
        )
    except Exception as e:
        print(f"❌ Error fetching submissions: {e}")
        return ("Failed to load submissions.", 500)
    

#>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
@app.route("/api/quizzes/<quiz_id>", methods=["GET"])
def api_get_quiz(quiz_id):
    """Fetch a single quiz by ID as JSON for the frontend."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        # Important: Use consistent JSON response for errors
        return jsonify({"error": "Quiz not found"}), 404 

    # Ensure you return only the necessary data (the whole quiz object)
    return jsonify(quiz_data), 200

# ===============================
# HEALTH
# ===============================
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

# ===============================
# QUIZ GEN API
# ===============================
@app.route("/api/quiz/from-pdf", methods=["POST"])
def quiz_from_pdf():
    """
    Generate quiz from uploaded PDF. Returns quiz JSON and saves via services/db.py.
    Enhanced with smart adaptive chunking.
    """
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

        # Distribution (use as type_targets)
        dist = options.get("distribution", {})

        # ---- ENHANCED PDF PROCESSING ----
        processor = SmartPDFProcessor(
            max_chars=70000,
            target_chunk_size=3500,
            chunk_overlap=200
        )
        
        # Extract text with structure analysis
        text, document_analysis = processor.extract_pdf_text(file)
        if not text or not text.strip():
            return ("Could not extract text from PDF", 400)

        # Use adaptive chunking based on document structure
        chunks_with_metadata = processor.adaptive_chunking(text, document_analysis)
        chunks = [chunk['text'] for chunk in chunks_with_metadata]
        
        # Log chunking strategy for debugging and FYP analysis
        structure_score = document_analysis.get('structure_score', 0)
        chunking_strategy = chunks_with_metadata[0]['chunk_type'] if chunks_with_metadata else 'none'
        
        print(f"📊 PDF Analysis Results:")
        print(f"   - Structure Score: {structure_score:.2f}")
        print(f"   - Chunking Strategy: {chunking_strategy}")
        print(f"   - Total Pages: {document_analysis.get('total_pages', 0)}")
        print(f"   - Total Chunks: {len(chunks)}")
        print(f"   - Estimated Tokens: {document_analysis.get('estimated_tokens', 0)}")
        
        # ---- difficulty mix ----
        mix_counts = {}
        if diff_mode == "custom":
            mix_counts = _allocate_counts(
                total=num_questions,
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

        # Enhanced metadata with chunking information
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
                # Enhanced chunking metadata for FYP analysis
                "chunking_analysis": {
                    "structure_score": round(structure_score, 2),
                    "strategy_used": chunking_strategy,
                    "total_chunks": len(chunks),
                    "total_pages": document_analysis.get('total_pages', 0),
                    "estimated_tokens": document_analysis.get('estimated_tokens', 0),
                    "chunk_types_distribution": _get_chunk_types_distribution(chunks_with_metadata)
                }
            }
        }

        quiz_id = save_quiz_to_store(result)
        result["metadata"]["quiz_id"] = quiz_id

        # FYP Performance logging
        print(f"✅ Quiz Generation Complete:")
        print(f"   - Quiz ID: {quiz_id}")
        print(f"   - Questions Generated: {len(questions)}")
        print(f"   - Chunking Strategy: {chunking_strategy}")
        print(f"   - Structure Score: {structure_score:.2f}")

        return jsonify(result), 200

    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        return ("Model returned invalid JSON. Try reducing PDF length or rephrasing.", 502)
    except Exception as e:
        print(f"❌ Server Error in quiz_from_pdf: {e}")
        return (f"Server error: {str(e)}", 500)

@app.route("/api/custom/extract-subtopics", methods=["POST"])
def extract_subtopics():
    """
    Extract subtopics from uploaded PDF/text file with enhanced processing.
    """
    if "file" not in request.files:
        return jsonify({"error": "Missing file (multipart field 'file')"}), 400

    uploaded_file = request.files['file']
    file_name = uploaded_file.filename or "uploaded_content.txt"

    try:
        # 1. ENHANCED TEXT EXTRACTION WITH STRUCTURE ANALYSIS
        processor = SmartPDFProcessor(
            max_chars=70000,
            target_chunk_size=3500,
            chunk_overlap=200
        )
        
        raw_text, document_analysis = processor.extract_pdf_text(uploaded_file)
        if not raw_text or len(raw_text.strip()) < 50:
            return jsonify({"error": "Could not extract sufficient text from file. Please ensure it's a valid PDF/Text document."}), 400

        # 2. Store enhanced data for later quiz generation
        upload_id = str(uuid.uuid4())
        _SUBTOPIC_UPLOADS[upload_id] = {
            'text': raw_text, 
            'file_name': file_name,
            'analysis': document_analysis  # Store analysis for later use
        }

                # 3. ENHANCED SUBTOPIC EXTRACTION WITH ADAPTIVE CHUNKING
        # Use adaptive chunking to get the most relevant content for subtopic detection
        chunks_with_metadata = processor.adaptive_chunking(raw_text, document_analysis)
        
        # ✅ Smart sampling across the *whole* document for subtopic extraction
        total_chunks = len(chunks_with_metadata)
        sample_chunks: List[Dict[str, Any]] = []

        if total_chunks == 0:
            sample_chunks = []
        elif total_chunks <= 6:
            # Small PDF → use all chunks
            sample_chunks = chunks_with_metadata
        else:
            # Larger PDF → pick ~6 chunks spread from start to end
            num_samples = 6
            step = max(1, total_chunks // num_samples)

            indices = set()
            indices.add(0)                    # very beginning
            indices.add(total_chunks - 1)     # very end

            # middle positions
            for i in range(1, num_samples - 1):
                idx = i * step
                if 0 <= idx < total_chunks:
                    indices.add(idx)

            for idx in sorted(indices):
                sample_chunks.append(chunks_with_metadata[idx])

        sample_text = "\n\n".join(chunk['text'] for chunk in sample_chunks)

        # If we have section-based chunks, still prioritize those for subtopic extraction
        section_chunks = [chunk for chunk in chunks_with_metadata if chunk.get('chunk_type') == 'section']
        if section_chunks:
            # Use section headings as potential subtopics
            section_based_subtopics = [chunk.get('section', '') for chunk in section_chunks if chunk.get('section')]
            if section_based_subtopics:
                sample_text += "\n\nDocument Sections: " + ", ".join(section_based_subtopics)


        print(f"📊 Subtopic Extraction Analysis:")
        print(f"   - Structure Score: {document_analysis.get('structure_score', 0):.2f}")
        print(f"   - Total Pages: {document_analysis.get('total_pages', 0)}")
        print(f"   - Chunks Used: {len(sample_chunks)}")
        print(f"   - Sample Text Length: {len(sample_text)}")

        try:
            subtopics_llm_output = extract_subtopics_llm(
                doc_text=sample_text,
                api_key=GROQ_API_KEY,
                n=10
            )
        except Exception as e:
            print(f"❌ Error in extract_subtopics_llm: {e}")
            # ENHANCED FALLBACK: Use structure analysis for better fallback subtopics
            fallback_subtopics = _get_enhanced_fallback_subtopics(raw_text, document_analysis)
            subtopics_llm_output = fallback_subtopics

        # normalize LLM output
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
        
        # If LLM returned empty or insufficient subtopics, use enhanced fallback
        if not subs or len(subs) < 3:
            enhanced_subs = _get_enhanced_fallback_subtopics(raw_text, document_analysis)
            # Combine with any LLM results
            subs = list(dict.fromkeys(subs + enhanced_subs))[:10]

        # Remove duplicates and ensure reasonable length
        subs = list(dict.fromkeys([str(s).strip() for s in subs if str(s).strip()]))[:10]

        return jsonify({
            "success": True,
            "upload_id": upload_id,
            "subtopics": subs,
            "source_file": file_name,
            "analysis_metadata": {
                "structure_score": round(document_analysis.get('structure_score', 0), 2),
                "total_pages": document_analysis.get('total_pages', 0),
                "chunking_strategy": sample_chunks[0]['chunk_type'] if sample_chunks else 'none'
            }
        }), 200

    except Exception as e:
        print(f"❌ Error in extract_subtopics: {e}")
        return jsonify({"error": f"Server error during subtopic extraction: {str(e)}"}), 500

@app.route("/api/custom/quiz-from-subtopics", methods=["POST"])
def quiz_from_subtopics():
    """
    Generate quiz based on chosen subtopics and save (No auth).
    """
    try:
        payload = request.get_json() or {}
        upload_id = payload.get("upload_id")
        chosen = payload.get("subtopics", [])
        totals = payload.get("totals", {})
        is_assignment = bool(payload.get("is_assignment"))

        # Difficulty settings
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

        # 1) LLM generate
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

        # FIX: Return the proper structure that frontend expects
        resp = {
            "success": True,
            "quiz_id": quiz_id,
            "title": source_file,
            "questions": questions,
            "metadata": quiz_data["metadata"],
            "message": "Quiz generated successfully."
        }

        # Clean memory
        if upload_id in _SUBTOPIC_UPLOADS:
            del _SUBTOPIC_UPLOADS[upload_id]

        return jsonify(resp), 200

    except Exception as e:
        print(f"❌ Error in quiz_from_subtopics: {e}")
        return jsonify({"error": f"Server error during quiz generation: {str(e)}"}), 500

@app.route("/generate-question", methods=["POST"])
def auto_generate_quiz():
    """
    Generate a simple AI-Powered quiz based on a topic text (no PDF/subtopic workflow).
    (No auth)
    """
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
            full_text=topic_text,                   # use topic text as context
            chosen_subtopics=[topic_text[:50] + "..."],  # snippet for metadata display
            totals={k: int(v) for k, v in totals.items()},
            difficulty="auto",
            api_key=GROQ_API_KEY
        )

        questions = out.get("questions", [])
        if not questions:
            error_message = out.get('error', "LLM generated an empty or invalid quiz structure.")
            return jsonify({"error": f"AI-Powered Quiz generation failed: {error_message}"}), 500

        quiz_data = {
            "title": topic_text,  # name quiz with the topic text
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
        return jsonify({
        "success": True,
        "quiz_id": quiz_id,
        "questions_count": len(questions),
        "questions": questions,      # <-- this is what assignments.js needs
        "quiz": quiz_data,           # optional, but nice to have
    }), 200

    except Exception as e:
        print(f"❌ Error in auto_generate_quiz: {e}")
        return jsonify({"error": f"Server error during quiz generation: {str(e)}"}), 500
# ===============================
# ADVANCED ASSIGNMENT GENERATION
# ===============================
# app.py - Update the advanced assignment route

@app.route("/api/custom/advanced-assignment", methods=["POST"])
def generate_advanced_assignment():
    """
    Generate advanced assignment with multiple question types.
    """
    try:
        payload = request.get_json() or {}
        upload_id = payload.get("upload_id")
        chosen = payload.get("subtopics", [])
        task_distribution = payload.get("task_distribution", {})
        difficulty = payload.get("difficulty", "auto")

        if not upload_id or upload_id not in _SUBTOPIC_UPLOADS:
            return jsonify({"error": "Invalid or expired upload_id"}), 400
        
        if not chosen:
            return jsonify({"error": "No subtopics selected"}), 400
        
        total_tasks = sum(task_distribution.values())
        if total_tasks <= 0:
            return jsonify({"error": "Task distribution must have at least 1 task"}), 400

        uploaded_data = _SUBTOPIC_UPLOADS[upload_id]
        full_text = uploaded_data['text']
        source_file = uploaded_data['file_name']

        # Generate using enhanced function
        result = generate_advanced_assignments_llm(
            full_text=full_text,
            chosen_subtopics=chosen,
            task_distribution=task_distribution,
            api_key=GROQ_API_KEY,
            difficulty=difficulty
        )

        if not result.get("success"):
            error_detail = result.get("error", "Unknown error")
            raw_response = result.get("raw_response", "")
            
            # Provide more detailed error message
            error_msg = f"Assignment generation failed: {error_detail}"
            if raw_response:
                error_msg += f"\n\nRaw LLM response snippet: {raw_response[:500]}..."
            
            return jsonify({
                "error": error_msg,
                "details": error_detail
            }), 500

        questions = result["questions"]
        if not questions:
            return jsonify({
                "error": "LLM generated an empty assignment",
                "details": "No questions were generated"
            }), 500

        assignment_data = {
            "title": f"{source_file} - Advanced Assignment",
            "questions": questions,
            "metadata": {
                "source": "advanced-assignment",
                "upload_id": upload_id,
                "source_file": source_file,
                "selected_subtopics": chosen,
                "task_distribution": task_distribution,
                "difficulty": difficulty,
                "kind": "assignment",
                "total_tasks": len(questions)
            }
        }

        assignment_id = save_quiz_to_store(assignment_data)

        # Clean up
        if upload_id in _SUBTOPIC_UPLOADS:
            del _SUBTOPIC_UPLOADS[upload_id]

        return jsonify({
            "success": True,
            "assignment_id": assignment_id,
            "title": assignment_data["title"],
            "questions": questions,
            "metadata": assignment_data["metadata"]
        }), 200

    except Exception as e:
        print(f"❌ Error in generate_advanced_assignment: {e}")
        return jsonify({
            "error": str(e),
            "message": "Internal server error during assignment generation"
        }),  jsonify({"error": str(e)}), 500
    
@app.route("/api/custom/advanced-assignment-topics", methods=["POST"])
def generate_advanced_assignment_from_topics():
    """
    Generate advanced assignment from typed topics (no PDF).
    """
    try:
        payload = request.get_json() or {}
        topic_text = (payload.get("topic_text") or "").strip()
        task_distribution = payload.get("task_distribution", {})
        difficulty = payload.get("difficulty", "auto")

        if not topic_text:
            return jsonify({"error": "Please enter at least one topic"}), 400
        
        total_tasks = sum(task_distribution.values())
        if total_tasks <= 0:
            return jsonify({"error": "Task distribution must have at least 1 task"}), 400

        # Split topics into a list
        topics_list = [t.strip() for t in topic_text.split('\n') if t.strip()]
        if not topics_list:
            return jsonify({"error": "No valid topics found"}), 400

        # Generate using enhanced function
        result = generate_advanced_assignments_llm(
            full_text=topic_text,  # Use topics as context
            chosen_subtopics=topics_list,
            task_distribution=task_distribution,
            api_key=GROQ_API_KEY,
            difficulty=difficulty
        )

        if not result.get("success") or not result.get("questions"):
            return jsonify({
                "error": result.get("error", "Failed to generate assignment")
            }), 500

        questions = result["questions"]

        assignment_data = {
            "title": "Topics-Based Assignment",
            "questions": questions,
            "metadata": {
                "source": "advanced-topics",
                "topics": topics_list,
                "task_distribution": task_distribution,
                "difficulty": difficulty,
                "kind": "assignment",
                "total_tasks": len(questions)
            }
        }

        assignment_id = save_quiz_to_store(assignment_data)

        return jsonify({
            "success": True,
            "assignment_id": assignment_id,
            "title": assignment_data["title"],
            "questions": questions,
            "metadata": assignment_data["metadata"]
        }), 200

    except Exception as e:
        print(f"❌ Error in generate_advanced_assignment_from_topics: {e}")
        return jsonify({"error": str(e)}), 500
# ===============================
# PUBLISH / VIEW API (for UI flow)
# ===============================
@app.route("/api/quizzes/<quiz_id>/publish", methods=["POST"])
def publish_quiz(quiz_id):
    quiz = get_quiz_by_id(quiz_id)
    if not quiz:
        # If you're storing numeric IDs, you might be passing a string UUID from the client.
        # Make sure both sides use the same ID type.
        return jsonify({"ok": False, "error": "Quiz not found"}), 404

    # Mark as published in your datastore
    quiz["published"] = True
    quiz["published_at"] = datetime.utcnow().isoformat() + "Z"

    # Optionally generate a stable public URL (adjust route if you serve a public page)
    quiz["publish_url"] = f"/quiz/{quiz_id}"

    # persist
    save_quiz_to_store(quiz)  # make sure this updates by id if it already exists

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

    # Normalize to the same schema used by student views
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
            # default to mcq if unknown
            qtype = "mcq"

        q = {
            "type": qtype,
            "prompt": it.get("prompt") or it.get("question_text") or "",
            "difficulty": it.get("difficulty"),
            "order": i
        }
        if qtype in ("mcq", "true_false"):
            q["options"] = it.get("options") or []
            q["answer"]  = it.get("answer")  # publish.js can infer correct index from "A"/"True"/text
        else:
            # short answer
            q["answer"] = it.get("answer")

        questions.append(q)

    quiz_dict = {
        "title": data.get("title") or "Untitled Quiz",
        "questions": questions,
        "metadata": data.get("metadata") or {},
        "created_at": datetime.utcnow()
    }

    quiz_id = save_quiz_to_store(quiz_dict)  # returns id (string)
    return jsonify({"id": quiz_id, "title": quiz_dict["title"]}), 201

@app.route("/api/quizzes", methods=["GET"])
def api_list_quizzes():
    # ?kind=quiz or ?kind=assignment or no param
    kind = request.args.get("kind")  # may be None

    quizzes = list_quizzes(kind=kind)

    return jsonify({
        "success": True,
        "items": quizzes,
        "kind": kind or "all",
    })

@app.post("/api/quizzes/<quiz_id>/publish")
def api_publish_quiz(quiz_id):
    # optional: mark as published; no-op is fine
    return jsonify({"quiz_id": quiz_id, "status": "published"}), 200

#>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
#>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
@app.route('/teacher/preview/<quiz_id>')
def teacher_preview(quiz_id):
    """
    Preview quiz as teacher.
    Loads the full quiz data, including questions and answers,
    and passes it to the teacher_preview.html template.
    """
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return "Quiz not found", 404
    
    # 💡 Ensure 'quiz_data' is complete here (questions, answers, metadata)
    # The template 'teacher_preview.html' will use this data to render the quiz.
    return render_template(
        'teacher_preview.html',
        quiz=quiz_data,
        quiz_id=quiz_id,
        # Optional: Pass title separately for template clarity
        quiz_title=quiz_data.get('title', f"Quiz {quiz_id}")
    )

@app.route('/api/quizzes/<quiz_id>/send', methods=['POST'])
def send_quiz_to_students(quiz_id):
    """Send quiz to students with notification"""
    try:
        data = request.get_json()
        quiz_data = get_quiz_by_id(quiz_id)
        
        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404
        
        # Mark quiz as published/active
        quiz_data["published"] = True
        quiz_data["published_at"] = datetime.utcnow().isoformat()
        quiz_data["notification_message"] = data.get('message', '')
        
        # Save updated quiz
        save_quiz_to_store(quiz_data)
        
        # Here you would integrate with your notification system
        # For now, we'll just return success
        return jsonify({
            "success": True,
            "message": "Quiz sent to students successfully",
            "quiz_id": quiz_id
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500



#?????????????????????????????????
    
@app.route('/api/quizzes/<quiz_id>/settings', methods=['GET'])
def get_quiz_settings(quiz_id):
    """Get current settings of a quiz"""
    try:
        quiz_data = get_quiz_by_id(quiz_id)
        
        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404
        
        # Fetch the current settings, if available
        settings = quiz_data.get('settings', {})
        
        return jsonify(settings)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/quizzes/<quiz_id>/settings', methods=['POST'])
def update_quiz_settings(quiz_id):
    """Update quiz settings"""
    try:
        data = request.get_json()
        quiz_data = get_quiz_by_id(quiz_id)
        
        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404
        
        # Validate time_limit (ensure it's a valid integer within range)
        time_limit = data.get('time_limit', 30)
        if not isinstance(time_limit, int) or not (5 <= time_limit <= 180):
            return jsonify({"error": "Invalid time limit. Must be between 5 and 180 minutes."}), 400
        
        # Validate due_date (ensure it's a valid datetime string)
        due_date = data.get('due_date', None)
        if due_date and not isinstance(due_date, str):
            return jsonify({"error": "Invalid due date format."}), 400
        
        # Ensure settings field exists
        if 'settings' not in quiz_data:
            quiz_data['settings'] = {}

        # Update the settings
        quiz_data['settings'].update({
            'time_limit': time_limit,
            'due_date': due_date,
            'allow_retakes': data.get('allow_retakes', False),
            'shuffle_questions': data.get('shuffle_questions', True),
            'notification_message': data.get('notification_message', '')
        })
        
        save_quiz_to_store(quiz_data)
        
        return jsonify({
            "success": True,
            "message": "Settings updated successfully"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    # Run and land on /teacher/generate via the root redirect
    app.run(host="127.0.0.1", port=5000, debug=True)
