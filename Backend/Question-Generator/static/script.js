/* ===========================
GLOBAL VARIABLES
=========================== */
let __lastQuizData = null; // Store the last generated quiz data (questions + metadata + settings)

/* ===========================
CONFIG
=========================== */
const API_BASE = window.location.origin;
const ENDPOINT = "/api/quiz/from-pdf";

/* ===========================
Helpers
=========================== */
function formatDateTime(value) {
    try {
        const d = value instanceof Date ? value : new Date(value);
        if (!d || Number.isNaN(d.getTime())) return '';
        return d.toLocaleString('en-US', {
            year: 'numeric',
            month: 'short',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
            timeZone: 'UTC',
        });
    } catch (e) {
        return '';
    }
}

function formatScoreCeil(val) {
    const n = Number(val);
    if (Number.isFinite(n)) return Math.ceil(n);
    return 0;
}

// Expose helpers for other scripts
window.__fmtDateTime = formatDateTime;
window.__fmtScore = formatScoreCeil;

function showToast(msg, ms = 2500) {
    const toastEl = document.getElementById('toast');
    if (!toastEl) return;

    toastEl.textContent = msg;
    toastEl.style.display = 'block';
    setTimeout(() => {
        toastEl.style.display = 'none';
    }, ms);
}

function setProgress(p) {
    const progress = document.getElementById('progress');
    const bar = progress?.querySelector('div');
    if (!progress || !bar) return;

    progress.style.display = 'block';
    bar.style.width = Math.max(0, Math.min(100, p)) + '%';
}

function resetProgress() {
    const progress = document.getElementById('progress');
    const bar = progress?.querySelector('div');
    if (!progress || !bar) return;

    progress.style.display = 'none';
    bar.style.width = '0%';
}

// Extract settings (time_limit, due_date, note) from metadata structure
function extractSettings(metadata = {}) {
    const direct = metadata.settings || {};
    const metaSettings = (metadata.metadata && metadata.metadata.settings) || {};

    const time_limit =
        metadata.time_limit ??
        direct.time_limit ??
        metaSettings.time_limit ??
        null;

    const due_date =
        metadata.due_date ??
        direct.due_date ??
        metaSettings.due_date ??
        null;

    const note =
        metadata.note ??
        direct.note ??
        metaSettings.note ??
        metaSettings.notification_message ??
        '';

    return { time_limit, due_date, note };
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

    // Extract settings for header display
    const settings = extractSettings(metadata);
    const timeLimitText =
        typeof settings.time_limit === 'number' && settings.time_limit > 0
            ? settings.time_limit + ' minutes'
            : '';
    const dueDateText = formatDateTime(settings.due_date);
    const noteText = settings.note && settings.note.trim();

    // Save last quiz data (including metadata + settings) for copy/save JSON
    __lastQuizData = {
        questions: questions || [],
        metadata: metadata || {},
        settings: settings,
    };

    // Show the quiz section
    section.style.display = 'block';

    // Clear previous content
    container.innerHTML = '';

    if (!questions || questions.length === 0) {
        container.innerHTML = '<p class="no-questions">No questions generated.</p>';
        return;
    }

    // Create quiz HTML header + metadata
    let quizHTML = '<div class="quiz-metadata">';
    quizHTML += `<p><strong>Total Questions:</strong> ${questions.length}</p>`;

    if (metadata.source_file) {
        quizHTML += `<p><strong>Source:</strong> ${metadata.source_file}</p>`;
    }

    if (metadata.generated_at) {
        quizHTML += `<p><strong>Generated:</strong> ${formatDateTime(metadata.generated_at)}</p>`;
    }

    // New: show per-quiz settings in teacher view
    if (timeLimitText || dueDateText || noteText) {
        quizHTML += '<div class="quiz-settings">';
        if (timeLimitText) {
            quizHTML += `<p><strong>Time limit:</strong> ${timeLimitText}</p>`;
        }
        if (dueDateText) {
            quizHTML += `<p><strong>Due date:</strong> ${dueDateText}</p>`;
        }
        if (noteText) {
            quizHTML += `<p><strong>Note:</strong> ${escapeHtml(noteText)}</p>`;
        }
        quizHTML += '</div>';
    }

    quizHTML += '</div>'; // end quiz-metadata

    questions.forEach((q, index) => {
        quizHTML += renderQuestion(q, index + 1);
    });

    container.innerHTML = quizHTML;

    // Initialize quiz actions (copy/save)
    initializeQuizActions();
}

