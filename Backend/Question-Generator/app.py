import json
import os
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
# === NEW IMPORTS FOR FIREBASE ===
#import firebase_admin
#from firebase_admin import credentials, firestore
from datetime import datetime
# ================================
# ⬇️ add with your other imports (near the top)
from typing import List, Dict
import re
import uuid

# simple in-memory store for uploaded pdf text
_SUBTOPIC_UPLOADS: Dict[str, str] = {}


from utils import (
    extract_pdf_text,
    split_into_chunks,
    build_user_prompt,
    SYSTEM_PROMPT,
    call_groq_json,
      # <-- Added missing import
      # <-- Added missing import for subtopic extraction
)

def enforce_flag_targets(questions, scenario_target, code_target):
    """
    Ensures that the number of scenario-based and code snippet questions matches the requested targets.
    If there are fewer than requested, it sets the flags on additional questions.
    """
    scenario_count = sum(1 for q in questions if q.get("scenario_based"))
    code_count = sum(1 for q in questions if q.get("code_snippet"))

    # Enforce scenario_based flag
    if scenario_count < scenario_target:
        for q in questions:
            if not q.get("scenario_based"):
                q["scenario_based"] = True
                scenario_count += 1
                if scenario_count >= scenario_target:
                    break

    # Enforce code_snippet flag
    if code_count < code_target:
        for q in questions:
            if not q.get("code_snippet"):
                q["code_snippet"] = True
                code_count += 1
                if code_count >= code_target:
                    break

    return questions
from utils.groq_utils import _allocate_counts, filter_and_trim_questions ,extract_subtopics_llm,generate_quiz_from_subtopics_llm # internal helpers

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# === NEW CONFIG FOR FIREBASE KEY PATH ===
# NOTE: You MUST create a .env variable called FIREBASE_SERVICE_ACCOUNT_PATH
# pointing to your downloaded Firebase Service Account JSON key.
# For local testing, you can use a default path like below, but update it.
FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "./serviceAccountKey.json")
# ========================================

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing in environment (.env).")

# ===========================
# FIREBASE SETUP
# ===========================
db = None
try:
    # Initialize the Firebase App using the service account key
    #cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_PATH)
    #firebase_admin.initialize_app(cred)
    #db = firestore.client()
    print("Firebase App Initialized successfully.")
except Exception as e:
    # This print statement ensures you know if Firestore is active
    print(f"WARNING: Firebase failed to initialize. Quizzes will NOT be saved to Firestore. Please check your FIREBASE_SERVICE_ACCOUNT_PATH. Error: {e}")
    db = None # Set db to None if initialization fails

# Function to save the quiz data
def save_quiz_to_firestore(quiz_data: dict):
    if db is None:
        print("Error: Firestore client is not available. Skipping save operation.")
        return None
    
    try:
        # Store the complete quiz result object
        # The .add() method creates a new document with an auto-generated ID
        doc_ref = db.collection('ai_quizzes').add({
            **quiz_data,
            "created_at": datetime.now(),
        })
        # doc_ref is a tuple (write_time, DocumentReference). We need the ID from the reference.
        return doc_ref[1].id
    except Exception as e:
        print(f"Error saving quiz to Firestore: {e}")
        return None
# ===========================


