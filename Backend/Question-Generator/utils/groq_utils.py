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
        "Number of questions: auto (choose a sensible count based on content length, typically 10-25)."
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
    if difficulty_mode == "auto" and num_questions is not None:
        # Enforce 1-2 MCQs and then fill with short-answer questions
        if "mcq" in qtypes and "short" in qtypes:
            specific_ratio_line = (
                "Crucially, generate 1 to 2 Multiple Choice Questions (MCQ), "
                "followed by short-answer questions to meet the total number of questions."
            )

    # Ensure chunks and context
    head_chunks = pdf_chunks[:6]  # Limit to 6 chunks, ensure prompt does not exceed limits
    joined = "\n\n".join(f"[PDF chunk {i+1}]\n{c}" for i, c in enumerate(head_chunks))

    return f"""
        You are given excerpts from a PDF (course/assignment/notes). Generate quiz questions strictly from this material.

{count_line}
{type_line}
{diff_line}
{specific_ratio_line}

PDF EXCERPTS START
{joined}
PDF EXCERPTS END
""".strip()


def _allocate_counts(total_questions: int, easy: int = 30, med: int = 50, hard: int = 20):
    """
    Allocate counts for each difficulty level based on percentages.
    """
    total_percent = easy + med + hard
    if total_percent == 0:
        return {"easy": 0, "medium": 0, "hard": 0}
    
    counts = {
        "easy": max(0, round(total_questions * easy / total_percent)),
        "medium": max(0, round(total_questions * med / total_percent)),
        "hard": max(0, round(total_questions * hard / total_percent))
    }
    
    # Adjust for rounding errors
    total_allocated = counts["easy"] + counts["medium"] + counts["hard"]
    if total_allocated != total_questions:
        diff = total_questions - total_allocated
        if diff > 0:
            counts["medium"] += diff
        else:
            counts["hard"] = max(0, counts["hard"] + diff)
    
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

# ================================
# Subtopic extraction + targeted quiz
# ================================
def extract_subtopics_llm(doc_text: str, api_key: str | None = None, model: str | None = None) -> list[str]:
    """
    Return a clean list of subtopic titles (short, distinct).
    """
    system = (
        "Extract clean, distinct subtopics from an academic document. "
        "Return ONLY JSON with {\"subtopics\": [\"...\"]}. Titles must be concise (≤ 8 words)."
    )
    user = (
        "From the following text, list 10–25 key subtopics as concise titles. "
        "Avoid duplicates and remove obvious noise like headers/footers.\n\n"
        f"TEXT:\n{doc_text[:12000]}"
    )

    try:
        out = call_groq_json(system, user, api_key=api_key, model=model, max_tokens=1200)
        arr = out.get("subtopics", [])
        # de-dup + trim empties
        cleaned = []
        seen = set()
        for t in arr:
            if not isinstance(t, str):
                continue
            s = t.strip()
            if len(s) >= 2 and s.lower() not in seen:
                seen.add(s.lower())
                cleaned.append(s[:120])
        return cleaned[:30]
    except Exception:
        return []


def generate_quiz_from_subtopics_llm(full_text: str, chosen_subtopics: list[str], count_per: int = 2,
                                     api_key: str | None = None, model: str | None = None) -> dict:
    """
    Build a targeted prompt constrained to the selected subtopics, mixing types naturally.
    Returns a dict like {"questions":[...]} (your renderer already supports it).
    """
    # small heuristic "retrieval": take lines containing the subtopic text
    lines = [ln for ln in full_text.splitlines() if ln.strip()]
    import re
    selected = []
    for st in chosen_subtopics:
        pat = re.compile(re.escape(st), re.IGNORECASE)
        hits = [ln for ln in lines if pat.search(ln)]
        selected.extend(hits[:60])  # budget per subtopic

    if not selected:
        selected = lines[:400]

    total = max(1, count_per * max(1, len(chosen_subtopics)))

    system_prompt = """You are an expert exam-setter. Output STRICT JSON ONLY.

Only use the provided excerpts. Make questions self-contained (no 'as above' or 'as mentioned').
Allowed types:
- mcq (4 options A/B/C/D, exactly one correct; include explanation)
- true_false (with explanation)
- short (1–3 sentences)

Vary question types naturally and avoid repeating the subtopic wording verbatim.
"""

    # ⬇️ Precompute the joined excerpts to avoid backslashes inside f-string expressions
    joined_selected = "\n".join(selected)[:14000]

    # ⬇️ Build the prompt WITHOUT putting literal braces inside an f-string
    user_prompt = (
        "Create " + str(total) + " questions focusing ONLY on these subtopics:\n"
        + str(chosen_subtopics) + "\n\n"
        "Relevant EXCERPTS:\n"
        + joined_selected + "\n\n"
        "Return JSON:\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "id": "q1",\n'
        '      "type": "mcq|true_false|short",\n'
        '      "prompt": "string",\n'
        '      "options": ["A","B","C","D"],\n'
        '      "answer": "A|B|C|D|True|False|string",\n'
        '      "explanation": "why it is correct"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )

    try:
        out = call_groq_json(system_prompt, user_prompt, api_key=api_key, model=model, max_tokens=4000)
        if isinstance(out, dict) and "questions" in out:
            return out
        return {"questions": []}
    except Exception:
        return {"questions": []}