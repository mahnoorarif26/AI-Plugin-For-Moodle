from typing import Dict


SYSTEM_PROMPT_GRADE = """
You are an expert educator and fair grader. You grade student answers using
clear rubric-based criteria and return STRICT JSON ONLY without any extra text.

You must:
- Assess correctness, completeness, and clarity according to the provided rubric weights.
- Be consistent with the requested grading policy (balanced/strict/lenient).
- Prefer the provided reference/ideal answer and prompt context when available.
- Avoid hallucinations; if uncertain, note uncertainty in feedback.
-if the answer is completely wrong, give a score of 0.
-if the answer is completely correct, give full score.

Return JSON of the form:
{
  "score": number,                 // between 0 and max_score
  "max_score": number,
  "verdict": "correct|partially_correct|incorrect",
  "feedback": "concise constructive feedback",
  "criteria": [
    {"name":"accuracy","score":number,"max":number,"feedback":"..."},
    {"name":"completeness","score":number,"max":number,"feedback":"..."},
    {"name":"clarity","score":number,"max":number,"feedback":"..."}
  ]
}
"""


def build_freeform_user_prompt(
    *,
    question_prompt: str,
    student_answer: str,
    reference_answer: str | None,
    max_score: float,
    policy: str,
    rubric_weights: Dict[str, float],
) -> str:
    ref_block = reference_answer or "(no explicit reference; grade using prompt)"
    return f"""
GRADE THE FOLLOWING ANSWER.

Grading policy: {policy}
Rubric weights (sum ~ 1.0): accuracy={rubric_weights.get('accuracy', 0.5):.2f}, completeness={rubric_weights.get('completeness', 0.3):.2f}, clarity={rubric_weights.get('clarity', 0.2):.2f}
Max score: {max_score}

QUESTION PROMPT:
{question_prompt}

REFERENCE / IDEAL ANSWER (if any):
{ref_block}

STUDENT ANSWER:
{student_answer}

Return STRICT JSON only.
"""

