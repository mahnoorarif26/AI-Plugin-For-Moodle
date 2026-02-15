"""Embedding routes for question similarity and duplicate prevention."""

from flask import Blueprint, request, jsonify
from services.embedding_service import get_embedding_service

embedding_bp = Blueprint('embedding', __name__)


@embedding_bp.route('/api/questions/similar', methods=['POST'])
def find_similar_questions():
    """
    API endpoint to find similar questions.
    Used when teacher is creating/editing questions.
    """
    embedder = get_embedding_service()
    
    if not embedder or not embedder.is_available():
        return jsonify({'similar': []}), 200
    
    try:
        data = request.get_json()
        query_text = data.get('question_text', '').strip()
        question_type = data.get('type')
        exclude_ids = data.get('exclude_ids', [])
        
        if not query_text:
            return jsonify({'similar': []}), 200
        
        similar = embedder.find_similar_questions(
            query_text=query_text,
            top_k=5,
            filter_type=question_type,
            min_similarity=0.7,
            exclude_ids=exclude_ids
        )
        
        return jsonify({'success': True, 'similar': similar}), 200
        
    except Exception as e:
        print(f"❌ Error in find_similar_questions: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@embedding_bp.route('/api/questions/stats', methods=['GET'])
def get_question_stats():
    """Get statistics about indexed questions."""
    embedder = get_embedding_service()
    
    if not embedder or not embedder.is_available():
        return jsonify({
            'success': True,
            'stats': {'total_questions': 0, 'by_type': {}, 'by_difficulty': {}}
        }), 200
    
    try:
        stats = embedder.get_stats()
        return jsonify({'success': True, 'stats': stats}), 200
    except Exception as e:
        print(f"❌ Error in get_question_stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@embedding_bp.route('/api/questions/check-duplicates', methods=['POST'])
def check_duplicates_in_quiz():
    """Check for duplicates before saving quiz."""
    embedder = get_embedding_service()
    
    if not embedder or not embedder.is_available():
        return jsonify({
            'success': True,
            'has_duplicates': False,
            'duplicate_count': 0,
            'report': []
        }), 200
    
    try:
        data = request.get_json()
        questions = data.get('questions', [])
        duplicates_report = []
        
        for i, q in enumerate(questions):
            question_text = q.get('prompt') or q.get('question_text', '')
            if not question_text:
                continue
            
            similar = embedder.find_similar_questions(
                query_text=question_text,
                top_k=3,
                min_similarity=0.75
            )
            
            if similar:
                duplicates_report.append({
                    'question_index': i,
                    'question_text': question_text[:100],
                    'similar_count': len(similar),
                    'highest_similarity': similar[0]['similarity_percent'],
                    'matches': similar
                })
        
        return jsonify({
            'success': True,
            'has_duplicates': len(duplicates_report) > 0,
            'duplicate_count': len(duplicates_report),
            'report': duplicates_report
        }), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@embedding_bp.route('/api/questions/analytics', methods=['GET'])
def question_analytics():
    """Get analytics about indexed questions."""
    embedder = get_embedding_service()
    
    if not embedder or not embedder.is_available():
        return jsonify({
            'success': True,
            'total_questions': 0,
            'by_type': {},
            'by_difficulty': {},
            'by_source': {}
        }), 200
    
    try:
        stats = embedder.get_stats()
        
        # Get source counts if available
        source_counts = {}
        if hasattr(embedder.embedder, 'questions_db'):
            for q in embedder.embedder.questions_db:
                source = q['metadata'].get('source', 'unknown')
                source_counts[source] = source_counts.get(source, 0) + 1
        
        return jsonify({
            'success': True,
            'total_questions': stats['total_questions'],
            'by_type': stats['by_type'],
            'by_difficulty': stats['by_difficulty'],
            'by_source': source_counts
        }), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@embedding_bp.route('/api/admin/embeddings/stats', methods=['GET'])
def get_embedding_stats():
    """Get embedding statistics (admin endpoint)."""
    embedder = get_embedding_service()
    
    if not embedder or not embedder.is_available():
        return jsonify({
            'success': True,
            'stats': {'total_questions': 0, 'by_type': {}, 'by_difficulty': {}}
        }), 200
    
    try:
        stats = embedder.get_stats()
        return jsonify({'success': True, 'stats': stats}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@embedding_bp.route('/api/admin/embeddings/cleanup', methods=['POST'])
def manual_cleanup_embeddings():
    """Manual cleanup trigger (admin endpoint)."""
    embedder = get_embedding_service()
    
    if not embedder or not embedder.is_available():
        return jsonify({'error': 'Embedding service not available'}), 503
    
    try:
        data = request.get_json() or {}
        days_old = int(data.get('days_old', 90))
        deleted = embedder.cleanup_old_embeddings(days_old=days_old)
        
        return jsonify({
            'success': True,
            'deleted': deleted,
            'message': f'Cleaned {deleted} embeddings'
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500