# services/db.py
import os
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv

# Firestore is optional – we'll try to initialize and fall back to local JSON.
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except Exception:
    firebase_admin = None
    credentials = None
    firestore = None

load_dotenv()

FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")

# ---------- Local JSON fallback paths ----------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # .../Question-Generator
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


# ----------------------------------------------------
#   SAVE QUIZ/ASSIGNMENT
# ----------------------------------------------------
def save_quiz(quiz: Dict[str, Any]) -> str:
    """
    Save quiz or assignment based on metadata.kind.
    - metadata.kind == 'assignment' → goes to 'assignments'
    - otherwise → goes to 'AIquizzes'
    """
    # id & title
    qid = quiz.get("id") or str(uuid.uuid4())
    quiz["id"] = qid
    quiz["title"] = quiz.get("title") or quiz.get("metadata", {}).get("source_file") or "AI Generated Content"
    quiz["created_at"] = quiz.get("created_at") or datetime.utcnow()

    # normalize question IDs
    for q in quiz.get("questions", []):
        if not q.get("id"):
            q["id"] = str(uuid.uuid4())
        if not q.get("prompt") and q.get("question_text"):
            q["prompt"] = q["question_text"]

    # DETECT COLLECTION - FIXED VERSION
    metadata = quiz.get("metadata", {})
    detected_kind = metadata.get("kind", "quiz")  # Default to "quiz"
    
    # Set collection based on detected kind
    if detected_kind == "assignment":
        collection_name = "assignments"
    else:
        collection_name = "AIquizzes"
    
    print(f"💾 DEBUG: Detected kind = '{detected_kind}'")
    print(f"💾 DEBUG: Saving to collection '{collection_name}' with ID: {qid}")

    # FIRESTORE SAVE
    if _db:
        try:
            _db.collection(collection_name).document(qid).set(quiz)
            print(f"✅ Successfully saved to Firestore collection: {collection_name}")
            return qid
        except Exception as e:
            print(f"⚠️ Firestore save failed; fallback to local. Error: {e}")

    # LOCAL JSON SAVE
    if isinstance(quiz.get("created_at"), datetime):
        quiz["created_at"] = quiz["created_at"].isoformat()

    with open(_local_path(qid), "w", encoding="utf-8") as f:
        json.dump(quiz, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Saved locally as: {_local_path(qid)}")
    return qid


# ----------------------------------------------------
#   GET QUIZ/ASSIGNMENT
# ----------------------------------------------------
def get_quiz_by_id(quiz_id: str) -> Optional[Dict[str, Any]]:
    print(f"🔍 Looking for quiz/assignment with ID: {quiz_id}")
    
    if _db:
        try:
            # Search in both collections
            for col in ["AIquizzes", "assignments"]:
                print(f"🔍 Checking collection: {col}")
                d = _db.collection(col).document(quiz_id).get()
                if d.exists:
                    q = d.to_dict() or {}
                    q["id"] = quiz_id
                    print(f"✅ Found in {col}: {q.get('title', 'No title')}")
                    return q
                else:
                    print(f"❌ Not found in {col}")
        except Exception as e:
            print(f"⚠️ Firestore get failed; falling back to local. Error: {e}")

    # local fallback
    path = _local_path(quiz_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"✅ Found locally: {data.get('title', 'No title')}")
            return data
    else:
        print(f"❌ Not found locally: {path}")

    return None


# ----------------------------------------------------
#   LIST QUIZZES + ASSIGNMENTS
# ----------------------------------------------------
def list_quizzes(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    print(f"📋 Listing quizzes/assignments. Filter by kind: {kind}")
    items: List[Dict[str, Any]] = []

    if _db:
        try:
            collections_to_search = []
            if kind == "assignment":
                collections_to_search = ["assignments"]
            elif kind == "quiz":
                collections_to_search = ["AIquizzes"]
            else:
                collections_to_search = ["AIquizzes", "assignments"]

            for col in collections_to_search:
                print(f"🔍 Searching collection: {col}")
                docs = _db.collection(col).order_by("created_at", direction=firestore.Query.DESCENDING).stream()
                
                for d in docs:
                    q = d.to_dict() or {}
                    qid = q.get("id") or d.id
                    title = q.get("title") or "Untitled"
                    meta = q.get("metadata") or {}
                    
                    if col == "assignments":
                        item_kind = "assignment"
                    else:
                        item_kind = meta.get("kind", "quiz")

                    questions = q.get("questions", [])
                    questions_count = len(questions)
                    
                    # Calculate counts by type
                    counts = {}
                    for question in questions:
                        qtype = question.get("type", "unknown")
                        counts[qtype] = counts.get(qtype, 0) + 1

                    time_limit_min = q.get("time_limit_min", 60)

                    items.append({
                        "id": qid,
                        "title": title,
                        "created_at": q.get("created_at"),
                        "questions_count": questions_count,
                        "counts": counts,  # Add this
                        "questions": questions,  # Include full questions
                        "time_limit_min": time_limit_min,
                        "metadata": meta,
                        "kind": item_kind
                    })
                    print(f"📝 Found: {title} ({item_kind}) - {questions_count} questions")

            print(f"✅ Total items found: {len(items)}")
            return items
            
        except Exception as e:
            print(f"⚠️ Firestore list failed: {e}")

    # Local JSON branch
    print("🔍 Searching local JSON files...")
    for name in os.listdir(DATA_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as f:
                q = json.load(f)

            qid = q.get("id") or name.replace(".json", "")
            title = q.get("title") or "Untitled"
            meta = q.get("metadata") or {}
            item_kind = meta.get("kind", "quiz")
            
            # Apply kind filter
            if kind and item_kind != kind:
                continue

            questions_count = len(q.get("questions", []))
            time_limit_min = q.get("time_limit_min", 60)

            items.append({
                "id": qid,
                "title": title,
                "created_at": q.get("created_at"),
                "questions_count": questions_count,
                "time_limit_min": time_limit_min,
                "metadata": meta,
                "questions": q.get("questions", []),
                "kind": item_kind
            })
            print(f"📝 Found local item: {title} (Kind: {item_kind})")

        except Exception as e:
            print(f"⚠️ Error loading local file {name}: {e}")
            continue

    # sort newest first
    def _key(v):
        ts = v.get("created_at")
        return ts if isinstance(ts, str) else str(ts or "")
    items.sort(key=_key, reverse=True)
    
    print(f"✅ Returning {len(items)} items")
    return items


# ----------------------------------------------------
#   SUBMISSIONS (Firestore only)
# ----------------------------------------------------
def save_submission(quiz_id: str, student_data: Dict[str, Any]) -> Optional[str]:
    if not _db:
        print("ℹ️ Submissions require Firestore; skipping (no _db).")
        return None
    try:
        # Determine collection robustly so quiz submissions go under AIquizzes
        quiz_data = get_quiz_by_id(quiz_id)
        collection_name = "AIquizzes"  # default

        # 1) Prefer explicit submission kind when present
        kind_hint = (student_data or {}).get("kind", "").lower()
        if kind_hint in ("assignment_submission", "assignment"):
            collection_name = "assignments"
        elif kind_hint in ("quiz_submission", "quiz"):
            collection_name = "AIquizzes"
        else:
            # 2) Prefer actual parent doc location (if it already exists)
            try:
                if _db.collection("AIquizzes").document(quiz_id).get().exists:
                    collection_name = "AIquizzes"
                elif _db.collection("assignments").document(quiz_id).get().exists:
                    collection_name = "assignments"
            except Exception:
                pass
            # 3) Fallback to metadata.kind when still ambiguous
            if collection_name == "AIquizzes":
                if quiz_data and quiz_data.get("metadata", {}).get("kind") == "assignment":
                    collection_name = "assignments"

        payload = {
            "quiz_id": quiz_id,
            "student_email": student_data.get("email"),
            "student_name": student_data.get("name"),
            "answers": student_data.get("answers", {}),
            "files": student_data.get("files", {}),
            "score": student_data.get("score", 0),
            "total_questions": student_data.get("total_questions", 0),
            "status": student_data.get("status", "completed"),
            "time_taken_sec": student_data.get("time_taken_sec", 0),
            "submitted_at": datetime.utcnow(),
            "kind": student_data.get("kind", "quiz_submission")
        }
        ref = _db.collection(collection_name).document(quiz_id).collection("submissions").add(payload)
        submission_id = ref[1].id
        print(f"✅ Submission saved to {collection_name} with ID: {submission_id}")
        return submission_id
    except Exception as e:
        print(f"❌ save_submission failed: {e}")
        return None


def get_submitted_quiz_ids(student_email: str) -> List[str]:
    """Get list of quiz/assignment IDs that the student has already submitted"""
    if not _db:
        print("ℹ️ Firestore not available for submission check")
        return []
    try:
        submitted_ids = set()
        
        # Check both collections for submissions
        for collection_name in ["AIquizzes", "assignments"]:
            print(f"🔍 Checking submissions in {collection_name} for {student_email}")
            
            # Get all documents in the collection
            quizzes_ref = _db.collection(collection_name).stream()
            
            for quiz_doc in quizzes_ref:
                quiz_id = quiz_doc.id
                
                # Check if this student has submissions for this quiz
                submissions_ref = _db.collection(collection_name).document(quiz_id).collection("submissions")
                student_submissions = submissions_ref.where("student_email", "==", student_email).limit(1).stream()
                
                if list(student_submissions):
                    submitted_ids.add(quiz_id)
                    print(f"📝 Student has submitted: {quiz_id}")
        
        print(f"✅ Student has submitted {len(submitted_ids)} items")
        return list(submitted_ids)
        
    except Exception as e:
        print(f"❌ get_submitted_quiz_ids failed: {e}")
        return []


# ----------------------------------------------------
#   DEBUG FUNCTIONS
# ----------------------------------------------------
def debug_list_all():
    """Debug what's in the database"""
    print("=" * 50)
    print("📊 DEBUG: ALL ITEMS IN DATABASE:")
    all_items = list_quizzes()
    for item in all_items:
        print(f"  - ID: {item['id']}")
        print(f"    Title: {item['title']}")
        print(f"    Kind: {item.get('kind', 'not_set')}")
        print(f"    Questions: {item.get('questions_count', 0)}")
        print(f"    Collection: {'assignments' if item.get('kind') == 'assignment' else 'AIquizzes'}")
        print()
    print(f"📊 TOTAL: {len(all_items)} items")
    print("=" * 50)
    return all_items


def create_sample_assignment():
    """Create a sample assignment for testing"""
    sample_assignment = {
        "title": "Sample Programming Assignment - Python Functions",
        "questions": [
            {
                "id": str(uuid.uuid4()),
                "type": "short",
                "prompt": "Write a Python function to calculate factorial of a number.",
                "difficulty": "medium"
            },
            {
                "id": str(uuid.uuid4()),
                "type": "short", 
                "prompt": "Explain the time complexity of your solution.",
                "difficulty": "hard"
            }
        ],
        "metadata": {
            "kind": "assignment",  # This makes it an assignment
            "source": "sample",
            "created_at": datetime.utcnow().isoformat()
        },
        "time_limit_min": 120
    }
    
    assignment_id = save_quiz(sample_assignment)
    print(f"✅ Created sample assignment with ID: {assignment_id}")
    return assignment_id


def get_submissions_for_quiz(quiz_id: str):
    if not _db:
        print("Firestore not available")
        return []

    try:
        # detect quiz type
        quiz_data = get_quiz_by_id(quiz_id)
        collection_name = "AIquizzes"
        if quiz_data and quiz_data.get("metadata", {}).get("kind") == "assignment":
            collection_name = "assignments"

        submissions_ref = _db.collection(collection_name).document(quiz_id).collection("submissions")
        submissions = []
        for doc in submissions_ref.stream():
            item = doc.to_dict()
            item["id"] = doc.id
            submissions.append(item)

        return submissions

    except Exception as e:
        print("❌ get_submissions_for_quiz failed:", e)
        return []
