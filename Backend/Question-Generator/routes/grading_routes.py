"""Grading routes for quiz submissions and grade management."""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from datetime import datetime, timezone
from typing import Dict, Any

from services.db import get_quiz_by_id
from services.grading_service import get_grading_service
from services import db as _db_mod

grading_bp = Blueprint('grading', __name__)


def _humanize_datetime(val: Any) -> str:
    """Return a consistent, human-readable UTC timestamp string."""
    try:
        if isinstance(val, datetime):
            dt = val
        elif isinstance(val, str):
            if val.endswith("Z"):
                val = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(val)
        else:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return ""


@grading_bp.route('/api/grades', methods=['GET'])
def api_grades():
    """
    Return graded submissions for a student (requires Firestore).
    Can filter by email.
    """
    email_filter = (request.args.get('email') or '').strip()
    fs = getattr(_db_mod, '_db', None)
    
    if fs is None:
        return jsonify({"success": True, "items": []})

    items = []
    grader = get_grading_service()
    
    try:
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                quiz = qdoc.to_dict() or {}
                title = (
                    quiz.get('title')
                    or quiz.get('metadata', {}).get('source_file')
                    or ('Assignment' if collection_name == 'assignments' else 'AI Generated Quiz')
                )

                # Calculate default max total
                max_total_default = 0.0
                for qq in quiz.get('questions', []) or []:
                    if grader:
                        max_total_default += float(qq.get('max_score') or grader.default_max_score(qq.get('type')))
                    else:
                        max_total_default += 1.0

                subs_ref = fs.collection(collection_name).document(qid).collection('submissions')
                if email_filter:
                    subs_ref = subs_ref.where('student_email', '==', email_filter)
                
                subs = subs_ref.stream()
                
                for sd in subs:
                    s = sd.to_dict() or {}

                    # Auto-grade if pending and grader available
                    if grader and grader.is_available() and s.get('status') == 'pending' and not s.get('grading_items'):
                        try:
                            quiz_for_grader = grader.prepare_quiz_for_grading(quiz)
                            result = grader.grade_quiz(
                                quiz=quiz_for_grader,
                                responses=s.get('answers') or {},
                            )
                            
                            # Update submission with grading results
                            fs.collection(collection_name).document(qid).collection('submissions').document(sd.id).update({
                                'score': grader.ceil_score(result.get('total_score', 0)),
                                'max_total': grader.ceil_score(result.get('max_total')) if result.get('max_total') is not None else None,
                                'grading_items': result.get('items') or [],
                            })
                            
                            s['score'] = grader.ceil_score(result.get('total_score', 0))
                            s['max_total'] = grader.ceil_score(result.get('max_total')) if result.get('max_total') is not None else None
                            s['grading_items'] = result.get('items') or []
                        except Exception as e:
                            print(f"[api/grades] auto-grade failed: {e}")

                    items.append({
                        'id': sd.id,
                        'title': title,
                        'date': str(s.get('submitted_at') or ''),
                        'date_human': _humanize_datetime(s.get('submitted_at') or ''),
                        'score': grader.ceil_score(s.get('score') or 0) if grader else int(s.get('score') or 0),
                        'max_score': grader.ceil_score(s.get('max_total') or max_total_default) if grader else int(s.get('max_total') or max_total_default),
                        'quiz_id': qid,
                        'student_email': s.get('student_email') or s.get('email') or '',
                        'student_name': s.get('student_name') or s.get('name') or '',
                        'roll_no': s.get('roll_no', 'N/A'),
                        'kind': 'assignment' if collection_name == 'assignments' else 'quiz',
                    })
        
        items.sort(key=lambda x: str(x.get('date') or ''), reverse=True)
        return jsonify({"success": True, "items": items})
    
    except Exception as e:
        return jsonify({"success": False, "error": f"grades_list_failed: {e}"}), 500


