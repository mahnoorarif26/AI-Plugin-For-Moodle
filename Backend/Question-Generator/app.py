import os
import re
import json
import uuid
from datetime import datetime
from typing import Dict, List, Any

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS

from utils.pdf_utils import SmartPDFProcessor

from services.db import (
    save_quiz as save_quiz_to_store,
    get_quiz_by_id,
    list_quizzes,
    save_submission as save_submission_to_store,
    get_submitted_quiz_ids
)

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

# ===============================
# LANDING (always open teacher/generate)
# ===============================
@app.route('/', methods=['GET'])
def root_redirect():
    """Always land on the teacher generation page."""
    return redirect(url_for('teacher_generate'))

# ===============================
# STUDENT ROUTES (no auth)
# ===============================
@app.route('/student')
def student_index():
    """List all available quizzes for students, filtering submitted ones (no auth)."""
    try:
        # In no-auth mode we don't have per-user submissions; keep API call for compatibility.
        # If your DB layer returns per-email submissions, you can pass a fixed email or skip filter.
        student_email = "student@example.com"
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
        return render_template('student_index.html', quizzes=quizzes, error=None, student_name="Student")
    except Exception as e:
        print(f"❌ Error fetching student quiz list: {e}")
        return render_template('student_index.html', quizzes=[], error=f"Failed to load quizzes: {e}", student_name="Student")


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

    # In no-auth mode, use fixed student identity
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
        # Pass empty list; implement fetching in your template/server as needed
        return render_template('teacher_submissions.html', quiz_title=quiz_title, quiz_id=quiz_id, submissions=[])
    except Exception as e:
        print(f"❌ Error fetching submissions: {e}")
        return ("Failed to load submissions.", 500)

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
        
        # Use first 2-3 chunks for subtopic extraction (saves tokens while maintaining quality)
        sample_chunks = chunks_with_metadata[:3]
        sample_text = "\n\n".join(chunk['text'] for chunk in sample_chunks)
        
        # If we have section-based chunks, prioritize those for subtopic extraction
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

@app.route('/teacher/preview/<quiz_id>')
def teacher_preview(quiz_id):
    """Preview quiz as teacher"""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return "Quiz not found", 404
    
    return render_template(
        'teacher_preview.html',
        quiz=quiz_data,
        quiz_id=quiz_id
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