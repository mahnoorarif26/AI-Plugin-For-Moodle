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
        """
        Initialize grading service.
        
        Args:
            api_key: Groq API key
            model: Model name (optional)
            default_policy: Default grading policy
        """
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
        """Check if grader is available."""
        return self.grader is not None
    
    def grade_quiz(self, quiz: Dict[str, Any], responses: Dict[str, str], 
                   policy: str = None) -> Dict[str, Any]:
        """
        Grade a quiz submission.
        
        Args:
            quiz: Quiz data with questions
            responses: Student responses
            policy: Grading policy (optional)
            
        Returns:
            Grading results
        """
        if not self.is_available():
            raise RuntimeError("Grader not available")
        
        policy = policy or self.default_policy
        return self.grader.grade_quiz(quiz=quiz, responses=responses, policy=policy)
    
    # services/grading_service.py — update prepare_quiz_for_grading()

    @staticmethod
    def prepare_quiz_for_grading(quiz: Dict[str, Any]) -> Dict[str, Any]:
        quiz_for_grader = dict(quiz or {})
        normalized_questions: List[Dict[str, Any]] = []

        for q in quiz_for_grader.get("questions", []) or []:
            qq = dict(q)
            qtype = (qq.get("type") or "").strip().lower()

            # Map assignment_task → keep assignment_type for the new grader
            if qtype == "assignment_task":
                atype = (qq.get("assignment_type") or "conceptual").lower()
                # Keep type as assignment_task — new _grade_assignment_task handles it
                qq["type"] = "assignment_task"
                qq["assignment_type"] = atype

            # Ensure max_score from marks field
            if qq.get("max_score") is None:
                marks = qq.get("marks")
                if marks is not None:
                    try:
                        qq["max_score"] = float(marks)
                    except Exception:
                        qq["max_score"] = GradingService.default_max_score(qq.get("type"))
                else:
                    qq["max_score"] = GradingService.default_max_score(qq.get("type"))

            # IMPORTANT: preserve all assignment metadata for rubric building
            # Do NOT strip requirements, grading_criteria, learning_objectives etc.
            normalized_questions.append(qq)

        quiz_for_grader["questions"] = normalized_questions
        return quiz_for_grader


    @staticmethod
    def default_max_score(qtype: str) -> float:
        q = (qtype or "").lower()
        if q in ("mcq", "true_false", "tf", "truefalse"):
            return 1.0
        if q == "short":
            return 3.0
        if q in ("long", "conceptual"):
            return 5.0
        if q in ("assignment_task", "scenario", "research",
                "project", "case_study", "comparative"):
            return 10.0  # ← was missing, defaulted to 1.0
        return 1.0
    
    @staticmethod
    def default_max_score(qtype: str) -> float:
        """Get default max score for question type."""
        q = (qtype or "").lower()
        if q in ("mcq", "true_false", "tf", "truefalse"):
            return 1.0
        if q == "short":
            return 3.0
        if q in ("long", "conceptual"):
            return 5.0
        return 1.0
    
    @staticmethod
    def ceil_score(val: Any) -> int:
        """Round up score to integer."""
        try:
            return int(math.ceil(float(val)))
        except Exception:
            return 0


# Global grading service instance (will be initialized in app.py)
grading_service: Optional[GradingService] = None


def init_grading_service(api_key: str, model: str = None, policy: str = "balanced"):
    """Initialize global grading service."""
    global grading_service
    grading_service = GradingService(api_key, model, policy)
    return grading_service


def get_grading_service() -> Optional[GradingService]:
    """Get global grading service instance."""
    return grading_service