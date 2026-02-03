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
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_cors import CORS

from utils.pdf_utils import SmartPDFProcessor
from utils.assignment_utils import generate_advanced_assignments_llm
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
    get_submissions_for_quiz,  # Assuming this exists
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
    """Enhanced fallback subtopic extraction using document structure analysis."""
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
            if (
                any(word.istitle() for word in words if len(word) > 3)
                or re.match(r'^\d+[\.\)]', line)
            ):
                if line not in subtopics:
                    subtopics.append(line)

    unique_subtopics = list(dict.fromkeys([s.strip() for s in subtopics if s.strip()]))

    if not unique_subtopics:
        paragraphs = [p.strip() for p in raw_text.split('\n\n') if len(p.strip()) > 50]
        for para in paragraphs[:5]:
            first_sentence = para.split('.')[0] + '.'
            if 20 < len(first_sentence) < 100:
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
        if qq.get("answer") is None:
            for key in [
                "correct_answer",
                "reference_answer",
                "expected_answer",
                "ideal_answer",
                "solution",
                "model_answer",
            ]:
                if qq.get(key) is not None:
                    qq["answer"] = qq.get(key)
                    break
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


@app.route('/api/quizzes/<quiz_id>/settings', methods=['POST'])
def update_quiz_settings(quiz_id):
    """Update quiz settings (time_limit, due_date, note, etc.)"""
    try:
        data = request.get_json()
        quiz_data = get_quiz_by_id(quiz_id)

        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404

        time_limit = data.get('time_limit', 30)
        # Allow 0 (no time limit), reject <0 or >180
        if not isinstance(time_limit, int) or time_limit < 0 or time_limit > 180:
            return jsonify({
                "error": "Invalid time limit. Must be between 0 and 180 minutes."
            }), 400

        due_date = data.get('due_date', None)
        if due_date and not isinstance(due_date, str):
            return jsonify({"error": "Invalid due date format."}), 400

        note = data.get('note', '')

        if 'settings' not in quiz_data:
            quiz_data['settings'] = {}

        quiz_data['settings'].update({
            'time_limit': time_limit,
            'due_date': due_date,
            'allow_retakes': data.get('allow_retakes', False),
            'shuffle_questions': data.get('shuffle_questions', True),
            'notification_message': data.get('notification_message', ''),
            'note': note,
        })

        # Expose as top-level fields so /api/quizzes sees them
        quiz_data['time_limit'] = time_limit
        quiz_data['due_date'] = due_date
        quiz_data['note'] = note

        if 'id' not in quiz_data:
            quiz_data['id'] = quiz_id

        save_quiz_to_store(quiz_data)

        return jsonify({
            "success": True,
            "message": "Settings updated successfully",
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================
# CRITICAL: SAVE QUIZ TO STORE (ENSURE ID IS SET)
# ===============================
def save_quiz_to_store(quiz_data):
    from services import db as _db_mod
    import uuid
    
    fs = getattr(_db_mod, '_db', None)
    
    # Ensure ID is set
    if 'id' not in quiz_data or not quiz_data['id']:
        quiz_data['id'] = str(uuid.uuid4())
    
    # Ensure settings object exists
    if 'settings' not in quiz_data or not isinstance(quiz_data['settings'], dict):
        quiz_data['settings'] = {}
    
    # Copy top-level fields into settings and vice versa
    for key in ['time_limit', 'due_date', 'note']:
        val = quiz_data.get(key, quiz_data['settings'].get(key))
        quiz_data[key] = val
        quiz_data['settings'][key] = val
    
    print("Saving quiz_data to Firestore:", {
        "id": quiz_data.get('id'),
        "title": quiz_data.get('title'),
        "time_limit": quiz_data.get('time_limit'),
        "due_date": quiz_data.get('due_date'),
        "note": quiz_data.get('note'),
        "has_settings": 'settings' in quiz_data
    }) # Debug print
    
    if fs is not None:
        fs.collection('AIquizzes').document(quiz_data['id']).set(quiz_data)
    
    return quiz_data['id']


# ===============================
# LIST QUIZZES (FILTER OUT ITEMS WITHOUT ID)
# ===============================
def list_quizzes(kind=None):
    from services import db as _db_mod
    
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return []
    
    quizzes = []
    collections = []
    
    if kind == "assignment":
        collections = ["assignments"]
    elif kind == "quiz":
        collections = ["AIquizzes"]
    else:
        collections = ["AIquizzes", "assignments"]
    
    for collection_name in collections:
        for doc in fs.collection(collection_name).stream():
            quiz = doc.to_dict()
            quiz_kind = quiz.get('kind') or (quiz.get('metadata') or {}).get('kind')
            if kind is None or quiz_kind == kind:
                quizzes.append(quiz)
    
    # Filter out any quiz/assignment without 'id'
    quizzes = [q for q in quizzes if 'id' in q and q['id']]
    return quizzes


# ===============================
# API: GET QUIZZES (FILTER OUT ITEMS WITHOUT ID)
# ===============================





# ===============================
# LANDING (always open teacher/generate)
# ===============================
@app.route('/', methods=['GET'])
def root_redirect():
    """Always land on the teacher generation page."""
    return redirect(url_for('teacher_generate'))


def get_submissions_by_quiz_id(quiz_id: str) -> list:
    """Fetches all student submissions for a given quiz ID (placeholder)."""
    return []

# ===============================
# LTI CONFIGURATION / ENDPOINTS
# ===============================

def generate_rsa_keys():
    """Generate RSA key pair for LTI 1.3"""
    try:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
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
                    "e": e_b64,
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
                "e": "AQAB",
            }]
        }


