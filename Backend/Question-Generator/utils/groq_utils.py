# utils/groq_utils.py
import json
import re
from typing import List, Dict, Tuple, Any, Optional
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
      "prompt": "clear question text",
      "options": ["A","B","C","D"],  // MCQ only (exactly 4)
      "answer": "A|B|C|D|True|False|answer text",
      "explanation": "why answer is correct (mcq/tf recommended)",
      "difficulty": "easy|medium|hard",
      "tags": ["topic","subtopic"]
    }
 ]
}"""

def call_groq_json(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2500,
) -> dict:
    """Call Groq in JSON mode and return parsed dict."""
    client = Groq(api_key=api_key)
    chat = client.chat.completions.create(
        model=model or DEFAULT_GROQ_MODEL,
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

def build_user_prompt(
    *,
    pdf_chunks: List[str],
    num_questions: int,
    qtypes: List[str],
    difficulty_mode: str,
    mix_counts: Dict[str, int] | None = None,
    type_targets: Dict[str, int] | None = None,
) -> str:
    """
    Build the 'user' prompt for the generic PDF → quiz route.
    - qtypes: allowed primary types ["mcq","true_false","short","long"]
    - difficulty_mode: "auto" or "custom"
    - mix_counts (custom): {"easy":N,"medium":N,"hard":N}
    - type_targets: {"mcq":X,"true_false":Y,"short":Z,"long":W}
    """
    mix_line = "Difficulty: auto (balanced)."
    if difficulty_mode == "custom" and mix_counts:
        mix_line = (
            f"Difficulty mix by approximate counts: "
            f"easy={mix_counts.get('easy',0)}, "
            f"medium={mix_counts.get('medium',0)}, "
            f"hard={mix_counts.get('hard',0)}."
        )

    type_targets = type_targets or {}
    type_contract_parts = []
    for key in ["mcq", "true_false", "short", "long"]:
        n = int(type_targets.get(key, 0))
        if n > 0:
            label = {
                "mcq": "MCQ",
                "true_false": "True/False",
                "short": "Short Answer",
                "long": "Long Answer",
            }[key]
            type_contract_parts.append(f"{n} {label}")

    counts_contract = ""
    if type_contract_parts:
        counts_contract = "Generate EXACTLY these question type counts: " + ", ".join(type_contract_parts) + "."

    joined = "\n\n---\n\n".join(pdf_chunks[:10])  # keep prompt manageable

    return f"""
You will read the provided PDF excerpts and generate STRICT JSON ONLY.

Primary allowed types: {", ".join(qtypes)}.
Total questions requested: {num_questions}.
{mix_line}
{counts_contract}

Rules:
- Make each question self-contained and unambiguous.
- MCQ must have exactly 4 options and one correct answer, include an explanation.
- True/False should include a brief explanation.
- Respect requested difficulty distribution if provided.

