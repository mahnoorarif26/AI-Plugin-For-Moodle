from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import os
import time
from typing import List, Dict, Any, Optional
from collections import OrderedDict
from datetime import datetime, timedelta

# Firestore imports
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    FIRESTORE_AVAILABLE = False
    print("⚠️ firebase-admin not installed. Install with: pip install firebase-admin")

from dotenv import load_dotenv
load_dotenv()


class FirestoreQuestionEmbedder:
    """
    Cloud-based semantic search using Firestore.
    
    Benefits:
    - No local storage needed
    - Scales automatically
    - Accessible from multiple servers
    - Automatic cleanup possible
    """
    
    def __init__(self, model_name='all-MiniLM-L6-v2', max_cache_size=100):
        """
        Initialize the embedding engine
        
        Args:
            model_name: SentenceTransformer model (lightweight, works on CPU)
            max_cache_size: Number of embeddings to keep in memory (LRU cache)
        """
        print("🔄 Initializing Firestore Embedding Engine...")
        
        # Load the embedding model
        self.model = SentenceTransformer(model_name)
        print(f"✅ Loaded embedding model: {model_name}")
        
        # Initialize Firestore connection
        self.db = None
        self._init_firestore()
        
        # LRU cache to avoid re-computing embeddings frequently
        self._cache = OrderedDict()
        self.max_cache_size = max_cache_size
        
        # Performance tracking
        self._stats = {
            'total_indexed': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'search_count': 0
        }
    
    def _init_firestore(self):
        """Initialize Firestore database connection"""
        if not FIRESTORE_AVAILABLE:
            print("❌ Firestore not available - firebase-admin not installed")
            return
        
        try:
            # Check if already initialized
            if firebase_admin._apps:
                self.db = firestore.client()
                print("✅ Using existing Firestore connection")
                return
            
            # Initialize new connection
            cred_path = os.getenv(
                "FIREBASE_SERVICE_ACCOUNT_PATH", 
                "./serviceAccountKey.json"
            )
            
            if not os.path.exists(cred_path):
                print(f"❌ Firebase credentials not found at: {cred_path}")
                print("   Please set FIREBASE_SERVICE_ACCOUNT_PATH in .env")
                return
            
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            
            print("✅ Firestore initialized successfully")
            
            # Create indexes (run once)
            self._ensure_indexes()
            
        except Exception as e:
            print(f"❌ Firestore initialization failed: {e}")
            print("   Falling back to in-memory storage")
            self.db = None
    
    def _ensure_indexes(self):
        """
        Ensure Firestore indexes exist for efficient queries.
        
        Note: Composite indexes must be created in Firebase Console:
        Collection: question_embeddings
        Fields: metadata.type (Ascending), created_at (Descending)
        """
        # Firestore indexes are created automatically for single-field queries
        # Composite indexes need to be created via Firebase Console
        pass
    
    def add_question(
        self, 
        question_id: str, 
        question_text: str, 
        metadata: dict
    ) -> bool:
        """
        Add a question to Firestore with its embedding
        
        Args:
            question_id: Unique identifier (e.g., "quiz_123_q1")
            question_text: The actual question text
            metadata: Dict with type, difficulty, tags, quiz_id, source
        
        Returns:
            bool: Success status
        """
        if not self.db:
            print("⚠️ Firestore not available, skipping indexing")
            return False
        
        if not question_text or not question_text.strip():
            print(f"⚠️ Empty question text for {question_id}, skipping")
            return False
        
        try:
            # Generate embedding vector
            embedding = self.model.encode(question_text)
            
            # Prepare document data
            doc_data = {
                'question_id': question_id,
                'text': question_text[:1000],  # Limit text length to save space
                'embedding': embedding.tolist(),  # Convert numpy array to list
                'metadata': {
                    'type': metadata.get('type', 'unknown'),
                    'difficulty': metadata.get('difficulty', 'medium'),
                    'tags': metadata.get('tags', []),
                    'quiz_id': metadata.get('quiz_id', ''),
                    'source': metadata.get('source', 'unknown'),
                    'has_code': metadata.get('has_code', False)
                },
                'created_at': firestore.SERVER_TIMESTAMP,
                'updated_at': firestore.SERVER_TIMESTAMP
            }
            
            # Store in Firestore
            doc_ref = self.db.collection('question_embeddings').document(question_id)
            doc_ref.set(doc_data, merge=True)
            
            # Update local cache
            self._update_cache(question_id, embedding)
            
            # Update stats
            self._stats['total_indexed'] += 1
            
            if self._stats['total_indexed'] % 10 == 0:
                print(f"✅ Indexed {self._stats['total_indexed']} questions")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to index question {question_id}: {e}")
            return False
    
    def add_questions_bulk(self, questions: List[Dict[str, Any]]) -> int:
        """
        Bulk add questions (more efficient than individual adds)
        
        Args:
            questions: List of dicts with 'id', 'text', and metadata
        
        Returns:
            int: Number of questions successfully indexed
        """
        if not self.db:
            return 0
        
        success_count = 0
        batch = self.db.batch()
        batch_size = 0
        max_batch_size = 500  # Firestore limit
        
        print(f"🔄 Bulk indexing {len(questions)} questions...")
        
        for q in questions:
            q_id = q.get('id', '')
            q_text = q.get('text', '') or q.get('prompt', '')
            
            if not q_id or not q_text:
                continue
            
            try:
                # Generate embedding
                embedding = self.model.encode(q_text)
                
                # Prepare document
                doc_data = {
                    'question_id': q_id,
                    'text': q_text[:1000],
                    'embedding': embedding.tolist(),
                    'metadata': q.get('metadata', {}),
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'updated_at': firestore.SERVER_TIMESTAMP
                }
                
                # Add to batch
                doc_ref = self.db.collection('question_embeddings').document(q_id)
                batch.set(doc_ref, doc_data, merge=True)
                batch_size += 1
                
                # Commit batch if reaching limit
                if batch_size >= max_batch_size:
                    batch.commit()
                    success_count += batch_size
                    batch = self.db.batch()
                    batch_size = 0
                    print(f"  ✅ Committed batch ({success_count} total)")
                
            except Exception as e:
                print(f"  ⚠️ Failed to add {q_id}: {e}")
        
        # Commit remaining
        if batch_size > 0:
            batch.commit()
            success_count += batch_size
        
        print(f"✅ Bulk indexing complete: {success_count}/{len(questions)} questions")
        return success_count
    
    def _update_cache(self, key: str, value: np.ndarray):
        """Update LRU cache"""
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            self._cache[key] = value
        
        # Evict oldest if over limit
        while len(self._cache) > self.max_cache_size:
            self._cache.popitem(last=False)
    
    def find_similar_questions(
        self, 
        query_text: str, 
        top_k: int = 5,
        filter_type: str = None,
        min_similarity: float = 0.7,
        exclude_ids: list = None
    ) -> List[Dict[str, Any]]:
        """
        Find semantically similar questions
        
        Args:
            query_text: Question text to search for
            top_k: Number of results to return
            filter_type: Optional question type filter (mcq, short, etc.)
            min_similarity: Minimum similarity threshold (0-1)
            exclude_ids: List of question IDs to exclude
        
        Returns:
            List of similar questions with similarity scores
        """
        if not self.db or not query_text.strip():
            return []
        
        self._stats['search_count'] += 1
        
        try:
            # Encode the query
            query_embedding = self.model.encode(query_text)
            
            # Fetch questions from Firestore (with pagination)
            collection_ref = self.db.collection('question_embeddings')
            
            # Apply type filter if specified
            if filter_type:
                collection_ref = collection_ref.where('metadata.type', '==', filter_type)
            
            # Process in batches to avoid memory issues
            batch_size = 200
            all_results = []
            last_doc = None
            
            print(f"🔍 Searching for similar questions (filter_type={filter_type})...")
            
            while True:
                # Build query
                query = collection_ref.limit(batch_size)
                if last_doc:
                    query = query.start_after(last_doc)
                
                # Execute query
                docs = list(query.stream())
                
                if not docs:
                    break
                
                # Process batch
                for doc in docs:
                    data = doc.to_dict()
                    q_id = data.get('question_id')
                    
                    # Skip excluded IDs
                    if exclude_ids and q_id in exclude_ids:
                        continue
                    
                    # Get stored embedding
                    stored_embedding = data.get('embedding', [])
                    if not stored_embedding:
                        continue
                    
                    stored_embedding = np.array(stored_embedding)
                    
                    # Calculate cosine similarity
                    similarity = cosine_similarity(
                        query_embedding.reshape(1, -1),
                        stored_embedding.reshape(1, -1)
                    )[0][0]
                    
                    # Filter by threshold
                    if similarity >= min_similarity:
                        all_results.append({
                            'question': {
                                'id': q_id,
                                'text': data.get('text', ''),
                                'type': data.get('metadata', {}).get('type'),
                                'difficulty': data.get('metadata', {}).get('difficulty'),
                                'tags': data.get('metadata', {}).get('tags', []),
                                'quiz_id': data.get('metadata', {}).get('quiz_id')
                            },
                            'similarity': float(similarity),
                            'similarity_percent': round(float(similarity) * 100, 1),
                            'reason': self._get_similarity_reason(similarity)
                        })
                
                # Check if more pages exist
                if len(docs) < batch_size:
                    break
                
                last_doc = docs[-1]
            
            # Sort by similarity and return top K
            all_results.sort(key=lambda x: x['similarity'], reverse=True)
            
            print(f"  ✅ Found {len(all_results)} matches (returning top {top_k})")
            
            return all_results[:top_k]
            
        except Exception as e:
            print(f"❌ Similarity search failed: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _get_similarity_reason(self, score: float) -> str:
        """Generate human-readable similarity explanation"""
        if score > 0.95:
            return "Nearly identical - likely duplicate"
        elif score > 0.85:
            return "Very similar - covers same concept"
        elif score > 0.75:
            return "Moderately similar - related topic"
        else:
            return "Somewhat related"
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about indexed questions
        
        Returns:
            Dict with total count, type breakdown, difficulty breakdown
        """
        if not self.db:
            return {
                'total_questions': 0,
                'by_type': {},
                'by_difficulty': {},
                'performance': self._stats
            }
        
        try:
            # Query all documents (with limit for safety)
            docs = self.db.collection('question_embeddings').limit(10000).stream()
            
            type_counts = {}
            difficulty_counts = {}
            source_counts = {}
            total = 0
            
            for doc in docs:
                total += 1
                data = doc.to_dict()
                metadata = data.get('metadata', {})
                
                # Count by type
                q_type = metadata.get('type', 'unknown')
                type_counts[q_type] = type_counts.get(q_type, 0) + 1
                
                # Count by difficulty
                difficulty = metadata.get('difficulty', 'unknown')
                difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
                
                # Count by source
                source = metadata.get('source', 'unknown')
                source_counts[source] = source_counts.get(source, 0) + 1
            
            return {
                'total_questions': total,
                'by_type': type_counts,
                'by_difficulty': difficulty_counts,
                'by_source': source_counts,
                'performance': self._stats
            }
            
        except Exception as e:
            print(f"❌ Stats query failed: {e}")
            return {
                'total_questions': 0,
                'by_type': {},
                'by_difficulty': {},
                'error': str(e)
            }
    
    def cleanup_old_embeddings(self, days_old: int = 90) -> int:
        """
        Delete embeddings older than specified days
        Prevents unlimited database growth
        
        Args:
            days_old: Delete embeddings older than this many days
        
        Returns:
            int: Number of embeddings deleted
        """
        if not self.db:
            return 0
        
        try:
            cutoff = datetime.now() - timedelta(days=days_old)
            
            print(f"🧹 Cleaning embeddings older than {days_old} days...")
            
            # Query old documents
            old_docs = self.db.collection('question_embeddings')\
                .where('created_at', '<', cutoff)\
                .stream()
            
            # Delete in batches
            batch = self.db.batch()
            batch_count = 0
            deleted = 0
            
            for doc in old_docs:
                batch.delete(doc.reference)
                batch_count += 1
                deleted += 1
                
                # Commit batch every 500 deletes (Firestore limit)
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0
                    print(f"  🧹 Deleted {deleted} old embeddings...")
            
            # Commit remaining
            if batch_count > 0:
                batch.commit()
            
            print(f"✅ Cleanup complete: {deleted} embeddings deleted")
            return deleted
            
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")
            return 0
    
    def delete_question(self, question_id: str) -> bool:
        """Delete a specific question embedding"""
        if not self.db:
            return False
        
        try:
            self.db.collection('question_embeddings').document(question_id).delete()
            
            # Remove from cache
            if question_id in self._cache:
                del self._cache[question_id]
            
            return True
        except Exception as e:
            print(f"❌ Failed to delete {question_id}: {e}")
            return False
    
    def update_question(
        self, 
        question_id: str, 
        question_text: str = None,
        metadata: dict = None
    ) -> bool:
        """
        Update an existing question
        
        Args:
            question_id: Question to update
            question_text: New text (will regenerate embedding)
            metadata: Updated metadata
        
        Returns:
            bool: Success status
        """
        if not self.db:
            return False
        
        try:
            doc_ref = self.db.collection('question_embeddings').document(question_id)
            
            update_data = {
                'updated_at': firestore.SERVER_TIMESTAMP
            }
            
            # Update text and regenerate embedding
            if question_text:
                embedding = self.model.encode(question_text)
                update_data['text'] = question_text[:1000]
                update_data['embedding'] = embedding.tolist()
                self._update_cache(question_id, embedding)
            
            # Update metadata
            if metadata:
                update_data['metadata'] = metadata
            
            doc_ref.update(update_data)
            return True
            
        except Exception as e:
            print(f"❌ Failed to update {question_id}: {e}")
            return False


# Global singleton instance
firestore_embedder = FirestoreQuestionEmbedder()


# ============= MIGRATION HELPER =============

def migrate_from_pickle_to_firestore(pickle_file_path: str) -> int:
    """
    One-time migration script to move embeddings from local pickle to Firestore
    
    Args:
        pickle_file_path: Path to the old question_embeddings.pkl file
    
    Returns:
        int: Number of questions migrated
    """
    import pickle
    
    if not os.path.exists(pickle_file_path):
        print(f"❌ Pickle file not found: {pickle_file_path}")
        return 0
    
    try:
        # Load old pickle data
        with open(pickle_file_path, 'rb') as f:
            old_data = pickle.load(f)
        
        questions_db = old_data.get('questions_db', [])
        
        print(f"🔄 Migrating {len(questions_db)} questions from pickle to Firestore...")
        
        # Prepare for bulk insert
        questions_to_add = []
        for q in questions_db:
            questions_to_add.append({
                'id': q.get('id'),
                'text': q.get('text'),
                'metadata': q.get('metadata', {})
            })
        
        # Bulk add to Firestore
        migrated = firestore_embedder.add_questions_bulk(questions_to_add)
        
        print(f"✅ Migration complete: {migrated} questions moved to Firestore")
        
        # Optional: Rename old pickle file as backup
        backup_path = pickle_file_path + '.backup'
        os.rename(pickle_file_path, backup_path)
        print(f"📦 Old pickle file backed up to: {backup_path}")
        
        return migrated
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 0