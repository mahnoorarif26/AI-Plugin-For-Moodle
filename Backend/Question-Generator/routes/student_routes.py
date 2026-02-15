"""Student routes for taking quizzes, assignments, and viewing results."""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session
from datetime import datetime
from typing import Dict

from services.db import (
    get_quiz_by_id,
    list_quizzes,
    get_submitted_quiz_ids,
    save_submission as save_submission_to_store
)

student_bp = Blueprint('student', __name__, url_prefix='/student')


@student_bp.route('/')
def student_index():
    """Student dashboard - shows available quizzes and assignments."""
    user_id = session.get('lti_user_id', 'Student')
    
    try:
        student_email = f"{user_id}@example.com" if user_id != 'Student' else "student@example.com"
        submitted_quiz_ids = set(get_submitted_quiz_ids(student_email) or [])
        
        items = list_quizzes() or []
        
        # Filter: Only show quizzes approved by teacher
        items = [q for q in items if q.get('is_allowed') == True]
        
        quizzes = []
        assignments = []
        
        for it in items:
            # Skip already attempted
            if it["id"] in submitted_quiz_ids:
                continue
            
            # Get settings
            settings = it.get('settings', {}) or {}
            time_limit = settings.get('time_limit') or it.get('time_limit')
            due_date = settings.get('due_date') or it.get('due_date')
            note = settings.get('note') or ''
            
            item_data = {
                "id": it["id"],
                "title": it.get("title") or "AI Generated Item",
                "questions_count": sum((it.get("counts") or {}).values()) if it.get("counts") else len(it.get("questions", [])),
                "created_at": it.get("created_at"),
                "time_limit": time_limit,
                "due_date": due_date,
                "note": note,
                "settings": settings,
            }
            
            # Separate quizzes and assignments
            metadata = it.get('metadata', {})
            if metadata.get('kind') == 'assignment':
                assignments.append(item_data)
            else:
                quizzes.append(item_data)
        
        return render_template(
            'student_index.html',
            quizzes=quizzes,
            assignments=assignments,
            error=None,
            student_name=user_id
        )
    
    except Exception as e:
        print(f"❌ Error fetching student item list: {e}")
        return render_template(
            'student_index.html',
            quizzes=[],
            assignments=[],
            error=f"Failed to load items: {e}",
            student_name=user_id
        )


@student_bp.route('/quiz/<quiz_id>', methods=['GET'])
def student_quiz(quiz_id):
    """Display quiz for student to complete - NO pre-filled student info."""
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return ("Quiz not found", 404)
    
    # Prepare questions for student
    questions_for_student = [
        {
            'id': q.get('id'),
            'type': q.get('type'),
            'prompt': q.get('prompt') or q.get('question_text'),
            'options': q.get('options') if q.get('type') in ['mcq', 'true_false'] else None,
            'difficulty': q.get('difficulty'),
        } for q in quiz_data.get('questions', [])
    ]
    
    title = quiz_data.get('title') or quiz_data.get('metadata', {}).get('source_file', f"Quiz #{quiz_id}")
    
    # Get settings
    settings = quiz_data.get('settings', {}) or {}
    time_limit = settings.get('time_limit') or quiz_data.get('time_limit') or 10
    due_date = settings.get('due_date') or quiz_data.get('due_date') or None
    
    print(f"✅ Loaded quiz {quiz_id}: time_limit={time_limit}, due_date={due_date}")
    
    return render_template(
        'student_quiz.html',
        quiz_id=quiz_id,
        title=title,
        questions=questions_for_student,
        time_limit=time_limit,
        due_date=due_date,
        settings=settings
    )


