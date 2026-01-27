# utils/assignment_utils.py
import json
from groq import Groq

ASSIGNMENT_SYSTEM_PROMPT = """You are an expert educational assessment designer specializing in creating diverse, challenging assignment questions.

Generate assignment questions that test different cognitive levels:
- Conceptual: Deep understanding of theories and principles
- Scenario-based: Real-world application and problem-solving (include code-based solutions when applicable)
- Research-based: Investigation, analysis, and critical thinking
- Project-based: Practical implementation and creative solutions
- Case Study: Analysis of complex situations (include technical/code problems when applicable)
- Comparative Analysis: Comparing and contrasting concepts

Each question should:
1. Be clear and well-structured
2. Have appropriate complexity for the topic
3. Include grading criteria that guide assessment
4. Specify expected word count/scope
5. Encourage critical thinking and application
6. For technical topics: Include code snippets, algorithms, or system design problems where relevant

IMPORTANT FOR SCENARIO-BASED & CASE STUDY QUESTIONS:
- When the topic is technical (programming, algorithms, data structures, software engineering, etc.):
  * Include actual code snippets or pseudocode in the problem statement
  * Present realistic debugging scenarios or optimization challenges
  * Include system design problems with architectural considerations
  * Provide specific technical constraints (time/space complexity, scalability, etc.)
  
- When the topic is non-technical (business, humanities, social sciences, etc.):
  * Focus on real-world decision-making scenarios
  * Include stakeholder perspectives and constraints
  * Present ethical dilemmas or strategic challenges

Return JSON with this exact structure:
{
  "questions": [
    {
      "id": "unique_id",
      "type": "assignment_task",
      "assignment_type": "conceptual|scenario|research|project|case_study|comparative",
      "prompt": "The detailed question/task",
      "context": "Background information if needed (include code snippets here for technical topics)",
      "code_snippet": "Optional: actual code that needs to be analyzed/debugged/optimized",
      "requirements": ["requirement 1", "requirement 2"],
      "grading_criteria": "How to evaluate the response",
      "marks": 10,
      "word_count": "500-750 words",
      "difficulty": "medium",
      "learning_objectives": ["objective 1", "objective 2"],
      "deliverables": ["Optional: specific outputs expected like 'corrected code', 'UML diagram', etc."]
    }
  ]
}"""


