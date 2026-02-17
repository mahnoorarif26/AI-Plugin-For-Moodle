<img width="1536" height="1024" alt="ChatGPT Image Feb 16, 2026, 04_41_04 PM (1)" src="https://github.com/user-attachments/assets/16c42c9a-0d5a-4038-8fcd-f9f9f25c7433" /># 🎓 SMART EVALUATION IN E- LEARNING : A CUSTOMIZED AI : BASED PLUGIN FOR MOODLE

An intelligent AI-driven assessment automation system integrated with Moodle.  
This system generates quizzes and assignments using Large Language Models (LLMs) and performs automated grading using rubric-based AI evaluation and semantic embeddings.

---

## 📌 Overview

Traditional assessment creation and grading require significant instructor effort. With increasing student numbers and digital platforms like Moodle, manual assessment becomes inefficient and inconsistent.

This project introduces an **AI-powered Smart Assessment System** that:

- Automatically generates quizzes from uploaded PDFs
- Creates advanced assignments from selected topics
- Supports both **code-based** and **decision-based** scenarios
- Performs intelligent grading for objective and subjective questions
- Prevents duplicate questions using semantic embeddings
- Stores data using Google Firestore
- Supports Dockerized deployment for scalable environments

The system reduces instructor workload, ensures grading consistency, and enhances digital learning experiences.

---

## 🚀 Key Features

### 🧠 Intelligent Quiz Generation
- Structure-aware PDF processing
- Adaptive text chunking
- Difficulty-level control
- Bloom taxonomy-based question design
- Strict JSON validation of LLM outputs

### 📚 Advanced Assignment Generator
Supports:
- Conceptual tasks
- Scenario-based tasks
- Research-based tasks
- Project-based tasks
- Case studies
- Comparative analysis

Scenario styles:
- **Code-based** (debugging, system design, optimization)
- **Decision-based** (strategic reasoning, stakeholder analysis)

### 📝 Smart Grading Engine
- Rule-based grading for MCQs and True/False
- LLM-based rubric grading for subjective answers
- Code evaluation with structured criteria
- Decision-based analytical grading
- Strict / Balanced / Lenient grading policies
- Fallback heuristic grading if LLM is unavailable

### 🔍 Embedding-Based Duplicate Prevention
- Uses `all-MiniLM-L6-v2` SentenceTransformer
- Stores embeddings in Firestore
- Uses cosine similarity for semantic comparison
- Prevents repeated or highly similar questions

### 🐳 Deployment Ready
- Environment-based configuration
- API-driven backend
- Cloud-based Firestore integration
<img width="1536" height="1024" alt="ChatGPT Image Feb 16, 2026, 04_41_04 PM (1)" src="https://github.com/user-attachments/assets/04e6b549-db0a-4bed-83ad-2cd07bc78263" />