LTI_JWKS = generate_rsa_keys()


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

        lti_data = request.form

        session['lti_user_id'] = lti_data.get('user_id', 'unknown')
        session['lti_roles'] = lti_data.get('roles', '')
        session['lti_course_id'] = lti_data.get('context_id', '')
        session['lti_context_title'] = lti_data.get('context_title', '')

        print(f"👤 User: {session['lti_user_id']}")
        print(f"🎭 Roles: {session['lti_roles']}")
        print(f"📚 Course: {session['lti_course_id']}")

        for key, value in lti_data.items():
            if value:
                v = str(value)
                print(f" {key}: {v[:100]}{'...' if len(v) > 100 else ''}")

        roles = session['lti_roles'].lower()
        if any(role in roles for role in ['instructor', 'teachingassistant', 'teacher', 'admin']):
            print("➡️ Redirecting to Teacher Interface")
            return redirect('/teacher/generate')
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
@app.route('/teacher')
def teacher_index():
    """Main teacher dashboard - ALWAYS show teacher interface"""
    return redirect(url_for('teacher_generate'))


# ===============================
# STUDENT ROUTES (no auth)
# ===============================
@app.route('/student')
def student_index():
    """Student dashboard - shows available quizzes"""
    user_id = session.get('lti_user_id', 'Student')

    try:
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
    """Display quiz for student with time limit and due date dynamically."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return ("Quiz not found", 404)

    questions_for_student = [
        {
            'id': q.get('id'),
            'type': q.get('type'),
            'prompt': q.get('prompt') or q.get('question_text'),
            'options': q.get('options') if q.get('type') in ['mcq', 'true_false'] else None,
            'difficulty': q.get('difficulty'),
        } for q in quiz_data.get('questions', [])
    ]

    title = quiz_data.get('title') or quiz_data.get('metadata', {}).get('source_file', f"Quiz #{quiz_id}")

    settings = quiz_data.get('settings', {})
    time_limit = settings.get('time_limit') or quiz_data.get('time_limit') or 10
    due_date = settings.get('due_date') or quiz_data.get('due_date') or None

    print(f"✅ Loaded quiz {quiz_id}: time_limit={time_limit}, due_date={due_date}")

    return render_template(
        'student_quiz.html',
        quiz_id=quiz_id,
        title=title,
        questions=questions_for_student,
        student_email="student@example.com",
        student_name="Student",
        time_limit=time_limit,
        due_date=due_date
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

    score = 0
    total_questions = len(correct_quiz_data.get('questions', []))
    student_answers: Dict[str, str] = {}

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
    }
    submission_id = save_submission_to_store(quiz_id, submission_data)

    return redirect(url_for('submission_confirmation', quiz_id=quiz_id, score=score, total=total_questions, submission_id=submission_id))


@app.route('/student/confirmation/<quiz_id>', methods=['GET'])
def submission_confirmation(quiz_id):
    """Display submission confirmation and score."""
    score = request.args.get('score', 'N/A')
    total = request.args.get('total', 'N/A')
    submission_id = request.args.get('submission_id', 'N/A')

    quiz_data = get_quiz_by_id(quiz_id)
    quiz_title = (
        (quiz_data.get("title") if quiz_data else None)
        or (quiz_data.get("metadata", {}).get("source_file") if quiz_data else None)
        or "Submitted Quiz"
    )

    return render_template(
        'submission_confirmation.html',
        quiz_title=quiz_title,
        score=score,
        total=total,
        submission_id=submission_id,
        student_name="Student",
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

                max_total_default = 0.0
                for qq in quiz.get('questions', []) or []:
                    max_total_default += float(qq.get('max_score') or _default_max_score(qq.get('type')))

                subs_ref = fs.collection(collection_name).document(qid).collection('submissions')
                if email_filter:
                    subs_ref = subs_ref.where('student_email', '==', email_filter)
                subs = subs_ref.stream()
                for sd in subs:
                    s = sd.to_dict() or {}

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
        return render_template('teacher_submissions.html', quiz_title=quiz_title, quiz_id=quiz_id, submissions=[])
    except Exception as e:
        print(f"❌ Error fetching submissions: {e}")
        return ("Failed to load submissions.", 500)


@app.route('/api/quizzes/<quiz_id>/submissions', methods=['GET'])
def api_get_quiz_submissions(quiz_id):
    """API endpoint to fetch all submissions for a specific quiz"""
    try:
        submissions = get_submissions_for_quiz(quiz_id)

        if submissions is None:
            return jsonify({
                "success": False,
                "error": "Could not fetch submissions. Firestore may not be available.",
            }), 500

        formatted_submissions = []
        for sub in submissions:
            formatted_submissions.append({
                "id": sub.get("id"),
                "student_name": sub.get("student_name", "Unknown"),
                "student_email": sub.get("student_email", "N/A"),
                "score": sub.get("score", 0),
                "total_questions": sub.get("total_questions", 0),
                "submitted_at": sub.get("submitted_at", ""),
                "time_taken_sec": sub.get("time_taken_sec", 0),
                "status": sub.get("status", "completed"),
            })

        return jsonify({
            "success": True,
            "submissions": formatted_submissions,
            "total": len(formatted_submissions),
        }), 200

    except Exception as e:
        print(f"❌ Error in api_get_quiz_submissions: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@app.route("/api/quizzes/<quiz_id>", methods=["GET"])
def api_get_quiz(quiz_id):
    """Fetch a single quiz by ID as JSON for the frontend."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return jsonify({"error": "Quiz not found"}), 404
    return jsonify(quiz_data), 200


