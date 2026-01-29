# utils/assignment_utils.py
import json
import re
from groq import Groq

ASSIGNMENT_SYSTEM_PROMPT = """You are an expert educational assessment designer specializing in creating diverse, challenging assignment questions.

Generate assignment questions that test different cognitive levels:
- Conceptual: Deep understanding of theories and principles
- Scenario-based: Real-world application and problem-solving (can be code-based OR decision-based)
- Research-based: Investigation, analysis, and critical thinking
- Project-based: Practical implementation and creative solutions
- Case Study: Analysis of complex situations (can be technical OR business/strategic)
- Comparative Analysis: Comparing and contrasting concepts

Each question should:
1. Be clear and well-structured
2. Have appropriate complexity for the topic
3. Include grading criteria that guide assessment
4. Specify expected word count/scope
5. Encourage critical thinking and application
6. Match the requested scenario style (code-based vs decision-based)

IMPORTANT - SCENARIO STYLES:
When scenario_style is "code_based":
  * Include actual code snippets or pseudocode
  * Present debugging scenarios or optimization challenges
  * Include system design problems
  * Provide technical constraints

When scenario_style is "decision_based":
  * Focus on strategic decision-making
  * Include stakeholder perspectives
  * Present ethical dilemmas or business challenges
  * ABSOLUTELY NO code anywhere (no code, no pseudocode, no syntax, no function names)
  * Do not include backticks, code formatting, or code-like blocks in ANY field (prompt/context/requirements/deliverables/grading_criteria)

Return JSON with this exact structure:
{
  "questions": [
    {
      "id": "unique_id",
      "type": "assignment_task",
      "assignment_type": "conceptual|scenario|research|project|case_study|comparative",
      "prompt": "The detailed question/task",
      "context": "Background information if needed",
      "code_snippet": "Optional: actual code (only for code-based scenarios/cases)",
      "requirements": ["requirement 1", "requirement 2"],
      "grading_criteria": "How to evaluate the response",
      "marks": 10,
      "word_count": "500-750 words",
      "difficulty": "medium",
      "learning_objectives": ["objective 1", "objective 2"],
      "deliverables": ["Optional: specific outputs expected"]
    }
  ]
}"""