@student_bp.route('/assignment/<assignment_id>', methods=['GET'])
def student_assignment(assignment_id):
    """Display assignment for student to complete - NO pre-filled student info."""
    assignment_data = get_quiz_by_id(assignment_id)
    
    if not assignment_data:
        return "Assignment not found", 404
    
    # Pass COMPLETE question data to template (including all metadata)
    questions_for_student = assignment_data.get('questions', [])
    
    title = assignment_data.get('title') or assignment_data.get('metadata', {}).get('source_file', 'Assignment')
    
    # Get settings
    settings = assignment_data.get('settings', {}) or {}
    time_limit = settings.get('time_limit') or assignment_data.get('time_limit') or 0
    due_date = settings.get('due_date') or assignment_data.get('due_date') or None
    note = settings.get('note') or ''
    
    return render_template(
        'student_assignment.html',
        assignment_id=assignment_id,
        quiz_id=assignment_id,  # For compatibility
        title=title,
        questions=questions_for_student,
        time_limit=time_limit,
        due_date=due_date,
        note=note,
        settings=settings
    )


@student_bp.route('/submit', methods=['POST'])
def submit_quiz():
    """Handle student quiz submission - CAPTURES STUDENT INFO."""
    form_data = request.form
    quiz_id = form_data.get('quiz_id')
    
    # Get student information from form
    student_name = (form_data.get('student_name') or '').strip()
    student_email = (form_data.get('student_email') or '').strip()
    roll_no = (form_data.get('roll_no') or '').strip()
    
    # Validate student information
    if not student_name or not student_email or not roll_no:
        return jsonify({
            "error": "Missing student information. Please provide name, email, and roll number."
        }), 400
    
    if not quiz_id:
        return jsonify({"error": "Missing quiz ID"}), 400
    
    correct_quiz_data = get_quiz_by_id(quiz_id)
    if not correct_quiz_data:
        return jsonify({"error": "Quiz not found"}), 404
    
    # Check if this student has already submitted this quiz
    submitted_quiz_ids = set(get_submitted_quiz_ids(student_email) or [])
    if quiz_id in submitted_quiz_ids:
        return render_template(
            'submission_confirmation.html',
            quiz_title=correct_quiz_data.get('title', 'Quiz already submitted'),
            score=None,
            total=None,
            submission_id='N/A',
            student_name=student_name,
            student_email=student_email,
            roll_no=roll_no,
            submitted_at=datetime.now().strftime("%b %d, %Y %I:%M %p"),
            confirmation_message="You have already attempted this quiz.",
            item_type="Quiz"
        )
    
    # Collect answers and grade
    total_questions = len(correct_quiz_data.get('questions', []))
    student_answers: Dict[str, str] = {}
    score = 0
    question_results = []
    
    for q in correct_quiz_data.get('questions', []):
        q_id = q.get('id')
        if not q_id:
            continue
        
        correct_answer = q.get('correct_answer') or q.get('answer')
        student_response = (form_data.get(q_id) or '').strip()
        student_answers[q_id] = student_response
        
        # Grade MCQ and True/False automatically
        is_correct = False
        if q.get('type') in ['mcq', 'true_false'] and correct_answer is not None:
            if str(student_response).lower() == str(correct_answer).lower():
                score += 1
                is_correct = True
        
        # Store detailed results
        question_results.append({
            'question_id': q_id,
            'question_text': q.get('prompt', ''),
            'student_answer': student_response,
            'correct_answer': correct_answer,
            'is_correct': is_correct,
            'question_type': q.get('type')
        })
    
    # Calculate percentage
    percentage = (score / total_questions * 100) if total_questions > 0 else 0
    
    # Save submission
    submission_data = {
        "email": student_email,
        "name": student_name,
        "roll_no": roll_no,
        "student_email": student_email,
        "student_name": student_name,
        "answers": student_answers,
        "score": score,
        "total_questions": total_questions,
        "percentage": percentage,
        "question_results": question_results,
        "status": "pending",  # Will be graded by grading service
        "submitted_at": datetime.utcnow().isoformat()
    }
    
    submission_id = save_submission_to_store(quiz_id, submission_data)
    
    # Redirect to confirmation
    return redirect(
        url_for(
            'student.submission_confirmation',
            quiz_id=quiz_id,
            score=score,
            total=total_questions,
            submission_id=submission_id,
            student_name=student_name,
            student_email=student_email,
            roll_no=roll_no,
        )
    )


