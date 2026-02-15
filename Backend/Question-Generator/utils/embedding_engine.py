"""
Firestore-only Embedding Engine - NO LOCAL STORAGE
All embeddings stored directly in Firestore
"""
from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import os

class QuestionEmbeddingEngine:
    """
    Semantic search for existing questions using embeddings.
    Stores ALL embeddings in Firestore - NO local pickle files.
    """
    
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        """
        Initialize with Firestore backend only.
        Uses in-memory cache for performance during session.
        """
        self.model = SentenceTransformer(model_name)
        self.embeddings_cache = {}  # Session-only in-memory cache
        self.questions_db = []      # Session-only in-memory cache
        self._db = None
        
        # Initialize Firestore connection
        self._init_firestore()
        
        # Load embeddings from Firestore into memory for this session
        self.load_from_firestore()
    
    def _init_firestore(self):
        """Initialize Firestore connection"""
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            
            # Get existing app or initialize
            if not firebase_admin._apps:
                cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "./serviceAccountKey.json")
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            
            self._db = firestore.client()
            print("✅ Firestore initialized for embeddings (cloud-only storage)")
        except Exception as e:
            print(f"⚠️ Firestore init failed: {e}")
            self._db = None
    
    def add_question(self, question_id: str, question_text: str, metadata: dict):
        """Add question embedding directly to Firestore"""
        if not question_text or not question_text.strip():
            return
        
        if not self._db:
            print("⚠️ Firestore not available, cannot save embedding")
            return
        
        # Generate embedding
        embedding = self.model.encode(question_text)
        
        # Update in-memory cache for this session
        question_entry = {
            'id': question_id,
            'text': question_text,
            'embedding': embedding,
            'metadata': metadata
        }
        
        # Update or add to session cache
        existing_idx = next((i for i, q in enumerate(self.questions_db) if q['id'] == question_id), None)
        if existing_idx is not None:
            self.questions_db[existing_idx] = question_entry
        else:
            self.questions_db.append(question_entry)
        
        self.embeddings_cache[question_id] = embedding
        
        # Save directly to Firestore (no pickle)
        self._save_to_firestore(question_id, question_text, embedding.tolist(), metadata)
    
    def _save_to_firestore(self, question_id: str, question_text: str, embedding_list: list, metadata: dict):
        """Save single embedding to Firestore"""
        if not self._db:
            return
        
        try:
            doc_data = {
                'question_id': question_id,
                'text': question_text,
                'embedding': embedding_list,
                'metadata': metadata,
                'type': metadata.get('type', 'unknown'),
                'difficulty': metadata.get('difficulty', 'medium'),
                'tags': metadata.get('tags', []),
                'quiz_id': metadata.get('quiz_id', ''),
                'source': metadata.get('source', 'unknown')
            }
            
            self._db.collection('question_embeddings').document(question_id).set(doc_data)
            
        except Exception as e:
            print(f"⚠️ Failed to save embedding to Firestore: {e}")
    
    def add_questions_bulk(self, questions: list):
        """Bulk add questions from a quiz"""
        if not self._db:
            print("⚠️ Firestore not available, cannot save embeddings")
            return 0
        
        success_count = 0
        
        for q in questions:
            q_id = q.get('id', '')
            q_text = q.get('prompt') or q.get('question_text', '')
            metadata = {
                'type': q.get('type'),
                'difficulty': q.get('difficulty'),
                'tags': q.get('tags', []),
                'quiz_id': q.get('quiz_id', ''),
                'source': q.get('source', 'bulk_import')
            }
            
            if q_id and q_text:
                try:
                    self.add_question(q_id, q_text, metadata)
                    success_count += 1
                except Exception as e:
                    print(f"⚠️ Failed to add question {q_id}: {e}")
        
        return success_count
    
    def load_from_firestore(self):
        """Load all embeddings from Firestore into memory at startup"""
        if not self._db:
            print("⚠️ Firestore not available, starting with empty index")
            return
        
        try:
            docs = self._db.collection('question_embeddings').stream()
            
            loaded_count = 0
            for doc in docs:
                data = doc.to_dict()
                
                question_id = data.get('question_id')
                text = data.get('text')
                embedding_list = data.get('embedding')
                metadata = data.get('metadata', {})
                
                if not question_id or not text or not embedding_list:
                    continue
                
                # Convert list back to numpy array
                embedding = np.array(embedding_list)
                
                # Add to in-memory cache
                self.questions_db.append({
                    'id': question_id,
                    'text': text,
                    'embedding': embedding,
                    'metadata': metadata
                })
                
                self.embeddings_cache[question_id] = embedding
                loaded_count += 1
            
            print(f"✅ Loaded {loaded_count} question embeddings from Firestore")
            
        except Exception as e:
            print(f"⚠️ Failed to load embeddings from Firestore: {e}")
    
    def find_similar_questions(
        self, 
        query_text: str, 
        top_k: int = 5,
        filter_type: str = None,
        min_similarity: float = 0.7,
        exclude_ids: list = None
    ) -> list:
        """
        Find similar questions semantically using in-memory index.
        
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
        source_counts = {}
        
        for q in self.questions_db:
            # Count by type
            q_type = q['metadata'].get('type', 'unknown')
            type_counts[q_type] = type_counts.get(q_type, 0) + 1
            
            # Count by difficulty
            diff = q['metadata'].get('difficulty', 'unknown')
            difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1
            
            # Count by source
            source = q['metadata'].get('source', 'unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
        
        return {
            'total_questions': len(self.questions_db),
            'by_type': type_counts,
            'by_difficulty': difficulty_counts,
            'by_source': source_counts,
            'storage': 'Firestore (cloud-only)'
        }
    
    def delete_question(self, question_id: str):
        """Delete a question embedding from Firestore and cache"""
        if not self._db:
            return False
        
        try:
            # Remove from Firestore
            self._db.collection('question_embeddings').document(question_id).delete()
            
            # Remove from in-memory cache
            self.questions_db = [q for q in self.questions_db if q['id'] != question_id]
            if question_id in self.embeddings_cache:
                del self.embeddings_cache[question_id]
            
            print(f"✅ Deleted embedding: {question_id}")
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to delete embedding: {e}")
            return False
    
    def clear_all_embeddings(self):
        """DANGER: Clear all embeddings from Firestore"""
        if not self._db:
            return False
        
        try:
            # Delete all documents in collection
            docs = self._db.collection('question_embeddings').stream()
            batch = self._db.batch()
            count = 0
            
            for doc in docs:
                batch.delete(doc.reference)
                count += 1
                
                # Commit in batches of 500 (Firestore limit)
                if count % 500 == 0:
                    batch.commit()
                    batch = self._db.batch()
            
            # Commit remaining
            if count % 500 != 0:
                batch.commit()
            
            # Clear in-memory cache
            self.questions_db = []
            self.embeddings_cache = {}
            
            print(f"✅ Cleared {count} embeddings from Firestore")
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to clear embeddings: {e}")
            return False


# Global instance - uses Firestore only
question_embedder = QuestionEmbeddingEngine()