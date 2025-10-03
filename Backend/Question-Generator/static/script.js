/* ===========================
   GLOBAL VARIABLES
=========================== */
let __lastQuizData = null;  // Store the last generated quiz data

/* ===========================
   CONFIG
=========================== */
const API_BASE = window.location.origin;
const ENDPOINT = "/api/quiz/from-pdf";

/* ===========================
   Helpers
=========================== */
function showToast(msg, ms=2500){
  const toastEl = document.getElementById('toast');
  if (!toastEl) return;
  
  toastEl.textContent = msg;
  toastEl.style.display = 'block';
  setTimeout(()=> {
    toastEl.style.display = 'none';
  }, ms);
}

function setProgress(p){
  const progress = document.getElementById('progress');
  const bar = progress?.querySelector('div');
  if (!progress || !bar) return;
  
  progress.style.display='block'; 
  bar.style.width = Math.max(0,Math.min(100,p))+'%';
}

function resetProgress(){
  const progress = document.getElementById('progress');
  const bar = progress?.querySelector('div');
  if (!progress || !bar) return;
  
  progress.style.display='none'; 
  bar.style.width='0%';
}

/* ===========================
   Quiz Rendering Functions
=========================== */
function renderQuiz(questions, metadata = {}) {
  console.log('Received questions:', questions); // Debug log
  
  const container = document.getElementById('quiz-container');
  const section = document.getElementById('quiz-section');
  
  if (!container || !section) {
    console.error('Quiz container or section not found');
    return;
  }

  // Show the quiz section
  section.style.display = 'block';
  
  // Clear previous content
  container.innerHTML = '';
  
  if (!questions || questions.length === 0) {
    container.innerHTML = '<p class="no-questions">No questions generated.</p>';
    return;
  }

  // Create quiz HTML
  let quizHTML = `
    <div class="quiz-metadata">
      <p><strong>Total Questions:</strong> ${questions.length}</p>
      ${metadata.source_file ? `<p><strong>Source:</strong> ${metadata.source_file}</p>` : ''}
      ${metadata.generated_at ? `<p><strong>Generated:</strong> ${new Date(metadata.generated_at).toLocaleString()}</p>` : ''}
    </div>
  `;

  questions.forEach((q, index) => {
    quizHTML += renderQuestion(q, index + 1);
  });

  container.innerHTML = quizHTML;
  
  // Initialize quiz actions
  initializeQuizActions();
}

function renderQuestion(question, number) {
  let html = `<div class="question-card" data-type="${question.type}">`;
  html += `<div class="question-header">`;
  
  // FIX: Use 'prompt' instead of 'question_text'
  const questionText = question.prompt || question.question_text || 'No question text';
  html += `<h3>Question ${number}</h3>`;
  html += `<span class="question-type">${getQuestionTypeLabel(question.type)}</span>`;
  html += `</div>`;
  
  // Question text in a separate paragraph for better readability
  html += `<div class="question-text">${escapeHtml(questionText)}</div>`;
  
  if (question.difficulty) {
    html += `<div class="question-meta"><strong>Difficulty:</strong> ${question.difficulty}</div>`;
  }
  
  if (question.scenario_based) {
    html += `<div class="scenario-flag">📝 Scenario-based</div>`;
  }
  
  if (question.code_snippet) {
    html += `<div class="code-flag">💻 Code-snippet</div>`;
  }

  // Render based on question type
  switch(question.type) {
    case 'mcq':
      html += renderMCQ(question);
      break;
    case 'true_false':
      html += renderTrueFalse(question);
      break;
    case 'short':
      html += renderShortAnswer(question);
      break;
    case 'long':
      html += renderLongAnswer(question);
      break;
    default:
      html += `<p>Unknown question type: ${question.type}</p>`;
  }

  if (question.explanation) {
    html += `<div class="explanation"><strong>Explanation:</strong> ${escapeHtml(question.explanation)}</div>`;
  }

  html += `</div>`;
  return html;
}

function renderMCQ(question) {
  let html = '<div class="options-container">';
  html += '<div class="options-label">Choose the correct option:</div>';
  html += '<div class="options">';
  
  if (question.options && Array.isArray(question.options)) {
    question.options.forEach((option, idx) => {
      const isCorrect = question.correct_answer === option || 
                        (Array.isArray(question.correct_answer) && question.correct_answer.includes(option)) ||
                        question.correct_answer === idx;
      const optionLetter = String.fromCharCode(65 + idx); // A, B, C, D...
      html += `<div class="option ${isCorrect ? 'correct' : ''}">`;
      html += `<span class="option-letter">${optionLetter}.</span>`;
      html += `<span class="option-text">${escapeHtml(option)}</span>`;
      if (isCorrect) {
        html += `<span class="correct-badge">Correct Answer</span>`;
      }
      html += '</div>';
    });
  } else {
    html += '<p>No options available</p>';
  }
  html += '</div></div>';
  return html;
}