app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route('/')
def index():
    return render_template('index.html')

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/api/quiz/from-pdf", methods=["POST"])
@app.route("/api/quiz/from-pdf", methods=["POST"])
def quiz_from_pdf():
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

        # ---- Distribution and flag targets ----
        dist = options.get("distribution", {})
        
        # FIX: Properly handle scenario_based and code_snippet counts
        scenario_target = options.get("scenario_based", 0)
        code_target = options.get("code_snippet", 0)
        
        # Convert to integers
        try:
            scenario_target = int(scenario_target)
            code_target = int(code_target)
        except (ValueError, TypeError):
            scenario_target = 0
            code_target = 0
        
        # Ensure non-negative
        scenario_target = max(0, scenario_target)
        code_target = max(0, code_target)

        # ---- PDF -> text ----
        text = extract_pdf_text(file)
        if not text.strip():
            return ("Could not extract text from PDF", 400)

        chunks = split_into_chunks(text)

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
            scenario_target=scenario_target,
            code_target=code_target,
        )

        llm_json = call_groq_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=GROQ_API_KEY,
        )

        questions = llm_json.get("questions", [])
        
        # FIX: Apply flag enforcement AFTER getting questions from LLM
        questions = enforce_flag_targets(questions, scenario_target, code_target)
        
        questions = filter_and_trim_questions(
            questions=questions,
            allowed_types=qtypes,
            difficulty_mode=diff_mode,
            mix_counts=mix_counts,
            num_questions=num_questions,
        )

        result = {
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
                "flag_targets": {
                    "scenario_based": scenario_target,
                    "code_snippet": code_target
                },
                "source_note": llm_json.get("source_note", ""),
            }
        }

        return jsonify(result), 200

    except json.JSONDecodeError:
        return ("Model returned invalid JSON. Try reducing PDF length or rephrasing.", 502)
    except Exception as e:
        return (f"Server error: {str(e)}", 500)


@app.route("/api/custom/extract-subtopics", methods=["POST"])
def extract_subtopics():
    if "file" not in request.files:
        return jsonify({"error": "Missing file (multipart field 'file')"}), 400
    f = request.files["file"]
    if not (f.mimetype == "application/pdf" or f.filename.lower().endswith(".pdf")):
        return jsonify({"error": "Only PDF accepted (.pdf)"}), 400

    text = extract_pdf_text(f)
    if not text.strip():
        return jsonify({"error": "Could not extract text from PDF"}), 400

    upload_id = str(uuid.uuid4())
    _SUBTOPIC_UPLOADS[upload_id] = text

    subs = extract_subtopics_llm(
        doc_text=text,
        api_key=GROQ_API_KEY
    )

    return jsonify({"upload_id": upload_id, "subtopics": subs}), 200


@app.route("/api/custom/quiz-from-subtopics", methods=["POST"])
def quiz_from_subtopics():
    payload = request.get_json(silent=True) or {}
    upload_id = payload.get("upload_id")
    chosen = payload.get("subtopics") or []

    totals = payload.get("totals") or {}  # {"mcq":2,"true_false":1,"short":3,"long":0}
    difficulty = payload.get("difficulty") or {"mode": "auto"}
    scenario_based = bool(payload.get("scenario_based") or False)
    code_snippet   = bool(payload.get("code_snippet") or False)

    if not upload_id or upload_id not in _SUBTOPIC_UPLOADS:
        return jsonify({"error": "Invalid or expired upload_id; run subtopic detection again."}), 400
    if not chosen:
        return jsonify({"error": "No subtopics provided"}), 400

    total_requested = int(totals.get("mcq", 0)) + int(totals.get("true_false", 0)) \
                      + int(totals.get("short", 0)) + int(totals.get("long", 0))
    if total_requested <= 0:
        return jsonify({"error": "Totals must request at least 1 question across types."}), 400

    full_text = _SUBTOPIC_UPLOADS[upload_id]

    out = generate_quiz_from_subtopics_llm(
        full_text=full_text,
        chosen_subtopics=chosen,
        totals={
            "mcq": int(totals.get("mcq", 0)),
            "true_false": int(totals.get("true_false", 0)),
            "short": int(totals.get("short", 0)),
            "long": int(totals.get("long", 0)),
        },
        difficulty=difficulty,
        scenario_based=scenario_based,
        code_snippet=code_snippet,
        api_key=GROQ_API_KEY
    )

    result = {
        "questions": out.get("questions", []),
        "metadata": {
            "source": "subtopics",
            "upload_id": upload_id,
            "selected_subtopics": chosen,
            "totals_requested": totals,
            "difficulty": difficulty,
            "flags": {
                "scenario_based": scenario_based,
                "code_snippet": code_snippet
            }
        }
    }
    return jsonify(result), 200

def enforce_flag_targets(questions, scenario_target, code_target):
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
if __name__ == "__main__":
    # Use 0.0.0.0 if you want to reach it from your phone/laptop on LAN
    app.run(host="127.0.0.1", port=5000, debug=True)