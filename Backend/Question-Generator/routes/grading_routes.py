"""Grading routes for quiz submissions and grade management."""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from datetime import datetime, timezone
from typing import Dict, Any

from services.db import get_quiz_by_id
from services.grading_service import get_grading_service
from services import db as _db_mod

grading_bp = Blueprint('grading', __name__)


# ── Local helpers (no cross-module imports needed) ────────────────────────────

def _default_max_score_for_type(qtype: str) -> float:
    """Return a sensible default max score based on question type."""
    q = (qtype or "").strip().lower()
    if q in ("mcq", "true_false", "tf", "truefalse"):
        return 1.0
    if q == "short":
        return 3.0
    if q in ("long", "conceptual"):
        return 5.0
    # Assignment tasks carry more marks — use 10 as default, not 1
    if q in ("assignment_task", "scenario", "research",
             "project", "case_study", "comparative"):
        return 10.0
    return 1.0


def _get_question_max_score(q: Dict[str, Any]) -> float:
    """
    Resolve the max score for a single question dict.
    Priority: max_score field > marks field > type-based default.
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
    return _default_max_score_for_type(q.get("type"))


def _extract_expected_answer(qq: Dict[str, Any]) -> str:
    """
    Pull the expected/reference answer from a question dict.
    For assignment tasks there is no fixed answer — return grading_criteria instead.
    """
    qtype = (qq.get('type') or '').lower()

    if qtype in ('mcq', 'true_false'):
        val = qq.get('answer') if qq.get('answer') is not None else qq.get('correct_answer')
        return str(val) if val is not None else ''

    if qtype in ('assignment_task', 'conceptual', 'scenario', 'research',
                 'project', 'case_study', 'comparative'):
        gc = qq.get('grading_criteria') or ''
        lo = qq.get('learning_objectives') or []
        parts = []
        if gc:
            parts.append(f"Grading criteria: {gc}")
        if lo:
            parts.append("Objectives: " + "; ".join(str(o) for o in lo))
        return "\n".join(parts) if parts else 'See grading criteria'

    for key in ("answer", "reference_answer", "expected_answer",
                "ideal_answer", "solution", "model_answer"):
        val = qq.get(key)
        if val:
            return str(val)
    return ''


def _humanize_datetime(val: Any) -> str:
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


# ── Routes ────────────────────────────────────────────────────────────────────

@grading_bp.route('/api/grades', methods=['GET'])
def api_grades():
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

                # Use _get_question_max_score so the marks field is respected
                max_total_default = sum(
                    _get_question_max_score(qq)
                    for qq in (quiz.get('questions') or [])
                )

                subs_ref = fs.collection(collection_name).document(qid).collection('submissions')
                if email_filter:
                    subs_ref = subs_ref.where('student_email', '==', email_filter)

                for sd in subs_ref.stream():
                    s = sd.to_dict() or {}

                    # Auto-grade pending submissions
                    if (grader and grader.is_available()
                            and s.get('status') == 'pending'
                            and not s.get('grading_items')):
                        try:
                            from services.grading_service import GradingService
                            quiz_for_grader = GradingService.prepare_quiz_for_grading(quiz)
                            result = grader.grade_quiz(
                                quiz=quiz_for_grader,
                                responses=s.get('answers') or {},
                            )
                            new_score = grader.ceil_score(result.get('total_score', 0))
                            new_max = (grader.ceil_score(result.get('max_total'))
                                       if result.get('max_total') is not None else None)
                            new_items = result.get('items') or []
                            fs.collection(collection_name).document(qid) \
                              .collection('submissions').document(sd.id).update({
                                'score': new_score,
                                'max_total': new_max,
                                'grading_items': new_items,
                            })
                            s['score'] = new_score
                            s['max_total'] = new_max
                            s['grading_items'] = new_items
                        except Exception as e:
                            print(f"[api/grades] auto-grade failed: {e}")

                    items.append({
                        'id': sd.id,
                        'title': title,
                        'date': str(s.get('submitted_at') or ''),
                        'date_human': _humanize_datetime(s.get('submitted_at') or ''),
                        'score': grader.ceil_score(s.get('score') or 0)
                                 if grader else int(s.get('score') or 0),
                        'max_score': grader.ceil_score(s.get('max_total') or max_total_default)
                                     if grader else int(s.get('max_total') or max_total_default),
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
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": False, "error": "firestore_disabled"}), 400

    grader = get_grading_service()

    try:
        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                subref = (fs.collection(collection_name).document(qid)
                          .collection('submissions').document(submission_id))
                sub = subref.get()
                if not sub.exists:
                    continue

                s = sub.to_dict() or {}
                has_max_total = "max_total" in s and s.get("max_total") is not None

                if grader:
                    s["score"] = grader.ceil_score(s.get("score") or 0)
                    s["max_total"] = grader.ceil_score(s.get("max_total") or 0) \
                                     if has_max_total else None
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
    fs = getattr(_db_mod, '_db', None)
    if fs is None:
        return jsonify({"success": False, "error": "firestore_disabled"}), 400

    grader = get_grading_service()
    if not grader or not grader.is_available():
        return jsonify({"success": False, "error": "grader_unavailable"}), 500

    try:
        target = quiz = collection_match = quiz_id = None

        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                sub = (fs.collection(collection_name).document(qid)
                       .collection('submissions').document(submission_id).get())
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

        from services.grading_service import GradingService
        quiz_for_grader = GradingService.prepare_quiz_for_grading(quiz)
        result = grader.grade_quiz(
            quiz=quiz_for_grader,
            responses=target.get('answers') or {},
        )
        fs.collection(collection_match).document(quiz_id) \
          .collection('submissions').document(submission_id).update({
            'score': grader.ceil_score(result.get('total_score', 0)),
            'max_total': grader.ceil_score(result.get('max_total'))
                         if result.get('max_total') is not None else None,
            'grading_items': result.get('items') or [],
        })

        return jsonify({"success": True, "result": result})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@grading_bp.route('/api/quizzes/<quiz_id>/submissions', methods=['GET'])
def api_get_quiz_submissions(quiz_id):
    try:
        from services.db import get_submissions_for_quiz
        submissions = get_submissions_for_quiz(quiz_id)

        if submissions is None:
            return jsonify({"success": False, "error": "Could not fetch submissions."}), 500

        formatted_submissions = []
        for sub in submissions:
            score = sub.get("score", 0)
            total_questions = sub.get("total_questions", 0)
            max_score = sub.get("max_total", total_questions)
            percentage = (score / max_score * 100) if max_score > 0 else 0

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
        return jsonify({"success": False, "error": str(e)}), 500


@grading_bp.route('/student/grade/<submission_id>', methods=['GET'])
def student_grade_detail(submission_id: str):
    """
    Render grade details page.
    - Triggers grading on-demand if grading_items is missing.
    - Always shows question rows even before grading completes.
    """
    origin = request.args.get('origin') or 'student'
    fs = getattr(_db_mod, '_db', None)

    if fs is None:
        return redirect(url_for('student.student_index'))

    grader = get_grading_service()

    try:
        found = quiz_data = collection_match = None

        for collection_name in ['AIquizzes', 'assignments']:
            for qdoc in fs.collection(collection_name).stream():
                qid = qdoc.id
                subref = (fs.collection(collection_name).document(qid)
                          .collection('submissions').document(submission_id))
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

        # ── Trigger grading on-demand if grading_items is empty ─────────────
        if grader and grader.is_available() and not (found.get('grading_items') or []):
            try:
                from services.grading_service import GradingService
                quiz_for_grader = GradingService.prepare_quiz_for_grading(quiz_data)
                result = grader.grade_quiz(
                    quiz=quiz_for_grader,
                    responses=found.get('answers') or {},
                )
                new_score = grader.ceil_score(result.get('total_score', 0))
                new_max = (grader.ceil_score(result.get('max_total'))
                           if result.get('max_total') is not None else None)
                new_items = result.get('items') or []

                update_payload = {'score': new_score, 'grading_items': new_items}
                if new_max is not None:
                    update_payload['max_total'] = new_max

                fs.collection(collection_match).document(quiz_data["id"]) \
                  .collection('submissions').document(submission_id).update(update_payload)

                found['score'] = new_score
                found['max_total'] = new_max
                found['grading_items'] = new_items
                print(f"✅ On-demand graded {len(new_items)} Qs for {submission_id}")
            except Exception as e:
                print(f"[student/grade] on-demand grading failed: {e}")
                import traceback
                traceback.print_exc()

        # ── Compute totals from question marks ───────────────────────────────
        questions = quiz_data.get('questions') or []
        max_total_from_questions = sum(_get_question_max_score(q) for q in questions)
        max_total_from_questions = (
            grader.ceil_score(max_total_from_questions) if grader
            else int(max_total_from_questions)
        )

        # ── Build per-question rows ──────────────────────────────────────────
        rows = []
        by_id = {q.get('id'): q for q in questions}
        grading_items = found.get('grading_items') or []

        if grading_items:
            for item in grading_items:
                qq = by_id.get(item.get('question_id')) or {}
                rows.append({
                    "prompt":         qq.get('prompt') or qq.get('question_text') or '(no prompt)',
                    "student_answer": (found.get('answers') or {}).get(item.get('question_id'), ''),
                    "expected":       _extract_expected_answer(qq),
                    "verdict":        item.get('verdict'),
                    "is_correct":     item.get('is_correct'),
                    "score":          item.get('score', 0),
                    "max_score":      item.get('max_score') or _get_question_max_score(qq),
                    "feedback":       item.get('feedback', ''),
                    "criteria":       item.get('criteria', []),
                })
        else:
            # Grading unavailable — still render questions + student answers
            answers = found.get('answers') or {}
            for qq in questions:
                rows.append({
                    "prompt":         qq.get('prompt') or qq.get('question_text') or '(no prompt)',
                    "student_answer": answers.get(qq.get('id') or '', '(no answer)'),
                    "expected":       _extract_expected_answer(qq),
                    "verdict":        None,
                    "is_correct":     None,
                    "score":          0,
                    "max_score":      _get_question_max_score(qq),
                    "feedback":       "Grading pending",
                    "criteria":       [],
                })

        # ── Compute display score ────────────────────────────────────────────
        if grading_items:
            try:
                display_score = sum(float(r.get('score') or 0) for r in rows)
                display_score = grader.ceil_score(display_score) if grader else int(display_score)
            except Exception:
                display_score = grader.ceil_score(found.get('score', 0)) if grader \
                                else int(found.get('score', 0))
        else:
            display_score = grader.ceil_score(found.get('score', 0)) if grader \
                            else int(found.get('score', 0))

        stored_max = found.get('max_total')
        max_total_display = (
            grader.ceil_score(stored_max) if grader else int(stored_max)
        ) if stored_max is not None else max_total_from_questions

        back_url = '/teacher/generate' if origin == 'teacher' else url_for('student.student_index')

        return render_template(
            'grade_detail.html',
            quiz_title=(
                quiz_data.get('title')
                or quiz_data.get('metadata', {}).get('source_file')
                or "Submitted Grade"
            ),
            score=display_score,
            total=max_total_from_questions,
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