function renderTrueFalse(question) {
  let html = '<div class="options-container">';
  html += '<div class="options-label">Select True or False:</div>';
  html += '<div class="options">';
  
  const correctAnswer = question.correct_answer;
  const isTrueCorrect = correctAnswer === true || correctAnswer === 'true' || correctAnswer === 'True';
  const isFalseCorrect = correctAnswer === false || correctAnswer === 'false' || correctAnswer === 'False';
  
  html += `<div class="option ${isTrueCorrect ? 'correct' : ''}">`;
  html += '<span class="option-letter">A.</span>';
  html += '<span class="option-text">True</span>';
  if (isTrueCorrect) {
    html += '<span class="correct-badge">Correct Answer</span>';
  }
  html += '</div>';
  
  html += `<div class="option ${isFalseCorrect ? 'correct' : ''}">`;
  html += '<span class="option-letter">B.</span>';
  html += '<span class="option-text">False</span>';
  if (isFalseCorrect) {
    html += '<span class="correct-badge">Correct Answer</span>';
  }
  html += '</div>';
  html += '</div></div>';
  return html;
}

function renderShortAnswer(question) {
  let html = '<div class="answer-section">';
  html += '<div class="answer-label">Answer:</div>';
  if (question.correct_answer) {
    html += `<div class="expected-answer">${escapeHtml(question.correct_answer)}</div>`;
  } else {
    html += `<div class="expected-answer">No answer provided</div>`;
  }
  html += '</div>';
  return html;
}

function renderLongAnswer(question) {
  let html = '<div class="answer-section">';
  html += '<div class="answer-label">Answer:</div>';
  if (question.correct_answer) {
    html += `<div class="expected-answer">${escapeHtml(question.correct_answer)}</div>`;
  } else {
    html += `<div class="expected-answer">No answer provided</div>`;
  }
  if (question.grading_criteria) {
    html += `<div class="grading-criteria"><strong>Grading Criteria:</strong> ${escapeHtml(question.grading_criteria)}</div>`;
  }
  html += '</div>';
  return html;
}

function getQuestionTypeLabel(type) {
  const typeMap = {
    'mcq': 'Multiple Choice',
    'true_false': 'True/False',
    'short': 'Short Answer',
    'long': 'Long Answer'
  };
  return typeMap[type] || type;
}

function escapeHtml(unsafe) {
  if (typeof unsafe !== 'string') return unsafe;
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/* ===========================
   Quiz Actions
=========================== */
function initializeQuizActions() {
  // Copy as Text button
  const copyBtn = document.getElementById('btn-copy-quiz');
  if (copyBtn) {
    copyBtn.onclick = copyQuizAsText;
  }
  
  // Save JSON button
  const saveBtn = document.getElementById('btn-save-json');
  if (saveBtn) {
    saveBtn.onclick = saveQuizAsJSON;
  }
}

function copyQuizAsText() {
  if (!__lastQuizData || !__lastQuizData.questions) {
    showToast('No quiz data to copy');
    return;
  }

  let text = `GENERATED QUIZ\n`;
  text += `====================\n`;
  text += `Total Questions: ${__lastQuizData.questions.length}\n`;
  text += `Generated: ${new Date().toLocaleString()}\n\n`;
  
  __lastQuizData.questions.forEach((q, index) => {
    const questionText = q.prompt || q.question_text || 'No question text';
    text += `QUESTION ${index + 1} (${getQuestionTypeLabel(q.type).toUpperCase()})\n`;
    text += `────────────────────\n`;
    text += `${questionText}\n\n`;
    
    if (q.difficulty) {
      text += `Difficulty: ${q.difficulty}\n`;
    }
    
    if (q.options && Array.isArray(q.options)) {
      text += `Options:\n`;
      q.options.forEach((option, idx) => {
        const letter = String.fromCharCode(65 + idx);
        text += `  ${letter}. ${option}\n`;
      });
      text += `\n`;
    }
    
    if (q.type === 'short' || q.type === 'long') {
      text += `Answer: ${q.correct_answer || 'No answer provided'}\n`;
    } else {
      if (Array.isArray(q.correct_answer)) {
        text += `Correct Answer(s): ${q.correct_answer.join(', ')}\n`;
      } else {
        text += `Correct Answer: ${q.correct_answer}\n`;
      }
    }
    
    if (q.explanation) {
      text += `Explanation: ${q.explanation}\n`;
    }
    
    text += '\n';
  });

  navigator.clipboard.writeText(text).then(() => {
    showToast('Quiz copied to clipboard!');
  }).catch(err => {
    console.error('Failed to copy text: ', err);
    showToast('Failed to copy quiz');
  });
}

function saveQuizAsJSON() {
  if (!__lastQuizData) {
    showToast('No quiz data to save');
    return;
  }

  const dataStr = JSON.stringify(__lastQuizData, null, 2);
  const dataBlob = new Blob([dataStr], { type: 'application/json' });
  
  const url = URL.createObjectURL(dataBlob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `quiz-${new Date().toISOString().split('T')[0]}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  
  showToast('Quiz saved as JSON!');
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  console.log('AI Quiz Generator initialized');
  initializeQuizActions();
});