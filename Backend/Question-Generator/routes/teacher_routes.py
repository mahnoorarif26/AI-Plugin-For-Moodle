"""Teacher-facing routes for quiz generation and management."""

from flask import Blueprint, render_template, request, jsonify
from datetime import datetime

# Import services - these will be injected from app.py
from services.db import (
    get_quiz_by_id,
    save_quiz as save_quiz_to_store
)
from services.quiz_service import (
    validate_quiz_settings,
    update_quiz_settings,
    publish_quiz as publish_quiz_service
)

teacher_bp = Blueprint('teacher', __name__, url_prefix='/teacher')


@teacher_bp.route('/generate')
def teacher_generate():
    """Teacher quiz generation page."""
    return render_template("index.html")


@teacher_bp.route('/list')
def list_quizzes():
    """Teacher's list of quizzes."""
    return render_template("list_quizzes.html")


@teacher_bp.route('/preview/<quiz_id>')
def teacher_preview(quiz_id):
    """Preview quiz as teacher."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return "Quiz not found", 404
    
    return render_template(
        'teacher_preview.html',
        quiz=quiz_data,
        quiz_id=quiz_id
    )


@teacher_bp.route('/preview')
def teacher_preview_page():
    """Generic teacher preview page."""
    return render_template("teacher_preview.html")


# Settings endpoints
@teacher_bp.route('/quizzes/<quiz_id>/settings', methods=['GET'])
def get_quiz_settings(quiz_id):
    """Get current settings of a quiz."""
    try:
        quiz_data = get_quiz_by_id(quiz_id)
        
        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404
        
        settings = quiz_data.get('settings', {})
        return jsonify(settings)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@teacher_bp.route('/quizzes/<quiz_id>/settings', methods=['POST'])
def update_settings(quiz_id):
    """Update quiz settings."""
    try:
        data = request.get_json()
        quiz_data = get_quiz_by_id(quiz_id)
        
        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404
        
        # Validate settings
        is_valid, error_msg = validate_quiz_settings(data)
        if not is_valid:
            return jsonify({"error": error_msg}), 400
        
        # Update settings
        quiz_data = update_quiz_settings(quiz_data, data)
        save_quiz_to_store(quiz_data)
        
        return jsonify({
            "success": True,
            "message": "Settings updated successfully"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@teacher_bp.route('/quizzes/<quiz_id>/send', methods=['POST'])
def send_quiz_to_students(quiz_id):
    """Send quiz to students with notification."""
    try:
        data = request.get_json()
        quiz_data = get_quiz_by_id(quiz_id)
        
        if not quiz_data:
            return jsonify({"error": "Quiz not found"}), 404
        
        # Mark quiz as published/active
        quiz_data["published"] = True
        quiz_data["published_at"] = datetime.utcnow().isoformat()
        quiz_data["notification_message"] = data.get('message', '')
        
        save_quiz_to_store(quiz_data)
        
        return jsonify({
            "success": True,
            "message": "Quiz sent to students successfully",
            "quiz_id": quiz_id
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500