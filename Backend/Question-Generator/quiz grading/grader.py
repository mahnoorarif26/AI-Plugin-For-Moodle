import os
import math
import re
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional

from dotenv import load_dotenv

from llm import chat_json, DEFAULT_MODEL
from prompts import SYSTEM_PROMPT_GRADE, build_freeform_user_prompt


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


def _letter_for_option_text(options: List[str], option_text: str) -> Optional[str]:
    try:
        norm = option_text.strip().lower()
        for idx, opt in enumerate(options):
            if opt.strip().lower() == norm:
                return chr(ord('A') + idx)
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

    def _grade_mcq(self, q: Dict[str, Any], ans: Any) -> GradeResult:
        qid = q.get("id") or ""
        options: List[str] = list(q.get("options") or [])
        max_score = float(q.get("max_score") or _default_max_score("mcq"))

        gold_letter = _letter_from_any(q.get("answer"), options)
        student_letter = _letter_from_any(ans, options)

        correct = (gold_letter is not None and student_letter == gold_letter)
        score = max_score if correct else 0.0
        fb = "Correct." if correct else (
            f"Incorrect. Expected {gold_letter}." if gold_letter else "No ground truth provided."
        )
        return GradeResult(
            question_id=qid,
            type="mcq",
            score=score,
            max_score=max_score,
            is_correct=correct if gold_letter else None,
            verdict=("correct" if correct else "incorrect") if gold_letter else None,
            feedback=fb,
        )

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
        if isinstance(q.get("answer"), str):
            reference_answer = q.get("answer")

        weights = rubric_weights or _policy_weights(policy)

        # Short-circuit: missing/empty answer must score 0
        if not student_answer:
            return GradeResult(
                question_id=qid,
                type=qtype,
                score=0.0,
                max_score=max_score,
                verdict="incorrect",
                feedback="No answer provided.",
                criteria=[
                    {"name": "accuracy", "score": 0.0, "max": max_score, "feedback": "No answer provided."}
                ],
            )

        if not self.api_key:
            # Fallback heuristic
            score, fb = _heuristic_overlap_score(reference_answer or "", student_answer, max_score)
            return GradeResult(
                question_id=qid,
                type=qtype,
                score=score,
                max_score=max_score,
                verdict=("correct" if math.isclose(score, max_score) else ("incorrect" if score == 0 else "partially_correct")),
                feedback=fb,
                criteria=[
                    {"name": "accuracy", "score": score, "max": max_score, "feedback": fb}
                ],
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
            out = chat_json(
                system_prompt=SYSTEM_PROMPT_GRADE,
                user_prompt=user_prompt,
                api_key=self.api_key,
                model=self.model,
                temperature=0.2,
                max_tokens=1000,
            )
            score = float(max(0.0, min(max_score, float(out.get("score", 0.0)))))
            verdict = str(out.get("verdict") or "").strip().lower() or (
                "correct" if math.isclose(score, max_score) else ("incorrect" if score == 0 else "partially_correct")
            )
            feedback = str(out.get("feedback") or "").strip() or ""
            criteria = out.get("criteria") if isinstance(out.get("criteria"), list) else None
            return GradeResult(
                question_id=qid,
                type=qtype,
                score=round(score, 2),
                max_score=max_score,
                verdict=verdict,
                feedback=feedback,
                criteria=criteria,
            )
        except Exception as e:
            score, fb = _heuristic_overlap_score(reference_answer or "", student_answer, max_score)
            return GradeResult(
                question_id=qid,
                type=qtype,
                score=score,
                max_score=max_score,
                verdict=("correct" if math.isclose(score, max_score) else ("incorrect" if score == 0 else "partially_correct")),
                feedback=f"LLM error; used heuristic: {e}. {fb}",
                criteria=[
                    {"name": "accuracy", "score": score, "max": max_score, "feedback": fb}
                ],
            )

    def grade_quiz(
        self,
        *,
        quiz: Dict[str, Any],
        responses: Dict[str, Any],
        policy: Optional[str] = None,
        rubric_weighting: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        policy = (policy or self.default_policy)
        results: List[GradeResult] = []

        qlist = list(quiz.get("questions") or [])
        for q in qlist:
            qid = q.get("id")
            qtype = (q.get("type") or "").strip().lower() or "mcq"
            ans = responses.get(qid)

            if qtype == "mcq":
                res = self._grade_mcq(q, ans)
            elif qtype in {"true_false", "truefalse", "tf"}:
                res = self._grade_true_false(q, ans)
            elif qtype in {"short", "long", "conceptual"}:
                res = self._grade_freeform(q, ans, policy=policy, rubric_weights=rubric_weighting)
            else:
                # default to freeform if unknown type
                res = self._grade_freeform(q, ans, policy=policy, rubric_weights=rubric_weighting)

            results.append(res)

        total = sum(r.score for r in results)
        max_total = sum(r.max_score for r in results)

        return {
            "quiz_id": quiz.get("id"),
            "total_score": round(total, 2),
            "max_total": round(max_total, 2),
            "items": [
                {
                    "question_id": r.question_id,
                    "type": r.type,
                    "score": r.score,
                    "max_score": r.max_score,
                    **({"is_correct": r.is_correct} if r.is_correct is not None else {}),
                    **({"verdict": r.verdict} if r.verdict is not None else {}),
                    **({"feedback": r.feedback} if r.feedback else {}),
                    **({"criteria": r.criteria} if r.criteria else {}),
                }
                for r in results
            ],
        }