def strip_code_like_text(s: str) -> str:
    """
    Best-effort sanitizer to remove code-like content from text fields
    when scenario_style is decision_based.
    """
    if not s:
        return s

    # Remove fenced blocks ```...```
    s = re.sub(r"```.*?```", "", s, flags=re.DOTALL)

    # Remove inline code `...`
    s = re.sub(r"`[^`]*`", "", s)

    # Remove obvious code/pseudocode lines (heuristics)
    code_line = re.compile(
        r"^\s*(?:"
        r"(def |class |import |from |return |for |while |if |else:|elif |try:|except |finally:)"
        r"|(#include|public |private |protected |static |void |int |string |bool |var |let |const |function )"
        r"|(\{|\}|\;\s*$)"
        r"|(\w+\s*\(.*\)\s*\{?)"
        r")",
        flags=re.IGNORECASE,
    )

    kept = []
    for line in s.splitlines():
        if code_line.search(line.strip()):
            continue
        kept.append(line)

    out = "\n".join(kept)

    # Clean extra blank lines
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def generate_advanced_assignments_llm(
    full_text: str,
    chosen_subtopics: list,
    task_distribution: dict,
    api_key: str,
    difficulty: str = "auto",
    scenario_style: str = "auto",
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
        scenario_style: "auto", "code_based", "decision_based"
    """

    client = Groq(api_key=api_key)

    total_tasks = sum(task_distribution.values())

    # Detect if topics are technical (only if scenario_style is "auto")
    technical_keywords = [
        "programming",
        "code",
        "algorithm",
        "data structure",
        "software",
        "python",
        "java",
        "javascript",
        "c++",
        "database",
        "sql",
        "api",
        "framework",
        "library",
        "function",
        "class",
        "object",
        "array",
        "sorting",
        "searching",
        "tree",
        "graph",
        "network",
        "system design",
        "optimization",
        "complexity",
        "debugging",
        "testing",
        "web development",
        "machine learning",
        "artificial intelligence",
        "neural network",
    ]

    content_lower = (full_text or "").lower()
    topics_lower = " ".join(chosen_subtopics or []).lower()

    # Determine actual scenario style to use
    if scenario_style == "auto":
        is_technical = any(
            (keyword in content_lower) or (keyword in topics_lower)
            for keyword in technical_keywords
        )
        effective_style = "code_based" if is_technical else "decision_based"
    else:
        effective_style = scenario_style
        is_technical = scenario_style == "code_based"

    user_prompt = f"""Based on the following educational content, generate {total_tasks} assignment tasks.

CONTENT:
{(full_text or "")[:15000]}

SELECTED TOPICS:
{", ".join(chosen_subtopics or [])}

SCENARIO STYLE: {effective_style.upper()}
{"IMPORTANT: Generate CODE-BASED scenarios with actual code snippets." if effective_style == "code_based" else "IMPORTANT: Generate DECISION-BASED scenarios focusing on strategy/analysis. ABSOLUTELY NO CODE ANYWHERE."}

TASK DISTRIBUTION:
"""

    for task_type, count in (task_distribution or {}).items():
        if count > 0:
            user_prompt += f"- {count} {task_type.replace('_', ' ').title()} question(s)\n"

    user_prompt += f"\nDIFFICULTY LEVEL: {difficulty}\n\n"

    # Add style-specific examples
    if effective_style == "code_based":
        user_prompt += """
SCENARIO-BASED EXAMPLE (Code-Based):
"You are reviewing a colleague's code for a user authentication system. The code below has a critical security flaw. Identify the vulnerability, explain why it's dangerous, and provide a corrected implementation."

PROJECT EXAMPLE (Code-Based):
"Design and implement a RESTful API for a library management system. Include: (1) API endpoint documentation, (2) Database schema, (3) Sample code for at least 3 endpoints, (4) Error handling strategy."

CASE STUDY EXAMPLE (Code-Based):
"A startup's e-commerce platform is experiencing severe performance degradation during peak hours. Analyze the system architecture below, identify bottlenecks, and propose specific optimizations with code examples."
"""
    else:
        user_prompt += """
SCENARIO-BASED EXAMPLE (Decision-Based):
"You are a consultant hired by Company X facing declining market share. The company has three strategic options: (1) Expand to new markets, (2) Invest heavily in R&D for product innovation, (3) Focus on cost reduction and operational efficiency. Analyze each option considering market conditions, competitive landscape, and organizational capabilities. What would you recommend and why?"

PROJECT EXAMPLE (Decision-Based):
"Develop a comprehensive digital transformation strategy for a traditional retail company. Include: (1) Assessment of current capabilities, (2) Technology roadmap, (3) Change management plan, (4) Risk mitigation strategies, (5) Success metrics."

CASE STUDY EXAMPLE (Decision-Based):
"Netflix decided to transition from DVD rentals to streaming, then to original content production. Analyze this strategic evolution: What were the key decision points? What risks did they take? How did they manage organizational change? What lessons can other companies learn?"
"""

    user_prompt += """
TASK TYPE DEFINITIONS:

1. CONCEPTUAL: Questions that test deep understanding of theories, principles, and fundamental concepts.

2. SCENARIO-BASED: Real-world situations requiring application of knowledge.
   - Must match the SCENARIO STYLE specified above

3. RESEARCH-BASED: Tasks requiring investigation, literature review, or data analysis.

4. PROJECT-BASED: Practical implementation tasks with deliverables.
   - Must match the SCENARIO STYLE for technical vs strategic projects

5. CASE STUDY: Analysis of complex real or hypothetical situations.
   - Must match the SCENARIO STYLE specified above

6. COMPARATIVE ANALYSIS: Comparing multiple concepts, approaches, or solutions.
"""

    json_instructions = """
CRITICAL JSON FORMATTING REQUIREMENTS:

1. The code_snippet field MUST be a plain string. Do NOT include markdown code blocks (```).
2. ONLY include code_snippet for CODE-BASED scenarios/cases when style is code_based
3. For DECISION-BASED style:
   - NEVER include code_snippet
   - ALSO: do NOT include code/pseudocode/code-like text in prompt/context/requirements/deliverables/grading_criteria
   - No backticks, no programming syntax, no code blocks
4. Escape special JSON characters properly in code_snippet:
   - Use \\" for double quotes inside strings
   - Use \\n for new lines
   - Use \\\\ for backslashes
5. Do NOT include any markdown formatting in JSON fields.
6. Ensure all string fields are properly escaped for JSON.

Generate questions that:
- Are specific and well-defined
- Include clear grading criteria
- Specify scope and expectations
- Encourage critical thinking
- Are appropriate for the difficulty level
"""
    user_prompt += json_instructions

    if effective_style == "code_based":
        user_prompt += """- Include code snippets in "code_snippet" field when presenting technical problems
- Specify concrete technical deliverables in the "deliverables" field
"""
    else:
        user_prompt += """- Focus on strategic analysis and decision-making
- Specify analytical deliverables (reports, frameworks, recommendations)
- NO code snippets and NO code-like text anywhere
"""

    user_prompt += "\nReturn ONLY valid JSON, no other text."

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": ASSIGNMENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        response_text = completion.choices[0].message.content
        print(f"DEBUG - Raw LLM response length: {len(response_text)} chars")
        print(f"DEBUG - Effective scenario style: {effective_style}")

        cleaned_response = (response_text or "").strip()

        # Remove markdown code blocks if present (extra safety)
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]

        # Parse JSON
        try:
            data = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            print(f"Cleaned response sample: {cleaned_response[:500]}")

            # Try one more cleanup - look for JSON object
            json_match = re.search(r"\{.*\}", cleaned_response, re.DOTALL)
            if json_match:
                cleaned_response = json_match.group(0)
                data = json.loads(cleaned_response)
            else:
                raise e

        questions = data.get("questions", [])
        if not questions:
            return {"success": False, "error": "No questions generated by LLM", "questions": []}

        cleaned_questions = []
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                continue

            # Ensure required fields
            if "id" not in q:
                q["id"] = f"assign_{i+1}"
            if "type" not in q:
                q["type"] = "assignment_task"
            if "assignment_type" not in q:
                q["assignment_type"] = "conceptual"
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

            # ✅ DECISION-BASED: remove code_snippet and sanitize ALL text fields
            if effective_style == "decision_based":
                if "code_snippet" in q:
                    del q["code_snippet"]

                for field in ["prompt", "context", "grading_criteria"]:
                    if field in q and q[field]:
                        q[field] = strip_code_like_text(str(q[field]).strip())

                if "requirements" in q and isinstance(q["requirements"], list):
                    new_reqs = []
                    for r in q["requirements"]:
                        rr = strip_code_like_text(str(r)).strip()
                        if rr:
                            new_reqs.append(rr)
                    q["requirements"] = new_reqs

                if "deliverables" in q and isinstance(q["deliverables"], list):
                    new_del = []
                    for d in q["deliverables"]:
                        dd = strip_code_like_text(str(d)).strip()
                        if dd:
                            new_del.append(dd)
                    q["deliverables"] = new_del

            else:
                # ✅ CODE-BASED: clean the code_snippet formatting if present
                if "code_snippet" in q and q["code_snippet"]:
                    code = str(q["code_snippet"])

                    # Remove markdown fences if LLM accidentally added them
                    if code.startswith("```"):
                        lines = code.split("\n")
                        if len(lines) > 1:
                            code = "\n".join(lines[1:-1])
                        else:
                            code = code.replace("```", "")

                    code = code.strip().replace("\\n", "\n")
                    q["code_snippet"] = code

                # Clean common string fields
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
                "scenario_style": effective_style,
                "is_technical": is_technical,
            },
        }

    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        print(
            f"Problematic response (first 1000 chars): {response_text[:1000] if 'response_text' in locals() else 'No response'}"
        )
        return {
            "success": False,
            "error": f"Failed to parse LLM response as JSON: {str(e)}",
            "raw_response": response_text[:1000] if "response_text" in locals() else None,
            "questions": [],
        }
    except Exception as e:
        print(f"Error generating assignments: {e}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e), "questions": []}
