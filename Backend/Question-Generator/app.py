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
                The quiz must contain a mix of:
                - Multiple Choice Questions (with 4 options, 1 correct)
                - Short Answer Questions (2–3 sentences expected)
                - Long Answer Questions (3–4 sentences expected, more descriptive/analytical)
                - If the subject requires, include code-based or scenario-based questions.

                Do not provide answers, only the questions.
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
        
        type_descriptions = []
        if "mcq" in question_types:
            type_descriptions.append("multiple-choice questions with 4 options")
        if "short" in question_types:
            type_descriptions.append("short answer questions")
        if "long" in question_types:
            type_descriptions.append("long answer/medium questions")
        
        type_description = " and ".join(type_descriptions)
        
        prompt = f"""Generate {num_questions} high-quality {type_description} for students on the topic of {topic}.
        
        Format requirements:
        - Clearly label each question with its type (MCQ, Short Answer, Long Answer)
        - For MCQ questions, provide 4 options labeled A, B, C, D and indicate the correct answer
        - For Short Answer questions, keep answers concise (1-2 sentences)
        - For Long Answer questions, provide detailed questions that require paragraph-length responses
        - Number all questions sequentially
        - Separate different question types with clear headings"""

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