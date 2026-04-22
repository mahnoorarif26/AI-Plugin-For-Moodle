"""API routes for quiz generation and management."""

import json
import uuid
from typing import Dict, Any
from flask import Blueprint, request, jsonify
from datetime import datetime
import os
# These will be imported from the main app
from config import Config
from utils.helpers import get_chunk_types_distribution, get_enhanced_fallback_subtopics
from services.db import save_quiz as save_quiz_to_store, get_quiz_by_id, list_quizzes
from services.quiz_service import (
    normalize_quiz_questions,
    create_quiz_dict,
    publish_quiz as publish_quiz_service
)

# Import from Question-Generator utils
from utils.pdf_utils import SmartPDFProcessor
from utils import (
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

api_bp = Blueprint('api', __name__, url_prefix='/api')

# Global memory store for subtopic uploads
_SUBTOPIC_UPLOADS: Dict[str, Dict[str, Any]] = {}


@api_bp.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"ok": True})


@api_bp.route('/quiz/from-pdf', methods=['POST'])
def quiz_from_pdf():
    """
    Generate quiz from uploaded PDF with smart adaptive chunking.
    """
    try:
        # Validate file upload
        if "file" not in request.files:
            return ("Missing file (multipart field 'file')", 400)

        file = request.files["file"]
        if not file or file.filename == "":
            return ("Empty file", 400)

        if not (file.mimetype == "application/pdf" or file.filename.lower().endswith(".pdf")):
            return ("Only PDF accepted (.pdf)", 400)

        # Parse options
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

        # Enhanced PDF processing
        processor = SmartPDFProcessor(
            max_chars=70000,
            target_chunk_size=3500,
            chunk_overlap=200
        )
        
        text, document_analysis = processor.extract_pdf_text(file)
        if not text or not text.strip():
            return ("Could not extract text from PDF", 400)

        # Adaptive chunking
        chunks_with_metadata = processor.adaptive_chunking(text, document_analysis)
        chunks = [chunk['text'] for chunk in chunks_with_metadata]
        
        # Log analysis results
        structure_score = document_analysis.get('structure_score', 0)
        chunking_strategy = chunks_with_metadata[0]['chunk_type'] if chunks_with_metadata else 'none'
        
        print(f"📊 PDF Analysis Results:")
        print(f"   - Structure Score: {structure_score:.2f}")
        print(f"   - Chunking Strategy: {chunking_strategy}")
        print(f"   - Total Pages: {document_analysis.get('total_pages', 0)}")
        print(f"   - Total Chunks: {len(chunks)}")
        print(f"   - Estimated Tokens: {document_analysis.get('estimated_tokens', 0)}")

        # Difficulty mix
        mix_counts = {}
        if diff_mode == "custom":
            mix_counts = _allocate_counts(
                total=num_questions,
                easy=int(diff.get("easy", 30)),
                med=int(diff.get("medium", 50)),
                hard=int(diff.get("hard", 20)),
            )

        # LLM call
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
            api_key=Config.GROQ_API_KEY,
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

        # Build result with enhanced metadata
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
                "chunking_analysis": {
                    "structure_score": round(structure_score, 2),
                    "strategy_used": chunking_strategy,
                    "total_chunks": len(chunks),
                    "total_pages": document_analysis.get('total_pages', 0),
                    "estimated_tokens": document_analysis.get('estimated_tokens', 0),
                    "chunk_types_distribution": get_chunk_types_distribution(chunks_with_metadata)
                }
            }
        }

        quiz_id = save_quiz_to_store(result)
        result["metadata"]["quiz_id"] = quiz_id

        print(f"✅ Quiz Generation Complete: Quiz ID: {quiz_id}, Questions: {len(questions)}")

        return jsonify(result), 200

    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        return ("Model returned invalid JSON. Try reducing PDF length or rephrasing.", 502)
    except Exception as e:
        print(f"❌ Server Error in quiz_from_pdf: {e}")
        return (f"Server error: {str(e)}", 500)