# ===============================
# HEALTH
# ===============================
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


# ===============================
# QUIZ GEN API (PDF)
# ===============================
@app.route("/api/quiz/from-pdf", methods=["POST"])
def quiz_from_pdf():
    """Generate quiz from uploaded PDF. Returns quiz JSON and saves via services/db.py."""
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

        processor = SmartPDFProcessor(
            max_chars=70000,
            target_chunk_size=3500,
            chunk_overlap=200,
        )

        text, document_analysis = processor.extract_pdf_text(file)
        if not text or not text.strip():
            return ("Could not extract text from PDF", 400)

        chunks_with_metadata = processor.adaptive_chunking(text, document_analysis)
        chunks = [chunk['text'] for chunk in chunks_with_metadata]

        structure_score = document_analysis.get('structure_score', 0)
        chunking_strategy = chunks_with_metadata[0]['chunk_type'] if chunks_with_metadata else 'none'

        print("📊 PDF Analysis Results:")
        print(f" - Structure Score: {structure_score:.2f}")
        print(f" - Chunking Strategy: {chunking_strategy}")
        print(f" - Total Pages: {document_analysis.get('total_pages', 0)}")
        print(f" - Total Chunks: {len(chunks)}")
        print(f" - Estimated Tokens: {document_analysis.get('estimated_tokens', 0)}")

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
            type_targets=dist,
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
        for i, q in enumerate(questions):
            if not q.get('id'):
                q['id'] = f"q{i+1}"
            if not q.get('prompt'):
                q['prompt'] = q.get('question_text', q.get('question', ''))
            if not q.get('answer') and q.get('correct_answer'):
                q['answer'] = q.get('correct_answer')

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
                    } if diff_mode == "custom" else {}),
                },
                "source_note": llm_json.get("source_note", ""),
                "source_file": source_file,
                "kind": "quiz",
                "chunking_analysis": {
                    "structure_score": round(structure_score, 2),
                    "strategy_used": chunking_strategy,
                    "total_chunks": len(chunks),
                    "total_pages": document_analysis.get('total_pages', 0),
                    "estimated_tokens": document_analysis.get('estimated_tokens', 0),
                    "chunk_types_distribution": _get_chunk_types_distribution(chunks_with_metadata),
                },
            },
        }

        quiz_id = save_quiz_to_store(result)
        result["id"] = quiz_id
        result["metadata"]["quiz_id"] = quiz_id

        print("✅ Quiz Generation Complete:")
        print(f" - Quiz ID: {quiz_id}")
        print(f" - Questions Generated: {len(questions)}")
        print(f" - Sample Question IDs: {[q.get('id') for q in questions[:3]]}")

        return jsonify(result), 200

    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        return ("Model returned invalid JSON. Try reducing PDF length or rephrasing.", 502)
    except Exception as e:
        print(f"❌ Server Error in quiz_from_pdf: {e}")
        import traceback
        traceback.print_exc()
        return (f"Server error: {str(e)}", 500)


