import json
import math
import os
from groq import Groq

# Choose a sensible default model here so .env only needs the API key
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are an expert exam-setter. You will read the provided PDF excerpts and generate
high-quality quiz questions in strict JSON (no prose outside JSON).

Question types you may use:
- mcq: Multiple choice (exactly 4 options, with one correct answer; include explanation).
- true_false: A statement marked true or false; include explanation.
- short: Short answer (1-3 sentences).
- long: Long answer (4-8 sentences or key points).

Difficulty guidelines:
- easy: direct recall/definitions/examples from text
- medium: understanding/application across 1-2 paragraphs
- hard: inference/synthesis/edge cases, multi-part reasoning

ALWAYS return a single JSON object with:
{
 "questions": [
    {
      "id": "q1",
      "type": "mcq|true_false|short|long",
      "prompt": "string",
      "options": ["A","B","C","D"],      // only for mcq; exactly 4
     "answer": "string|0|1|2|3|true|false",
     "explanation": "string (why/derivation, if applicable)",
     "difficulty": "easy|medium|hard",
     "tags": ["topic","subtopic"]
    },
    ... 
],
"source_note": "brief note about which parts of the PDF were used"
}

No backticks. No commentary. Output must be valid JSON ONLY.
"""

def build_user_prompt(pdf_chunks,
                    num_questions,
                    qtypes,
                    difficulty_mode,
                    mix_counts):

    type_line = (
        f"Allowed types: {', '.join(qtypes)}."
         if qtypes else
        "Allowed types: mcq, true_false, short, long."
 )

    count_line = (
        "Number of questions: auto (choose a sensible count based on content length, typically 10–25)."
        if num_questions is None else
         f"Number of questions: {num_questions}."
    )


    if difficulty_mode == "auto":
        diff_line = "Difficulty mix: auto (balanced across easy/medium/hard)."
    else:
        diff_line = (
            "Difficulty mix (counts): "
            f"easy={mix_counts.get('easy',0)}, "
            f"medium={mix_counts.get('medium',0)}, "
            f"hard={mix_counts.get('hard',0)}."
        )

    # === NEW LOGIC TO ENFORCE 2-3 MCQ / 4-5 SHORT SPLIT IN AUTO MODE ===
    # This targets the default 'Auto' mode where num_questions is set (e.g., 8) and only mcq/short are selected.
    specific_ratio_line = ""
    if (difficulty_mode == "auto" and 
    num_questions is not None and
        len(qtypes) == 2 and
        "mcq" in qtypes and 
        "short" in qtypes and 
        6 <= num_questions <= 9):
        # Inject instruction to meet the required 2-3 MCQ and 4-5 Short Answer range.
        specific_ratio_line = (
             "Crucially, you must prioritize the question types to meet the target range: "
            "generate 2 to 3 Multiple Choice Questions (MCQ) and 4 to 5 Short Answer questions. "
             "Ensure the total number of generated questions equals the requested number."
        )
    # ===================================================================

    # Keep first few chunks to respect context limits
    head_chunks = pdf_chunks[:6]
    joined = "\n\n".join(f"[PDF chunk {i+1}]\n{c}" for i, c in enumerate(head_chunks))
    return f"""
        You are given excerpts from a PDF (course/assignment/notes). Generate quiz questions strictly from this material.

{count_line}
{type_line}
{diff_line}
{specific_ratio_line}

Use clear, unambiguous academic wording. Avoid trick questions unless needed for "hard".
Distribute tags meaningfully (e.g., chapter names, key concepts).
Vary verbs (define, explain, compare, derive, choose best).

PDF EXCERPTS START
{joined}
PDF EXCERPTS END
""".strip()


def _allocate_counts(total: int, easy: int, med: int, hard: int) -> dict:
    """Convert percentages to integer counts that sum to total."""
    if total is None:
        return {}
    raw = {
        "easy":   total * (easy/100),
        "medium": total * (med/100),
        "hard":   total * (hard/100),
    }
    counts = {k: int(round(v)) for k, v in raw.items()}
    drift = total - sum(counts.values())
    order = sorted(raw, key=lambda k: raw[k] - math.floor(raw[k]), reverse=True)
    for k in order:
        if drift == 0:
            break
        counts[k] += 1 if drift > 0 else -1
        drift += -1 if drift > 0 else 1
    return counts

def enforce_custom_mix(questions, mix_counts, num_questions):
    """Trim/arrange questions to respect custom difficulty counts."""
    if not num_questions:
        return questions
    buckets = {"easy": [], "medium": [], "hard": []}
    others = []
    for q in questions:
        d = (q.get("difficulty") or "").lower()
        if d in buckets:
            buckets[d].append(q)
        else:
            others.append(q)

    final = []
    for k in ("easy", "medium", "hard"):
        want = max(0, mix_counts.get(k, 0))
        final.extend(buckets[k][:want])

    if len(final) < num_questions:
        pool = []
        for k in ("easy", "medium", "hard"):
            pool.extend(buckets[k][len(final):])
        pool.extend(others)
        final.extend(pool[: max(0, num_questions - len(final))])

    return final[:num_questions]

def sanitize_mcq(q):
    """Ensure MCQ has exactly 4 options and a valid answer."""
    if q.get("type") != "mcq":
        return q
    opts = q.get("options") or []
    if len(opts) != 4:
        return None
    ans = q.get("answer")
    if isinstance(ans, int):
        if ans < 0 or ans > 3:
            return None
    elif isinstance(ans, str):
        if ans not in opts:
            return None
    elif isinstance(ans, bool):
        # bool not allowed for mcq
        return None
    return q

def sanitize_true_false(q):
    if q.get("type") != "true_false":
        return q
    ans = q.get("answer")
    if isinstance(ans, str):
        if ans.lower() not in ("true", "false"):
            return None
    elif isinstance(ans, bool):
        pass
    else:
        return None
    return q

def sanitize_question(q):
    """Basic schema checks."""
    if not isinstance(q, dict): return None
    if q.get("type") not in ("mcq","true_false","short","long"): return None
    if not q.get("prompt"): return None
    if "difficulty" not in q or q["difficulty"] not in ("easy","medium","hard"): return None

    t = q["type"]
    if t == "mcq":
        return sanitize_mcq(q)
    if t == "true_false":
        return sanitize_true_false(q)
    # short/long: no extra constraints beyond prompt/difficulty
    return q

def filter_and_trim_questions(questions, allowed_types, difficulty_mode, mix_counts, num_questions):
    # Filter by type if requested
    if allowed_types:
        questions = [q for q in questions if (q.get("type") in allowed_types)]
    # Sanitize
    cleaned = []
    for q in questions:
        sq = sanitize_question(q)
        if sq is not None:
            cleaned.append(sq)

    # Enforce counts
    if difficulty_mode == "custom" and num_questions:
        cleaned = enforce_custom_mix(cleaned, mix_counts, num_questions)
    elif difficulty_mode == "auto" and num_questions and len(cleaned) > num_questions:
        cleaned = cleaned[:num_questions]
    return cleaned

def call_groq_json(system_prompt: str, user_prompt: str, api_key: str, model: str | None = None, temperature: float = 0.3, max_tokens: int = 2500) -> dict:
    """Call Groq in JSON mode and return parsed dict."""
    client = Groq(api_key=api_key)
    chat = client.chat.completions.create(
        model=model or DEFAULT_GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    content = chat.choices[0].message.content
    return json.loads(content)
