import json
import os
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

from utils import (
    extract_pdf_text,
    split_into_chunks,
    build_user_prompt,
    SYSTEM_PROMPT,
    call_groq_json,
)
from utils.groq_utils import _allocate_counts, filter_and_trim_questions  # internal helpers

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing in environment (.env).")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
@app.route('/')
def index():
    return render_template('index.html')

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/api/quiz/from-pdf", methods=["POST"])
def quiz_from_pdf():
    try:
        # ---- file (PDF) ----
        if "file" not in request.files:
            return ("Missing file (multipart field 'file')", 400)

        file = request.files["file"]
        if not file or file.filename == "":
            return ("Empty file", 400)

        # Windows/Chrome sometimes sends octet-stream; accept by extension too
        if not (file.mimetype == "application/pdf" or file.filename.lower().endswith(".pdf")):
            return ("Only PDF accepted (.pdf)", 400)

        # ---- options (JSON) ----
        options_raw = request.form.get("options")
        if not options_raw:
            # Some browsers send 'options' as a file part; accept that too
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

        num_questions = options.get("num_questions")  # can be None
        qtypes = options.get("question_types", [])
        diff   = options.get("difficulty", {"mode": "auto"})
        diff_mode = diff.get("mode", "auto")

        # ---- PDF -> text ----
        text = extract_pdf_text(file)
        if not text.strip():
            return ("Could not extract text from PDF", 400)

        chunks = split_into_chunks(text)

        # ---- difficulty mix ----
        mix_counts = {}
        if diff_mode == "custom":
            mix_counts = _allocate_counts(
                total=num_questions if num_questions is not None else 0,
                easy=int(diff.get("easy", 0)),
                med=int(diff.get("medium", 0)),
                hard=int(diff.get("hard", 0)),
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
            }
        }
        return jsonify(result), 200

    except json.JSONDecodeError:
        return ("Model returned invalid JSON. Try reducing PDF length or rephrasing.", 502)
    except Exception as e:
        return (f"Server error: {str(e)}", 500)

if __name__ == "__main__":
    # Use 0.0.0.0 if you want to reach it from your phone/laptop on LAN
    app.run(host="127.0.0.1", port=5000, debug=True)
