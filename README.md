# 🎓 AI-Powered Moodle Plugin — Automated Quiz & Assignment Generator

> **Final Year Project** · University of the Punjab · 2025–2026

An intelligent Moodle-integrated plugin that transforms lecture PDFs into fully graded quizzes and assignments using Large Language Models, semantic embeddings, and LTI 1.3 integration.

---

## 📌 GitHub Repository Description

> AI-powered Moodle LTI 1.3 plugin that auto-generates quizzes and assignments from PDF lecture material using Groq LLaMA-3.3-70B, Flask, Firebase Firestore, and Sentence Transformers — with automated multi-type grading and semantic duplicate detection.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| 📄 **PDF Intelligence** | Adaptive chunking with structure analysis (section-aware, paragraph, sentence-level) |
| 🤖 **AI Quiz Generation** | LLaMA-3.3-70B generates MCQ, True/False, Short Answer, Long Answer questions |
| 🎯 **Subtopic Detection** | Auto-detects document sections for targeted question generation |
| 📋 **6 Assignment Types** | Conceptual, Scenario, Research, Project, Case Study, Comparative |
| ✅ **Auto Grading Engine** | Rule-based (MCQ/T-F) + LLM semantic grading + heuristic F1 fallback |
| 🔍 **Duplicate Prevention** | Sentence Transformers + cosine similarity to avoid repeated questions |
| 🔗 **Moodle LTI 1.3** | Full LTI integration with role-based access and grade sync |
| ⏱️ **Quiz Controls** | Time limits, due dates, one-attempt enforcement, shuffle |
| 📊 **Grade Dashboard** | Per-question breakdown with verdict, feedback, and criterion scores |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11, Flask, Flask-CORS |
| **LLM** | Groq API — LLaMA-3.3-70B-Versatile |
| **Database** | Firebase Firestore (cloud), Local JSON (fallback) |
| **Embeddings** | `sentence-transformers` — `all-MiniLM-L6-v2` |
| **PDF Processing** | PyPDF, custom adaptive chunker |
| **LTI Integration** | LTI 1.3 / LTI 1.1 (simplified), PyJWT, cryptography |
| **Scheduling** | APScheduler (background cleanup) |
| **Frontend** | Vanilla JS, HTML5, CSS3 (no framework) |

---

## 📁 Project Structure

```
Backend/
└── Question-Generator/
    ├── app.py                      # Main Flask entry point
    ├── config/                     # Environment config & validation
    ├── routes/
    │   ├── api_routes.py           # Quiz/assignment generation APIs
    │   ├── teacher_routes.py       # Teacher dashboard routes
    │   ├── student_routes.py       # Student quiz/assignment routes
    │   ├── grading_routes.py       # Grading & submission routes
    │   ├── embedding_routes.py     # Similarity search routes
    │   └── lti_routes.py           # Moodle LTI launch routes
    ├── services/
    │   ├── db.py                   # Firestore + local JSON data layer
    │   ├── grading_service.py      # QuizGrader service wrapper
    │   ├── embedding_service.py    # Embedding engine service
    │   └── quiz_service.py         # Quiz normalization utilities
    ├── utils/
    │   ├── pdf_utils.py            # SmartPDFProcessor (adaptive chunking)
    │   ├── groq_utils.py           # LLM prompts & question generation
    │   ├── assignment_utils.py     # Advanced assignment generation
    │   ├── embedding_engine.py     # Firestore-backed embeddings
    │   ├── duplicate_prevention.py # Semantic dedup logic
    │   └── lti_utils.py            # RSA key, JWKS, OIDC helpers
    ├── quiz grading/
    │   ├── grader.py               # QuizGrader — all question types
    │   ├── llm.py                  # Groq JSON chat wrapper
    │   ├── prompts.py              # Grading system/user prompts
    │   └── ingestion.py            # PDF response parser
    ├── templates/                  # Jinja2 HTML templates
    │   ├── index.html              # Teacher dashboard
    │   ├── student_index.html      # Student dashboard
    │   ├── student_quiz.html       # Quiz-taking interface
    │   ├── student_assignment.html # Assignment interface
    │   ├── grade_detail.html       # Per-question grade breakdown
    │   └── ...
    ├── static/                     # JS & CSS
    │   ├── modal.js                # AI quiz generation modal
    │   ├── customizeModal.js       # Custom quiz settings modal
    │   ├── assignments.js          # Assignment generation logic
    │   ├── publish.js              # Quiz preview & rendering
    │   └── style.css
    └── requirements.txt
```

---

## ⚙️ Setup & Installation

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/ai-moodle-plugin.git
cd ai-moodle-plugin
```

### 2. Install Dependencies

```bash
cd Backend/Question-Generator
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in `Backend/Question-Generator/`:

