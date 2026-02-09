import os
import math
import re
import difflib
import ast
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

from llm import chat_json, DEFAULT_MODEL
from prompts import (
    SYSTEM_PROMPT_GRADE,
    SYSTEM_PROMPT_CODE,
    SYSTEM_PROMPT_DECISION,
    build_freeform_user_prompt,
    build_code_grading_prompt,
    build_decision_grading_prompt,
)


load_dotenv()


@dataclass
class GradeResult:
    question_id: str
    type: str
    score: float
    max_score: float
    is_correct: Optional[bool] = None
    verdict: Optional[str] = None
    feedback: Optional[str] = None
    criteria: Optional[List[Dict[str, Any]]] = None
    expected: Optional[str] = None


# Question type labels (for documentation / possible validation)
QUESTION_TYPES: Dict[str, str] = {
    "mcq": "Multiple Choice",
    "true_false": "True/False",
    "short": "Short Answer",
    "long": "Long Answer",
    "conceptual": "Conceptual",
    # Code-based:
    "code_writing": "Write code from scratch",
    "code_completion": "Complete partial code",
    "code_debugging": "Find and fix bugs",
    "code_output": "Predict code output",
    "code_explanation": "Explain what code does",
    # Decision-based:
    "decision": "Decision-based",
    "case_study": "Case study",
    "scenario": "Scenario-based",
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _normalize_bool(val: Any) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in {"true", "t", "yes", "y", "1"}:
        return True
    if s in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _norm_text(s: str) -> str:
    try:
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    except Exception:
        return (s or "").strip().lower()


def _letter_for_option_text(options: List[str], option_text: str) -> Optional[str]:
    try:
        norm = _norm_text(option_text)
        for idx, opt in enumerate(options):
                if _norm_text(opt) == norm:
                    return chr(ord('A') + idx)
        # Fuzzy: choose the best match if sufficiently similar
        best = None
        best_ratio = 0.0
        for idx, opt in enumerate(options):
            ratio = difflib.SequenceMatcher(None, norm, _norm_text(opt)).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = idx
        if best is not None and best_ratio >= 0.75:
            return chr(ord('A') + best)
    except Exception:
        pass
    return None


def _letter_from_any(answer: Any, options: List[str]) -> Optional[str]:
    if answer is None:
        return None
    # letter
    s = str(answer).strip()
    if len(s) == 1 and s.upper() in {"A", "B", "C", "D"}:
        return s.upper()
    # numeric index
    if s.isdigit():
        idx = int(s)
        if 0 <= idx < len(options):
            return chr(ord('A') + idx)
    # option text
    by_text = _letter_for_option_text(options, s)
    if by_text:
        return by_text
    # Fuzzy: treat long free-text answers as best-match to options
    try:
        norm = _norm_text(s)
        best = None
        best_ratio = 0.0
        for idx, opt in enumerate(options):
            ratio = difflib.SequenceMatcher(None, norm, _norm_text(opt)).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = idx
        if best is not None and best_ratio >= 0.75:
            return chr(ord('A') + best)
    except Exception:
        pass
    return None


def _default_max_score(qtype: str) -> float:
    return {
        "mcq": 1.0,
        "true_false": 1.0,
        "short": 3.0,
        "long": 5.0,
        "conceptual": 5.0,
    }.get(qtype, 1.0)


def _policy_weights(policy: str) -> Dict[str, float]:
    p = (policy or "balanced").strip().lower()
    if p == "strict":
        return {"accuracy": 0.7, "completeness": 0.2, "clarity": 0.1}
    if p == "lenient":
        return {"accuracy": 0.4, "completeness": 0.3, "clarity": 0.3}
    return {"accuracy": 0.5, "completeness": 0.3, "clarity": 0.2}


def _heuristic_overlap_score(ref: str, ans: str, max_score: float) -> Tuple[float, str]:
    """Very lightweight fallback when no LLM available. Uses token overlap."""
    if not ref:
        return 0.0, "No reference; unable to grade without LLM."
    ref_tokens = set(re.findall(r"\w+", ref.lower()))
    ans_tokens = set(re.findall(r"\w+", ans.lower()))
    if not ref_tokens or not ans_tokens:
        return 0.0, "Insufficient content for heuristic grading."
    overlap = len(ref_tokens & ans_tokens)
    recall = overlap / max(1, len(ref_tokens))
    precision = overlap / max(1, len(ans_tokens))
    f1 = 0.0 if (recall + precision) == 0 else 2 * recall * precision / (recall + precision)
    score = round(max_score * min(1.0, f1 * 1.1), 2)
    return score, f"Heuristic grading used (no LLM). Token F1={f1:.2f}."


def _validate_and_fix_llm_response(
    response: Dict[str, Any],
    max_score: float,
    question_id: str,
) -> Dict[str, Any]:
    """
    Validate LLM response and fix common issues.
    Ensures response always has required fields with valid values.
    """
    validated: Dict[str, Any] = {}

    # 1. Score
    try:
        score_val = float(response.get("score", 0.0))
        score_val = max(0.0, min(max_score, score_val))
        score_val = round(score_val, 2)
    except (TypeError, ValueError):
        logger.warning("Invalid score for %s; defaulting to 0", question_id)
        score_val = 0.0
    validated["score"] = score_val
    validated["max_score"] = max_score

    # 2. Verdict
    raw_verdict = str(response.get("verdict", "")).strip().lower()
    valid_verdicts = {"correct", "partially_correct", "incorrect"}
    if raw_verdict not in valid_verdicts:
        if score_val >= 0.9 * max_score:
            raw_verdict = "correct"
        elif score_val <= 0.1 * max_score:
            raw_verdict = "incorrect"
        else:
            raw_verdict = "partially_correct"
        logger.warning("Invalid verdict for %s; inferred '%s' from score", question_id, raw_verdict)
    validated["verdict"] = raw_verdict

    # 3. Feedback
    feedback = str(response.get("feedback", "")).strip()
    if len(feedback) < 10:
        feedback = f"Score: {score_val}/{max_score}. Answer was {raw_verdict}."
        logger.warning("Missing/short feedback for %s", question_id)
    validated["feedback"] = feedback

    # 4. Criteria
    criteria_raw = response.get("criteria", [])
    if not isinstance(criteria_raw, list):
        criteria_raw = []

    criterion_names = {"accuracy", "completeness", "clarity"}
    validated_criteria: List[Dict[str, Any]] = []

    for c in criteria_raw:
        if not isinstance(c, Dict):
            continue
        name = str(c.get("name", "")).lower()
        if name not in criterion_names:
            continue
        try:
            c_score = float(c.get("score", 0.0))
            c_max = float(c.get("max", 0.0))
            c_score = max(0.0, min(c_score, c_max))
        except (TypeError, ValueError):
            c_score = 0.0
            c_max = 0.0
        validated_criteria.append(
            {
                "name": name,
                "score": round(c_score, 2),
                "max": round(c_max, 2),
                "feedback": str(c.get("feedback", f"{name} evaluated")).strip(),
            }
        )

    if len(validated_criteria) != 3:
        logger.warning("Invalid criteria for %s; generating defaults", question_id)
        validated_criteria = [
            {
                "name": "accuracy",
                "score": round(score_val * 0.5, 2),
                "max": round(max_score * 0.5, 2),
                "feedback": "Evaluated for factual correctness",
            },
            {
                "name": "completeness",
                "score": round(score_val * 0.3, 2),
                "max": round(max_score * 0.3, 2),
                "feedback": "Evaluated for coverage",
            },
            {
                "name": "clarity",
                "score": round(score_val * 0.2, 2),
                "max": round(max_score * 0.2, 2),
                "feedback": "Evaluated for expression",
            },
        ]

    validated["criteria"] = validated_criteria
    return validated


def _analyze_python_code(code: str) -> Dict[str, Any]:
    """
    Perform static analysis on Python code.
    Returns syntax validity, structure info, and basic metrics.
    """
    analysis: Dict[str, Any] = {
        "is_valid_syntax": False,
        "has_functions": False,
        "has_classes": False,
        "has_loops": False,
        "has_conditionals": False,
        "imports": [],
        "function_names": [],
        "class_names": [],
        "line_count": 0,
        "error": None,
    }

    try:
        lines = [
            l.strip()
            for l in code.split("\n")
            if l.strip() and not l.strip().startswith("#")
        ]
        analysis["line_count"] = len(lines)

        tree = ast.parse(code)
        analysis["is_valid_syntax"] = True

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                analysis["has_functions"] = True
                analysis["function_names"].append(node.name)
            elif isinstance(node, ast.ClassDef):
                analysis["has_classes"] = True
                analysis["class_names"].append(node.name)
            elif isinstance(node, (ast.For, ast.While)):
                analysis["has_loops"] = True
            elif isinstance(node, ast.If):
                analysis["has_conditionals"] = True
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    analysis["imports"].extend(alias.name for alias in node.names)
                else:
                    analysis["imports"].append(node.module)

    except SyntaxError as e:
        analysis["error"] = f"Syntax error: {e}"
    except Exception as e:  # defensive
        analysis["error"] = f"Analysis error: {e}"

    return analysis


def _check_code_requirements(
    code: str, requirements: Dict[str, Any]
) -> List[Tuple[str, bool, str]]:
    """
    Check if code meets specific structural / style requirements.
    """
    checks: List[Tuple[str, bool, str]] = []
    analysis = _analyze_python_code(code)

    # Syntax check (always first)
    if not analysis["is_valid_syntax"]:
        checks.append(
            ("valid_syntax", False, analysis.get("error", "Invalid syntax"))
        )
        return checks
    checks.append(("valid_syntax", True, "Code has valid Python syntax"))

    # Function name check
    if "must_have_function" in requirements:
        required_func = requirements["must_have_function"]
        has_func = required_func in analysis["function_names"]
        msg = ("Found" if has_func else "Missing") + f" function '{required_func}'"
        checks.append((f"has_function_{required_func}", has_func, msg))

    # Loop check
    if requirements.get("must_use_loop"):
        msg = (
            "Code uses loops"
            if analysis["has_loops"]
            else "Code should use a loop"
        )
        checks.append(("uses_loop", analysis["has_loops"], msg))

    # Conditional check
    if requirements.get("must_have_conditional"):
        msg = (
            "Code uses conditionals"
            if analysis["has_conditionals"]
            else "Code should use if/else"
        )
        checks.append(("uses_conditional", analysis["has_conditionals"], msg))

    # Line count check
    if "max_lines" in requirements:
        max_lines = requirements["max_lines"]
        within_limit = analysis["line_count"] <= max_lines
        status_word = "within" if within_limit else "exceeds"
        msg = (
            f"Code has {analysis['line_count']} lines "
            f"({status_word} {max_lines} limit)"
        )
        checks.append(("line_count", within_limit, msg))

    # Forbidden imports
    if "forbidden_imports" in requirements:
        forbidden = set(requirements["forbidden_imports"] or [])
        used_forbidden = set(analysis["imports"]) & forbidden
        is_clean = not used_forbidden
        msg = (
            "No forbidden imports"
            if is_clean
            else "Uses forbidden imports: " + ", ".join(sorted(used_forbidden))
        )
        checks.append(("forbidden_imports", is_clean, msg))

    # Required keywords
    if "required_keywords" in requirements:
        code_lower = code.lower()
        for keyword in requirements["required_keywords"] or []:
            has_keyword = keyword.lower() in code_lower
            msg = (
                "Uses" if has_keyword else "Missing"
            ) + f" keyword '{keyword}'"
            checks.append((f"keyword_{keyword}", has_keyword, msg))

    return checks


def _execute_python_code(
    code: str, test_cases: List[Dict[str, Any]], timeout: int = 5
) -> Dict[str, Any]:
    """
    Safely execute Python code with test cases.
    """
    result: Dict[str, Any] = {
        "executed": False,
        "results": [],
        "error": None,
    }

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_file = f.name

        try:
            for idx, test in enumerate(test_cases):
                test_input = test.get("input", "")
                expected = test.get("expected_output", "")

                proc = subprocess.run(
                    ["python3", temp_file],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

                actual_output = proc.stdout
                passed = actual_output.strip() == expected.strip()

                result["results"].append(
                    {
                        "test": idx,
                        "description": test.get(
                            "description", f"Test {idx + 1}"
                        ),
                        "passed": passed,
                        "output": actual_output,
                        "expected": expected,
                        "error": proc.stderr or None,
                    }
                )

            result["executed"] = True

        finally:
            try:
                Path(temp_file).unlink(missing_ok=True)
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        result["error"] = f"Code execution timeout ({timeout}s)"
    except Exception as e:
        result["error"] = f"Execution error: {e}"

    return result


def validate_quiz_structure(quiz: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate quiz structure and return (is_valid, list_of_errors).
    """
    errors: List[str] = []

    if "questions" not in quiz:
        return False, ["Quiz must have a 'questions' field"]

    questions = quiz.get("questions")
    if not isinstance(questions, list):
        return False, ["'questions' must be a list"]

    if not questions:
        return False, ["Quiz must have at least one question"]

    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            errors.append(f"Question {idx}: must be a dictionary")
            continue

        q_id = q.get("id", f"Q{idx + 1}")

        if "type" not in q:
            errors.append(f"Question {q_id}: missing 'type' field")

        if not (q.get("prompt") or q.get("question_text")):
            errors.append(
                f"Question {q_id}: missing question text ('prompt' or 'question_text')"
            )

        qtype = str(q.get("type", "")).lower()

        if qtype == "mcq":
            options = q.get("options", [])
            if not isinstance(options, list) or len(options) < 2:
                errors.append(
                    f"Question {q_id}: MCQ must have at least 2 'options'"
                )
        elif qtype in {"true_false", "truefalse", "tf"}:
            pass
        elif qtype in {"short", "long", "conceptual"}:
            has_reference = any(
                q.get(field)
                for field in [
                    "answer",
                    "reference_answer",
                    "expected_answer",
                    "ideal_answer",
                    "solution",
                ]
            )
            if not has_reference:
                # This is a soft warning, not a hard error.
                errors.append(
                    f"Question {q_id}: WARNING - no reference answer provided (grading may be less accurate)"
                )
        elif qtype in {
            "code_writing",
            "code_completion",
            "code_debugging",
            "code_output",
            "code_explanation",
            "decision",
            "case_study",
            "scenario",
        }:
            # For now, only basic checks on these new types
            pass
        else:
            errors.append(
                f"Question {q_id}: unknown type '{qtype}' "
                "(expected: mcq, true_false, short, long, conceptual, or supported code/decision types)"
            )

        if "max_score" in q:
            try:
                ms = float(q["max_score"])
                if ms <= 0:
                    errors.append(
                        f"Question {q_id}: max_score must be positive"
                    )
            except (TypeError, ValueError):
                errors.append(f"Question {q_id}: max_score must be a number")

    # Only treat non-warning messages as hard errors
    hard_errors = [e for e in errors if "WARNING - " not in e]
    return (len(hard_errors) == 0), errors


def validate_responses(
    responses: Dict[str, Any],
    quiz: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Validate responses match quiz structure.
    Returns (is_valid, warnings). Warnings never invalidate grading.
    """
    warnings: List[str] = []

    if not isinstance(responses, dict):
        return False, [
            "Responses must be a dictionary mapping question IDs to answers"
        ]

    questions = quiz.get("questions") or []
    question_ids = {q.get("id") for q in questions if q.get("id")}
    response_ids = set(responses.keys())

    missing = question_ids - response_ids
    if missing:
        warnings.append(
            "Missing responses for questions: "
            + ", ".join(sorted(missing))
        )

    extra = response_ids - question_ids
    if extra:
        warnings.append(
            "Extra responses for unknown questions: "
            + ", ".join(sorted(extra))
        )

    return True, warnings


class QuizGrader:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        default_policy: str = "balanced",
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or DEFAULT_MODEL
        self.default_policy = default_policy

    def _grade_mcq_with_llm_fallback(self, q: Dict[str, Any], ans: Any) -> GradeResult:
        """
        Grade MCQ with rule-based matching first, then optional LLM fallback
        to interpret ambiguous student responses.
        """
        qid = q.get("id") or ""
        options: List[str] = list(q.get("options") or [])
        max_score = float(q.get("max_score") or _default_max_score("mcq"))

        gold_letter = _letter_from_any(q.get("answer"), options)
        student_letter = _letter_from_any(ans, options)

        # If we successfully parsed the student's answer, use rule-based grading
        if gold_letter is not None and student_letter is not None:
            correct = (student_letter == gold_letter)
            score = max_score if correct else 0.0
            fb = (
                "Correct."
                if correct
                else f"Incorrect. Expected {gold_letter}, got {student_letter}."
            )
            return GradeResult(
                question_id=qid,
                type="mcq",
                score=score,
                max_score=max_score,
                is_correct=correct,
                verdict="correct" if correct else "incorrect",
                feedback=fb,
            )

        # If parsing failed but we have an API key and a non-empty answer,
        # try an LLM to interpret the student's response.
        if student_letter is None and self.api_key and ans:
            try:
                options_str = "\n".join(
                    f"{chr(65 + i)}) {opt}" for i, opt in enumerate(options)
                )

                llm_prompt = f"""
Determine which option (A, B, C, or D) the student selected.

QUESTION: {q.get('prompt', '')}

OPTIONS:
{options_str}

CORRECT ANSWER: {gold_letter or 'Not specified'}

STUDENT RESPONSE: {ans}

The student's response might be:
- A letter (A/B/C/D)
- An option number (0/1/2/3)
- The full option text
- A paraphrase of an option
- Conversational (e.g., "I think it's B")

Determine which option best matches their response.

Return JSON:
{{
  "matched_letter": "A|B|C|D|UNCLEAR",
  "is_correct": true|false|null,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}
"""
                raw = chat_json(
                    system_prompt=(
                        "You are an expert at interpreting student responses to "
                        "multiple choice questions. Return only valid JSON."
                    ),
                    user_prompt=llm_prompt,
                    api_key=self.api_key,
                    model=self.model,
                    temperature=0.0,
                    max_tokens=300,
                )

                matched = str(raw.get("matched_letter", "")).upper()
                confidence = float(raw.get("confidence", 0.0) or 0.0)
                reasoning = str(raw.get("reasoning", "")).strip()

                if matched in {"A", "B", "C", "D"} and confidence >= 0.7:
                    is_correct = (
                        gold_letter is not None and matched == gold_letter
                    )
                    score = max_score if is_correct else 0.0
                    prefix = (
                        "Correct. "
                        if is_correct
                        else f"Incorrect. Expected {gold_letter}. "
                    )
                    fb = prefix + f"Interpreted as {matched}. {reasoning}"

                    return GradeResult(
                        question_id=qid,
                        type="mcq",
                        score=score,
                        max_score=max_score,
                        is_correct=is_correct,
                        verdict="correct" if is_correct else "incorrect",
                        feedback=fb,
                    )

                # Low confidence or unclear match
                return GradeResult(
                    question_id=qid,
                    type="mcq",
                    score=0.0,
                    max_score=max_score,
                    is_correct=None,
                    verdict="unclear",
                    feedback=(
                        "Could not confidently interpret answer."
                        + (f" {reasoning}" if reasoning else "")
                    ),
                )

            except Exception as e:
                logger.error("LLM MCQ fallback failed for %s: %s", qid, e)
                # Fall through to default behaviour below

        # Default behaviour when we cannot interpret the answer or no API key
        if gold_letter is None:
            fb = "No ground truth provided."
        else:
            fb = f"Could not interpret answer. Expected {gold_letter}."

        return GradeResult(
            question_id=qid,
            type="mcq",
            score=0.0,
            max_score=max_score,
            is_correct=None,
            verdict=None,
            feedback=fb,
        )

    def _grade_mcq(self, q: Dict[str, Any], ans: Any) -> GradeResult:
        """Wrapper to use the enhanced MCQ grading with LLM fallback."""
        return self._grade_mcq_with_llm_fallback(q, ans)

    def _grade_true_false(self, q: Dict[str, Any], ans: Any) -> GradeResult:
        qid = q.get("id") or ""
        max_score = float(q.get("max_score") or _default_max_score("true_false"))
        gold_bool = _normalize_bool(q.get("answer"))
        student_bool = _normalize_bool(ans)

        correct = (gold_bool is not None and student_bool == gold_bool)
        score = max_score if correct else 0.0
        fb = "Correct." if correct else (
            f"Incorrect. Expected {gold_bool}." if gold_bool is not None else "No ground truth provided."
        )
        return GradeResult(
            question_id=qid,
            type="true_false",
            score=score,
            max_score=max_score,
            is_correct=correct if gold_bool is not None else None,
            verdict=("correct" if correct else "incorrect") if gold_bool is not None else None,
            feedback=fb,
        )

    def _grade_freeform(
        self,
        q: Dict[str, Any],
        ans: Any,
        *,
        policy: str,
        rubric_weights: Optional[Dict[str, float]] = None,
    ) -> GradeResult:
        qid = q.get("id") or ""
        qtype = q.get("type") or "short"
        max_score = float(q.get("max_score") or _default_max_score(qtype))

        prompt = (q.get("prompt") or q.get("question_text") or "").strip()
        student_answer = (str(ans) if ans is not None else "").strip()
        reference_answer = None
        # Prefer a string reference; if dict or list appears, stringify
        ref_candidates = [
            q.get("answer"),
            q.get("reference_answer"),
            q.get("expected_answer"),
            q.get("ideal_answer"),
            q.get("solution"),
            q.get("model_answer"),
        ]
        for rc in ref_candidates:
            if rc is None:
                continue
            if isinstance(rc, str):
                reference_answer = rc
                break
            try:
                reference_answer = str(rc)
                break
            except Exception:
                continue

        weights = rubric_weights or _policy_weights(policy)

        # Short-circuit: empty answer
        if not student_answer:
            return GradeResult(
                question_id=qid,
                type=qtype,
                score=0.0,
                max_score=max_score,
                verdict="incorrect",
                feedback="No answer provided.",
                criteria=[
                    {
                        "name": "accuracy",
                        "score": 0.0,
                        "max": round(max_score * 0.5, 2),
                        "feedback": "No answer provided.",
                    },
                    {
                        "name": "completeness",
                        "score": 0.0,
                        "max": round(max_score * 0.3, 2),
                        "feedback": "No answer provided.",
                    },
                    {
                        "name": "clarity",
                        "score": 0.0,
                        "max": round(max_score * 0.2, 2),
                        "feedback": "No answer provided.",
                    },
                ],
            )

        # No API key: heuristic fallback
        if not self.api_key:
            score, fb = _heuristic_overlap_score(
                reference_answer or "",
                student_answer,
                max_score,
            )
            verdict = (
                "correct"
                if math.isclose(score, max_score)
                else ("incorrect" if score == 0 else "partially_correct")
            )
            return GradeResult(
                question_id=qid,
                type=qtype,
                score=score,
                max_score=max_score,
                verdict=verdict,
                feedback=fb,
                criteria=[
                    {
                        "name": "accuracy",
                        "score": score,
                        "max": max_score,
                        "feedback": fb,
                    }
                ],
                expected=reference_answer,
            )

        user_prompt = build_freeform_user_prompt(
            question_prompt=prompt,
            student_answer=student_answer,
            reference_answer=reference_answer,
            max_score=max_score,
            policy=policy,
            rubric_weights=weights,
        )

        try:
            raw = chat_json(
                system_prompt=SYSTEM_PROMPT_GRADE,
                user_prompt=user_prompt,
                api_key=self.api_key,
                model=self.model,
                temperature=0.1,
                max_tokens=1500,
            )
            validated = _validate_and_fix_llm_response(
                raw,
                max_score=max_score,
                question_id=qid,
            )

            return GradeResult(
                question_id=qid,
                type=qtype,
                score=validated["score"],
                max_score=max_score,
                verdict=validated["verdict"],
                feedback=validated["feedback"],
                criteria=validated["criteria"],
                expected=reference_answer,
            )
        except Exception as e:
            logger.error("Error grading %s with LLM: %s", qid, e)
            score, fb = _heuristic_overlap_score(
                reference_answer or "",
                student_answer,
                max_score,
            )
            verdict = (
                "correct"
                if math.isclose(score, max_score)
                else ("incorrect" if score == 0 else "partially_correct")
            )
            return GradeResult(
                question_id=qid,
                type=qtype,
                score=score,
                max_score=max_score,
                verdict=verdict,
                feedback=f"Error during LLM grading: {e}. Used heuristic fallback. {fb}",
                criteria=[
                    {
                        "name": "accuracy",
                        "score": score,
                        "max": max_score,
                        "feedback": fb,
                    }
                ],
                expected=reference_answer,
            )

    def _grade_code_static(
        self,
        q: Dict[str, Any],
        ans: Any,
        *,
        policy: str,
    ) -> GradeResult:
        """Grade code using static (rule-based) analysis only."""
        qid = q.get("id") or ""
        max_score = float(q.get("max_score") or 10.0)

        student_code = (str(ans) if ans is not None else "").strip()
        requirements = q.get("requirements") or {}

        if not student_code:
            return GradeResult(
                question_id=qid,
                type="code_writing",
                score=0.0,
                max_score=max_score,
                verdict="incorrect",
                feedback="No code submitted.",
            )

        checks = _check_code_requirements(student_code, requirements)

        passed = sum(1 for _, ok, _ in checks if ok)
        total = len(checks)

        if total == 0:
            # No structural requirements: fall back to LLM-based grading
            return self._grade_code_with_llm(q, ans, policy=policy)

        score = (passed / total) * max_score

        feedback_parts: List[str] = []
        for _, ok, msg in checks:
            status = "✓" if ok else "✗"
            feedback_parts.append(f"{status} {msg}")

        feedback = "\n".join(feedback_parts)

        if score >= 0.9 * max_score:
            verdict = "correct"
        elif score <= 0.3 * max_score:
            verdict = "incorrect"
        else:
            verdict = "partially_correct"

        return GradeResult(
            question_id=qid,
            type="code_writing",
            score=round(score, 2),
            max_score=max_score,
            verdict=verdict,
            feedback=feedback,
        )

    def _grade_code_with_llm(
        self,
        q: Dict[str, Any],
        ans: Any,
        *,
        policy: str,
    ) -> GradeResult:
        """Grade code using LLM for semantic understanding."""
        qid = q.get("id") or ""
        max_score = float(q.get("max_score") or 10.0)

        prompt = (q.get("prompt") or q.get("question_text") or "").strip()
        student_code = (str(ans) if ans is not None else "").strip()
        reference_code = q.get("reference_code") or q.get("solution_code")
        requirements = q.get("requirements") or {}

        if not student_code:
            return GradeResult(
                question_id=qid,
                type="code_writing",
                score=0.0,
                max_score=max_score,
                verdict="incorrect",
                feedback="No code submitted.",
            )

        if not self.api_key:
            return GradeResult(
                question_id=qid,
                type="code_writing",
                score=0.0,
                max_score=max_score,
                verdict="error",
                feedback="LLM API key required for code grading.",
            )

        user_prompt = build_code_grading_prompt(
            question_prompt=prompt,
            student_code=student_code,
            reference_code=reference_code,
            requirements=requirements,
            max_score=max_score,
            policy=policy,
        )

        try:
            raw_response = chat_json(
                system_prompt=SYSTEM_PROMPT_CODE,
                user_prompt=user_prompt,
                api_key=self.api_key,
                model=self.model,
                temperature=0.1,
                max_tokens=2000,
            )

            score = float(
                max(0.0, min(max_score, float(raw_response.get("score", 0.0))))
            )
            verdict = (raw_response.get("verdict") or "").lower()
            if verdict not in {"correct", "partially_correct", "incorrect"}:
                if score >= 0.9 * max_score:
                    verdict = "correct"
                elif score <= 0.3 * max_score:
                    verdict = "incorrect"
                else:
                    verdict = "partially_correct"

            feedback = str(raw_response.get("feedback") or "").strip()

            bugs = raw_response.get("bugs_found", [])
            strengths = raw_response.get("strengths", [])

            if bugs and isinstance(bugs, list):
                feedback += "\n\nIssues found:\n" + "\n".join(
                    f"- {b}" for b in bugs
                )
            if strengths and isinstance(strengths, list):
                feedback += "\n\nStrengths:\n" + "\n".join(
                    f"+ {s}" for s in strengths
                )

            criteria = raw_response.get("criteria", [])
            if not isinstance(criteria, list) or len(criteria) != 3:
                criteria = [
                    {
                        "name": "correctness",
                        "score": score * 0.5,
                        "max": max_score * 0.5,
                        "feedback": "Evaluated",
                    },
                    {
                        "name": "code_quality",
                        "score": score * 0.3,
                        "max": max_score * 0.3,
                        "feedback": "Evaluated",
                    },
                    {
                        "name": "requirements",
                        "score": score * 0.2,
                        "max": max_score * 0.2,
                        "feedback": "Evaluated",
                    },
                ]

            return GradeResult(
                question_id=qid,
                type="code_writing",
                score=round(score, 2),
                max_score=max_score,
                verdict=verdict,
                feedback=feedback,
                criteria=criteria,
            )

        except Exception as e:
            return GradeResult(
                question_id=qid,
                type="code_writing",
                score=0.0,
                max_score=max_score,
                verdict="error",
                feedback=f"Error during code grading: {e}",
            )

    def _grade_code_with_tests(
        self,
        q: Dict[str, Any],
        ans: Any,
        *,
        policy: str,
    ) -> GradeResult:
        """Grade code by executing it against test cases."""
        qid = q.get("id") or ""
        max_score = float(q.get("max_score") or 10.0)

        student_code = (str(ans) if ans is not None else "").strip()
        test_cases = q.get("test_cases") or []

        if not student_code:
            return GradeResult(
                question_id=qid,
                type="code_writing",
                score=0.0,
                max_score=max_score,
                verdict="incorrect",
                feedback="No code submitted.",
            )

        if not test_cases:
            return self._grade_code_with_llm(q, ans, policy=policy)

        analysis = _analyze_python_code(student_code)
        if not analysis["is_valid_syntax"]:
            return GradeResult(
                question_id=qid,
                type="code_writing",
                score=0.0,
                max_score=max_score,
                verdict="incorrect",
                feedback=f"Syntax Error: {analysis.get('error', 'Invalid Python syntax')}",
            )

        execution = _execute_python_code(student_code, test_cases)
        if not execution.get("executed"):
            return GradeResult(
                question_id=qid,
                type="code_writing",
                score=0.0,
                max_score=max_score,
                verdict="error",
                feedback=f"Execution failed: {execution.get('error', 'Unknown error')}",
            )

        results = execution["results"]
        passed = sum(1 for r in results if r.get("passed"))
        total = len(results)
        test_score = (passed / total) * max_score if total else 0.0

        feedback_parts: List[str] = [f"Test Results: {passed}/{total} passed\n"]
        for r in results:
            status = "✓" if r.get("passed") else "✗"
            desc = r.get("description", "")
            feedback_parts.append(f"{status} {desc}")
            if not r.get("passed"):
                feedback_parts.append(
                    f"  Expected: {str(r.get('expected', '')).strip()}"
                )
                feedback_parts.append(
                    f"  Got: {str(r.get('output', '')).strip()}"
                )
                if r.get("error"):
                    feedback_parts.append(f"  Error: {r['error']}")

        feedback = "\n".join(feedback_parts)

        # Optional: if all tests passed, call LLM to assess code quality.
        if self.api_key and passed == total and total > 0:
            try:
                quality_prompt = f"""
The student's code passed all test cases. Assess code quality:

CODE:
```python
{student_code}
```

Rate code quality (0.0-1.0) based on:
- Readability and style
- Efficiency
- Best practices
- Comments and documentation

Return JSON:
{{
  "quality_score": 0.0-1.0,
  "quality_feedback": "brief assessment"
}}
"""
                quality_response = chat_json(
                    system_prompt=(
                        "You are a code quality reviewer. "
                        "Return only JSON."
                    ),
                    user_prompt=quality_prompt,
                    api_key=self.api_key,
                    model=self.model,
                    temperature=0.1,
                    max_tokens=500,
                )
                quality_score = float(
                    quality_response.get("quality_score", 0.8)
                )
                quality_feedback = str(
                    quality_response.get("quality_feedback", "")
                )

                final_score = (test_score * 0.7) + (
                    max_score * quality_score * 0.3
                )
                feedback += f"\n\nCode Quality: {quality_feedback}"
            except Exception:
                final_score = test_score
        else:
            final_score = test_score

        if final_score >= 0.9 * max_score:
            verdict = "correct"
        elif final_score <= 0.3 * max_score:
            verdict = "incorrect"
        else:
            verdict = "partially_correct"

        return GradeResult(
            question_id=qid,
            type="code_writing",
            score=round(final_score, 2),
            max_score=max_score,
            verdict=verdict,
            feedback=feedback,
        )

    def _grade_decision(
        self,
        q: Dict[str, Any],
        ans: Any,
        *,
        policy: str,
        rubric_weights: Optional[Dict[str, float]] = None,
    ) -> GradeResult:
        """Grade decision / case-study / scenario questions."""
        qid = q.get("id") or ""
        max_score = float(q.get("max_score") or 10.0)

        scenario = q.get("scenario") or ""
        prompt = (q.get("prompt") or q.get("question_text") or "").strip()
        student_answer = (str(ans) if ans is not None else "").strip()
        reference_analysis = q.get("reference_analysis") or q.get("sample_answer")

        weights = rubric_weights or {
            "analysis": 0.4,
            "reasoning": 0.4,
            "communication": 0.2,
        }

        if not student_answer:
            return GradeResult(
                question_id=qid,
                type="decision",
                score=0.0,
                max_score=max_score,
                verdict="weak",
                feedback="No response provided.",
            )

        if not self.api_key:
            return GradeResult(
                question_id=qid,
                type="decision",
                score=0.0,
                max_score=max_score,
                verdict="error",
                feedback="LLM API key required for decision-based grading.",
            )

        user_prompt = build_decision_grading_prompt(
            scenario=scenario,
            question_prompt=prompt,
            student_answer=student_answer,
            reference_analysis=reference_analysis,
            rubric_weights=weights,
            max_score=max_score,
            policy=policy,
        )

        try:
            raw_response = chat_json(
                system_prompt=SYSTEM_PROMPT_DECISION,
                user_prompt=user_prompt,
                api_key=self.api_key,
                model=self.model,
                temperature=0.1,
                max_tokens=2000,
            )

            score = float(
                max(0.0, min(max_score, float(raw_response.get("score", 0.0))))
            )

            verdict = (raw_response.get("verdict") or "").lower()
            if verdict not in {"strong", "acceptable", "weak"}:
                if score >= 0.8 * max_score:
                    verdict = "strong"
                elif score <= 0.4 * max_score:
                    verdict = "weak"
                else:
                    verdict = "acceptable"

            feedback = str(raw_response.get("feedback") or "").strip()

            strengths = raw_response.get("key_strengths", [])
            improvements = raw_response.get("areas_for_improvement", [])

            if strengths and isinstance(strengths, list):
                feedback += "\n\nStrengths:\n" + "\n".join(
                    f"+ {s}" for s in strengths
                )
            if improvements and isinstance(improvements, list):
                feedback += "\n\nAreas for improvement:\n" + "\n".join(
                    f"- {i}" for i in improvements
                )

            criteria = raw_response.get("criteria", [])
            if not isinstance(criteria, list) or len(criteria) != 3:
                criteria = [
                    {
                        "name": "analysis",
                        "score": score * 0.4,
                        "max": max_score * 0.4,
                        "feedback": "Evaluated",
                    },
                    {
                        "name": "reasoning",
                        "score": score * 0.4,
                        "max": max_score * 0.4,
                        "feedback": "Evaluated",
                    },
                    {
                        "name": "communication",
                        "score": score * 0.2,
                        "max": max_score * 0.2,
                        "feedback": "Evaluated",
                    },
                ]

            return GradeResult(
                question_id=qid,
                type="decision",
                score=round(score, 2),
                max_score=max_score,
                verdict=verdict,
                feedback=feedback,
                criteria=criteria,
            )

        except Exception as e:
            return GradeResult(
                question_id=qid,
                type="decision",
                score=0.0,
                max_score=max_score,
                verdict="error",
                feedback=f"Error during decision grading: {e}",
            )

    def grade_quiz(
        self,
        *,
        quiz: Dict[str, Any],
        responses: Dict[str, Any],
        policy: Optional[str] = None,
        rubric_weighting: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Grade a quiz with comprehensive validation and support for all types.
        """
        start_time = datetime.now()
        quiz_id = quiz.get("id")
        logger.info("Starting grading for quiz %s", quiz_id)

        # Quiz structure validation
        is_valid, errors = validate_quiz_structure(quiz)
        if not is_valid:
            logger.error("Invalid quiz structure for %s: %s", quiz_id, errors)
            return {
                "quiz_id": quiz_id,
                "error": "Invalid quiz structure",
                "details": errors,
                "total_score": 0.0,
                "max_total": 0.0,
                "percentage": 0.0,
                "items": [],
            }

        # Responses validation (warnings only)
        _, warnings = validate_responses(responses, quiz)

        policy = (policy or self.default_policy).lower()
        if policy not in {"strict", "balanced", "lenient"}:
            warnings.append(f"Unknown policy '{policy}', using 'balanced'")
            policy = "balanced"

        results: List[GradeResult] = []

        qlist = list(quiz.get("questions") or [])
        for q in qlist:
            qid = q.get("id")
            if not qid:
                logger.warning("Question without ID encountered; skipping")
                continue

            qtype = (q.get("type") or "").strip().lower() or "mcq"
            ans = responses.get(qid)

            try:
                if qtype == "mcq":
                    res = self._grade_mcq(q, ans)
                elif qtype in {"true_false", "truefalse", "tf"}:
                    res = self._grade_true_false(q, ans)
                elif qtype in {"short", "long", "conceptual"}:
                    res = self._grade_freeform(
                        q,
                        ans,
                        policy=policy,
                        rubric_weights=rubric_weighting,
                    )
                # Code-based types
                elif qtype in {
                    "code_writing",
                    "code_completion",
                    "code_debugging",
                }:
                    if q.get("test_cases"):
                        res = self._grade_code_with_tests(
                            q,
                            ans,
                            policy=policy,
                        )
                    elif q.get("requirements"):
                        res = self._grade_code_static(
                            q,
                            ans,
                            policy=policy,
                        )
                    else:
                        res = self._grade_code_with_llm(
                            q,
                            ans,
                            policy=policy,
                        )
                elif qtype in {"code_output", "code_explanation"}:
                    res = self._grade_code_with_llm(
                        q,
                        ans,
                        policy=policy,
                    )
                # Decision-based types
                elif qtype in {"decision", "case_study", "scenario"}:
                    res = self._grade_decision(
                        q,
                        ans,
                        policy=policy,
                        rubric_weights=rubric_weighting,
                    )
                else:
                    logger.warning(
                        "Unknown question type '%s' for %s; treating as free-form",
                        qtype,
                        qid,
                    )
                    res = self._grade_freeform(
                        q,
                        ans,
                        policy=policy,
                        rubric_weights=rubric_weighting,
                    )
            except Exception as e:
                logger.error("Error grading %s: %s", qid, e)
                max_score = float(
                    q.get("max_score") or _default_max_score(qtype)
                )
                res = GradeResult(
                    question_id=qid,
                    type=qtype,
                    score=0.0,
                    max_score=max_score,
                    verdict="error",
                    feedback=f"Grading failed: {e}",
                )

            results.append(res)

        total = sum(r.score for r in results)
        max_total = sum(r.max_score for r in results)
        percentage = (total / max_total * 100.0) if max_total > 0 else 0.0

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Completed grading quiz %s in %.2fs - %.1f/%.1f (%.1f%%)",
            quiz_id,
            duration,
            total,
            max_total,
            percentage,
        )

        result: Dict[str, Any] = {
            "quiz_id": quiz_id,
            "total_score": round(total, 2),
            "max_total": round(max_total, 2),
            "percentage": round(percentage, 1),
            "items": [
                {
                    "question_id": r.question_id,
                    "type": r.type,
                    "score": r.score,
                    "max_score": r.max_score,
                    **(
                        {"is_correct": r.is_correct}
                        if r.is_correct is not None
                        else {}
                    ),
                    **({"verdict": r.verdict} if r.verdict is not None else {}),
                    **({"feedback": r.feedback} if r.feedback else {}),
                    **({"criteria": r.criteria} if r.criteria else {}),
                    **({"expected": r.expected} if r.expected is not None else {}),
                }
                for r in results
            ],
        }

        if warnings:
            result["warnings"] = warnings

        return result

    def grade_quiz_parallel(
        self,
        *,
        quiz: Dict[str, Any],
        responses: Dict[str, Any],
        policy: Optional[str] = None,
        rubric_weighting: Optional[Dict[str, float]] = None,
        max_workers: int = 3,
    ) -> Dict[str, Any]:
        """
        Grade a quiz using parallel LLM calls for slower free-form/code questions.
        Fast types (MCQ/True-False) are graded sequentially.
        """
        start_time = datetime.now()
        quiz_id = quiz.get("id")
        logger.info("Starting parallel grading for quiz %s", quiz_id)

        is_valid, errors = validate_quiz_structure(quiz)
        if not is_valid:
            logger.error("Invalid quiz structure for %s: %s", quiz_id, errors)
            return {
                "quiz_id": quiz_id,
                "error": "Invalid quiz structure",
                "details": errors,
                "total_score": 0.0,
                "max_total": 0.0,
                "percentage": 0.0,
                "items": [],
            }

        _, warnings = validate_responses(responses, quiz)

        policy = (policy or self.default_policy).lower()
        if policy not in {"strict", "balanced", "lenient"}:
            warnings.append(f"Unknown policy '{policy}', using 'balanced'")
            policy = "balanced"

        qlist = list(quiz.get("questions") or [])

        fast_questions: List[Dict[str, Any]] = []
        slow_questions: List[Dict[str, Any]] = []

        for q in qlist:
            qtype = (q.get("type") or "").strip().lower()
            if qtype in {"mcq", "true_false", "truefalse", "tf"}:
                fast_questions.append(q)
            else:
                slow_questions.append(q)

        results: List[GradeResult] = []

        # Grade fast questions
        for q in fast_questions:
            qid = q.get("id")
            if not qid:
                logger.warning("Question without ID encountered; skipping")
                continue
            qtype = (q.get("type") or "").strip().lower() or "mcq"
            ans = responses.get(qid)
            try:
                if qtype == "mcq":
                    res = self._grade_mcq(q, ans)
                else:
                    res = self._grade_true_false(q, ans)
            except Exception as e:
                logger.error("Error grading %s: %s", qid, e)
                max_score = float(
                    q.get("max_score") or _default_max_score(qtype)
                )
                res = GradeResult(
                    question_id=qid,
                    type=qtype,
                    score=0.0,
                    max_score=max_score,
                    verdict="error",
                    feedback=f"Grading failed: {e}",
                )
            results.append(res)

        # Grade slow questions in parallel
        def _grade_one(q: Dict[str, Any]) -> GradeResult:
            qid_inner = q.get("id")
            qtype_inner = (q.get("type") or "").strip().lower() or "short"
            ans_inner = responses.get(qid_inner)
            if qtype_inner in {"short", "long", "conceptual"}:
                return self._grade_freeform(
                    q,
                    ans_inner,
                    policy=policy,
                    rubric_weights=rubric_weighting,
                )
            if qtype_inner in {
                "code_writing",
                "code_completion",
                "code_debugging",
            }:
                if q.get("test_cases"):
                    return self._grade_code_with_tests(
                        q,
                        ans_inner,
                        policy=policy,
                    )
                if q.get("requirements"):
                    return self._grade_code_static(
                        q,
                        ans_inner,
                        policy=policy,
                    )
                return self._grade_code_with_llm(
                    q,
                    ans_inner,
                    policy=policy,
                )
            if qtype_inner in {"code_output", "code_explanation"}:
                return self._grade_code_with_llm(
                    q,
                    ans_inner,
                    policy=policy,
                )
            if qtype_inner in {"decision", "case_study", "scenario"}:
                return self._grade_decision(
                    q,
                    ans_inner,
                    policy=policy,
                    rubric_weights=rubric_weighting,
                )
            # Fallback to freeform for unknown types
            return self._grade_freeform(
                q,
                ans_inner,
                policy=policy,
                rubric_weights=rubric_weighting,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_grade_one, q): q for q in slow_questions
            }
            for future in as_completed(future_map):
                q = future_map[future]
                qid = q.get("id")
                qtype = (q.get("type") or "").strip().lower() or "short"
                try:
                    res = future.result()
                except Exception as e:
                    logger.error("Error grading %s in parallel: %s", qid, e)
                    max_score = float(
                        q.get("max_score") or _default_max_score(qtype)
                    )
                    res = GradeResult(
                        question_id=qid,
                        type=qtype,
                        score=0.0,
                        max_score=max_score,
                        verdict="error",
                        feedback=f"Grading failed: {e}",
                    )
                results.append(res)

        # Preserve original question order
        order = {q.get("id"): idx for idx, q in enumerate(qlist)}
        results.sort(key=lambda r: order.get(r.question_id, 1_000_000))

        total = sum(r.score for r in results)
        max_total = sum(r.max_score for r in results)
        percentage = (total / max_total * 100.0) if max_total > 0 else 0.0

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Completed parallel grading quiz %s in %.2fs - %.1f/%.1f (%.1f%%)",
            quiz_id,
            duration,
            total,
            max_total,
            percentage,
        )

        result: Dict[str, Any] = {
            "quiz_id": quiz_id,
            "total_score": round(total, 2),
            "max_total": round(max_total, 2),
            "percentage": round(percentage, 1),
            "items": [
                {
                    "question_id": r.question_id,
                    "type": r.type,
                    "score": r.score,
                    "max_score": r.max_score,
                    **(
                        {"is_correct": r.is_correct}
                        if r.is_correct is not None
                        else {}
                    ),
                    **({"verdict": r.verdict} if r.verdict is not None else {}),
                    **({"feedback": r.feedback} if r.feedback else {}),
                    **({"criteria": r.criteria} if r.criteria else {}),
                    **({"expected": r.expected} if r.expected is not None else {}),
                }
                for r in results
            ],
        }

        if warnings:
            result["warnings"] = warnings

        return result

