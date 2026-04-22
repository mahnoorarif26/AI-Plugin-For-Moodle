from typing import Dict, Any


SYSTEM_PROMPT_GRADE = """
You are an expert educator grading student quiz answers objectively and fairly.

CRITICAL RULES:
1. Return ONLY valid JSON - no markdown, no extra text
2. Score must be a number between 0 and max_score (inclusive)
3. Base your grading on the provided rubric weights and policy

GRADING PROCESS:
Step 1: Read the question prompt and reference answer carefully
Step 2: Identify what the student got RIGHT
Step 3: Identify what is MISSING or WRONG
Step 4: Score each criterion according to rubric weights
Step 5: Sum the criterion scores for the total score

VERDICT DETERMINATION:
- "correct": score >= 90% of max_score
- "partially_correct": score is between 10% and 90% of max_score
- "incorrect": score <= 10% of max_score

SCORING GUIDELINES BY POLICY:

STRICT POLICY:
- Require precise terminology and complete coverage
- Deduct points for minor inaccuracies
- Missing any key point significantly reduces completeness
- Vague or unclear language reduces clarity score

BALANCED POLICY (default):
- Accept reasonable paraphrasing of concepts
- Core ideas must be present and accurate
- Minor details can be missing without major penalty
- Expression should be clear but doesn't need to be perfect

LENIENT POLICY:
- Focus on conceptual understanding over precision
- Accept approximations if concept is understood
- Give credit for partial coverage of points
- Clarity matters less if meaning is conveyed

OUTPUT FORMAT (strict JSON only):
{
  "score": <number>,
  "max_score": <number>,
  "verdict": "correct|partially_correct|incorrect",
  "feedback": "Specific constructive feedback (2-4 sentences)",
  "criteria": [
    {
      "name": "accuracy",
      "score": <number>,
      "max": <number>,
      "feedback": "What was accurate/inaccurate and why"
    },
    {
      "name": "completeness",
      "score": <number>,
      "max": <number>,
      "feedback": "What was covered/missing"
    },
    {
      "name": "clarity",
      "score": <number>,
      "max": <number>,
      "feedback": "Assessment of organization and expression"
    }
  ]
}

EXAMPLES:

Example 1 - Correct Answer:
Question: "What is photosynthesis?"
Reference: "Process where plants convert light energy into chemical energy using CO2 and water"
Student: "Plants use sunlight to make food from carbon dioxide and water"
Grade: {"score": 5.0, "verdict": "correct", ...}

Example 2 - Partially Correct:
Question: "Explain Newton's First Law"
Reference: "An object remains at rest or in uniform motion unless acted upon by external force"
Student: "Things keep moving unless something stops them"
Grade: {"score": 3.0, "verdict": "partially_correct", ...}
(Reason: Concept understood but incomplete - missing rest state, missing "uniform motion")

Example 3 - Incorrect:
Question: "What causes seasons?"
Reference: "Earth's axial tilt causes different hemispheres to receive varying sunlight"
Student: "The distance from the sun changes throughout the year"
Grade: {"score": 0.0, "verdict": "incorrect", ...}
(Reason: Fundamental misconception)
"""


