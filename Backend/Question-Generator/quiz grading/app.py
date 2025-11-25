import os
from typing import Any, Dict

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from grader import QuizGrader
from ingestion import (
    parse_json_from_str_or_file,
    extract_pdf_text_from_file,
    responses_from_pdf_text,
)


load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    grader = QuizGrader(
        api_key=os.getenv("GROQ_API_KEY"),
        model=os.getenv("GROQ_MODEL", None),
        default_policy=os.getenv("GRADING_POLICY", "balanced"),
    )

    @app.get("/healthz")
    def health() -> Any:
        return jsonify({"ok": True})

    @app.post("/api/grade")
    def grade():
        try:
            data: Dict[str, Any] = request.get_json(force=True)  # type: ignore
        except Exception:
            return jsonify({"error": "Invalid JSON"}), 400

        quiz = data.get("quiz") or {}
        responses = data.get("responses") or {}
        grading = data.get("grading") or {}

        policy = grading.get("policy")
        rubric_weighting = grading.get("rubric_weighting")

        try:
            result = grader.grade_quiz(
                quiz=quiz,
                responses=responses,
                policy=policy,
                rubric_weighting=rubric_weighting,
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": f"grading_failed: {e}"}), 500

    @app.post("/api/grade-upload")
    def grade_upload():
        """Accept multipart form-data with quiz and responses as JSON or PDF.
        Fields:
          - quiz_json: JSON string (alternative to quiz_file)
          - quiz_file: JSON file (application/json)
          - responses_file: JSON or PDF file
          - policy: optional grading policy
          - rubric_weighting: optional JSON string
        """
        # Quiz
        quiz: Dict[str, Any] = {}
        if 'quiz_json' in request.form and request.form['quiz_json'].strip():
            try:
                quiz = parse_json_from_str_or_file(request.form['quiz_json'])
            except Exception as e:
                return jsonify({"error": f"invalid_quiz_json: {e}"}), 400
        elif 'quiz_file' in request.files:
            qf = request.files['quiz_file']
            try:
                quiz = parse_json_from_str_or_file(qf.read())
            except Exception as e:
                return jsonify({"error": f"invalid_quiz_file: {e}"}), 400
        else:
            return jsonify({"error": "missing quiz_json or quiz_file"}), 400

        # Responses
        if 'responses_file' not in request.files:
            return jsonify({"error": "missing responses_file"}), 400
        rf = request.files['responses_file']
        rname = (rf.filename or '').lower()
        rbytes = rf.read()

        try:
            if rname.endswith('.json') or rf.mimetype == 'application/json':
                responses = parse_json_from_str_or_file(rbytes)
            elif rname.endswith('.pdf') or rf.mimetype in {'application/pdf', 'application/x-pdf'}:
                text = extract_pdf_text_from_file(rbytes)
                responses = responses_from_pdf_text(text, quiz)
            else:
                return jsonify({"error": "responses_file must be .json or .pdf"}), 400
        except Exception as e:
            return jsonify({"error": f"invalid_responses_file: {e}"}), 400

        policy = request.form.get('policy')
        rubric_weighting = None
        rubric_str = request.form.get('rubric_weighting')
        if rubric_str:
            try:
                rubric_weighting = parse_json_from_str_or_file(rubric_str)
            except Exception as e:
                return jsonify({"error": f"invalid_rubric_weighting: {e}"}), 400

        try:
            result = grader.grade_quiz(
                quiz=quiz,
                responses=responses,
                policy=policy,
                rubric_weighting=rubric_weighting,
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": f"grading_failed: {e}"}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5051"))
    app.run(host=host, port=port, debug=bool(os.getenv("DEBUG", "").lower() in {"1","true","yes"}))


