from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)
LM_STUDIO_URL = "http://localhost:1234/v1/completions"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate-question', methods=['POST'])
def generate_question():
    try:
        data = request.get_json()
        topic = data.get("topic", "").strip()

        if not topic:
            return jsonify({"success": False, "error": "No topic provided"}), 400

        prompt = f"""
                Generate exactly 5 short questions about {topic}? Each question should be difficult and to the point.
                """



        payload = {
            "model": "llama-2-7b",
            "prompt": prompt,
            "max_tokens": 150,
            "temperature": 0.8,
            "stop": ["Answer:", "Explanation:"]
        }


        response = requests.post(LM_STUDIO_URL, json=payload)
        response.raise_for_status()
        result = response.json()

        generated_text = result["choices"][0]["text"].strip()

        return jsonify({
            "success": True,
            "question": generated_text
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
