"""Duplicate Prevention for Quiz Generation"""
from typing import List, Dict, Any
from utils.embedding_engine import question_embedder

def get_existing_questions_context(
    topic_keywords: List[str],
    question_type: str = None,
    max_results: int = 10
) -> str:
    """
    Fetch existing questions and format them for LLM prompt.
    Returns a string to insert into the generation prompt.
    """
    try:
        search_query = " ".join(topic_keywords[:3])
        
        similar = question_embedder.find_similar_questions(
            query_text=search_query,
            top_k=max_results,
            filter_type=question_type,
            min_similarity=0.6  # Lower threshold to catch more
        )
        
        if not similar:
            return ""
        
        # Format for LLM
        context = "\n\n" + "="*60 + "\n"
        context += "⚠️ EXISTING QUESTIONS - AVOID DUPLICATES\n"
        context += "="*60 + "\n\n"
        context += f"Database contains {len(similar)} similar questions.\n"
        context += "Generate questions that:\n"
        context += "• Cover DIFFERENT aspects\n"
        context += "• Use DIFFERENT wording\n"
        context += "• Test DIFFERENT concepts\n\n"
        
        for i, item in enumerate(similar, 1):
            q = item['question']
            context += f"{i}. [{q['type'].upper()}] {q['text'][:150]}...\n"
        
        context += "\n" + "="*60 + "\n"
        context += "Make your questions substantially different!\n"
        context += "="*60 + "\n\n"
        
        return context
    except Exception as e:
        print(f"⚠️ Duplicate prevention error: {e}")
        return ""