"""Configuration module for the Quiz Application."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from multiple possible locations
current_dir = Path(__file__).parent
project_root = current_dir.parent
services_dir = project_root / "services"

# Try to load .env from multiple locations
env_loaded = False
for env_path in [
    project_root / ".env",
    services_dir / ".env",
    current_dir / ".env",
    Path.cwd() / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded environment from: {env_path}")
        env_loaded = True
        break

if not env_loaded:
    print("⚠️ No .env file found. Using environment variables if set.")
    load_dotenv()


class Config:
    """Application configuration class."""
    
    # API Keys
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    
    # Flask Configuration
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev_only_secret_change_me")
    
    # CORS Configuration
    CORS_ORIGINS = "*"
    
    # Application Settings
    HOST = "127.0.0.1"
    PORT = 5000
    DEBUG = True
    
    # Upload Settings
    UPLOAD_FOLDER = "student_uploads"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Grading Settings
    GRADING_POLICY = os.getenv("GRADING_POLICY", "balanced")
    
    # Cleanup Settings
    UPLOAD_CLEANUP_HOURS = 6  # Clean uploads older than 6 hours
    EMBEDDING_CLEANUP_DAYS = 90  # Clean embeddings older than 90 days
    
    @classmethod
    def validate(cls):
        """Validate required configuration."""
        if not cls.GROQ_API_KEY:
            raise RuntimeError("❌ GROQ_API_KEY is missing in environment (.env).")
        print("✅ Configuration validated successfully")
        
    @classmethod
    def get_grader_path(cls):
        """Get path to grader module."""
        return Path(__file__).parent.parent / "quiz grading" / "grader.py"