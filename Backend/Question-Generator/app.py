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
        
        prompt = f"""Generate {num_questions} high-quality quiz questions for students on the topic of {topic}.No explaination"""

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=1000,
            temperature=0.7,
            top_p=1
        )

        output = completion.choices[0].message.content
        return jsonify({"questions": output})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)