def generate_advanced_assignments_llm(
    full_text: str,
    chosen_subtopics: list,
    task_distribution: dict,
    api_key: str,
    difficulty: str = "auto"
):
    """
    Generate diverse assignment tasks based on subtopics.
    
    Args:
        full_text: Source material text
        chosen_subtopics: List of selected subtopics
        task_distribution: Dict like {
            "conceptual": 2,
            "scenario": 2,
            "research": 1,
            "project": 1,
            "case_study": 1,
            "comparative": 1
        }
        api_key: Groq API key
        difficulty: "auto", "easy", "medium", "hard"
    """
    
    client = Groq(api_key=api_key)
    
    # Build detailed prompt
    total_tasks = sum(task_distribution.values())
    
    # Detect if topics are technical
    technical_keywords = [
        'programming', 'code', 'algorithm', 'data structure', 'software', 
        'python', 'java', 'javascript', 'c++', 'database', 'sql', 'api',
        'framework', 'library', 'function', 'class', 'object', 'array',
        'sorting', 'searching', 'tree', 'graph', 'network', 'system design',
        'optimization', 'complexity', 'debugging', 'testing', 'web development',
        'machine learning', 'artificial intelligence', 'neural network'
    ]
    
    content_lower = full_text.lower()
    topics_lower = ' '.join(chosen_subtopics).lower()
    is_technical = any(keyword in content_lower or keyword in topics_lower for keyword in technical_keywords)
    
    user_prompt = f"""Based on the following educational content, generate {total_tasks} assignment tasks.

CONTENT:
{full_text[:15000]}

SELECTED TOPICS:
{', '.join(chosen_subtopics)}

CONTENT TYPE: {'TECHNICAL/PROGRAMMING' if is_technical else 'GENERAL/NON-TECHNICAL'}

TASK DISTRIBUTION:
"""
    
    for task_type, count in task_distribution.items():
        if count > 0:
            user_prompt += f"- {count} {task_type.replace('_', ' ').title()} question(s)\n"
    
    # Build the technical-specific instructions
    tech_scenario_example = 'Example: "You are reviewing a colleague\'s code for a user authentication system. The code below has a critical security flaw. Identify the vulnerability, explain why it\'s dangerous, and provide a corrected implementation."'
    general_scenario_example = 'Example: "You are a consultant hired by Company X facing declining market share. Analyze the situation and propose a comprehensive turnaround strategy."'
    
    tech_project_example = 'Example: "Design and implement a RESTful API for a library management system. Include: (1) API endpoint documentation, (2) Database schema, (3) Sample code for at least 3 endpoints, (4) Error handling strategy."'
    general_project_example = 'Example: "Develop a comprehensive marketing campaign for a new sustainable product line. Include market research, target audience analysis, and budget allocation."'
    
    tech_case_example = 'Example: "A startup\'s e-commerce platform is experiencing severe performance degradation during peak hours. Analyze the system architecture below, identify bottlenecks, and propose specific optimizations with code examples."'
    general_case_example = 'Example: "Analyze Amazon\'s decision to enter the grocery market with Amazon Fresh. Evaluate the strategic rationale, competitive positioning, and outcomes."'
    
    # Build the examples section separately
    examples_section = f"""
DIFFICULTY LEVEL: {difficulty}

TASK TYPE DEFINITIONS:

1. CONCEPTUAL: Questions that test deep understanding of theories, principles, and fundamental concepts.
   Example: "Explain the underlying principles of binary search trees and discuss how they maintain O(log n) search complexity."

2. SCENARIO-BASED: Real-world situations requiring application of knowledge.
   
   {'FOR TECHNICAL TOPICS - Include code-based problems:' if is_technical else 'FOR NON-TECHNICAL TOPICS:'}
   {tech_scenario_example if is_technical else general_scenario_example}
   
   {'MUST include actual code snippets that need debugging, optimization, or refactoring.' if is_technical else 'Focus on strategic decision-making with multiple stakeholders.'}

3. RESEARCH-BASED: Tasks requiring investigation, literature review, or data analysis.
   Example: "Conduct a comparative analysis of sorting algorithms (QuickSort, MergeSort, HeapSort) using at least 5 peer-reviewed sources. Include time/space complexity analysis and practical use cases."

4. PROJECT-BASED: Practical implementation tasks with deliverables.
   {tech_project_example if is_technical else general_project_example}

5. CASE STUDY: Analysis of complex real or hypothetical situations.
   
   {'FOR TECHNICAL TOPICS - Include problematic code or system designs:' if is_technical else 'FOR NON-TECHNICAL TOPICS:'}
   {tech_case_example if is_technical else general_case_example}

6. COMPARATIVE ANALYSIS: Comparing multiple concepts, approaches, or solutions.
   Example: "Compare and contrast SQL vs NoSQL databases. Discuss use cases, performance characteristics, scalability, and provide code examples demonstrating when to use each."

"""
    
    user_prompt += examples_section
    
    # Add technical-specific requirements if applicable
    if is_technical:
        user_prompt += """
CRITICAL FOR SCENARIO & CASE STUDY QUESTIONS IN TECHNICAL CONTENT:
- Include actual code snippets (buggy code, inefficient algorithms, poorly designed classes)
- Specify technical constraints (memory limits, API rate limits, database query optimization)
- Request specific deliverables (corrected code, UML diagrams, performance benchmarks)
- Use realistic technical scenarios (authentication bugs, race conditions, API design flaws)

"""
    
    # Add JSON formatting instructions (without backslashes in f-string)
    json_instructions = """
CRITICAL JSON FORMATTING REQUIREMENTS:

1. The code_snippet field MUST be a plain string. Do NOT include markdown code blocks (```).
2. Escape special JSON characters properly in code_snippet:
   - Use \\" for double quotes inside strings
   - Use \\n for new lines
   - Use \\\\ for backslashes
3. Example of proper code_snippet formatting:
   "code_snippet": "import numpy as np\\n\\nclass NeuralNetwork:\\n    def __init__(self):\\n        self.training_data = []\\n\\n    def add_training_data(self, data):\\n        self.training_data.append(data)\\n\\n    def train(self):\\n        for data in self.training_data:\\n            # training logic\\n            pass"
4. Do NOT include any markdown formatting in JSON fields.
5. Ensure all string fields are properly escaped for JSON.

Generate questions that:
- Are specific and well-defined
- Include clear grading criteria
- Specify scope and expectations  
- Encourage critical thinking
- Are appropriate for the difficulty level
"""
    
    user_prompt += json_instructions
    
    if is_technical:
        user_prompt += """- Include code snippets in "code_snippet" field when presenting technical problems
- Specify concrete deliverables in the "deliverables" field
"""
    
    user_prompt += "\nReturn ONLY valid JSON, no other text."

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": ASSIGNMENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=4000,
            response_format={"type": "json_object"}
        )
        
        response_text = completion.choices[0].message.content
        print(f"DEBUG - Raw LLM response length: {len(response_text)} chars")
        
        # Try to clean the response before parsing
        cleaned_response = response_text.strip()
        
        # Remove markdown code blocks if present
        if cleaned_response.startswith('```json'):
            cleaned_response = cleaned_response[7:]  # Remove '```json'
        if cleaned_response.startswith('```'):
            cleaned_response = cleaned_response[3:]  # Remove '```'
        if cleaned_response.endswith('```'):
            cleaned_response = cleaned_response[:-3]  # Remove trailing '```'
        
        # Try to parse JSON
        try:
            data = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            print(f"Cleaned response sample: {cleaned_response[:500]}")
            
            # Try one more cleanup - look for JSON object
            import re
            json_match = re.search(r'\{.*\}', cleaned_response, re.DOTALL)
            if json_match:
                cleaned_response = json_match.group(0)
                data = json.loads(cleaned_response)
            else:
                raise e
        
        # Validate and enhance questions
        questions = data.get("questions", [])
        
        if not questions:
            return {
                "success": False,
                "error": "No questions generated by LLM",
                "questions": []
            }
        
        # Clean and validate each question
        cleaned_questions = []
        for i, q in enumerate(questions):
            # Ensure all required fields exist
            if "id" not in q:
                q["id"] = f"assign_{i+1}"
            if "type" not in q:
                q["type"] = "assignment_task"
            if "assignment_type" not in q:
                q["assignment_type"] = "conceptual"  # Default
            if "marks" not in q:
                q["marks"] = 10
            if "difficulty" not in q:
                q["difficulty"] = difficulty if difficulty != "auto" else "medium"
            if "requirements" not in q:
                q["requirements"] = []
            if "learning_objectives" not in q:
                q["learning_objectives"] = []
            if "deliverables" not in q:
                q["deliverables"] = []
            if "word_count" not in q:
                q["word_count"] = "500-750 words"
            
            # Clean the code_snippet field if it exists
            if "code_snippet" in q and q["code_snippet"]:
                code = str(q["code_snippet"])
                # Remove markdown code blocks
                if code.startswith('```'):
                    lines = code.split('\n')
                    if len(lines) > 1:
                        # Remove first line (```python or similar) and last line (```)
                        code = '\n'.join(lines[1:-1])
                    else:
                        code = code.replace('```', '')
                
                # Clean up
                code = code.strip()
                # Replace escaped newlines with actual newlines for storage
                code = code.replace('\\n', '\n')
                q["code_snippet"] = code
            
            # Clean other string fields
            for field in ["prompt", "context", "grading_criteria"]:
                if field in q and q[field]:
                    q[field] = str(q[field]).strip()
            
            cleaned_questions.append(q)
        
        return {
            "success": True,
            "questions": cleaned_questions,
            "metadata": {
                "total_tasks": len(cleaned_questions),
                "task_distribution": task_distribution,
                "difficulty": difficulty,
                "is_technical": is_technical
            }
        }
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        print(f"Problematic response (first 1000 chars): {response_text[:1000] if 'response_text' in locals() else 'No response'}")
        return {
            "success": False,
            "error": f"Failed to parse LLM response as JSON: {str(e)}",
            "raw_response": response_text[:1000] if 'response_text' in locals() else None,
            "questions": []
        }
    except Exception as e:
        print(f"Error generating assignments: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "questions": []
        }