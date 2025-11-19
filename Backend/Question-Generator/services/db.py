# services/db.py
import os
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv

# Firestore is optional – we’ll try to initialize and fall back to local JSON.
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except Exception:
    firebase_admin = None
    credentials = None
    firestore = None

load_dotenv()

FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "./serviceAccountKey.json")

# ---------- Local JSON fallback ----------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))        # .../Question-Generator
DATA_DIR = os.path.join(BASE_DIR, "data", "quizzes")
os.makedirs(DATA_DIR, exist_ok=True)

def _local_path(qid: str) -> str:
    return os.path.join(DATA_DIR, f"{qid}.json")

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

# ---------- Firestore init ----------
_db = None
if firebase_admin and credentials and firestore:
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_PATH)
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
        print("✅ Firestore initialized in services/db.py")
    except Exception as e:
        print(f"⚠️ Firestore init failed (services/db.py): {e}")
        _db = None
else:
    print("ℹ️ Firestore libraries not available; using local JSON storage.")

# ---------- public API ----------

def save_quiz(quiz: Dict[str, Any]) -> str:
    """
    Save quiz. Prefer Firestore; fallback to local JSON.
    Returns quiz_id.
    """
    # ensure id and timestamps
    qid = quiz.get("id") or str(uuid.uuid4())
    quiz["id"] = qid

    # top-level title convenience (in addition to metadata.source_file)
    quiz["title"] = quiz.get("title") or quiz.get("metadata", {}).get("source_file") or "AI Generated Quiz"

    created_at = quiz.get("created_at") or datetime.utcnow()
    quiz["created_at"] = created_at

    # give each question a stable id and normalize prompt
    for q in quiz.get("questions", []):
        if not q.get("id"):
            q["id"] = str(uuid.uuid4())
        if not q.get("prompt") and q.get("question_text"):
            q["prompt"] = q["question_text"]

    # try Firestore
    if _db:
        try:
            # store as a document under AIquizzes with provided/derived id
            _db.collection("AIquizzes").document(qid).set(quiz)
            return qid
        except Exception as e:
            print(f"⚠️ Firestore save failed; falling back to local. Error: {e}")

    # local fallback
    # convert datetime to iso string for JSON
    if isinstance(quiz.get("created_at"), datetime):
        quiz["created_at"] = quiz["created_at"].isoformat()

    with open(_local_path(qid), "w", encoding="utf-8") as f:
        json.dump(quiz, f, ensure_ascii=False, indent=2)
    return qid


def get_quiz_by_id(quiz_id: str) -> Optional[Dict[str, Any]]:
    if _db:
        try:
            d = _db.collection("AIquizzes").document(quiz_id).get()
            if d.exists:
                q = d.to_dict() or {}
                q["id"] = quiz_id
                return q
        except Exception as e:
            print(f"⚠️ Firestore get failed; falling back to local. Error: {e}")

    # local
    path = _local_path(quiz_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def list_quizzes(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List quizzes, optionally filtered by metadata.kind.
    kind: "quiz", "assignment", or None (for all).
    """
    items: List[Dict[str, Any]] = []

    # ---------- Firestore branch ----------
    if _db:
        try:
            docs = _db.collection("AIquizzes") \
                      .order_by("created_at", direction=firestore.Query.DESCENDING) \
                      .stream()
            for d in docs:
                q = d.to_dict() or {}
                qid = q.get("id") or d.id
                title = q.get("title") or q.get("metadata", {}).get("source_file") or "AI Generated Quiz"
                created_at = q.get("created_at")

                meta = q.get("metadata") or {}
                meta_kind = meta.get("kind", "quiz")  # default old data as quiz

                # 🔍 filter by kind if requested
                if kind and meta_kind != kind:
                    continue

                counts = {
                    "mcq": sum(1 for x in q.get("questions", []) if x.get("type") == "mcq"),
                    "true_false": sum(1 for x in q.get("questions", []) if x.get("type") == "true_false"),
                    "short": sum(1 for x in q.get("questions", []) if x.get("type") == "short"),
                    "long": sum(1 for x in q.get("questions", []) if x.get("type") == "long"),
                }
                items.append({
                    "id": qid,
                    "title": title,
                    "created_at": created_at,
                    "counts": counts,
                    "kind": meta_kind,   # 🔹 expose kind for frontend
                })
            return items
        except Exception as e:
            print(f"⚠️ Firestore list failed; falling back to local. Error: {e}")

    # ---------- Local JSON branch ----------
    for name in os.listdir(DATA_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as f:
                q = json.load(f)
            qid = q.get("id") or name.replace(".json", "")
            title = q.get("title") or q.get("metadata", {}).get("source_file") or "AI Generated Quiz"

            meta = q.get("metadata") or {}
            meta_kind = meta.get("kind", "quiz")  # default old data as quiz

            # 🔍 filter by kind if requested
            if kind and meta_kind != kind:
                continue

            counts = {
                "mcq": sum(1 for x in q.get("questions", []) if x.get("type") == "mcq"),
                "true_false": sum(1 for x in q.get("questions", []) if x.get("type") == "true_false"),
                "short": sum(1 for x in q.get("questions", []) if x.get("type") == "short"),
                "long": sum(1 for x in q.get("questions", []) if x.get("type") == "long"),
            }
            items.append({
                "id": qid,
                "title": title,
                "created_at": q.get("created_at"),
                "counts": counts,
                "kind": meta_kind,   # 🔹 expose kind for frontend
            })
        except Exception:
            continue

    # sort newest first (string iso or dt)
    def _key(v):
        ts = v.get("created_at")
        return ts if isinstance(ts, str) else str(ts or "")
    items.sort(key=_key, reverse=True)
    return items



def save_submission(quiz_id: str, student_data: Dict[str, Any]) -> Optional[str]:
    """
    Save a submission (Firestore only; no local index).
    Returns submission id or None.
    """
    if not _db:
        print("ℹ️ Submissions require Firestore; skipping (no _db).")
        return None
    try:
        payload = {
            "quiz_id": quiz_id,
            "student_email": student_data.get("email"),
            "student_name": student_data.get("name"),
            "answers": student_data.get("answers", {}),
            "score": student_data.get("score", 0),
            "total_questions": student_data.get("total_questions", 0),
            "submitted_at": datetime.utcnow(),
        }
        ref = _db.collection("AIquizzes").document(quiz_id).collection("submissions").add(payload)
        return ref[1].id
    except Exception as e:
        print(f"❌ save_submission failed: {e}")
        return None


def get_submitted_quiz_ids(student_email: str) -> List[str]:
    """
    Returns list of quiz_ids this student already submitted (Firestore only).
    """
    if not _db:
        return []
    try:
        submitted = set()
        quiz_refs = _db.collection("AIquizzes").select([]).stream()
        for qd in quiz_refs:
            qid = qd.id
            sub_q = _db.collection("AIquizzes").document(qid).collection("submissions") \
                      .where("student_email", "==", student_email).limit(1)
            if list(sub_q.stream()):
                submitted.add(qid)
        return list(submitted)
    except Exception as e:
        print(f"❌ get_submitted_quiz_ids failed: {e}")
        return []
