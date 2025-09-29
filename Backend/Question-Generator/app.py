import os, re, json
from dotenv import load_dotenv
from flask import Flask, request, render_template, jsonify
from groq import Groq

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise RuntimeError("Missing GROQ_API_KEY in .env")

app = Flask(__name__)
client = Groq(api_key=api_key)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate-quiz", methods=["POST"])
def generate_quiz():
    try:
        data = request.get_json(force=True) or {}
        topic = (data.get("topic") or "").strip()
        if not topic:
            return jsonify({"ok": False, "error": "Topic is required"}), 400

        num_questions  = max(3, min(int(data.get("num_questions", 5)), 20))
        question_types = data.get("question_types", [])
        structured     = bool(data.get("structured", False))  # NEW flag

        # ----- Build composition text -----
        if question_types:
            base = num_questions // len(question_types)
            rem  = num_questions % len(question_types)
            dist = {t: base for t in question_types}
            for i in range(rem):
                dist[question_types[i]] += 1
            mix = []
            if "mcq"   in dist: mix.append(f'{dist["mcq"]} MCQs')
            if "short" in dist: mix.append(f'{dist["short"]} short answers')
            if "long"  in dist: mix.append(f'{dist["long"]} long/scenario-based')
            mix_text = ", ".join(mix)
        else:
            mix_text = "2–3 MCQs, 2–3 short answers, and 1 scenario-based (if count ≥ 5)"

        # ----- Prompt (plain text vs JSON) -----
        if not structured:
            prompt = f"""
Generate {num_questions} quiz questions on "{topic}".
Mix: {mix_text}.
Rules:
- Balance easy/medium/hard
- MCQs: 4 options A–D, one correct
- Short/long: require reasoning
- For algorithms/programming: include scenarios or code
Output format (plain text):

1. (MCQ) Question?
   A. ...
   B. ...
   C. ...
   D. ...
"""
        else:
            prompt = f"""
You are a strict quiz generator. Return ONLY a JSON object in this schema:
{{
  "topic": "{topic}",
  "questions": [
    {{
      "type": "mcq" | "short" | "long",
      "prompt": "question text",
      "options": ["A ...","B ...","C ...","D ..."] | null,
      "answer": "A"/"B"/"C"/"D" | "reference text",
      "explanation": "why this answer is correct" | null,
      "difficulty": "easy" | "medium" | "hard"
    }}
  ]
}}
Constraints:
- Total {num_questions} questions
- Mix: {mix_text}
- Must balance easy/medium/hard
- MCQs: exactly 4 options
- Include scenario-based items if topic relates to algorithms/programming
Return ONLY the JSON object. Do not include markdown or extra text.
"""

        # ----- Call Groq -----
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=2000,
            temperature=0.6,
        )
        raw = completion.choices[0].message.content or ""

        # ----- Return plain text mode -----
        if not structured:
            return jsonify({"ok": True, "format": "text", "questions": raw})

        # ----- Try JSON parse, fallback to text -----
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            return jsonify({"ok": True, "format": "text", "questions": raw,
                            "note": "Model did not return JSON; fallback to text."})

        try:
            obj = json.loads(m.group(0))
            return jsonify({"ok": True, "format": "json", "json": obj})
        except Exception:
            return jsonify({"ok": True, "format": "text", "questions": raw,
                            "note": "JSON parse failed; fallback to text."})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
