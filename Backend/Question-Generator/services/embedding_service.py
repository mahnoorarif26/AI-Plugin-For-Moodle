"""Embedding service for question similarity and duplicate prevention."""

from typing import Optional

# Import the embedding engine
try:
    from utils.embedding_engine_firestore import firestore_embedder as question_embedder
    EMBEDDER_TYPE = "firestore"
except ImportError:
    try:
        from utils.embedding_engine import question_embedder
        EMBEDDER_TYPE = "local"
    except ImportError:
        question_embedder = None
        EMBEDDER_TYPE = "none"

# Import duplicate prevention utility
try:
    from utils.duplicate_prevention import get_existing_questions_context
except ImportError:
    def get_existing_questions_context(topic_keywords, max_results=15):
        """Fallback if duplicate_prevention module not available."""
        return ""


class EmbeddingService:
    """Service for managing question embeddings and similarity search."""
    
    def __init__(self):
        """Initialize embedding service."""
        self.embedder = question_embedder
        self.type = EMBEDDER_TYPE
        
        if self.embedder:
            print(f"✅ Embedding service initialized ({self.type})")
        else:
            print("⚠️ Embedding service not available")
    
    def is_available(self) -> bool:
        """Check if embedding service is available."""
        return self.embedder is not None
    
    def add_question(self, question_id: str, question_text: str, metadata: dict):
        """
        Add a question to the embedding index.
        
        Args:
            question_id: Unique question identifier
            question_text: Question text
            metadata: Question metadata
        """
        if not self.is_available():
            return
        
        try:
            self.embedder.add_question(
                question_id=question_id,
                question_text=question_text,
                metadata=metadata
            )
        except Exception as e:
            print(f"⚠️ Failed to add question to embeddings: {e}")
    
    def find_similar_questions(self, query_text: str, top_k: int = 5, 
                              filter_type: str = None, min_similarity: float = 0.7,
                              exclude_ids: list = None):
        """
        Find similar questions.
        
        Args:
            query_text: Question text to search for
            top_k: Number of results to return
            filter_type: Filter by question type
            min_similarity: Minimum similarity threshold
            exclude_ids: Question IDs to exclude
            
        Returns:
            List of similar questions
        """
        if not self.is_available():
            return []
        
        try:
            return self.embedder.find_similar_questions(
                query_text=query_text,
                top_k=top_k,
                filter_type=filter_type,
                min_similarity=min_similarity,
                exclude_ids=exclude_ids or []
            )
        except Exception as e:
            print(f"⚠️ Failed to find similar questions: {e}")
            return []
    
    def get_stats(self):
        """Get embedding statistics."""
        if not self.is_available():
            return {"total_questions": 0, "by_type": {}, "by_difficulty": {}}
        
        try:
            return self.embedder.get_stats()
        except Exception as e:
            print(f"⚠️ Failed to get stats: {e}")
            return {"total_questions": 0, "by_type": {}, "by_difficulty": {}}
    
    def cleanup_old_embeddings(self, days_old: int = 90):
        """
        Clean up old embeddings.
        
        Args:
            days_old: Delete embeddings older than this many days
            
        Returns:
            Number of deleted embeddings
        """
        if not self.is_available():
            return 0
        
        try:
            return self.embedder.cleanup_old_embeddings(days_old=days_old)
        except Exception as e:
            print(f"⚠️ Cleanup failed: {e}")
            return 0
    
    def get_existing_context(self, topic_keywords: list, max_results: int = 15) -> str:
        """
        Get context from existing questions to prevent duplicates.
        
        Args:
            topic_keywords: Keywords to search for
            max_results: Maximum number of results
            
        Returns:
            Context string with existing questions
        """
        try:
            return get_existing_questions_context(
                topic_keywords=topic_keywords,
                max_results=max_results
            )
        except Exception as e:
            print(f"⚠️ Failed to get existing context: {e}")
            return ""
    
    def index_quiz_questions(self, quiz_id: str, questions: list, source: str = "quiz"):
        """
        Index all questions from a quiz.
        
        Args:
            quiz_id: Quiz identifier
            questions: List of questions
            source: Source identifier
        """
        if not self.is_available():
            return
        
        try:
            for q in questions:
                question_text = q.get('prompt', '')
                if q.get('context'):
                    question_text = f"{question_text} [Context: {q.get('context')[:100]}]"
                
                self.add_question(
                    question_id=f"{quiz_id}_{q.get('id', '')}",
                    question_text=question_text,
                    metadata={
                        'type': q.get('type'),
                        'difficulty': q.get('difficulty'),
                        'tags': q.get('tags', []),
                        'quiz_id': quiz_id,
                        'source': source,
                        'has_code': bool(q.get('code_snippet'))
                    }
                )
            print(f"✅ Indexed {len(questions)} questions from {source}")
        except Exception as e:
            print(f"⚠️ Indexing failed: {e}")


# Global embedding service instance
embedding_service: Optional[EmbeddingService] = None


def init_embedding_service():
    """Initialize global embedding service."""
    global embedding_service
    embedding_service = EmbeddingService()
    return embedding_service


def get_embedding_service() -> Optional[EmbeddingService]:
    """Get global embedding service instance."""
    return embedding_service