@student_bp.route('/submit_assignment', methods=['POST'])
def submit_assignment():
    """Handle student assignment submission - CAPTURES STUDENT INFO, NO FILE UPLOAD."""
    try:
        form_data = request.form
        assignment_id = form_data.get('assignment_id') or form_data.get('quiz_id')
        
        # Get student information from form
        student_name = (form_data.get('student_name') or '').strip()
        student_email = (form_data.get('student_email') or '').strip()
        roll_no = (form_data.get('roll_no') or '').strip()
        
        # Validate student information
        if not student_name or not student_email or not roll_no:
            return jsonify({
                "error": "Missing student information. Please provide name, email, and roll number."
            }), 400
        
        if not assignment_id:
            return jsonify({"error": "Missing assignment ID"}), 400
        
        assignment_data = get_quiz_by_id(assignment_id)
        if not assignment_data:
            return jsonify({"error": "Assignment not found"}), 404
        
        # Check if already submitted
        submitted_quiz_ids = set(get_submitted_quiz_ids(student_email) or [])
        if assignment_id in submitted_quiz_ids:
            return render_template(
                'submission_confirmation.html',
                quiz_title=assignment_data.get('title', 'Assignment already submitted'),
                score=None,
                total=None,
                submission_id='N/A',
                student_name=student_name,
                student_email=student_email,
                roll_no=roll_no,
                confirmation_message="You have already submitted this assignment.",
                item_type="Assignment"
            )
        
        # Collect student answers (text only - no file uploads)
        student_answers = {}
        
        for q in assignment_data.get('questions', []):
            q_id = q.get('id')
            if not q_id:
                continue
            
            answer_text = (form_data.get(q_id) or '').strip()
            student_answers[q_id] = answer_text
        
        # Calculate preliminary score
        total_questions = len(assignment_data.get('questions', []))
        
        submission_data = {
            "email": student_email,
            "name": student_name,
            "roll_no": roll_no,
            "student_email": student_email,
            "student_name": student_name,
            "answers": student_answers,
            "score": 0,  # Assignments start at 0 until manually graded
            "total_questions": total_questions,
            "status": "pending_review",
            "kind": "assignment_submission",
            "submitted_at": datetime.utcnow().isoformat()
        }
        
        submission_id = save_submission_to_store(assignment_id, submission_data)
        
        return render_template(
            'submission_confirmation.html',
            quiz_title=assignment_data.get('title', 'Assignment'),
            score=None,  # Don't show score for assignments
            total=total_questions,
            submission_id=submission_id,
            student_name=student_name,
            student_email=student_email,
            roll_no=roll_no,
            submitted_at=datetime.now().strftime("%b %d, %Y %H:%M UTC"),
            confirmation_message="Your assignment has been submitted successfully and is pending review by your instructor.",
            is_assignment=True,
            item_type="Assignment",
        )
        
    except Exception as e:
        print(f"❌ Error submitting assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@student_bp.route('/confirmation/<quiz_id>', methods=['GET'])
def submission_confirmation(quiz_id):
    """Display submission confirmation and score."""
    # Get data from query parameters
    score = request.args.get('score', 'N/A')
    total = request.args.get('total', 'N/A')
    submission_id = request.args.get('submission_id', 'N/A')
    student_name = request.args.get('student_name', 'Student')
    student_email = request.args.get('student_email', '')
    roll_no = request.args.get('roll_no', 'N/A')
    
    quiz_data = get_quiz_by_id(quiz_id)
    quiz_title = (
        (quiz_data.get("title") if quiz_data else None)
        or (quiz_data.get("metadata", {}).get("source_file") if quiz_data else None)
        or "Submitted Quiz"
    )
    
    return render_template(
        'submission_confirmation.html',
        quiz_title=quiz_title,
        score=score,
        total=total,
        submission_id=submission_id,
        student_name=student_name,
        student_email=student_email,
        roll_no=roll_no,
        submitted_at=datetime.now().strftime("%b %d, %Y %I:%M %p"),
        item_type="Quiz",
        confirmation_message="Your quiz has been submitted successfully!"
    )


@student_bp.route('/submission/<quiz_id>/<submission_id>', methods=['GET'])
def view_submission_details(quiz_id, submission_id):
    """View detailed results of a quiz submission."""
    # This route redirects to the grading route for detailed view
    return redirect(url_for('grading.student_grade_detail', submission_id=submission_id))