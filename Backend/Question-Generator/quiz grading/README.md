Quiz Grading Module (Standalone)

Overview
- Self-contained Flask service for grading quizzes: MCQ, True/False, Short, and Long/Conceptual answers.
- Uses Groq LLM (default model `llama-3.3-70b-versatile`) to evaluate free-form answers and generate feedback.
- Does not modify existing code; built to integrate later with the Question-Generator backend.

Quick Start
- Set environment variable `GROQ_API_KEY` (use `.env` locally).
- Install: `pip install -r requirements.txt`
- Run: `python app.py`
- Health: `GET /healthz`
- Grade: `POST /api/grade` (JSON)
- Grade (uploads): `POST /api/grade-upload` (multipart; JSON quiz + JSON or PDF answers)

POST /api/grade
Request JSON shape:
{
  "quiz": {
    "id": "quiz123",
    "questions": [
      {
        "id": "q1",
        "type": "mcq|true_false|short|long",
        "prompt": "...",
        "options": ["A","B","C","D"],          // for mcq
        "answer": "B" | 1 | "option text",        // ground truth (optional for free-form)
        "max_score": 1                                // optional; default by type
      }
    ]
  },
  "responses": { "q1": "B", "q2": "free text" },
  "grading": {
    "policy": "balanced|strict|lenient",            // optional
    "llm_model": "llama-3.3-70b-versatile",         // optional
    "rubric_weighting": {"accuracy":0.5,"completeness":0.3,"clarity":0.2}
  }
}

Response JSON shape:
{
  "quiz_id": "quiz123",
  "total_score": 7.5,
  "max_total": 10,
  "items": [
    {
      "question_id":"q1",
      "type":"mcq",
      "score":1,
      "max_score":1,
      "is_correct":true,
      "feedback":"Correct."
    }
  ]
}

Notes
- MCQ/True-False are graded locally for speed and determinism.
- Short/Long answers use LLM JSON-mode scoring with structured feedback and a rubric.
- If the LLM is unavailable, a lightweight heuristic fallback is used when a reference answer exists.

File Uploads: POST /api/grade-upload
- Content-Type: `multipart/form-data`
- Fields:
  - `quiz_json`: JSON string for quiz (or provide `quiz_file`(json file) instead).
  - `quiz_file`: JSON file with quiz (same shape as above).
  - `responses_file`: Either a `.json` mapping `{qid: answer}` or a `.pdf` with student answers.
  - `policy`: optional grading policy.
  - `rubric_weighting`: optional JSON string like `{ "accuracy":0.5, "completeness":0.3, "clarity":0.2 }`.

Notes
- Only JSON is accepted for uploads (quiz and responses).
- MCQ/True-False are graded locally; short/long use LLM with heuristic fallback if no API key.