PDF EXCERPTS:
{joined}
"""

def _allocate_counts(*, total: int, easy: int, med: int, hard: int) -> Dict[str, int]:
    """
    Convert percent-like inputs (easy/med/hard) into integer counts that sum to 'total'.
    Inputs can be 0–100; we normalize and round fairly.
    """
    weights = [max(0, easy), max(0, med), max(0, hard)]
    s = sum(weights) or 1
    ratios = [w / s for w in weights]
    raw = [total * r for r in ratios]
    base = [int(x) for x in raw]
    rem = total - sum(base)
    # distribute remainder by largest fractional parts
    fracs = sorted(
        [(i, raw[i] - base[i]) for i in range(3)],
        key=lambda x: x[1],
        reverse=True,
    )
    for i, _frac in fracs:
        if rem <= 0:
            break
        base[i] += 1
        rem -= 1
    return {"easy": base[0], "medium": base[1], "hard": base[2]}

def filter_and_trim_questions(
    *,
    questions: List[Dict[str, Any]],
    allowed_types: List[str],
    difficulty_mode: str,
    mix_counts: Dict[str, int] | None,
    num_questions: int,
) -> List[Dict[str, Any]]:
    """
    Keep only allowed primary types, trim to difficulty mix (if custom), and cap at num_questions.
    """
    # keep allowed types
    qs = [q for q in questions if q.get("type") in allowed_types]

    if difficulty_mode == "custom" and mix_counts:
        buckets = {"easy": [], "medium": [], "hard": []}
        for q in qs:
            lvl = q.get("difficulty", "medium")
            if lvl not in buckets:
                lvl = "medium"
            buckets[lvl].append(q)

        out: List[Dict[str, Any]] = []
        for lvl in ["easy", "medium", "hard"]:
            need = int(mix_counts.get(lvl, 0))
            if need > 0:
                out.extend(buckets[lvl][:need])
        qs = out

    # pad or trim to num_questions
    return qs[:num_questions]

def extract_subtopics_llm(*, doc_text: str, api_key: str, n: int = 10) -> List[str]:
    """
    Ask LLM to extract n salient subtopics from doc_text (JSON list).
    """
    sys = "Extract key subtopics as a flat JSON array of short strings. No prose."
    user = f"Text:\n{doc_text[:14000]}\n\nReturn {n} concise subtopics."
    try:
        out = call_groq_json(sys, user, api_key, max_tokens=800, temperature=0.2)
        if isinstance(out, dict):
            # Support either {"subtopics":[...]} or {"items":[...]} or {"list":[...]}
            for key in ["subtopics", "items", "list"]:
                if key in out and isinstance(out[key], list):
                    return [str(x).strip() for x in out[key] if str(x).strip()]
        if isinstance(out, list):
            return [str(x).strip() for x in out if str(x).strip()]
    except Exception:
        pass
    # fallback: simple headings extraction
    lines = [ln.strip() for ln in doc_text.splitlines() if ln.strip()]
    heads = [ln for ln in lines if re.match(r"^\s*\d+[\.\)]\s+\w+", ln) or len(ln.split()) <= 6]
    return list(dict.fromkeys(heads))[:n]

# ---------- Subtopic-targeted quiz generation (used by /api/custom/quiz-from-subtopics) ----------

def _sanitize_question(q: Any) -> Optional[dict]:
    if not isinstance(q, dict):
        return None

    # --- normalize basics ---
    qtype = (q.get("type") or "").strip().lower()
    if qtype not in ("mcq", "true_false", "short", "long"):
        return None
    q["type"] = qtype

    prompt = (q.get("prompt") or q.get("question") or q.get("question_text") or "").strip()
    if not prompt:
        return None
    q["prompt"] = prompt

    # difficulty: accept many variants and normalize to easy/medium/hard
    diff = (q.get("difficulty") or "").strip().lower()
    alias_map = {
        "e": "easy", "ez": "easy", "simple": "easy",
        "m": "medium", "med": "medium", "normal": "medium",
        "h": "hard", "difficult": "hard"
    }
    diff = alias_map.get(diff, diff)
    if diff not in ("easy", "medium", "hard"):
        # default if missing/invalid
        diff = "medium"
    q["difficulty"] = diff

    # --- type-specific normalization ---
    if qtype == "mcq":
        opts = q.get("options") or q.get("choices") or []
        # If model gave more than 4, take first 4; if fewer than 4, reject
        opts = [str(o).strip() for o in opts if str(o).strip()]
        if len(opts) < 4:
            return None
        if len(opts) > 4:
            opts = opts[:4]
        q["options"] = opts

        ans = q.get("answer")
        # Accept index (0..3), letter ("A".."D"), or exact string value
        if isinstance(ans, str):
            s = ans.strip()
            upper = s.upper()
            if upper in ("A","B","C","D"):
                q["answer"] = "ABCD".index(upper)  # store as index
            elif s in opts:
                q["answer"] = opts.index(s)
            else:
                # try parse int index
                try:
                    idx = int(s)
                    if 0 <= idx <= 3:
                        q["answer"] = idx
                    else:
                        return None
                except Exception:
                    return None
        elif isinstance(ans, int):
            if 0 <= ans <= 3:
                q["answer"] = ans
            else:
                return None
        else:
            return None

        # Optional fields
        if q.get("explanation") is None:
            q["explanation"] = ""

    elif qtype == "true_false":
        ans = q.get("answer")
        # Accept bool, "true"/"false", "t"/"f", "yes"/"no"
        if isinstance(ans, bool):
            q["answer"] = ans
        elif isinstance(ans, str):
            s = ans.strip().lower()
            if s in ("true", "t", "yes", "y", "1"):
                q["answer"] = True
            elif s in ("false", "f", "no", "n", "0"):
                q["answer"] = False
            else:
                return None
        else:
            return None
        if q.get("explanation") is None:
            q["explanation"] = ""

    # short/long: nothing special beyond prompt/difficulty
    return q
def _enforce_question_type_targets(questions: List[dict], type_targets: Dict[str, int]) -> List[dict]:
    """
    Simplified version that only handles primary question types.
    """
    counters = {k: 0 for k in ["mcq", "true_false", "short", "long"]}
    typed = {k: [] for k in ["mcq", "true_false", "short", "long"]}
    other = []

    for q in questions:
        qt = q.get("type")
        if qt in typed:
            typed[qt].append(q)
        else:
            other.append(q)

    out: List[dict] = []
    # primary types only
    for qt in ["mcq", "true_false", "short", "long"]:
        want = int(type_targets.get(qt, 0))
        out.extend(typed[qt][:want])

    # fill to total
    total_target = sum(int(v) for v in type_targets.values())
    all_candidates = typed["mcq"] + typed["true_false"] + typed["short"] + typed["long"] + other
    for q in all_candidates:
        if len(out) >= total_target:
            break
        if q not in out:
            out.append(q)

    return out[:total_target]

def generate_quiz_from_subtopics_llm(
    *,
    full_text: str,
    chosen_subtopics: List[str],
    totals: Dict[str, int] | None = None,
    difficulty: Dict[str, Any] | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> dict:
    """
    Create a targeted quiz constrained to the selected subtopics.

    totals: {"mcq": int, "true_false": int, "short": int, "long": int}
    difficulty: {"mode":"auto"} or {"mode":"custom","easy":..,"medium":..,"hard":..}

    Returns {"questions":[...]}.
    """
    if not api_key:
        return {"error": "API key is required", "questions": []}
        
    totals = totals or {}
    want_mcq = int(totals.get("mcq") or 0)
    want_tf = int(totals.get("true_false") or 0)
    want_sh = int(totals.get("short") or 0)
    want_lg = int(totals.get("long") or 0)

    # retrieval
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
    selected: List[str] = []
    for sub in chosen_subtopics:
        pat = re.compile(re.escape(sub), re.IGNORECASE)
        hits = [ln for ln in lines if pat.search(ln)]
        selected.extend(hits[:80])
    if not selected:
        selected = lines[:600]
    joined = "\n".join(selected)[:18000]

    # difficulty
    diff_line = "Difficulty: auto (balanced)."
    if isinstance(difficulty, dict) and difficulty.get("mode") == "custom":
        e = int(difficulty.get("easy", 0))
        m = int(difficulty.get("medium", 0))
        h = int(difficulty.get("hard", 0))
        diff_line = f"Difficulty mix by percent (approx): easy={e}%, medium={m}%, hard={h}%."

    parts = []
    if want_mcq: parts.append(f"{want_mcq} MCQ")
    if want_tf:  parts.append(f"{want_tf} True/False")
    if want_sh:  parts.append(f"{want_sh} Short Answer")
    if want_lg:  parts.append(f"{want_lg} Long Answer")
    type_contract = ", ".join(parts)
    counts_contract = f"Generate EXACTLY these question types and counts: {type_contract}."

    system_prompt = """You are an expert exam-setter creating quizzes from specific subtopics. 
