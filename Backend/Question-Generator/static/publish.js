// static/publish.js
// Enhanced Student/teacher-friendly quiz renderer with improved PDF generation
// Modified to show only correct answers (answer key mode)

(function () {
    'use strict';

    const SEC_ID = 'quiz-section';
    const CONT_ID = 'quiz-container';
    const VIEW_MODE_KEY = 'quiz_view_mode'; // 'student' or 'teacher'

    /* ---------------- Configuration ---------------- */
    const CONFIG = {
        pdf: {
            margin: [12, 12, 12, 12],
            scale: 2,
            format: 'a4',
            orientation: 'portrait',
            filenamePrefix: 'quiz_'
        },
        ui: {
            animationDuration: 300,
            scrollBehavior: 'smooth'
        },
        validation: {
            maxFilenameLength: 100
        }
    };

    /* ---------------- Utilities ---------------- */
    const $ = (id) => document.getElementById(id);
    const $$ = (selector, context = document) => context.querySelectorAll(selector);
    const create = (tag, props = {}, children = []) => {
        const el = document.createElement(tag);
        Object.assign(el, props);
        if (children.length) el.append(...children);
        return el;
    };

    const safeArray = (x) => Array.isArray(x) ? x : [];
    const letterFrom = (i) => String.fromCharCode(65 + i); // 0 -> A
    const escapeHtml = (text) => {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };

    function unhide(el) {
        if (!el) return;
        
        // Remove display none
        if (el.style.display === 'none') {
            el.style.display = '';
        }
        
        // Check computed style
        const computed = getComputedStyle(el);
        if (computed.display === 'none') {
            el.style.display = 'block';
        }
        
        // Ensure visibility
        if (computed.visibility === 'hidden') {
            el.style.visibility = 'visible';
        }
    }

    function fmtDateTime(value) {
        if (!value) return '';
        try {
            const d = new Date(value);
            if (Number.isNaN(d.getTime())) return '';
            
            const options = {
                year: 'numeric',
                month: 'short',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                hour12: false
            };
            
            return d.toLocaleString('en-US', options);
        } catch (e) {
            console.warn('Date formatting error:', e);
            return '';
        }
    }

    /* ---------------- View Mode Management ---------------- */
    class ViewModeManager {
        static getMode() {
            return localStorage.getItem(VIEW_MODE_KEY) || 'teacher'; // Default to teacher mode (answer key)
        }

        static setMode(mode) {
            if (mode === 'student' || mode === 'teacher') {
                localStorage.setItem(VIEW_MODE_KEY, mode);
                return true;
            }
            return false;
        }

        static isTeacherMode() {
            return this.getMode() === 'teacher';
        }

        static toggleMode() {
            const newMode = this.isTeacherMode() ? 'student' : 'teacher';
            this.setMode(newMode);
            return newMode;
        }
    }

    /* ---------------- Helper Functions ---------------- */
    function prettyType(t) {
        const typeMap = {
            'mcq': 'Multiple Choice',
            'true_false': 'True / False',
            'short': 'Short Answer',
            'long': 'Long Answer',
            'matching': 'Matching',
            'fill_in': 'Fill in the Blank',
            'essay': 'Essay'
        };
        
        const key = String(t || '').toLowerCase();
        return typeMap[key] || (t || 'Question');
    }

    function prettyDifficulty(d) {
        const diffMap = {
            'easy': 'Easy',
            'medium': 'Medium',
            'hard': 'Hard',
            'beginner': 'Beginner',
            'intermediate': 'Intermediate',
            'advanced': 'Advanced'
        };
        
        const key = String(d || '').toLowerCase();
        return diffMap[key] || '';
    }

    function getAnswerIndex(q) {
        const a = q?.answer;
        
        // Handle numeric answer
        if (Number.isFinite(a)) return a;
        
        // Handle string numeric
        if (typeof a === 'string') {
            const n = parseInt(a, 10);
            if (!isNaN(n)) return n;
            
            // Check for letter answers like "A", "B", "C"
            const upper = a.toUpperCase();
            if (upper >= 'A' && upper <= 'Z') {
                return upper.charCodeAt(0) - 'A'.charCodeAt(0);
            }
        }
        
        return -1;
    }

    function extractSettings(root) {
        const meta = root.metadata || {};
        const direct = root.settings || {};
        const metaSettings = meta.settings || {};

        const settings = {
            time_limit: root.time_limit ?? direct.time_limit ?? metaSettings.time_limit ?? null,
            due_date: root.due_date ?? direct.due_date ?? metaSettings.due_date ?? null,
            note: root.note ?? direct.note ?? metaSettings.note ?? metaSettings.notification_message ?? '',
            total_points: root.total_points ?? meta.total_points ?? 0,
            shuffle: root.shuffle ?? direct.shuffle ?? metaSettings.shuffle ?? false,
            show_answers: root.show_answers ?? direct.show_answers ?? metaSettings.show_answers ?? false,
            pdf_name: root.pdf_name ?? meta.pdf_name ?? direct.pdf_name ?? ''
        };

        return settings;
    }

    /* ---------------- Quiz State Management ---------------- */
    class QuizState {
        constructor() {
            this.currentQuiz = null;
            this.isRendered = false;
            this.pdfGenerator = null;
        }

        setQuiz(quizData) {
            this.currentQuiz = quizData;
            this.isRendered = false;
        }

        getQuiz() {
            return this.currentQuiz;
        }

        clear() {
            this.currentQuiz = null;
            this.isRendered = false;
        }
    }

    const quizState = new QuizState();

    /* ---------------- Exam Header ---------------- */
    function renderExamHeader(title, settings, viewMode = 'teacher') {
        const { time_limit, due_date, note, total_points, pdf_name } = settings || {};

        const timeLimitText = typeof time_limit === 'number' && time_limit > 0 
            ? `${time_limit} minutes` 
            : '';
        
        const dueDateText = fmtDateTime(due_date);
        
        // Display PDF name as title if available
        const displayTitle = pdf_name || title || 'Quiz';
        
        const hasMeta = !!(timeLimitText || dueDateText || (note && note.trim()));

        return `
<div class="exam-header">
    <div class="exam-header-top">
        <h1>${escapeHtml(displayTitle)}</h1>
    </div>
    
    ${hasMeta ? `
    <div class="exam-meta">
        ${timeLimitText ? `<div class="meta-item"><strong>Time limit:</strong> ${timeLimitText}</div>` : ''}
        ${dueDateText ? `<div class="meta-item"><strong>Due date:</strong> ${dueDateText}</div>` : ''}
        ${note && note.trim() ? `<div class="exam-note meta-item"><strong>Note:</strong> ${escapeHtml(note.trim())}</div>` : ''}
    </div>
    ` : ''}
    
    <hr class="exam-divider" />
</div>
`;
    }

    /* ---------------- Toolbar - Removed ---------------- */
    function renderToolbar() {
        return ''; // No toolbar needed
    }

    /* ---------------- Question Renderers ---------------- */
    
    // Show all options with correct one marked
    function renderOptions(q, viewMode = 'teacher') {
        const ansIdx = getAnswerIndex(q);
        const options = safeArray(q.options);
        const showAnswers = viewMode === 'teacher';

        // Check if options already have letters in them
        const hasLetterPrefix = options.some(opt => 
            typeof opt === 'string' && /^[A-Z][\.\)]\s/.test(opt)
        );

        const items = options.map((opt, i) => {
            const isCorrect = i === ansIdx;
            const shouldShowAnswer = showAnswers && isCorrect;
            
            // Extract clean option text (remove any existing letter prefix)
            let cleanText = opt ?? '';
            if (hasLetterPrefix && typeof cleanText === 'string') {
                // Remove common prefixes like "A.", "A)", "A", etc.
                cleanText = cleanText.replace(/^[A-Z][\.\)]?\s*/, '');
            }
            
            return `
    <div class="option ${shouldShowAnswer ? 'correct' : ''}">
        <span class="option-letter">${letterFrom(i)}.</span>
        <span class="option-text">${escapeHtml(cleanText)}</span>
        ${shouldShowAnswer ? `<span class="correct-badge" aria-label="Correct answer">✓ Correct</span>` : ''}
    </div>
    `;
        }).join('');

        return `
    <div class="options-container">
        <div class="options">${items}</div>
    </div>
    `;
    }
    function renderTrueFalse(viewMode = 'teacher') {
        return `
        <div class="options-container">
            <div class="option">
                <span class="option-letter">A.</span>
                <span class="option-text">True</span>
            </div>
            <div class="option">
                <span class="option-letter">B.</span>
                <span class="option-text">False</span>
            </div>
        </div>
        `;
            }

    function renderWrittenSpace(lines = 4, viewMode = 'student') {
        const lineElements = Array.from({ length: lines })
            .map(() => `<div class="answer-line"></div>`)
            .join('');
            
        return `
<div class="written-answer-space">
    ${lineElements}
</div>
`;
    }

    function renderCorrectAnswer(q, viewMode = 'teacher') {
        // Don't show separate correct answer section for MCQ (shown inline with options)
        if (viewMode !== 'teacher') return '';
        
        const type = (q.type || '').toLowerCase();
        if (type === 'mcq') {
            return ''; // Already shown in renderOptions
        }
        
        // For other question types, we don't show correct answer separately
        return '';
    }

    // Points rendering removed
    function renderQuestionPoints(q) {
        return ''; // Don't show points
    }

    /* ---------------- Main Question Renderer ---------------- */
    function toHtml(q, idx, viewMode = 'teacher') {
        const n = idx + 1;
        const type = (q.type || '').toLowerCase();
        const typeLabel = prettyType(q.type);
        const diffLabel = prettyDifficulty(q.difficulty);
        const showAnswers = viewMode === 'teacher';

        // Determine question body based on type
        let body = '';
        if (type === 'mcq' && Array.isArray(q.options)) {
            body = renderOptions(q, viewMode);
        } else if (type === 'true_false') {
            body = renderTrueFalse(viewMode);
        } else {
            // For written questions, show expected answer in teacher mode
            if (showAnswers) {
                const expected = (q.answer ?? q.expected_answer ?? '').toString();
                body = `
<div class="answer-section">
    <div class="answer-label">Expected Answer:</div>
    <div class="expected-answer">${escapeHtml(expected || '—')}</div>
</div>
`;
            } else {
                body = renderWrittenSpace(type === 'long' ? 8 : 4, viewMode);
            }
        }

        // Get explanation (only in teacher mode)
        const explanation = showAnswers ? (q.explanation || '').trim() : '';

        return `
<article class="question-card" data-question-index="${idx}" data-question-type="${type}">
    <div class="question-header">
        <div class="question-header-left">
            <h3 class="question-number">Question ${n}</h3>
            ${diffLabel ? `<span class="difficulty-badge" aria-label="Difficulty: ${diffLabel}">${diffLabel}</span>` : ''}
        </div>
        <div class="question-header-right">
            <span class="question-type" aria-label="Question type: ${typeLabel}">${typeLabel}</span>
        </div>
    </div>

    <div class="question-content">
        <div class="question-text">${escapeHtml(q.question || q.prompt || '')}</div>
        
        ${body}
        
        ${explanation ? `
        <div class="explanation">
            <div class="explanation-label">Explanation:</div>
            <div class="explanation-content">${escapeHtml(explanation)}</div>
        </div>
        ` : ''}
        
        ${renderCorrectAnswer(q, viewMode)}
    </div>
</article>
`;
    }

    /* ---------------- PDF Generation with Error Handling ---------------- */
    class PDFGenerator {
        static async generate(container, filenameHint = 'quiz') {
            if (!container) {
                throw new Error('Quiz container not found');
            }

            // Check if html2pdf is available
            if (typeof html2pdf === 'undefined') {
                console.warn('html2pdf not available, falling back to print');
                window.print();
                return;
            }

            // Clean filename
            const cleanFilename = String(filenameHint || 'quiz')
                .replace(/[^\w\s-]/g, '')
                .replace(/\s+/g, '_')
                .substring(0, CONFIG.validation.maxFilenameLength);
            
            const filename = `${CONFIG.pdf.filenamePrefix}${cleanFilename}.pdf`;

            // Clone container to avoid affecting displayed content
            const pdfContainer = container.cloneNode(true);
            pdfContainer.classList.add('pdf-version');
            
            // Remove interactive elements for PDF
            pdfContainer.querySelectorAll('.toolbar-btn, .view-toggle, [contenteditable]').forEach(el => el.remove());
            
            // Add print-specific styles
            const style = document.createElement('style');
            style.textContent = `
                .pdf-version .question-card {
                    page-break-inside: avoid;
                    margin-bottom: 20px;
                }
                .pdf-version .options-container {
                    margin: 10px 0;
                }
                .pdf-version .written-answer-space {
                    min-height: 100px;
                }
                @media print {
                    .quiz-toolbar { display: none !important; }
                }
            `;
            document.head.appendChild(style);

            try {
                const opt = {
                    margin: CONFIG.pdf.margin,
                    filename: filename,
                    image: { type: 'jpeg', quality: 0.95 },
                    html2canvas: { 
                        scale: CONFIG.pdf.scale,
                        useCORS: true,
                        logging: false 
                    },
                    jsPDF: { 
                        unit: 'mm', 
                        format: CONFIG.pdf.format, 
                        orientation: CONFIG.pdf.orientation 
                    },
                    pagebreak: { 
                        mode: ['avoid-all', 'css'],
                        before: '.page-break'
                    }
                };

                await html2pdf().set(opt).from(pdfContainer).save();
            } catch (error) {
                console.error('PDF generation failed:', error);
                throw new Error('Failed to generate PDF. Please try again or use print.');
            } finally {
                // Clean up
                style.remove();
            }
        }
    }

    /* ---------------- UI Event Handlers ---------------- */
    function setupToolbarEvents() {
        // No events to set up since close button is removed
    }

    /* ---------------- Main Render Function ---------------- */
    function renderQuiz(quizDataRaw, forcedViewMode = null) {
        console.log('🎯 renderQuiz called with:', quizDataRaw);

        const section = $(SEC_ID);
        const container = $(CONT_ID);

        if (!section || !container) {
            console.error('Quiz section or container not found in DOM');
            return;
        }

        // Extract quiz data
        const quizData = quizDataRaw?.data || quizDataRaw;
        const questions = safeArray(quizData.questions);

        if (!questions.length) {
            container.innerHTML = `
                <div class="no-questions">
                    <p>No questions available to display.</p>
                </div>
            `;
            unhide(section);
            return;
        }

        // Store quiz data
        quizState.setQuiz(quizData);

        // Determine view mode
        const viewMode = forcedViewMode || ViewModeManager.getMode();

        // Extract settings
        const settings = extractSettings(quizData);
        const title = quizData.title || quizData.metadata?.title || settings.pdf_name || 'Quiz';

        // Build HTML
        const questionsHtml = questions.map((q, i) => toHtml(q, i, viewMode)).join('');

        container.innerHTML = `
            ${renderExamHeader(title, settings, viewMode)}
            ${renderToolbar()}
            <div class="questions-list">
                ${questionsHtml}
            </div>
        `;

        // Setup events
        setupToolbarEvents();

        // Show section
        unhide(section);

        // Scroll to top with a small delay to ensure rendering is complete
        setTimeout(() => {
            section.scrollIntoView({ behavior: CONFIG.ui.scrollBehavior, block: 'start' });
        }, 100);

        quizState.isRendered = true;
    }

    /* ---------------- Public API ---------------- */
    window.renderGeneratedQuiz = function (payload) {
        console.log('📦 renderGeneratedQuiz called with:', payload);
        renderQuiz(payload, 'teacher'); // Always start in teacher mode (answer key)
    };

    /* ---------------- Styles ---------------- */
    function initStyles() {
        if (document.getElementById('publish-styles')) return;

        const style = document.createElement('style');
        style.id = 'publish-styles';
        style.textContent = `
                /* Container - Centered Layout */
                #quiz-section {
                    max-width: 900px;
                    margin: 2rem auto 0 auto;  /* Added top margin of 2rem */
                    padding: 2rem 1rem;
                    position: relative;
                    display: none; /* Hidden by default */
                }

                #quiz-container {
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
                    padding: 2rem;
                    position: relative;
                }

                /* Exam Header */
                .exam-header {
                    margin-bottom: 2rem;
                    text-align: center;
                    position: relative;
                }

                .exam-header-top {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    margin-bottom: 1.5rem;
                    padding: 0;
                    position: relative;
                    min-height: 48px;
                }

                .exam-header h1 {
                    margin: 0;
                    font-size: 2rem;
                    font-weight: 700;
                    color: #1f2937;
                }

                .exam-meta {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 1rem;
                    justify-content: center;
                    margin: 1rem 0;
                    padding: 1rem;
                    background: #f9fafb;
                    border-radius: 6px;
                }

                .meta-item {
                    color: #6b7280;
                    font-size: 0.875rem;
                }

                .meta-item strong {
                    color: #374151;
                    margin-right: 0.25rem;
                }

                .exam-note {
                    flex-basis: 100%;
                    text-align: center;
                    padding: 0.75rem;
                    background: #fef3c7;
                    border: 1px solid #fbbf24;
                    border-radius: 6px;
                    color: #92400e;
                }

                .exam-divider {
                    border: none;
                    border-top: 2px solid #e5e7eb;
                    margin: 1.5rem 0;
                }

                /* Questions */
                .questions-list {
                    display: flex;
                    flex-direction: column;
                    gap: 1.5rem;
                }

                .question-card {
                    background: white;
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                    padding: 1.5rem;
                    transition: all 0.2s ease;
                }

                .question-card:hover {
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
                }

                .question-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 1rem;
                    flex-wrap: wrap;
                    gap: 0.5rem;
                }

                .question-header-left {
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    flex-wrap: wrap;
                }

                .question-header-right {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                }

                .question-number {
                    margin: 0;
                    font-size: 1.125rem;
                    font-weight: 600;
                    color: #1f2937;
                }

                .difficulty-badge {
                    padding: 0.25rem 0.75rem;
                    border-radius: 9999px;
                    font-size: 0.75rem;
                    font-weight: 600;
                    text-transform: uppercase;
                }

                .difficulty-badge[aria-label*="Easy"] {
                    background: #d1fae5;
                    color: #065f46;
                }

                .difficulty-badge[aria-label*="Medium"] {
                    background: #fef3c7;
                    color: #92400e;
                }

                .difficulty-badge[aria-label*="Hard"] {
                    background: #fee2e2;
                    color: #991b1b;
                }

                .question-type {
                    padding: 0.25rem 0.75rem;
                    background: #f3f4f6;
                    color: #4b5563;
                    border-radius: 9999px;
                    font-size: 0.75rem;
                    font-weight: 500;
                }

                .question-text {
                    margin-bottom: 1rem;
                    line-height: 1.6;
                    color: #374151;
                    font-size: 1rem;
                }

                /* Options */
                .options-container {
                    margin: 1rem 0;
                }

                .option {
                    display: flex;
                    align-items: center;
                    padding: 0.75rem;
                    margin-bottom: 0.5rem;
                    background: #f9fafb;
                    border: 1px solid #e5e7eb;
                    border-radius: 6px;
                    transition: all 0.2s ease;
                }

                .option:hover {
                    background: #f3f4f6;
                }

                .option.correct {
                    background: #d1fae5;
                    border-color: #34d399;
                }

                .option-letter {
                    font-weight: 600;
                    margin-right: 0.75rem;
                    color: #6b7280;
                    min-width: 1.5rem;
                }

                .option.correct .option-letter {
                    color: #065f46;
                }

                .option-text {
                    flex: 1;
                    color: #374151;
                }

                .correct-badge {
                    margin-left: 0.75rem;
                    padding: 0.25rem 0.5rem;
                    background: #10b981;
                    color: white;
                    border-radius: 4px;
                    font-size: 0.75rem;
                    font-weight: 600;
                }

                /* Written Answers */
                .written-answer-space {
                    margin: 1rem 0;
                    padding: 1rem;
                    background: #f9fafb;
                    border: 1px solid #e5e7eb;
                    border-radius: 6px;
                }

                .answer-line {
                    height: 1px;
                    background: #d1d5db;
                    margin-bottom: 2rem;
                }

                .answer-line:last-child {
                    margin-bottom: 0;
                }

                .expected-answer {
                    padding: 0.75rem;
                    background: #f0f9ff;
                    border: 1px solid #bae6fd;
                    border-radius: 6px;
                    color: #0369a1;
                    font-family: monospace;
                    white-space: pre-wrap;
                    line-height: 1.5;
                }

                .answer-section {
                    margin-top: 1rem;
                    padding: 1rem;
                    background: #f0fdf4;
                    border: 1px solid #bbf7d0;
                    border-radius: 6px;
                }

                .answer-label {
                    font-weight: 600;
                    color: #166534;
                    margin-bottom: 0.5rem;
                    font-size: 0.875rem;
                }

                /* Correct Answer Section */
                .correct-answer-section {
                    margin-top: 1rem;
                    padding: 0.75rem;
                    background: #f0fdf4;
                    border: 1px solid #bbf7d0;
                    border-radius: 6px;
                }

                .correct-answer-label {
                    font-weight: 600;
                    color: #166534;
                    margin-bottom: 0.25rem;
                    font-size: 0.875rem;
                }

                .correct-answer-content {
                    color: #15803d;
                    line-height: 1.5;
                }

                /* Explanation */
                .explanation {
                    margin-top: 1rem;
                    padding: 0.75rem;
                    background: #fefce8;
                    border: 1px solid #fde047;
                    border-radius: 6px;
                }

                .explanation-label {
                    font-weight: 600;
                    color: #854d0e;
                    margin-bottom: 0.25rem;
                }

                .explanation-content {
                    color: #a16207;
                    line-height: 1.5;
                }

                /* No Questions State */
                .no-questions {
                    padding: 2rem;
                    text-align: center;
                    color: #6b7280;
                    background: #f9fafb;
                    border-radius: 8px;
                    border: 1px dashed #d1d5db;
                }

                /* Loading Spinner Animation */
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }

                /* Print Styles */
                @media print {
                    .question-card {
                        break-inside: avoid;
                        page-break-inside: avoid;
                        border: 1px solid #d1d5db;
                    }

                    .exam-header {
                        break-after: avoid;
                    }

                    body {
                        font-size: 12pt;
                        line-height: 1.5;
                    }
                }

                /* Responsive */
                @media (max-width: 768px) {
                    #quiz-container {
                        padding: 1rem;
                    }

                    .exam-header-top {
                        padding: 0;
                    }

                    .exam-header h1 {
                        font-size: 1.5rem;
                    }
                }
            `;
        document.head.appendChild(style);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initStyles);
    } else {
        initStyles();
    }

})();