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
    
    @staticmethod
    def prepare_quiz_for_grading(quiz: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize quiz structure for the grader.
        
        Args:
            quiz: Raw quiz data
            
        Returns:
            Normalized quiz data
        """
        quiz_for_grader = dict(quiz or {})
        normalized_questions: List[Dict[str, Any]] = []
        
        for q in quiz_for_grader.get("questions", []) or []:
            qq = dict(q)
            
            # Map assignment-specific question types to grader-supported types
            qtype = (qq.get("type") or "").strip().lower()
            if qtype == "assignment_task":
                atype = (qq.get("assignment_type") or "").strip().lower()
                if atype == "conceptual":
                    mapped_type = "conceptual"
                elif atype == "scenario":
                    mapped_type = "scenario"
                elif atype in {"case_study", "case-study"}:
                    mapped_type = "case_study"
                else:
                    mapped_type = "long"
                qq["type"] = mapped_type
            
            # Ensure answer field exists
            if qq.get("answer") is None:
                for key in [
                    "correct_answer",
                    "reference_answer",
                    "expected_answer",
                    "ideal_answer",
                    "solution",
                    "model_answer",
                ]:
                    if qq.get(key) is not None:
                        qq["answer"] = qq.get(key)
                        break
            
            # Ensure max_score exists
            if qq.get("max_score") is None:
                if qq.get("marks") is not None:
                    try:
                        qq["max_score"] = float(qq.get("marks"))
                    except Exception:
                        qq["max_score"] = GradingService.default_max_score(qq.get("type"))
                else:
                    qq["max_score"] = GradingService.default_max_score(qq.get("type"))
            
            normalized_questions.append(qq)
        
        quiz_for_grader["questions"] = normalized_questions
        return quiz_for_grader
    
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