@grading_bp.route('/api/submissions/<submission_id>', methods=['GET'])
def api_get_submission(submission_id: str):
    """Fetch a specific submission by ID (Firestore required)."""
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": False, "error": "firestore_disabled"}), 400
    
    grader = get_grading_service()
    
    try:
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                subref = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id)
                sub = subref.get()
                
                if not sub.exists:
                    continue
                
                s = sub.to_dict() or {}
                has_max_total = "max_total" in s and s.get("max_total") is not None
                
                if grader:
                    s["score"] = grader.ceil_score(s.get("score") or 0)
                    s["max_total"] = grader.ceil_score(s.get("max_total") or 0) if has_max_total else None
                else:
                    s["score"] = int(s.get("score") or 0)
                    s["max_total"] = int(s.get("max_total") or 0) if has_max_total else None
                
                s["submitted_at_human"] = _humanize_datetime(s.get("submitted_at") or '')
                s["student_email"] = s.get("student_email") or s.get("email")
                s["student_name"] = s.get("student_name") or s.get("name")
                
                return jsonify({
                    "success": True,
                    "submission": s,
                    "quiz_id": qid,
                    "collection": collection_name,
                })
        
        return jsonify({"success": False, "error": "submission_not_found"}), 404
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@grading_bp.route('/api/submissions/<submission_id>/regrade', methods=['POST'])
def api_regrade_submission(submission_id: str):
    """Force regrading of a submission (Firestore required)."""
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": False, "error": "firestore_disabled"}), 400
    
    grader = get_grading_service()
    if not grader or not grader.is_available():
        return jsonify({"success": False, "error": "grader_unavailable"}), 500
    
    try:
        target = None
        quiz = None
        collection_match = None
        quiz_id = None
        
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                sub = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id).get()
                
                if sub.exists:
                    target = sub.to_dict() or {}
                    quiz = qdoc.to_dict() or {}
                    collection_match = collection_name
                    quiz_id = qid
                    break
            
            if target:
                break

        if not target or not quiz or not collection_match:
            return jsonify({"success": False, "error": "submission_not_found"}), 404

        # Prepare and grade
        quiz_for_grader = grader.prepare_quiz_for_grading(quiz)
        result = grader.grade_quiz(
            quiz=quiz_for_grader,
            responses=target.get('answers') or {},
        )
        
        # Update submission
        fs.collection(collection_match).document(quiz_id).collection('submissions').document(submission_id).update({
            'score': grader.ceil_score(result.get('total_score', 0)),
            'max_total': grader.ceil_score(result.get('max_total')) if result.get('max_total') is not None else None,
            'grading_items': result.get('items') or [],
        })

        return jsonify({"success": True, "result": result})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@grading_bp.route('/api/quizzes/<quiz_id>/submissions', methods=['GET'])