```env
# Required
GROQ_API_KEY=your_groq_api_key_here

# Optional — Firestore (falls back to local JSON if not set)
FIREBASE_SERVICE_ACCOUNT_PATH=./serviceAccountKey.json

# Optional — defaults shown
GROQ_MODEL=llama-3.3-70b-versatile
GRADING_POLICY=balanced
FLASK_SECRET_KEY=your_secret_key_here
HOST=0.0.0.0
PORT=5000
DEBUG=1

# Optional — LTI 1.3
LTI_CLIENT_ID=your_lti_client_id
LTI_PLATFORM_ISSUER=https://your-moodle.com
LTI_AUTH_ENDPOINT=https://your-moodle.com/mod/lti/auth.php
LTI_JWKS_ENDPOINT=https://your-moodle.com/mod/lti/certs.php
```

### 4. Run the Application

```bash
python app.py
```

Visit `http://localhost:5000` — the teacher dashboard loads automatically.

---

## 🔌 Moodle LTI Integration

1. In Moodle, go to **Site Administration → Plugins → External Tools → Manage Tools**
2. Add a new tool with:
   - **Tool URL:** `http://your-server:5000/lti/launch`
   - **LTI Version:** LTI 1.1 (or 1.3 with JWKS endpoint)
   - **Consumer Key / Secret:** set in `lti_routes.py` → `LTI_CONSUMER_KEYS`
3. Add the tool as an activity in any Moodle course
4. Teachers see the quiz generator; students see available quizzes

---

## 🧠 How It Works

```
PDF Upload
    │
    ▼
SmartPDFProcessor          ← structure scoring, adaptive chunking
    │
    ▼
Groq LLaMA-3.3-70B         ← generates questions in JSON mode
    │
    ▼
Duplicate Detection        ← sentence-transformers cosine similarity
    │
    ▼
Quiz Editor (Teacher)      ← review, approve, flag, edit questions
    │
    ▼
Published to Students      ← one-attempt enforcement, timer, due date
    │
    ▼
Auto Grading               ← MCQ (exact) → Short/Long (LLM + F1 fallback)
    │
    ▼
Grade Dashboard            ← per-question verdict, feedback, criterion scores
```

---

## 🎯 Grading Engine

| Question Type | Method |
|---|---|
| MCQ | Exact match (letter index) + LLM fallback for ambiguous responses |
| True/False | Boolean normalization + exact match |
| Short Answer | LLM semantic evaluation with accuracy / completeness / clarity rubric |
| Long Answer | LLM evaluation with configurable rubric weights |
| Code Questions | Static analysis + sandbox execution + LLM quality review |
| Assignment Tasks | LLM rubric-based grading (no fixed answer) |

**Grading Policies:** `strict` · `balanced` (default) · `lenient`

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/quiz/from-pdf` | Generate quiz from PDF upload |
| `POST` | `/api/custom/extract-subtopics` | Detect subtopics from PDF |
| `POST` | `/api/custom/quiz-from-subtopics` | Generate quiz targeting subtopics |
| `POST` | `/api/custom/advanced-assignment` | Generate assignment from PDF |
| `POST` | `/api/custom/advanced-assignment-topics` | Generate assignment from typed topics |
| `GET` | `/api/quizzes` | List all quizzes/assignments |
| `GET` | `/api/quizzes/<id>` | Get a specific quiz |
| `POST` | `/api/quizzes/<id>/settings` | Update time limit, due date, note |
| `POST` | `/api/quizzes/<id>/allow` | Publish quiz to students |
| `GET` | `/api/quizzes/<id>/submissions` | Get all submissions |
| `GET` | `/api/grades` | Get all grades |
| `POST` | `/api/questions/similar` | Find semantically similar questions |
| `GET` | `/api/health` | Health check |
| `GET` | `/lti/launch` | Moodle LTI launch endpoint |

---

## 🖼️ Application Views

| View | Path | Description |
|---|---|---|
| Teacher Dashboard | `/teacher/generate` | Create quizzes/assignments |
| Quiz Editor | `/teacher/quiz-editor/<id>` | Review & approve generated questions |
| Quiz Preview | `/teacher/preview/<id>` | Preview with answer key |
| Submissions | `/teacher/submissions/<id>` | View all student submissions |
| Student Dashboard | `/student` | Available quizzes and assignments |
| Take Quiz | `/student/quiz/<id>` | Timed quiz interface |
| Take Assignment | `/student/assignment/<id>` | Assignment submission form |
| Grade Detail | `/student/grade/<submission_id>` | Full per-question feedback |

---

## 🔒 Key Constraints & Security

- **One-attempt enforcement** — checked at both UI and database level
- **Input validation** — file type, size, and content checks on all uploads
- **LTI signature validation** — configurable (bypass mode available for testing)
- **RSA key management** — auto-generated on first run, stored as PEM
- **Firestore security rules** — recommended for production deployment

---

## 📦 Requirements

```
flask
flask-cors
groq
pypdf
PyPDF2
python-dotenv
firebase-admin
cryptography
sentence-transformers
scikit-learn
numpy
apscheduler
pylti1p3
PyJWT
fpdf
```

---

## 👩‍💻 Author

**Mahnoor Arif**  
B.Sc. Data Science — University of the Punjab (2022–2026)  
📧 mahnoorarif138@gmail.com

---

## 📄 License

This project was developed as a Final Year Project (FYP). All rights reserved by the author.

---

*Built with Python · Flask · Groq LLaMA · Firebase · Sentence Transformers · LTI 1.3*