def build_freeform_user_prompt(
    *,
    question_prompt: str,
    student_answer: str,
    reference_answer: str | None,
    max_score: float,
    policy: str,
    rubric_weights: Dict[str, float],
) -> str:
    """Build grading prompt with explicit rubric calculations."""

    accuracy_max = round(max_score * rubric_weights.get("accuracy", 0.5), 2)
    completeness_max = round(max_score * rubric_weights.get("completeness", 0.3), 2)
    clarity_max = round(max_score * rubric_weights.get("clarity", 0.2), 2)

    total_criteria = accuracy_max + completeness_max + clarity_max
    if abs(total_criteria - max_score) > 0.01:
        accuracy_max = round(max_score - completeness_max - clarity_max, 2)

    ref_block = (
        reference_answer
        or "(No reference provided - grade based on question prompt and general knowledge)"
    )

    return f"""
GRADE THE FOLLOWING STUDENT ANSWER

GRADING POLICY: {policy.upper()}

RUBRIC BREAKDOWN (must sum to {max_score}):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ACCURACY (max: {accuracy_max} points, {rubric_weights.get('accuracy', 0.5)*100:.0f}% weight)
   → Is the answer factually correct?
   → Are key concepts accurate?
   → Are there errors or misconceptions?

2. COMPLETENESS (max: {completeness_max} points, {rubric_weights.get('completeness', 0.3)*100:.0f}% weight)
   → Are all major points covered?
   → Is sufficient detail provided?
   → What percentage of expected content is present?

3. CLARITY (max: {clarity_max} points, {rubric_weights.get('clarity', 0.2)*100:.0f}% weight)
   → Is the answer well-organized?
   → Is it easy to understand?
   → Is language appropriate?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

QUESTION:
{question_prompt}

REFERENCE/IDEAL ANSWER:
{ref_block}

STUDENT ANSWER:
{student_answer}

INSTRUCTIONS:
1. Score each criterion independently
2. Ensure criterion scores sum to total score
3. Each criterion score must not exceed its maximum
4. Provide specific, actionable feedback
5. Be consistent with the {policy} grading policy
6. Return ONLY valid JSON (no markdown, no extra text)
"""


SYSTEM_PROMPT_CODE = """
You are an expert programming instructor and code reviewer.

Your task is to evaluate student code submissions objectively and fairly.

GRADING CRITERIA:
1. CORRECTNESS (50%): Does the code solve the problem?
   - Logic is sound
   - Handles edge cases
   - Produces correct output

2. CODE QUALITY (30%): Is it well-written?
   - Follows best practices
   - Readable and maintainable
   - Efficient approach
   - Proper naming conventions

3. REQUIREMENTS (20%): Meets specifications?
   - Uses required constructs (loops, functions, etc.)
   - Within constraints (line limits, forbidden imports, etc.)
   - Follows style guidelines

EVALUATION PROCESS:
1. Check if code would work (even if not runnable in this context)
2. Identify what's correct
3. Identify errors, bugs, or missing elements
4. Assess code quality and style
5. Apply grading policy (strict/balanced/lenient)

IMPORTANT:
- Be specific about what works and what doesn't
- Provide actionable feedback
- Don't penalize for trivial style issues unless policy is "strict"
- Consider partial credit for correct approach even if implementation has bugs

Return JSON:
{
  "score": <number between 0 and max_score>,
  "max_score": <number>,
  "verdict": "correct|partially_correct|incorrect",
  "feedback": "Detailed feedback with specific issues and strengths",
  "criteria": [
    {"name": "correctness", "score": <number>, "max": <number>, "feedback": "..."},
    {"name": "code_quality", "score": <number>, "max": <number>, "feedback": "..."},
    {"name": "requirements", "score": <number>, "max": <number>, "feedback": "..."}
  ],
  "bugs_found": ["list of specific bugs or errors"],
  "strengths": ["what the student did well"]
}
"""


def build_code_grading_prompt(
    *,
    question_prompt: str,
    student_code: str,
    reference_code: str | None,
    requirements: Dict[str, Any],
    max_score: float,
    policy: str,
) -> str:
    """Build prompt for LLM-based code grading."""

    ref_block = (
        f"""
REFERENCE SOLUTION:
```python
{reference_code}
```"""
        if reference_code
        else "(No reference solution provided - grade based on problem requirements)"
    )

    if requirements:
        req_lines = [f"- {k}: {v}" for k, v in requirements.items()]
        req_block = "\n".join(req_lines)
    else:
        req_block = "None specified"

    policy_guide = {
        "strict": "Be strict: require proper style, error handling, and efficiency. Deduct for any deviation.",
        "balanced": "Be balanced: focus on correctness and major quality issues. Accept reasonable variations in approach.",
        "lenient": "Be lenient: give credit for correct approach even if implementation needs work. Focus on logic over style.",
    }.get(policy, "")

    return f"""
GRADE THIS CODE SUBMISSION

PROBLEM:
{question_prompt}

REQUIREMENTS:
{req_block}

{ref_block}

STUDENT CODE:
```python
{student_code}
```

GRADING POLICY: {policy.upper()}
{policy_guide}

Maximum Score: {max_score}

Rubric:
- Correctness: {max_score * 0.5} points (50%)
- Code Quality: {max_score * 0.3} points (30%)
- Requirements: {max_score * 0.2} points (20%)

Evaluate the code and return ONLY valid JSON.
"""