def api_get_quiz_submissions(quiz_id):
    """API endpoint to fetch all submissions for a specific quiz."""
    try:
        from services.db import get_submissions_for_quiz
        
        submissions = get_submissions_for_quiz(quiz_id)

        if submissions is None:
            return jsonify({
                "success": False,
                "error": "Could not fetch submissions. Database may not be available.",
            }), 500

        formatted_submissions = []
        for sub in submissions:
            score = sub.get("score", 0)
            total_questions = sub.get("total_questions", 0)
            max_score = sub.get("max_total", total_questions)
            
            if max_score > 0:
                percentage = (score / max_score) * 100
            else:
                percentage = 0

            formatted_submissions.append({
                "id": sub.get("id", "unknown"),
                "student_name": sub.get("student_name") or sub.get("name") or "Unknown",
                "student_email": sub.get("student_email") or sub.get("email") or "N/A",
                "roll_no": sub.get("roll_no", "N/A"),
                "score": score,
                "max_score": max_score,
                "percentage": round(percentage, 1),
                "total_questions": total_questions,
                "submitted_at": sub.get("submitted_at", ""),
                "time_taken_sec": sub.get("time_taken_sec", 0),
                "status": sub.get("status", "completed"),
            })

        return jsonify({
            "success": True,
            "submissions": formatted_submissions,
            "total": len(formatted_submissions),
            "quiz_id": quiz_id
        }), 200

    except Exception as e:
        print(f"❌ Error in api_get_quiz_submissions: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@grading_bp.route('/student/grade/<submission_id>', methods=['GET'])
def student_grade_detail(submission_id: str):
    """Render grade details page for a submission (Firestore required)."""
    origin = request.args.get('origin') or 'student'
    fs = getattr(_db_mod, '_db', None)
    
    if fs is None:
        return redirect(url_for('student.student_index'))
    
    grader = get_grading_service()
    
    try:
        found = None
        quiz_data = None
        collection_match = None
        
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                subref = fs.collection(collection_name).document(qid).collection('submissions').document(submission_id)
                sub = subref.get()
                
                if not sub.exists:
                    continue
                
                found = sub.to_dict() or {}
                quiz_data = qdoc.to_dict() or {}
                collection_match = collection_name
                quiz_data["id"] = qid
                break
            
            if found:
                break

        if not found or not quiz_data:
            return redirect(url_for('student.student_index'))

        # Auto-grade if not graded and grader available
        if grader and grader.is_available() and not (found.get('grading_items') or []):
            try:
                quiz_for_grader = grader.prepare_quiz_for_grading(quiz_data)
                result = grader.grade_quiz(
                    quiz=quiz_for_grader,
                    responses=found.get('answers') or {},
                )
                
                fs.collection(collection_match).document(quiz_data["id"]).collection('submissions').document(submission_id).update({
                    'score': grader.ceil_score(result.get('total_score', 0)),
                    'max_total': grader.ceil_score(result.get('max_total')) if result.get('max_total') is not None else None,
                    'grading_items': result.get('items') or [],
                })
                
                found['score'] = grader.ceil_score(result.get('total_score', 0))
                found['max_total'] = grader.ceil_score(result.get('max_total')) if result.get('max_total') is not None else None
                found['grading_items'] = result.get('items') or []
            except Exception as e:
                print(f"[student/grade] auto-grade failed: {e}")

        # Prepare grade details
        rows = []
        total_max = 0.0
        by_id = {q.get('id'): q for q in (quiz_data.get('questions') or [])}
        
        for q in quiz_data.get('questions', []) or []:
            if grader:
                total_max += float(q.get('max_score') or grader.default_max_score(q.get('type')))
            else:
                total_max += 1.0
        
        total_max = int(total_max) if not grader else grader.ceil_score(total_max)

        for item in found.get('grading_items') or []:
            qq = by_id.get(item.get('question_id')) or {}
            expected_val = ""
            
            if (qq.get('type') or '').lower() in ('mcq', 'true_false'):
                expected_val = qq.get('answer') if qq.get('answer') is not None else qq.get('correct_answer')
            else:
                for key in ["answer", "reference_answer", "expected_answer", "ideal_answer", "solution", "model_answer"]:
                    if qq.get(key):
                        expected_val = str(qq.get(key))
                        break
            
            rows.append({
                "prompt": qq.get('prompt') or qq.get('question_text') or '(no prompt)',
                "student_answer": (found.get('answers') or {}).get(item.get('question_id')),
                "expected": expected_val,
                "verdict": item.get('verdict'),
                "is_correct": item.get('is_correct'),
                "score": item.get('score'),
                "max_score": item.get('max_score'),
            })

        if rows:
            try:
                display_score = sum(float(r.get('score') or 0) for r in rows)
                display_score = int(display_score) if not grader else grader.ceil_score(display_score)
            except Exception:
                display_score = found.get('score', 0)
        else:
            display_score = int(found.get('score', 0)) if not grader else grader.ceil_score(found.get('score', 0))
        
        max_total_display = int(found.get('max_total') or total_max) if not grader else grader.ceil_score(found.get('max_total') or total_max)
        
        back_url = '/teacher/generate' if origin == 'teacher' else url_for('student.student_index')
        
        return render_template(
            'grade_detail.html',
            quiz_title=quiz_data.get('title') or quiz_data.get('metadata', {}).get('source_file') or "Submitted Grade",
            score=display_score,
            total=total_max,
            max_total=max_total_display,
            submission_id=submission_id,
            submitted_at=_humanize_datetime(found.get('submitted_at') or ''),
            student_email=found.get('student_email') or found.get('email') or '',
            student_name=found.get('student_name') or found.get('name') or '',
            roll_no=found.get('roll_no', 'N/A'),
            back_url=back_url,
            rows=rows,
        )
    
    except Exception as e:
        print(f"[student/grade] failed: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('student.student_index'))