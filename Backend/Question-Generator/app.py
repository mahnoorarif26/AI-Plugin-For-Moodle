import os
import re
import sys
import json
import uuid
import math
from datetime import datetime, timezone
from typing import Dict, List, Any
import importlib.util
import time
from utils.embedding_engine import question_embedder
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
    get_submissions_for_quiz,
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
# Format: {upload_id: {'text': raw_text, 'file_name': file_name, 'timestamp': time.time()}}
_SUBTOPIC_UPLOADS: Dict[str, Dict[str, Any]] = {}

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


def _cleanup_old_uploads(max_age_hours=6):
    """Remove old uploads from memory to prevent memory leaks"""
    current_time = time.time()
    to_delete = []
    
    for upload_id, data in _SUBTOPIC_UPLOADS.items():
        upload_time = data.get('timestamp', 0)
        if current_time - upload_time > max_age_hours * 3600:
            to_delete.append(upload_id)
    
    for upload_id in to_delete:
        del _SUBTOPIC_UPLOADS[upload_id]
    
    if to_delete:
        print(f"🧹 Cleaned up {len(to_delete)} old uploads from memory")
    
    return len(to_delete)


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


# Add periodic cleanup decorator
@app.before_request
def cleanup_before_request():
    """Clean up old uploads before each request"""
    # Run cleanup with 1% probability per request
    import random
    if random.random() < 0.01:  # 1% chance per request
        _cleanup_old_uploads()


# ===============================
# API ROUTES
# ===============================

