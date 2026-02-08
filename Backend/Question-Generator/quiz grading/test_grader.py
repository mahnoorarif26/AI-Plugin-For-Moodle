"""
Basic test harness for the grading system.
Run with: python3 test_grader.py

These tests assume GROQ_API_KEY is set in the environment for
LLM-backed grading. MCQ/True-False tests work without an API key.
"""

import os

from grader import QuizGrader


def test_mcq_grading() -> None:
    grader = QuizGrader(api_key=os.getenv("GROQ_API_KEY"))

    quiz = {
        "id": "test_mcq",
        "questions": [
            {
                "id": "Q1",
                "type": "mcq",
                "prompt": "What is 2+2?",
                "options": ["3", "4", "5", "6"],
                "answer": "B",
                "max_score": 1.0,
            }
        ],
    }

    responses = {"Q1": "4"}
    result = grader.grade_quiz(quiz=quiz, responses=responses)
    item = result["items"][0]
    print("MCQ grading:", item)

    # Conversational answer to exercise LLM fallback (if API key set)
    if os.getenv("GROQ_API_KEY"):
        conv_result = grader.grade_quiz(
            quiz=quiz,
            responses={"Q1": "I think the answer is four"},
        )
        conv_item = conv_result["items"][0]
        print("MCQ grading (conversational):", conv_item)


def test_freeform_grading() -> None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Skipping freeform LLM test (GROQ_API_KEY not set)")
        return

    grader = QuizGrader(api_key=api_key)

    quiz = {
        "id": "test_freeform",
        "questions": [
            {
                "id": "Q1",
                "type": "short",
                "prompt": "What is photosynthesis?",
                "answer": "The process by which plants convert light energy into chemical energy using CO2 and water",
                "max_score": 5.0,
            }
        ],
    }

    responses = {
        "Q1": "Plants use sunlight to make food from carbon dioxide and water"
    }
    result = grader.grade_quiz(quiz=quiz, responses=responses, policy="balanced")
    item = result["items"][0]
    print("Freeform grading:", item)


def test_code_static() -> None:
    grader = QuizGrader(api_key=os.getenv("GROQ_API_KEY"))

    quiz = {
        "id": "test_code_static",
        "questions": [
            {
                "id": "Q1",
                "type": "code_writing",
                "prompt": "Write a function to calculate factorial",
                "max_score": 5.0,
                "requirements": {
                    "must_have_function": "factorial",
                    "must_use_loop": True,
                    "max_lines": 10,
                },
            }
        ],
    }

    good_code = """
def factorial(n):
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result
"""

    result = grader.grade_quiz(quiz=quiz, responses={"Q1": good_code})
    item = result["items"][0]
    print("Code static grading:", item)


def test_decision_grading() -> None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Skipping decision LLM test (GROQ_API_KEY not set)")
        return

    grader = QuizGrader(api_key=api_key)

    quiz = {
        "id": "test_decision",
        "questions": [
            {
                "id": "Q1",
                "type": "decision",
                "scenario": "Your team needs to choose between SQL and NoSQL database.",
                "prompt": "What would you choose and why?",
                "max_score": 10.0,
            }
        ],
    }

    response = """
I would choose SQL (PostgreSQL) because:
1. Our data is relational (users, orders, products)
2. We need ACID guarantees for transactions
3. Complex queries with joins are common
4. Team already knows SQL

Trade-offs: NoSQL might scale better horizontally, but we can
optimize SQL with read replicas and caching for now.
"""

    result = grader.grade_quiz(
        quiz=quiz,
        responses={"Q1": response},
        policy="balanced",
    )
    item = result["items"][0]
    print("Decision grading:", item)


if __name__ == "__main__":
    print("Running grading system smoke tests...\n")
    test_mcq_grading()
    test_freeform_grading()
    test_code_static()
    test_decision_grading()
    print("\nDone.")
