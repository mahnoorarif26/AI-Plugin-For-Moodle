import json
from typing import Optional, Dict, Any

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def chat_json(
    *,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 1500,
) -> Dict[str, Any]:
    """
    Call Groq chat completions in JSON mode and return parsed dict.

    Uses JSON response_format and validates that the returned content
    is non-empty and valid JSON before returning.
    """
    from groq import Groq

    client = Groq(api_key=api_key)

    try:
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
        if not content:
            raise ValueError("Empty response from API")

        return json.loads(content)

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON response: {e}")
    except Exception as e:
        raise RuntimeError(f"API call failed: {e}")