# ===============================
# CUSTOM SUBTOPIC / ASSIGNMENT ROUTES (unchanged from earlier version)
# ===============================
# (I’ll skip re-pasting those here to keep this answer within limits,
# since your question is specifically about dynamic settings & list API.)

# ===============================
# QUIZ CREATION API (manual)
# ===============================
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
            "order": i,
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
        "created_at": datetime.utcnow(),
    }

    quiz_id = save_quiz_to_store(quiz_dict)
    return jsonify({"id": quiz_id, "title": quiz_dict["title"]}), 201


# ===============================
# LIST QUIZZES (includes dynamic settings)
# ===============================
@app.route("/api/quizzes", methods=["GET"])
def api_list_quizzes():
    """List quizzes/assignments with time_limit, due_date, note per item."""
    kind = request.args.get("kind")

    try:
        raw_quizzes = list_quizzes(kind=kind) or []

        items = []
        for q in raw_quizzes:
            settings = (
                q.get('settings')
                or (q.get('metadata') or {}).get('settings')
                or {}
            )

            time_limit = settings.get('time_limit')
            due_date = settings.get('due_date')
            note = settings.get('note') or settings.get('notification_message') or ''

            item = dict(q)

            meta_kind = (q.get('metadata') or {}).get('kind')
            item['kind'] = (meta_kind or kind or 'quiz')

            if 'questions_count' not in item:
                if 'counts' in q and isinstance(q['counts'], dict):
                    item['questions_count'] = sum(q['counts'].values())
                else:
                    item['questions_count'] = len(q.get('questions') or [])

            item['time_limit'] = time_limit
            item['due_date'] = due_date
            item['note'] = note

            items.append(item)

        print(f"📊 API /api/quizzes called with kind={kind}")
        print(f"📊 Returning {len(items)} items")
        for q in items[:3]:
            print(
                f" - {q.get('title')}: {q.get('questions_count', 0)} questions, "
                f"time_limit={q.get('time_limit')}, due_date={q.get('due_date')}"
            )

        return jsonify({
            "success": True,
            "items": items,
            "kind": kind or "all",
        })

    except Exception as e:
        print(f"❌ Error in api_list_quizzes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e),
            "items": [],
        }), 500


@app.post("/api/quizzes/<quiz_id>/publish")
def api_publish_quiz(quiz_id):
    return jsonify({"quiz_id": quiz_id, "status": "published"}), 200


@app.route('/teacher/preview/<quiz_id>')
def teacher_preview(quiz_id):
    """Preview quiz as teacher."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return "Quiz not found", 404

    return render_template(
        'teacher_preview.html',
        quiz=quiz_data,
        quiz_id=quiz_id,
        quiz_title=quiz_data.get('title', f"Quiz {quiz_id}"),
    )


@app.route('/api/quizzes/<quiz_id>/send', methods=['POST'])
def send_quiz_to_students(quiz_id):
    """Send quiz to students with notification"""
    try:
        data = request.get_json()
        quiz_data = get_quiz_by_id(quiz_id)

        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404

        quiz_data["published"] = True
        quiz_data["published_at"] = datetime.utcnow().isoformat()
        quiz_data["notification_message"] = data.get('message', '')

        save_quiz_to_store(quiz_data)

        return jsonify({
            "success": True,
            "message": "Quiz sent to students successfully",
            "quiz_id": quiz_id,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
