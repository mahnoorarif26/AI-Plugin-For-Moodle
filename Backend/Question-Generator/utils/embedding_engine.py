from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import pickle
import os

class QuestionEmbeddingEngine:
    """
    Semantic search for existing questions using embeddings.
    Helps teachers avoid duplicate questions and find similar ones.
    """
    
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        """
        Uses a lightweight model (90MB) that works on CPU.
        Fast inference: ~50ms per query
        """
        self.model = SentenceTransformer(model_name)
        self.embeddings_cache = {}
        self.questions_db = []
        self.cache_file = os.path.join(
            os.path.dirname(__file__), 
            '..', 
            'data', 
            'question_embeddings.pkl'
        )
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        
        # Load existing embeddings if available
        self.load_cache()
    
    def add_question(self, question_id: str, question_text: str, metadata: dict):
        """Add a question to the searchable database"""
        if not question_text or not question_text.strip():
            return
        
        # Generate embedding
        embedding = self.model.encode(question_text)
        
        # Check if already exists
        existing = next((q for q in self.questions_db if q['id'] == question_id), None)
        if existing:
            # Update existing
            existing['text'] = question_text
            existing['embedding'] = embedding
            existing['metadata'] = metadata
        else:
            # Add new
            self.questions_db.append({
                'id': question_id,
                'text': question_text,
                'embedding': embedding,
                'metadata': metadata
            })
        
        # Update cache
        self.embeddings_cache[question_id] = embedding
        self.save_cache()
    
    def add_questions_bulk(self, questions: list):
        """Bulk add questions from a quiz"""
        for q in questions:
            q_id = q.get('id', '')
            q_text = q.get('prompt') or q.get('question_text', '')
            metadata = {
                'type': q.get('type'),
                'difficulty': q.get('difficulty'),
                'tags': q.get('tags', []),
                'quiz_id': q.get('quiz_id', '')
            }
            if q_id and q_text:
                self.add_question(q_id, q_text, metadata)
    
    def find_similar_questions(
        self, 
        query_text: str, 
        top_k: int = 5,
        filter_type: str = None,
        min_similarity: float = 0.7,
        exclude_ids: list = None
    ) -> list:
        """
        Find similar questions semantically.
        
        Returns: [
            {
                'question': {...},
                'similarity': 0.85,
                'similarity_percent': 85,
                'reason': 'High semantic overlap'
            }
        ]
        """
        if not self.questions_db or not query_text.strip():
            return []
        
        # Encode query
        query_embedding = self.model.encode(query_text)
        
        # Calculate similarities
        results = []
        for q in self.questions_db:
            # Skip excluded IDs
            if exclude_ids and q['id'] in exclude_ids:
                continue
            
            # Filter by type if specified
            if filter_type and q['metadata'].get('type') != filter_type:
                continue
            
            similarity = cosine_similarity(
                query_embedding.reshape(1, -1),
                q['embedding'].reshape(1, -1)
            )[0][0]
            
            if similarity >= min_similarity:
                results.append({
                    'question': {
                        'id': q['id'],
                        'text': q['text'],
                        'type': q['metadata'].get('type'),
                        'difficulty': q['metadata'].get('difficulty'),
                        'tags': q['metadata'].get('tags', []),
                        'quiz_id': q['metadata'].get('quiz_id')
                    },
                    'similarity': float(similarity),
                    'similarity_percent': round(float(similarity) * 100, 1),
                    'reason': self._get_similarity_reason(similarity)
                })
        
        # Sort by similarity and return top K
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:top_k]
    
    def _get_similarity_reason(self, score: float) -> str:
        """Human-readable similarity explanation"""
        if score > 0.95:
            return "Nearly identical - likely duplicate"
        elif score > 0.85:
            return "Very similar - covers same concept"
        elif score > 0.75:
            return "Moderately similar - related topic"
        else:
            return "Somewhat related"
    
    def get_stats(self) -> dict:
        """Get statistics about the question database"""
        type_counts = {}
        difficulty_counts = {}
        
        for q in self.questions_db:
            # Count by type
            q_type = q['metadata'].get('type', 'unknown')
            type_counts[q_type] = type_counts.get(q_type, 0) + 1
            
            # Count by difficulty
            diff = q['metadata'].get('difficulty', 'unknown')
            difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1
        
        return {
            'total_questions': len(self.questions_db),
            'by_type': type_counts,
            'by_difficulty': difficulty_counts
        }
    
    def save_cache(self):
        """Save embeddings to disk"""
        try:
            with open(self.cache_file, 'wb') as f:
                pickle.dump({
                    'questions_db': self.questions_db,
                    'embeddings_cache': self.embeddings_cache
                }, f)
            print(f"✅ Saved {len(self.questions_db)} questions to cache")
        except Exception as e:
            print(f"⚠️ Failed to save cache: {e}")
    
    def load_cache(self):
        """Load embeddings from disk"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'rb') as f:
                    data = pickle.load(f)
                    self.questions_db = data.get('questions_db', [])
                    self.embeddings_cache = data.get('embeddings_cache', {})
                print(f"✅ Loaded {len(self.questions_db)} questions from cache")
            except Exception as e:
                print(f"⚠️ Failed to load cache: {e}")
                self.questions_db = []
                self.embeddings_cache = {}

# Global instance
question_embedder = QuestionEmbeddingEngine()