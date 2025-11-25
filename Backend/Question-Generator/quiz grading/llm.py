import json
from typing import Optional, Dict, Any

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def chat_json(
    *,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> Dict[str, Any]:
    """Call Groq chat completions in JSON mode and return parsed dict."""
    # Lazy import to avoid hard dependency during non-LLM flows (e.g., heuristic tests)
    from groq import Groq
    client = Groq(api_key=api_key)
    chat = client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    content = chat.choices[0].message.content
    return json.loads(content)