@app.route('/api/quizzes/<quiz_id>/settings', methods=['POST'])
def update_quiz_settings(quiz_id):
    """Update quiz settings (time_limit, due_date, note, etc.)"""
    try:
        data = request.get_json()
        quiz_data = get_quiz_by_id(quiz_id)

        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404

        # Validate time_limit (0 = no limit)
        time_limit = data.get('time_limit', 30)
        if not isinstance(time_limit, int) or time_limit < 0 or time_limit > 180:
            return jsonify({
                "error": "Invalid time limit. Must be between 0 and 180 minutes."
            }), 400

        due_date = data.get('due_date', None)
        if due_date and not isinstance(due_date, str):
            return jsonify({"error": "Invalid due date format."}), 400

        note = data.get('note', '')

        # ✅ CRITICAL FIX: Ensure quiz_data has settings object
        if 'settings' not in quiz_data:
            quiz_data['settings'] = {}
        
        # Update settings
        quiz_data['settings'].update({
            'time_limit': time_limit,
            'due_date': due_date,
            'allow_retakes': data.get('allow_retakes', False),
            'shuffle_questions': data.get('shuffle_questions', True),
            'notification_message': data.get('notification_message', ''),
            'note': note,
        })

        # ✅ Also update top-level fields for backward compatibility
        quiz_data['time_limit'] = time_limit
        quiz_data['due_date'] = due_date
        quiz_data['note'] = note

        # ✅ Ensure ID is preserved
        quiz_data['id'] = quiz_id

        # ✅ Save using the imported function
        save_quiz_to_store(quiz_data)

        return jsonify({
            "success": True,
            "message": "Settings updated successfully",
            "quiz_id": quiz_id
        })

    except Exception as e:
        print(f"❌ Error in update_quiz_settings: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/quizzes/<quiz_id>/settings', methods=['GET'])
def get_quiz_settings(quiz_id):
    """Get current settings of a quiz"""
    try:
        quiz_data = get_quiz_by_id(quiz_id)
        
        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404
        
        # Get settings from quiz data
        settings = quiz_data.get('settings', {})
        
        # If no settings object, create basic one
        if not settings:
            settings = {
                'time_limit': quiz_data.get('time_limit', 30),
                'due_date': quiz_data.get('due_date'),
                'note': quiz_data.get('note', ''),
                'allow_retakes': quiz_data.get('allow_retakes', False),
                'shuffle_questions': quiz_data.get('shuffle_questions', True)
            }
        
        return jsonify({
            "success": True,
            "quiz_id": quiz_id,
            "settings": settings
        })
        
    except Exception as e:
        print(f"❌ Error in get_quiz_settings: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/questions/similar', methods=['POST'])
def find_similar_questions():
    """
    API endpoint to find similar questions.
    Used when teacher is creating/editing questions.
    """
    try:
        data = request.get_json()
        query_text = data.get('question_text', '').strip()
        question_type = data.get('type')
        exclude_ids = data.get('exclude_ids', [])
        
        if not query_text:
            return jsonify({'similar': []}), 200
        
        similar = question_embedder.find_similar_questions(
            query_text=query_text,
            top_k=5,
            filter_type=question_type,
            min_similarity=0.7,
            exclude_ids=exclude_ids
        )
        
        return jsonify({'success': True, 'similar': similar}), 200
        
    except Exception as e:
        print(f"❌ Error in find_similar_questions: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/questions/stats', methods=['GET'])
def get_question_stats():
    """Get statistics about indexed questions"""
    try:
        stats = question_embedder.get_stats()
        return jsonify({'success': True, 'stats': stats}), 200
    except Exception as e:
        print(f"❌ Error in get_question_stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/questions/check-duplicates', methods=['POST'])
def check_duplicates_in_quiz():
    """Check for duplicates before saving quiz"""
    try:
        data = request.get_json()
        questions = data.get('questions', [])
        duplicates_report = []
        
        for i, q in enumerate(questions):
            question_text = q.get('prompt') or q.get('question_text', '')
            if not question_text:
                continue
            
            similar = question_embedder.find_similar_questions(
                query_text=question_text,
                top_k=3,
                min_similarity=0.75
            )
            
            if similar:
                duplicates_report.append({
                    'question_index': i,
                    'question_text': question_text[:100],
                    'similar_count': len(similar),
                    'highest_similarity': similar[0]['similarity_percent'],
                    'matches': similar
                })
        
        return jsonify({
            'success': True,
            'has_duplicates': len(duplicates_report) > 0,
            'duplicate_count': len(duplicates_report),
            'report': duplicates_report
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/questions/analytics', methods=['GET'])
def question_analytics():
    """Get analytics about indexed questions"""
    try:
        stats = question_embedder.get_stats()
        source_counts = {}
        for q in question_embedder.questions_db:
            source = q['metadata'].get('source', 'unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
        
        return jsonify({
            'success': True,
            'total_questions': stats['total_questions'],
            'by_type': stats['by_type'],
            'by_difficulty': stats['by_difficulty'],
            'by_source': source_counts
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route("/api/quizzes", methods=["GET"])
def api_list_quizzes():
    """List quizzes/assignments with time_limit, due_date, note per item."""
    kind = request.args.get("kind")

    try:
        # Use the imported function from services.db
        raw_quizzes = list_quizzes(kind=kind) or []

        items = []
        for q in raw_quizzes:
            # Get settings from the quiz data
            settings = q.get('settings', {})
            if not settings:
                # Try to get from metadata as fallback
                settings = q.get('metadata', {}).get('settings', {})

            # Extract settings
            time_limit = settings.get('time_limit') or q.get('time_limit')
            due_date = settings.get('due_date') or q.get('due_date')
            note = settings.get('note') or settings.get('notification_message') or ''

            # Determine item kind
            metadata = q.get('metadata', {})
            item_kind = metadata.get('kind', 'quiz')
            if kind and item_kind != kind:
                continue  # Skip if filter doesn't match

            # Calculate questions count
            questions_count = len(q.get('questions', []))
            if questions_count == 0 and 'counts' in q:
                # Sum up counts if available
                counts = q.get('counts', {})
                questions_count = sum(counts.values())

            item = {
                "id": q.get('id'),
                "title": q.get('title', 'Untitled Quiz'),
                "created_at": q.get('created_at'),
                "questions_count": questions_count,
                "time_limit": time_limit,
                "due_date": due_date,
                "note": note,
                "kind": item_kind,
                "metadata": metadata
            }
            
            # Add questions for preview if available
            if q.get('questions'):
                item['questions'] = q['questions'][:3]  # First 3 for preview

            items.append(item)

        print(f"📊 API /api/quizzes called with kind={kind}")
        print(f"📊 Returning {len(items)} items")
        
        return jsonify({
            "success": True,
            "items": items,
            "total": len(items),
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


# ===============================
# BASIC ROUTES
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
# TEACHER ROUTES
# ===============================

@app.route('/teacher')
def teacher_index():
    """Main teacher dashboard - ALWAYS show teacher interface"""
    return redirect(url_for('teacher_generate'))


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


# ===============================
# STUDENT ROUTES
# ===============================

@app.route('/student')
def student_index():
    """Student dashboard - shows available quizzes and assignments"""
    user_id = session.get('lti_user_id', 'Student')

    try:
        student_email = f"{user_id}@example.com" if user_id != 'Student' else "student@example.com"
        submitted_quiz_ids = set(get_submitted_quiz_ids(student_email) or [])
        items = list_quizzes() or []
        
        quizzes = []
        assignments = []
        
        for it in items:
            if it["id"] in submitted_quiz_ids:
                continue
            
            item_data = {
                "id": it["id"],
                "title": it.get("title") or "AI Generated Item",
                "questions_count": sum((it.get("counts") or {}).values()) if it.get("counts") else len(it.get("questions", [])),
                "created_at": it.get("created_at"),
            }
            
            # Check if it's an assignment or quiz
            metadata = it.get('metadata', {})
            if metadata.get('kind') == 'assignment':
                assignments.append(item_data)
            else:
                quizzes.append(item_data)
        
        return render_template(
            'student_index.html', 
            quizzes=quizzes,
            assignments=assignments,
            error=None, 
            student_name=user_id
        )
    except Exception as e:
        print(f"❌ Error fetching student item list: {e}")
        return render_template(
            'student_index.html', 
            quizzes=[], 
            assignments=[],
            error=f"Failed to load items: {e}", 
            student_name=user_id
        )


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


@app.route('/student/assignment/<assignment_id>', methods=['GET'])
def student_assignment(assignment_id):
    """Display assignment for student to complete."""
    assignment_data = get_quiz_by_id(assignment_id)
    
    if not assignment_data:
        return "Assignment not found", 404
    
    # Check if it's actually an assignment
    metadata = assignment_data.get('metadata', {})
    if metadata.get('kind') != 'assignment':
        return redirect(url_for('student_quiz', quiz_id=assignment_id))
    
    questions = assignment_data.get('questions', [])
    title = assignment_data.get('title') or f"Assignment #{assignment_id}"
    
    return render_template(
        'student_assignment.html',
        assignment_id=assignment_id,
        quiz_id=assignment_id,  # For compatibility
        title=title,
        questions=questions,
        student_email="student@example.com",
        student_name="Student"
    )


@app.route('/student/submit_assignment', methods=['POST'])
def submit_assignment():
    """Handle student assignment submission."""
    try:
        form_data = request.form
        files = request.files
        
        assignment_id = form_data.get('assignment_id') or form_data.get('quiz_id')
        
        if not assignment_id:
            return jsonify({"error": "Missing assignment ID"}), 400
        
        assignment_data = get_quiz_by_id(assignment_id)
        if not assignment_data:
            return jsonify({"error": "Assignment not found"}), 404
        
        # Collect student answers
        student_answers = {}
        uploaded_files = {}
        
        for q in assignment_data.get('questions', []):
            q_id = q.get('id')
            if not q_id:
                continue
            
            # Get text answer
            answer_text = (form_data.get(q_id) or '').strip()
            student_answers[q_id] = answer_text
        
        # Handle file upload
        if 'assignment_file_final' in files:
            uploaded_file = files['assignment_file_final']
            if uploaded_file and uploaded_file.filename:
                # Store file info (you may want to save the actual file)
                uploaded_files['main_file'] = uploaded_file.filename
        
        # Calculate preliminary score (assignments need manual grading)
        total_questions = len(assignment_data.get('questions', []))
        
        submission_data = {
            "email": "student@example.com",
            "name": "Student",
            "answers": student_answers,
            "files": uploaded_files,
            "score": 0,  # Assignments start at 0 until manually graded
            "total_questions": total_questions,
            "status": "pending_review",
            "kind": "assignment_submission"
        }
        
        submission_id = save_submission_to_store(assignment_id, submission_data)
        
        return render_template(
            'submission_confirmation.html',
            quiz_title=assignment_data.get('title', 'Assignment'),
            score=None,  # Don't show score for assignments
            total=total_questions,
            submission_id=submission_id,
            student_name="Student",
            student_email="student@example.com",
            submitted_at=datetime.now().strftime("%b %d, %Y %H:%M UTC"),
            confirmation_message="Your assignment has been submitted successfully and is pending review by your instructor.",
            is_assignment=True,
            item_type="Assignment",
            now=datetime.now().strftime("%b %d, %Y %H:%M UTC")
        )
        
    except Exception as e:
        print(f"❌ Error submitting assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


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


@app.route('/api/quizzes/<quiz_id>/submissions', methods=['GET'])
def api_get_quiz_submissions(quiz_id):
    """API endpoint to fetch all submissions for a specific quiz"""
    try:
        submissions = get_submissions_for_quiz(quiz_id)

        # Check if submissions is a list (even if empty)
        if submissions is None:
            return jsonify({
                "success": False,
                "error": "Could not fetch submissions. Database may not be available.",
            }), 500

        formatted_submissions = []
        for sub in submissions:
            # Calculate score percentage if possible
            score = sub.get("score", 0)
            total_questions = sub.get("total_questions", 0)
            max_score = sub.get("max_total", total_questions)
            
            if max_score > 0:
                percentage = (score / max_score) * 100
            else:
                percentage = 0

            formatted_submissions.append({
                "id": sub.get("id", "unknown"),
                "student_name": sub.get("student_name") or sub.get("name") or "Unknown",
                "student_email": sub.get("student_email") or sub.get("email") or "N/A",
                "score": score,
                "max_score": max_score,
                "percentage": round(percentage, 1),
                "total_questions": total_questions,
                "submitted_at": sub.get("submitted_at", ""),
                "time_taken_sec": sub.get("time_taken_sec", 0),
                "status": sub.get("status", "completed"),
            })

        return jsonify({
            "success": True,
            "submissions": formatted_submissions,
            "total": len(formatted_submissions),
            "quiz_id": quiz_id
        }), 200

    except Exception as e:
        print(f"❌ Error in api_get_quiz_submissions: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


# ===============================
# QUIZ/ASSIGNMENT APIs
# ===============================

@app.route("/api/quizzes/<quiz_id>", methods=["GET"])
def api_get_quiz(quiz_id):
    """Fetch a single quiz by ID as JSON for the frontend."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return jsonify({"error": "Quiz not found"}), 404
    return jsonify(quiz_data), 200


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


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

        try:
            for q in questions:
                question_embedder.add_question(
                    question_id=f"{quiz_id}_{q.get('id', '')}",
                    question_text=q.get('prompt', ''),
                    metadata={
                        'type': q.get('type'),
                        'difficulty': q.get('difficulty'),
                        'tags': q.get('tags', []),
                        'quiz_id': quiz_id,
                        'source': 'ai_pdf'
                    }
                )
            print(f"✅ Indexed {len(questions)} questions from AI quiz")
        except Exception as e:
            print(f"⚠️ Indexing failed: {e}")
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
            'analysis': document_analysis,
            'timestamp': time.time()  # Add timestamp for cleanup
        }

        # 3. ENHANCED SUBTOPIC EXTRACTION WITH ADAPTIVE CHUNKING
        chunks_with_metadata = processor.adaptive_chunking(raw_text, document_analysis)
        
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
        for i, q in enumerate(questions):
            if not q.get('id'):
                q['id'] = f"q{i+1}"
            if not q.get('prompt'):
                q['prompt'] = q.get('question_text', q.get('question', ''))
            if not q.get('answer') and q.get('correct_answer'):
                q['answer'] = q.get('correct_answer')

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

        try:
            for q in questions:
                question_embedder.add_question(
                    question_id=f"{quiz_id}_{q.get('id', '')}",
                    question_text=q.get('prompt', ''),
                    metadata={
                        'type': q.get('type'),
                        'difficulty': q.get('difficulty'),
                        'tags': chosen,
                        'quiz_id': quiz_id,
                        'source': 'subtopics'
                    }
                )
            print(f"✅ Indexed {len(questions)} from subtopics")
        except Exception as e:
            print(f"⚠️ Indexing failed: {e}")
        
        resp = {
            "success": True,
            "quiz_id": quiz_id,
            "id": quiz_id,
            "title": source_file,
            "questions": questions,
            "metadata": quiz_data["metadata"],
            "message": "Quiz generated successfully."
        }

        # Clean memory
        if upload_id in _SUBTOPIC_UPLOADS:
            del _SUBTOPIC_UPLOADS[upload_id]

        print(f"✅ Quiz from subtopics saved: {quiz_id}, Questions: {len(questions)}")
        return jsonify(resp), 200

    except Exception as e:
        print(f"❌ Error in quiz_from_subtopics: {e}")
        import traceback
        traceback.print_exc()
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

        for i, q in enumerate(questions):
            if not q.get('id'):
                q['id'] = f"q{i+1}"
            if not q.get('prompt'):
                q['prompt'] = q.get('question_text', q.get('question', ''))
            if not q.get('answer') and q.get('correct_answer'):
                q['answer'] = q.get('correct_answer')

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

        try:
            for q in questions:
                question_embedder.add_question(
                    question_id=f"{quiz_id}_{q.get('id', '')}",
                    question_text=q.get('prompt', ''),
                    metadata={
                        'type': q.get('type'),
                        'difficulty': q.get('difficulty'),
                        'tags': [topic_text[:50]],
                        'quiz_id': quiz_id,
                        'source': 'auto_topic'
                    }
                )
            print(f"✅ Indexed {len(questions)} from auto-quiz")
        except Exception as e:
            print(f"⚠️ Indexing failed: {e}")
        
        return jsonify({
            "success": True,
            "quiz_id": quiz_id,
            "id": quiz_id,
            "questions_count": len(questions),
            "questions": questions,
            "quiz": quiz_data,
            "title": topic_text,
            "metadata": quiz_data["metadata"]
        }), 200

    except Exception as e:
        print(f"❌ Error in auto_generate_quiz: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server error during quiz generation: {str(e)}"}), 500


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
        scenario_style = payload.get("scenario_style", "auto")

        if not upload_id or upload_id not in _SUBTOPIC_UPLOADS:
            return jsonify({"error": "Invalid or expired upload_id"}), 400

        if not chosen:
            return jsonify({"error": "No subtopics selected"}), 400

        total_tasks = sum(task_distribution.values())
        if total_tasks <= 0:
            return jsonify({"error": "Task distribution must have at least 1 task"}), 400

        uploaded_data = _SUBTOPIC_UPLOADS[upload_id]
        full_text = uploaded_data["text"]
        source_file = uploaded_data["file_name"]

        # Generate using enhanced function
        result = generate_advanced_assignments_llm(
            full_text=full_text,
            chosen_subtopics=chosen,
            task_distribution=task_distribution,
            api_key=GROQ_API_KEY,
            difficulty=difficulty,
            scenario_style=scenario_style,
        )

        if not result.get("success"):
            error_detail = result.get("error", "Unknown error")
            raw_response = result.get("raw_response", "")

            error_msg = f"Assignment generation failed: {error_detail}"
            if raw_response:
                error_msg += f"\n\nRaw LLM response snippet: {raw_response[:500]}..."

            return jsonify({"error": error_msg, "details": error_detail}), 500

        questions = result.get("questions", [])
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
                "scenario_style": scenario_style,
                "kind": "assignment",
                "total_tasks": len(questions),
            },
        }

        assignment_id = save_quiz_to_store(assignment_data)

        try:
            for q in questions:
                question_text = q.get('prompt', '')
                if q.get('context'):
                    question_text = f"{question_text} [Context: {q.get('context')[:100]}]"
                
                question_embedder.add_question(
                    question_id=f"{assignment_id}_{q.get('id', '')}",
                    question_text=question_text,
                    metadata={
                        'type': q.get('assignment_type', 'task'),
                        'difficulty': difficulty,
                        'tags': chosen,
                        'quiz_id': assignment_id,
                        'source': 'assignment_pdf',
                        'has_code': bool(q.get('code_snippet'))
                    }
                )
            print(f"✅ Indexed {len(questions)} assignment tasks")
        except Exception as e:
            print(f"⚠️ Indexing failed: {e}")
        
        # Clean up
        if upload_id in _SUBTOPIC_UPLOADS:
            del _SUBTOPIC_UPLOADS[upload_id]

        return jsonify({
            "success": True,
            "assignment_id": assignment_id,
            "title": assignment_data["title"],
            "questions": questions,
            "metadata": assignment_data["metadata"],
        }), 200

    except Exception as e:
        print(f"❌ Error in generate_advanced_assignment: {e}")
        return jsonify({
            "error": str(e),
            "message": "Internal server error during assignment generation"
        }), 500


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
        scenario_style = payload.get("scenario_style", "auto")

        if not topic_text:
            return jsonify({"error": "Please enter at least one topic"}), 400

        total_tasks = sum(task_distribution.values())
        if total_tasks <= 0:
            return jsonify({"error": "Task distribution must have at least 1 task"}), 400

        topics_list = [t.strip() for t in topic_text.split("\n") if t.strip()]
        if not topics_list:
            return jsonify({"error": "No valid topics found"}), 400

        result = generate_advanced_assignments_llm(
            full_text=topic_text,
            chosen_subtopics=topics_list,
            task_distribution=task_distribution,
            api_key=GROQ_API_KEY,
            difficulty=difficulty,
            scenario_style=scenario_style,
        )

        if not result.get("success") or not result.get("questions"):
            return jsonify({"error": result.get("error", "Failed to generate assignment")}), 500

        questions = result["questions"]

        assignment_data = {
            "title": "Topics-Based Assignment",
            "questions": questions,
            "metadata": {
                "source": "advanced-topics",
                "topics": topics_list,
                "task_distribution": task_distribution,
                "difficulty": difficulty,
                "scenario_style": scenario_style,
                "kind": "assignment",
                "total_tasks": len(questions),
            },
        }

        assignment_id = save_quiz_to_store(assignment_data)

        try:
            for q in questions:
                question_text = q.get('prompt', '')
                if q.get('context'):
                    question_text = f"{question_text} [Context: {q.get('context')[:100]}]"
                
                question_embedder.add_question(
                    question_id=f"{assignment_id}_{q.get('id', '')}",
                    question_text=question_text,
                    metadata={
                        'type': q.get('assignment_type', 'task'),
                        'difficulty': difficulty,
                        'tags': topics_list,
                        'quiz_id': assignment_id,
                        'source': 'assignment_topics',
                        'has_code': bool(q.get('code_snippet'))
                    }
                )
            print(f"✅ Indexed {len(questions)} from topics assignment")
        except Exception as e:
            print(f"⚠️ Indexing failed: {e}")
            
        return jsonify({
            "success": True,
            "assignment_id": assignment_id,
            "title": assignment_data["title"],
            "questions": questions,
            "metadata": assignment_data["metadata"],
        }), 200

    except Exception as e:
        print(f"❌ Error in generate_advanced_assignment_from_topics: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/api/quizzes")
def api_create_quiz():
    """Create quiz and index questions for similarity search"""
    data = request.get_json(force=True) or {}
    items = data.get("items") or []

    # Normalize questions (existing code)
    questions = []
    for i, it in enumerate(items):
        qtype = (it.get("type") or "").strip().lower()
        if qtype in ("tf", "truefalse", "true_false"):
            qtype = "true_false"
        elif qtype in ("mcq", "multiple_choice"):
            qtype = "mcq"
        elif qtype in ("short", "short_answer", "saq"):
            qtype = "short"

        q = {
            "type": qtype,
            "prompt": it.get("prompt") or it.get("question_text") or "",
            "difficulty": it.get("difficulty"),
            "order": i,
            "id": it.get("id") or f"q{i+1}"
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

    # Save quiz
    quiz_id = save_quiz_to_store(quiz_dict)
    
    # Index all questions for similarity search
    try:
        for q in questions:
            question_embedder.add_question(
                question_id=f"{quiz_id}_{q.get('id', '')}",
                question_text=q.get('prompt', ''),
                metadata={
                    'type': q.get('type'),
                    'difficulty': q.get('difficulty'),
                    'tags': q.get('tags', []),
                    'quiz_id': quiz_id
                }
            )
        print(f"✅ Indexed {len(questions)} questions for quiz {quiz_id}")
    except Exception as e:
        print(f"⚠️ Failed to index questions: {e}")
    
    return jsonify({"id": quiz_id, "title": quiz_dict["title"]}), 201


@app.post("/api/quizzes/<quiz_id>/publish")
def api_publish_quiz(quiz_id):
    return jsonify({"quiz_id": quiz_id, "status": "published"}), 200


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