function renderQuestion(question, number) {
    let html = `<div class="question-card" data-type="${question.type}">`;
    html += '<div class="question-header">';

    const questionText = question.prompt || question.question_text || 'No question text';
    html += `<h3>Question ${number}</h3>`;
    html += `<span class="question-type">${getQuestionTypeLabel(question.type)}</span>`;
    html += '</div>';

    html += `<div class="question-text">${escapeHtml(questionText)}</div>`;

    if (question.difficulty) {
        html += `<div class="question-meta"><strong>Difficulty:</strong> ${question.difficulty}</div>`;
    }

    if (question.scenario_based) {
        html += '<div class="scenario-flag">📝 Scenario-based</div>';
    }

    if (question.code_snippet) {
        html += '<div class="code-flag">💻 Code-snippet</div>';
    }

    switch (question.type) {
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
        html += `<div class="explanation"><strong>Explanation:</strong> ${escapeHtml(
            question.explanation,
        )}</div>`;
    }

    html += '</div>';
    return html;
}

function renderMCQ(question) {
    let html = '<div class="options-container">';
    html += '<div class="options-label">Choose the correct option:</div>';
    html += '<div class="options">';

    if (question.options && Array.isArray(question.options)) {
        question.options.forEach((option, idx) => {
            const isCorrect =
                question.correct_answer === option ||
                (Array.isArray(question.correct_answer) &&
                    question.correct_answer.includes(option)) ||
                question.correct_answer === idx;
            const optionLetter = String.fromCharCode(65 + idx); // A, B, C, D...
            html += `<div class="option ${isCorrect ? 'correct' : ''}">`;
            html += `<span class="option-letter">${optionLetter}.</span>`;
            html += `<span class="option-text">${escapeHtml(option)}</span>`;
            if (isCorrect) {
                html += '<span class="correct-badge">Correct Answer</span>';
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
    const isTrueCorrect =
        correctAnswer === true ||
        correctAnswer === 'true' ||
        correctAnswer === 'True';
    const isFalseCorrect =
        correctAnswer === false ||
        correctAnswer === 'false' ||
        correctAnswer === 'False';

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
        html += `<div class="expected-answer">${escapeHtml(
            question.correct_answer,
        )}</div>`;
    } else {
        html += '<div class="expected-answer">No answer provided</div>';
    }
    html += '</div>';
    return html;
}

function renderLongAnswer(question) {
    let html = '<div class="answer-section">';
    html += '<div class="answer-label">Answer:</div>';
    if (question.correct_answer) {
        html += `<div class="expected-answer">${escapeHtml(
            question.correct_answer,
        )}</div>`;
    } else {
        html += '<div class="expected-answer">No answer provided</div>';
    }
    if (question.grading_criteria) {
        html += `<div class="grading-criteria"><strong>Grading Criteria:</strong> ${escapeHtml(
            question.grading_criteria,
        )}</div>`;
    }
    html += '</div>';
    return html;
}

function getQuestionTypeLabel(type) {
    const typeMap = {
        mcq: 'Multiple Choice',
        true_false: 'True/False',
        short: 'Short Answer',
        long: 'Long Answer',
    };
    return typeMap[type] || type;
}

function escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') return unsafe;
    return unsafe
        .replace(/&/g, "&")
        .replace(/</g, "<")
        .replace(/>/g, ">")
        .replace(/"/g, "\"")
        .replace(/'/g, "&#039;");
}

/* ===========================
Quiz Actions
=========================== */
function initializeQuizActions() {
    const copyBtn = document.getElementById('btn-copy-quiz');
    if (copyBtn) {
        copyBtn.onclick = copyQuizAsText;
    }

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

    const questions = __lastQuizData.questions;
    const metadata = __lastQuizData.metadata || {};
    const settings = __lastQuizData.settings || {};

    let text = `GENERATED QUIZ\n`;
    text += `====================\n`;
    text += `Total Questions: ${questions.length}\n`;
    text += `Generated: ${formatDateTime(new Date())}\n`;

    // Include settings summary at top for teacher
    if (typeof settings.time_limit === 'number' && settings.time_limit > 0) {
        text += `Time limit: ${settings.time_limit} minutes\n`;
    }
    if (settings.due_date) {
        text += `Due date: ${formatDateTime(settings.due_date)}\n`;
    }
    if (settings.note && settings.note.trim()) {
        text += `Note: ${settings.note.trim()}\n`;
    }

    text += `\n`;

    questions.forEach((q, index) => {
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
                text += ` ${letter}. ${option}\n`;
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

    navigator.clipboard
        .writeText(text)
        .then(() => {
            showToast('Quiz copied to clipboard!');
        })
        .catch((err) => {
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
document.addEventListener('DOMContentLoaded', function () {
    console.log('AI Quiz Generator initialized');
    initializeQuizActions();
});