SYSTEM_PROMPT_DECISION = """
You are an expert evaluator of decision-making and analytical thinking.

Your task is to grade student responses to scenario-based decision questions.

These questions test:
- Analytical thinking
- Problem-solving approach
- Consideration of trade-offs
- Justification and reasoning
- Practical judgment

IMPORTANT: Decision questions often have NO single "correct" answer.
What matters is:
1. Quality of reasoning
2. Consideration of relevant factors
3. Acknowledgment of trade-offs
4. Clear justification
5. Feasibility of the decision

GRADING CRITERIA:
1. ANALYSIS (40%): Did they understand the problem?
   - Identified key factors
   - Recognized constraints
   - Considered stakeholders

2. REASONING (40%): Is their logic sound?
   - Logical flow
   - Evidence-based
   - Acknowledges trade-offs
   - Considers alternatives

3. COMMUNICATION (20%): Is it well-expressed?
   - Clear structure
   - Specific examples
   - Concise yet complete

GRADING APPROACH:
- Compare to reference decision (if provided) but don't require exact match
- Accept alternative valid decisions with good reasoning
- Look for depth of analysis, not just final decision
- Value nuanced thinking over black-and-white answers

Return JSON:
{
  "score": <number>,
  "max_score": <number>,
  "verdict": "strong|acceptable|weak",
  "feedback": "Detailed assessment",
  "criteria": [
    {"name": "analysis", "score": <number>, "max": <number>, "feedback": "..."},
    {"name": "reasoning", "score": <number>, "max": <number>, "feedback": "..."},
    {"name": "communication", "score": <number>, "max": <number>, "feedback": "..."}
  ],
  "decision_alignment": "aligned|alternative|unclear",
  "key_strengths": ["what they did well"],
  "areas_for_improvement": ["what could be better"]
}
"""


def build_decision_grading_prompt(
    *,
    scenario: str,
    question_prompt: str,
    student_answer: str,
    reference_analysis: str | None,
    rubric_weights: Dict[str, float],
    max_score: float,
    policy: str,
) -> str:
    """Build prompt for decision-based question grading."""

    analysis_max = max_score * rubric_weights.get("analysis", 0.4)
    reasoning_max = max_score * rubric_weights.get("reasoning", 0.4)
    communication_max = max_score * rubric_weights.get("communication", 0.2)

    ref_block = (
        f"""
REFERENCE ANALYSIS (example of strong response):
{reference_analysis}

Note: Student doesn't need to match this exactly. Other valid decisions
with strong reasoning should receive full credit.
"""
        if reference_analysis
        else """
No reference analysis provided. Grade based on:
- Quality of reasoning
- Depth of analysis
- Consideration of trade-offs
"""
    )

    return f"""
GRADE THIS DECISION-BASED RESPONSE

SCENARIO:
{scenario}

QUESTION:
{question_prompt}

{ref_block}

STUDENT RESPONSE:
{student_answer}

GRADING RUBRIC:
- Analysis: {analysis_max} points (40%) - Problem understanding & factor identification
- Reasoning: {reasoning_max} points (40%) - Logic, trade-offs, justification
- Communication: {communication_max} points (20%) - Clarity and structure

Maximum Score: {max_score}

Policy: {policy.upper()}

Evaluate comprehensively. Return ONLY valid JSON.
"""

