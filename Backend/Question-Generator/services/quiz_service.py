"""Quiz service for managing quiz operations."""

from datetime import datetime
from typing import Dict, List, Any, Optional


def normalize_quiz_questions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize quiz questions to a consistent schema.
    
    Args:
        items: List of raw question items
        
    Returns:
        list: Normalized questions
    """
    questions = []
    for i, item in enumerate(items):
        qtype = (item.get("type") or "").strip().lower()
        
        # Normalize question type
        if qtype in ("tf", "truefalse", "true_false"):
            qtype = "true_false"
        elif qtype in ("mcq", "multiple_choice"):
            qtype = "mcq"
        elif qtype in ("short", "short_answer", "saq"):
            qtype = "short"
        else:
            qtype = "mcq"  # default

        question = {
            "type": qtype,
            "prompt": item.get("prompt") or item.get("question_text") or "",
            "difficulty": item.get("difficulty"),
            "order": i
        }
        
        if qtype in ("mcq", "true_false"):
            question["options"] = item.get("options") or []
            question["answer"] = item.get("answer")
        else:
            # short answer
            question["answer"] = item.get("answer")

        questions.append(question)
    
    return questions


def create_quiz_dict(title: str, questions: List[Dict[str, Any]], 
                      metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a standardized quiz dictionary.
    
    Args:
        title: Quiz title
        questions: List of questions
        metadata: Optional metadata
        
    Returns:
        dict: Quiz dictionary
    """
    return {
        "title": title,
        "questions": questions,
        "metadata": metadata or {},
        "created_at": datetime.utcnow()
    }


def validate_quiz_settings(settings: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate quiz settings.
    
    Args:
        settings: Settings to validate
        
    Returns:
        tuple: (is_valid, error_message)
    """
    time_limit = settings.get('time_limit', 30)
    
    if not isinstance(time_limit, int) or not (5 <= time_limit <= 180):
        return False, "Invalid time limit. Must be between 5 and 180 minutes."
    
    due_date = settings.get('due_date')
    if due_date and not isinstance(due_date, str):
        return False, "Invalid due date format."
    
    return True, None


def update_quiz_settings(quiz_data: Dict[str, Any], new_settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update quiz settings with validation.
    
    Args:
        quiz_data: Existing quiz data
        new_settings: New settings to apply
        
    Returns:
        dict: Updated quiz data
    """
    if 'settings' not in quiz_data:
        quiz_data['settings'] = {}
    
    quiz_data['settings'].update({
        'time_limit': new_settings.get('time_limit', 30),
        'due_date': new_settings.get('due_date'),
        'allow_retakes': new_settings.get('allow_retakes', False),
        'shuffle_questions': new_settings.get('shuffle_questions', True),
        'notification_message': new_settings.get('notification_message', '')
    })
    
    return quiz_data


def publish_quiz(quiz_data: Dict[str, Any], quiz_id: str) -> Dict[str, Any]:
    """
    Mark quiz as published and add metadata.
    
    Args:
        quiz_data: Quiz data to publish
        quiz_id: Quiz identifier
        
    Returns:
        dict: Updated quiz data
    """
    quiz_data["published"] = True
    quiz_data["published_at"] = datetime.utcnow().isoformat() + "Z"
    quiz_data["publish_url"] = f"/quiz/{quiz_id}"
    
    return quiz_data