@api_bp.route('/custom/extract-subtopics', methods=['POST'])
def extract_subtopics():
    """Extract subtopics from uploaded PDF/text file with enhanced processing."""
    if "file" not in request.files:
        return jsonify({"error": "Missing file (multipart field 'file')"}), 400

    uploaded_file = request.files['file']
    file_name = uploaded_file.filename or "uploaded_content.txt"

    try:
        # Enhanced text extraction
        processor = SmartPDFProcessor(
            max_chars=70000,
            target_chunk_size=3500,
            chunk_overlap=200
        )
        
        raw_text, document_analysis = processor.extract_pdf_text(uploaded_file)
        if not raw_text or len(raw_text.strip()) < 50:
            return jsonify({"error": "Could not extract sufficient text from file."}), 400

        # Store for later use
        upload_id = str(uuid.uuid4())
        _SUBTOPIC_UPLOADS[upload_id] = {
            'text': raw_text, 
            'file_name': file_name,
            'analysis': document_analysis
        }

        # Adaptive chunking for subtopic extraction
        chunks_with_metadata = processor.adaptive_chunking(raw_text, document_analysis)
        
        # Smart sampling across document
        total_chunks = len(chunks_with_metadata)
        sample_chunks = []

        if total_chunks == 0:
            sample_chunks = []
        elif total_chunks <= 6:
            sample_chunks = chunks_with_metadata
        else:
            num_samples = 6
            step = max(1, total_chunks // num_samples)
            indices = {0, total_chunks - 1}
            
            for i in range(1, num_samples - 1):
                idx = i * step
                if 0 <= idx < total_chunks:
                    indices.add(idx)
            
            for idx in sorted(indices):
                sample_chunks.append(chunks_with_metadata[idx])

        sample_text = "\n\n".join(chunk['text'] for chunk in sample_chunks)

        # Enhance with section headings
        section_chunks = [chunk for chunk in chunks_with_metadata if chunk.get('chunk_type') == 'section']
        if section_chunks:
            section_based_subtopics = [chunk.get('section', '') for chunk in section_chunks if chunk.get('section')]
            if section_based_subtopics:
                sample_text += "\n\nDocument Sections: " + ", ".join(section_based_subtopics)

        print(f"📊 Subtopic Extraction Analysis:")
        print(f"   - Structure Score: {document_analysis.get('structure_score', 0):.2f}")
        print(f"   - Chunks Used: {len(sample_chunks)}")

        try:
            subtopics_llm_output = extract_subtopics_llm(
                doc_text=sample_text,
                api_key=Config.GROQ_API_KEY,
                n=10
            )
        except Exception as e:
            print(f"❌ Error in extract_subtopics_llm: {e}")
            subtopics_llm_output = get_enhanced_fallback_subtopics(raw_text, document_analysis)

        # Normalize output
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
        
        # Fallback if insufficient
        if not subs or len(subs) < 3:
            enhanced_subs = get_enhanced_fallback_subtopics(raw_text, document_analysis)
            subs = list(dict.fromkeys(subs + enhanced_subs))[:10]

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
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@api_bp.route('/custom/quiz-from-subtopics', methods=['POST'])
def quiz_from_subtopics():
    """Generate quiz based on chosen subtopics."""
    try:
        payload = request.get_json() or {}
        upload_id = payload.get("upload_id")
        chosen = payload.get("subtopics", [])
        totals = payload.get("totals", {})
        is_assignment = bool(payload.get("is_assignment"))
        difficulty = payload.get("difficulty", {})
        difficulty_mode = difficulty.get('mode', 'auto') if isinstance(difficulty, dict) else difficulty

        if not upload_id or upload_id not in _SUBTOPIC_UPLOADS:
            return jsonify({"error": "Invalid or expired upload_id"}), 400
        if not chosen:
            return jsonify({"error": "No subtopics provided"}), 400

        total_requested = sum(int(v) for v in totals.values()) if isinstance(totals, dict) else 0
        if total_requested <= 0:
            return jsonify({"error": "Totals must request at least 1 question"}), 400

        uploaded_data = _SUBTOPIC_UPLOADS[upload_id]
        full_text = uploaded_data['text']
        source_file = uploaded_data['file_name']

        out = generate_quiz_from_subtopics_llm(
            full_text=full_text,
            chosen_subtopics=chosen,
            totals={k: int(v) for k, v in totals.items()},
            difficulty=difficulty,
            api_key=Config.GROQ_API_KEY
        )

        questions = out.get("questions", [])
        if not questions:
            error_message = out.get('error', "LLM generated an empty quiz structure.")
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

        # Clean up memory
        if upload_id in _SUBTOPIC_UPLOADS:
            del _SUBTOPIC_UPLOADS[upload_id]

        return jsonify(resp), 200

    except Exception as e:
        print(f"❌ Error in quiz_from_subtopics: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@api_bp.route('/custom/advanced-assignment-topics', methods=['POST'])
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

        # Get existing context (for duplicate prevention)
        from services.embedding_service import get_embedding_service
        embedder = get_embedding_service()
        existing_context = ""
        
        if embedder and embedder.is_available():
            try:
                existing_context = embedder.get_existing_context(
                    topic_keywords=topics_list,
                    max_results=15
                )
            except Exception as e:
                print(f"⚠️ Could not get existing context: {e}")

        # Generate assignment using LLM
        from utils.assignment_utils import generate_advanced_assignments_llm
        
        result = generate_advanced_assignments_llm(
            full_text=topic_text,
            chosen_subtopics=topics_list,
            task_distribution=task_distribution,
            api_key=os.getenv("GROQ_API_KEY"),
            difficulty=difficulty,
            scenario_style=scenario_style,
            existing_context=existing_context
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

        # Save to database
        from services.db import save_quiz as save_quiz_to_store
        assignment_id = save_quiz_to_store(assignment_data)

        # Index questions (non-critical)
        if embedder and embedder.is_available():
            try:
                embedder.index_quiz_questions(
                    quiz_id=assignment_id,
                    questions=questions,
                    source='assignment_topics'
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
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/custom/advanced-assignment', methods=['POST'])
def generate_advanced_assignment():
    """
    Generate advanced assignment with multiple question types.
    Handles both new PDF uploads and previously uploaded PDFs.
    """
    try:
        # Try to get JSON data first (for already-uploaded PDFs)
        if request.is_json:
            # Using already-detected subtopics
            payload = request.get_json() or {}
            upload_id = payload.get("upload_id")
            chosen = payload.get("subtopics", [])
            task_distribution = payload.get("task_distribution", {})
            difficulty = payload.get("difficulty", "auto")
            scenario_style = payload.get("scenario_style", "auto")
        else:
            # New file upload with options
            if "file" not in request.files:
                return jsonify({"error": "Missing file or upload_id"}), 400
            
            file = request.files["file"]
            if not file or file.filename == "":
                return jsonify({"error": "Empty file"}), 400
            
            # Get options from form data
            options_raw = request.form.get("options")
            if not options_raw:
                return jsonify({"error": "Missing options"}), 400
            
            try:
                options = json.loads(options_raw)
            except Exception:
                return jsonify({"error": "Invalid JSON in options"}), 400
            
            upload_id = options.get("upload_id")
            chosen = options.get("subtopics", [])
            task_distribution = options.get("task_distribution", {})
            difficulty = options.get("difficulty", "auto")
            scenario_style = options.get("scenario_style", "auto")
        
        # Validate
        if not upload_id or upload_id not in _SUBTOPIC_UPLOADS:
            return jsonify({"error": "Invalid or expired upload_id. Please detect subtopics again."}), 400
        
        if not chosen:
            return jsonify({"error": "No subtopics selected"}), 400
        
        total_tasks = sum(task_distribution.values())
        if total_tasks <= 0:
            return jsonify({"error": "Task distribution must have at least 1 task"}), 400
        
        uploaded_data = _SUBTOPIC_UPLOADS[upload_id]
        full_text = uploaded_data["text"]
        source_file = uploaded_data["file_name"]
        
        # Get existing context (for duplicate prevention)
        from services.embedding_service import get_embedding_service
        embedder = get_embedding_service()
        existing_context = ""
        
        if embedder and embedder.is_available():
            try:
                existing_context = embedder.get_existing_context(
                    topic_keywords=chosen,
                    max_results=15
                )
            except Exception as e:
                print(f"⚠️ Could not get existing context: {e}")
        
        # Generate assignment
        from utils.assignment_utils import generate_advanced_assignments_llm
        
        result = generate_advanced_assignments_llm(
            full_text=full_text,
            chosen_subtopics=chosen,
            task_distribution=task_distribution,
            api_key=os.getenv("GROQ_API_KEY"),
            difficulty=difficulty,
            scenario_style=scenario_style,
            existing_context=existing_context
        )
        
        if not result.get("success"):
            error_detail = result.get("error", "Unknown error")
            return jsonify({
                "error": f"Assignment generation failed: {error_detail}"
            }), 500
        
        questions = result.get("questions", [])
        if not questions:
            return jsonify({
                "error": "LLM generated an empty assignment"
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
        
        # Save to database
        from services.db import save_quiz as save_quiz_to_store
        assignment_id = save_quiz_to_store(assignment_data)
        
        if not assignment_id:
            return jsonify({"error": "Failed to save assignment"}), 500
        
        # Index (non-critical)
        if embedder and embedder.is_available():
            try:
                embedder.index_quiz_questions(assignment_id, questions, 'assignment_pdf')
                print(f"✅ Indexed {len(questions)} assignment tasks")
            except Exception as e:
                print(f"⚠️ Indexing failed (non-critical): {e}")
        
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
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "message": "Internal server error during assignment generation"
        }), 500

    

@api_bp.route('/quizzes', methods=['POST'])
def api_create_quiz():
    """Create a new quiz from items."""
    data = request.get_json(force=True) or {}
    items = data.get("items") or []

    questions = normalize_quiz_questions(items)
    quiz_dict = create_quiz_dict(
        title=data.get("title") or "Untitled Quiz",
        questions=questions,
        metadata=data.get("metadata") or {}
    )

    quiz_id = save_quiz_to_store(quiz_dict)
    return jsonify({"id": quiz_id, "title": quiz_dict["title"]}), 201


@api_bp.route('/quizzes', methods=['GET'])
def api_list_quizzes():
    """List all quizzes, optionally filtered by kind."""
    kind = request.args.get("kind")
    quizzes = list_quizzes(kind=kind)

    return jsonify({
        "success": True,
        "items": quizzes,
        "kind": kind or "all",
    })


@api_bp.route('/quizzes/<quiz_id>/publish', methods=['POST'])
def api_publish_quiz(quiz_id):
    """Publish a quiz."""
    quiz = get_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({"ok": False, "error": "Quiz not found"}), 404

    quiz = publish_quiz_service(quiz, quiz_id)
    save_quiz_to_store(quiz)

    return jsonify({
        "ok": True,
        "quiz_id": quiz_id,
        "publish_url": quiz["publish_url"],
        "published_at": quiz["published_at"]
    }), 200

@api_bp.route('/quizzes/<quiz_id>/settings', methods=['POST'])
def api_update_quiz_settings(quiz_id):
    """Save time limit / due date / note for a quiz."""
    quiz = get_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({"ok": False, "error": "Quiz not found"}), 404

    data = request.get_json(force=True) or {}

    # Normalize fields
    time_limit = data.get("time_limit", 0)
    due_date = data.get("due_date", None)
    note = data.get("note", "")

    # Store settings in a dedicated object
    quiz.setdefault("settings", {})
    quiz["settings"]["time_limit"] = int(time_limit) if time_limit is not None else 0
    quiz["settings"]["due_date"] = due_date
    quiz["settings"]["note"] = note

    # keep other flags if you send them
    for k in ["allow_retakes", "shuffle_questions"]:
        if k in data:
            quiz["settings"][k] = data.get(k)

    save_quiz_to_store(quiz)  # must UPDATE same quiz, not create new one

    return jsonify({"ok": True, "quiz_id": quiz_id, "settings": quiz["settings"]}), 200


@api_bp.route('/quizzes/<quiz_id>/settings', methods=['GET'])
def api_get_quiz_settings(quiz_id):
    """Return saved settings for a quiz."""
    quiz = get_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({"ok": False, "error": "Quiz not found"}), 404

    return jsonify({
        "ok": True,
        "quiz_id": quiz_id,
        "settings": quiz.get("settings", {})
    }), 200

@api_bp.route('/generate-question', methods=['POST'])
def auto_generate_quiz():
    """Generate a simple AI-Powered quiz based on topic text."""
    try:
        payload = request.get_json() or {}
        topic_text = (payload.get("topic_text") or "").strip()
        totals = payload.get("totals", {})
        is_assignment = bool((payload or {}).get("is_assignment"))

        if not topic_text:
            return jsonify({"error": "Please enter a topic to generate a quiz."}), 400

        total_requested = sum(int(v) for v in totals.values()) if isinstance(totals, dict) else 0
        if total_requested <= 0:
            return jsonify({"error": "Totals must request at least 1 question"}), 400

        out = generate_quiz_from_subtopics_llm(
            full_text=topic_text,
            chosen_subtopics=[topic_text[:50] + "..."],
            totals={k: int(v) for k, v in totals.items()},
            difficulty="auto",
            api_key=Config.GROQ_API_KEY
        )

        questions = out.get("questions", [])
        if not questions:
            error_message = out.get('error', "LLM generated an empty quiz structure.")
            return jsonify({"error": f"Quiz generation failed: {error_message}"}), 500

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
        
        return jsonify({
            "success": True,
            "quiz_id": quiz_id,
            "questions_count": len(questions),
            "questions": questions,
            "quiz": quiz_data,
        }), 200

    except Exception as e:
        print(f"❌ Error in auto_generate_quiz: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500