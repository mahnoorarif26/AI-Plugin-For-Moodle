import os
from dotenv import load_dotenv
from flask import Flask, request, render_template, jsonify
from groq import Groq

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

app = Flask(__name__)

client = Groq(api_key=api_key)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate-question", methods=["POST"])
def generate_question():
    try:
        data = request.json
        topic = data.get("topic", "Python basics")
        num_questions = int(data.get("num_questions", 5))
        
        prompt = f"""
        Generate {num_questions} high-quality quiz questions for students on the topic "{topic}".
        The quiz must contain a mix of question types(2-3 mcqs,2-3 short question and 1 long).
        If subject is coding, include code snippets in questions.

        IMPORTANT: Return the questions in plain text format, NOT markdown tables.
        Format each question clearly with:
        - Question number and type
        - The question text
        - Options (for MCQ) labeled A, B, C, D

        Avoid using markdown tables or complex formatting.
        Use simple text formatting like:
        1. (MCQ) Your question here?
           A. Option 1
           B. Option 2
           C. Option 3
           D. Option 4

        Keep it simple and readable.
        """



        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=8192,
            temperature=0.7,
            top_p=1
        )

        output = completion.choices[0].message.content
        return jsonify({"questions": output})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/generate-custom-quiz", methods=["POST"])
def generate_custom_quiz():
    try:
        data = request.json
        topic = data.get("topic", "Python basics")
        num_questions = int(data.get("num_questions", 5))
        question_types = data.get("question_types", [])
        
        if not question_types:
            return jsonify({"error": "Please select at least one question type"}), 400

        # ✅ Fair distribution of questions across selected types
        base = num_questions // len(question_types)
        remainder = num_questions % len(question_types)

        distribution = {qtype: base for qtype in question_types}
        for i in range(remainder):
            distribution[question_types[i]] += 1

        # ✅ Build type description string for prompt
        type_descriptions = []
        if "mcq" in question_types:
            type_descriptions.append(f"{distribution['mcq']} multiple-choice questions with 4 options")
        if "short" in question_types:
            type_descriptions.append(f"{distribution['short']} short answer questions")
        if "long" in question_types:
            type_descriptions.append(f"{distribution['long']} long answer/medium questions")

        type_description = ", ".join(type_descriptions)

        prompt = f"""Generate exactly {num_questions} quiz questions for students on the topic "{topic}".
        The quiz should include: {type_description}.

        IMPORTANT: Return the questions in plain text format, NOT markdown tables.
        Format each question clearly with:
        - Question number and type
        - The question text
        - Options (for MCQ) labeled A, B, C, D

        Example format:
        1. (MCQ) Your question here?
           A. Option 1
           B. Option 2
           C. Option 3
           D. Option 4

        Keep it simple and readable.
        """

        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=2000,
            temperature=0.7,
            top_p=1
        )

        output = completion.choices[0].message.content
        return jsonify({"questions": output})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)