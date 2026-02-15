"""
Main Application Entry Point
Quiz Generation System with LTI Integration, Grading, and Embeddings
"""

import os
import sys
from pathlib import Path
from flask import Flask, redirect, url_for, render_template
from flask_cors import CORS

# ===============================
# PATH SETUP
# ===============================
BASE_DIR = os.path.dirname(__file__)
QG_DIR = os.path.join(BASE_DIR, "Backend", "Question-Generator")
if QG_DIR not in sys.path:
    sys.path.insert(0, QG_DIR)

# ===============================
# IMPORT CONFIGURATION
# ===============================
from config import Config

# ===============================
# CREATE AND CONFIGURE APP
# ===============================
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}})

# Create upload folder
UPLOAD_FOLDER = Path(BASE_DIR) / Config.UPLOAD_FOLDER
UPLOAD_FOLDER.mkdir(exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

# Validate configuration
Config.validate()

# ===============================
# INITIALIZE SERVICES
# ===============================
from services.grading_service import init_grading_service, get_grading_service
from services.embedding_service import init_embedding_service, get_embedding_service

# Initialize grading service
grading_service = init_grading_service(
    api_key=Config.GROQ_API_KEY,
    model=Config.GROQ_MODEL,
    policy=Config.GRADING_POLICY
)

# Initialize embedding service
embedding_service = init_embedding_service()

# ===============================
# BACKGROUND CLEANUP
# ===============================
import atexit
from apscheduler.schedulers.background import BackgroundScheduler

def cleanup_old_data():
    """Background cleanup task."""
    try:
        # Cleanup old embeddings
        if embedding_service and embedding_service.is_available():
            deleted = embedding_service.cleanup_old_embeddings(
                days_old=Config.EMBEDDING_CLEANUP_DAYS
            )
            print(f"🧹 Cleaned {deleted} old embeddings")
    except Exception as e:
        print(f"⚠️ Cleanup error: {e}")

# Start scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=cleanup_old_data, trigger="interval", hours=24)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())
print("✅ Background cleanup started")

# ===============================
# REGISTER BLUEPRINTS
# ===============================
from routes.lti_routes import lti_bp
from routes.teacher_routes import teacher_bp
from routes.student_routes import student_bp
from routes.api_routes import api_bp
from routes.grading_routes import grading_bp
from routes.embedding_routes import embedding_bp

app.register_blueprint(lti_bp)
app.register_blueprint(teacher_bp)
app.register_blueprint(student_bp)
app.register_blueprint(api_bp)
app.register_blueprint(grading_bp)
app.register_blueprint(embedding_bp)

# ===============================
# MAIN ROUTES
# ===============================

@app.route('/', methods=['GET'])
def root_redirect():
    """Landing page - redirect to teacher interface."""
    return redirect(url_for('teacher.teacher_generate'))


@app.route('/home')
def home():
    """Home page with navigation links."""
    grading_status = '✅ Enabled' if grading_service and grading_service.is_available() else '❌ Disabled'
    embedding_status = '✅ Enabled' if embedding_service and embedding_service.is_available() else '❌ Disabled'
    
    return f'''
    <html>
    <head>
        <title>AI Quiz Generator</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }}
            .container {{
                background: rgba(255, 255, 255, 0.1);
                padding: 40px;
                border-radius: 20px;
                backdrop-filter: blur(10px);
            }}
            h1 {{
                font-size: 2.5em;
                margin-bottom: 10px;
            }}
            .status {{
                background: rgba(255, 255, 255, 0.2);
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
            }}
            .links {{
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 15px;
                margin-top: 30px;
            }}
            a {{
                background: rgba(255, 255, 255, 0.3);
                color: white;
                text-decoration: none;
                padding: 15px 20px;
                border-radius: 10px;
                text-align: center;
                transition: all 0.3s;
            }}
            a:hover {{
                background: rgba(255, 255, 255, 0.5);
                transform: translateY(-2px);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎓 AI Quiz Generator</h1>
            <p><strong>Status:</strong> ✅ Running</p>
            
            <div class="status">
                <h3>Services Status:</h3>
                <p>🔧 Grading: {grading_status}</p>
                <p>🔍 Embeddings: {embedding_status}</p>
                <p>📊 Background Cleanup: ✅ Active</p>
            </div>
            
            <div class="links">
                <a href="/teacher">👨‍🏫 Teacher Dashboard</a>
                <a href="/student">👨‍🎓 Student Dashboard</a>
                <a href="/lti/launch">🔗 Test LTI Launch</a>
                <a href="/.well-known/jwks.json">🔐 View JWKS</a>
            </div>
        </div>
    </body>
    </html>
    '''


@app.route('/teacher')
def teacher_index():
    """Teacher dashboard - redirect to generation page."""
    return redirect(url_for('teacher.teacher_generate'))


@app.route('/teacher/list')
def list_quizzes():
    """Teacher's list of quizzes."""
    return render_template("list_quizzes.html")


@app.route('/teacher/manual', methods=['GET'])
def teacher_manual():
    """Manual quiz creation page."""
    return render_template('manual_create.html')


@app.route('/teacher/submissions/<quiz_id>', methods=['GET'])
def teacher_submissions(quiz_id):
    """View student submissions for a quiz."""
    from services.db import get_quiz_by_id
    
    quiz_data = get_quiz_by_id(quiz_id)
    if not quiz_data:
        return ("Quiz not found.", 404)
    
    quiz_title = quiz_data.get("title") or quiz_data.get("metadata", {}).get("source_file", f"Quiz #{quiz_id}")
    
    try:
        return render_template(
            'teacher_submissions.html',
            quiz_title=quiz_title,
            quiz_id=quiz_id,
            submissions=[]
        )
    except Exception as e:
        print(f"❌ Error fetching submissions: {e}")
        return ("Failed to load submissions.", 500)


@app.route('/.well-known/jwks.json', methods=['GET'])
def jwks():
    """Public JWKS endpoint for LTI 1.3."""
    from flask import jsonify
    from utils.lti_utils import LTI_JWKS
    return jsonify(LTI_JWKS)


# ===============================
# GLOBAL MEMORY STORE (for subtopic uploads)
# ===============================
# This is used by API routes for temporary storage
_SUBTOPIC_UPLOADS = {}

def get_subtopic_uploads():
    """Get global subtopic uploads store."""
    return _SUBTOPIC_UPLOADS

# Make it available to API routes
app.config['SUBTOPIC_UPLOADS'] = _SUBTOPIC_UPLOADS


# ===============================
# PERIODIC CLEANUP
# ===============================
import random
import time

@app.before_request
def cleanup_before_request():
    """Clean up old uploads before each request (1% probability)."""
    if random.random() < 0.01:  # 1% chance per request
        current_time = time.time()
        to_delete = []
        
        for upload_id, data in _SUBTOPIC_UPLOADS.items():
            upload_time = data.get('timestamp', 0)
            if current_time - upload_time > Config.UPLOAD_CLEANUP_HOURS * 3600:
                to_delete.append(upload_id)
        
        for upload_id in to_delete:
            del _SUBTOPIC_UPLOADS[upload_id]
        
        if to_delete:
            print(f"🧹 Cleaned up {len(to_delete)} old uploads from memory")


# ===============================
# ERROR HANDLERS
# ===============================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return render_template('404.html') if Path('templates/404.html').exists() else ('Page not found', 404)


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    print(f"❌ Internal error: {error}")
    return ('Internal server error', 500)


# ===============================
# RUN APPLICATION
# ===============================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Quiz Generator Application Starting")
    print("=" * 60)
    print(f"📍 Environment: {'Production' if not Config.DEBUG else 'Development'}")
    print(f"🌐 Host: {Config.HOST}:{Config.PORT}")
    print(f"🔧 Debug Mode: {Config.DEBUG}")
    print()
    print("📊 Services Status:")
    print(f"   Grading: {'✅ Enabled' if grading_service and grading_service.is_available() else '❌ Disabled'}")
    print(f"   Embeddings: {'✅ Enabled' if embedding_service and embedding_service.is_available() else '❌ Disabled'}")
    print(f"   Background Cleanup: ✅ Running (every 24 hours)")
    print()
    print("📋 Registered Blueprints:")
    print(f"   • LTI Routes: /lti/*")
    print(f"   • Teacher Routes: /teacher/*")
    print(f"   • Student Routes: /student/*")
    print(f"   • API Routes: /api/*")
    print(f"   • Grading Routes: /api/grades, /api/submissions/*")
    print(f"   • Embedding Routes: /api/questions/*, /api/admin/embeddings/*")
    print("=" * 60)
    print()
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG
    )