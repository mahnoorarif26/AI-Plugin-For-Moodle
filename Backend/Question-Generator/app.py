import os
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()

# Get API key safely
api_key = os.getenv("GROQ_API_KEY")

client = Groq(api_key=api_key)

completion = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[
        {"role": "user", "content": "Generate code-based Python questions for beginners."}
    ],
    temperature=1,
    max_completion_tokens=512,
    top_p=1,
    stream=True
)

for chunk in completion:
    print(chunk.choices[0].delta.content or "", end="")