Output STRICT JSON ONLY with no additional text.

CRITICAL RULES:
- Use ONLY the provided excerpts related to the specified subtopics.
- Make every question self-contained (no references like "as above").
- Ensure EXACT question counts for each specified type.
- Questions must test understanding, not just verbatim recall.

QUESTION TYPES:
- mcq: Multiple choice with exactly 4 options (A/B/C/D), one correct answer, include explanation
- true_false: Statement that is either true or false, include explanation
- short: Short answer requiring 1-3 sentences
- long: Long answer requiring 4-8 sentences or key points

DIFFICULTY LEVELS:
- easy, medium, hard

OUTPUT FORMAT:
{"questions":[{...}]}"""

    user_prompt = f"""
TARGET SUBTOPICS:
{", ".join(chosen_subtopics)}

REQUIREMENTS:
{counts_contract}
{diff_line}

Generate questions that:
- Relate directly to the specified subtopics
- Test conceptual understanding

RELEVANT TEXT EXCERPTS:
{joined}

Return valid JSON only.
"""

    try:
        out = call_groq_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            model=model,
            max_tokens=6000,
            temperature=0.4,
        )
        
        # Debug: Print the raw output
        print(f"Raw LLM output: {out}")
        
        qs = []
        for q in (out.get("questions") or []):
            s = _sanitize_question(q)
            if s:
                qs.append(s)
        
        print(f"Sanitized questions: {len(qs)}")
        
        enforced = _enforce_question_type_targets(qs, totals)
        print(f"After enforcing type targets: {len(enforced)}")
        
        return {"questions": enforced}
    except Exception as e:
        print(f"Error in generate_quiz_from_subtopics_llm: {e}")
        return {"questions": [], "error": str(e)}