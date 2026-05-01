"""Grading service for automatic quiz grading using LLM."""

import os
import sys
import math
import importlib.util
from typing import Dict, List, Any, Optional
from pathlib import Path


class GradingService:
    """Service for grading quizzes using QuizGrader."""
    
    def __init__(self, api_key: str, model: str = None, default_policy: str = "balanced"):
        self.api_key = api_key
        self.model = model
        self.default_policy = default_policy
        self.grader = None
        self._load_grader()
    
    def _load_grader(self):
        """Load the QuizGrader module."""
        grader_file = Path(__file__).parent.parent / "quiz grading" / "grader.py"
        quiz_grading_dir = grader_file.parent
        
        if str(quiz_grading_dir) not in sys.path:
            sys.path.insert(0, str(quiz_grading_dir))
        
        if not grader_file.exists():
            print(f"⚠️ Grader file not found at {grader_file}; grading disabled.")
            return
        
        try:
            spec = importlib.util.spec_from_file_location("quizgrading.grader", grader_file)
            grader_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(grader_mod)
            QuizGrader = grader_mod.QuizGrader
            
            self.grader = QuizGrader(
                api_key=self.api_key,
                model=self.model,
                default_policy=self.default_policy,
            )
            print(f"✅ Quiz grader loaded from {grader_file}")
        except Exception as e:
            print(f"⚠️ Quiz grader failed to load: {e}")
            self.grader = None
    
    def is_available(self) -> bool:
        return self.grader is not None
    
    def grade_quiz(self, quiz: Dict[str, Any], responses: Dict[str, str],
                   policy: str = None) -> Dict[str, Any]:
        if not self.is_available():
            raise RuntimeError("Grader not available")
        policy = policy or self.default_policy
        return self.grader.grade_quiz(quiz=quiz, responses=responses, policy=policy)

    @staticmethod
    def prepare_quiz_for_grading(quiz: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize quiz questions for the grader.
        Critically: preserves 'marks' as max_score for assignment tasks.
        """
        quiz_for_grader = dict(quiz or {})
        normalized_questions: List[Dict[str, Any]] = []

        ASSIGNMENT_TYPES = {
            "assignment_task", "conceptual", "scenario", "research",
            "project", "case_study", "comparative"
        }

        for q in quiz_for_grader.get("questions", []) or []:
            qq = dict(q)
            qtype = (qq.get("type") or "").strip().lower()

            # Normalize assignment task types
            if qtype == "assignment_task":
                atype = (qq.get("assignment_type") or "conceptual").lower()
                qq["type"] = "assignment_task"
                qq["assignment_type"] = atype

            # ── FIX: Resolve max_score from multiple possible sources ──
            # Priority: explicit max_score > marks field > type-based default
            if qq.get("max_score") is None:
                marks = qq.get("marks")
                if marks is not None:
                    try:
                        qq["max_score"] = float(marks)
                    except (TypeError, ValueError):
                        qq["max_score"] = GradingService.default_max_score(qq.get("type"))
                else:
                    qq["max_score"] = GradingService.default_max_score(qq.get("type"))
            else:
                # Ensure max_score is a float even if already set
                try:
                    qq["max_score"] = float(qq["max_score"])
                except (TypeError, ValueError):
                    qq["max_score"] = GradingService.default_max_score(qq.get("type"))

            # Preserve all assignment metadata — do NOT strip these fields
            # The grader needs: requirements, grading_criteria, learning_objectives,
            # deliverables, context, code_snippet, word_count, etc.

            normalized_questions.append(qq)

        quiz_for_grader["questions"] = normalized_questions
        return quiz_for_grader

    @staticmethod
    def default_max_score(qtype: str) -> float:
        """
        Get default max score for question type.
        Assignment types default to 10 (not 1) since they carry more marks.
        """
        q = (qtype or "").strip().lower()

        # Objective types: 1 point each
        if q in ("mcq", "true_false", "tf", "truefalse"):
            return 1.0

        # Short answer: 3 points
        if q == "short":
            return 3.0

        # Long / conceptual: 5 points
        if q in ("long", "conceptual"):
            return 5.0

        # ── FIX: Assignment tasks deserve 10 points by default (not 1) ──
        if q in (
            "assignment_task", "scenario", "research",
            "project", "case_study", "comparative"
        ):
            return 10.0

        # Unknown type: fall back to 1
        return 1.0

    @staticmethod
    def ceil_score(val: Any) -> int:
        """Round up score to integer."""
        try:
            return int(math.ceil(float(val)))
        except Exception:
            return 0


# ── Helpers used by grading_routes.py ─────────────────────────────────────────

def _get_question_max_score(q: Dict[str, Any]) -> float:
    """
    Resolve the max score for a single question dict.
    Checks max_score, then marks, then type-based default.
    This is the single source of truth used by grading_routes when computing
    max_total_default so that it matches what the grader actually uses.
    """
    if q.get("max_score") is not None:
        try:
            return float(q["max_score"])
        except (TypeError, ValueError):
            pass
    if q.get("marks") is not None:
        try:
            return float(q["marks"])
        except (TypeError, ValueError):
            pass
    return GradingService.default_max_score(q.get("type"))


# ── Singleton management ───────────────────────────────────────────────────────

grading_service: Optional[GradingService] = None


def init_grading_service(api_key: str, model: str = None, policy: str = "balanced"):
    global grading_service
    grading_service = GradingService(api_key, model, policy)
    return grading_service


def get_grading_service() -> Optional[GradingService]:
    return grading_service