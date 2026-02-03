// static/publish.js
// Enhanced Student/teacher-friendly quiz renderer with improved PDF generation
// Supports both student view (no answers) and teacher view (with answers)

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
            return localStorage.getItem(VIEW_MODE_KEY) || 'student';
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
            show_answers: root.show_answers ?? direct.show_answers ?? metaSettings.show_answers ?? false
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
    function renderExamHeader(title, settings, viewMode = 'student') {
        const { time_limit, due_date, note, total_points } = settings || {};

        const timeLimitText = typeof time_limit === 'number' && time_limit > 0 
            ? `${time_limit} minutes` 
            : '';
        
        const dueDateText = fmtDateTime(due_date);
        const pointsText = total_points ? `${total_points} points` : '';
        
        const hasMeta = !!(timeLimitText || dueDateText || pointsText || (note && note.trim()));
        
        const viewModeIndicator = viewMode === 'teacher' 
            ? '<span class="view-mode-badge teacher-mode">Teacher View</span>' 
            : '<span class="view-mode-badge student-mode">Student View</span>';

        return `
<div class="exam-header">
    <div class="exam-header-top">
        <h1>${escapeHtml(title || 'Quiz')}</h1>
        ${viewModeIndicator}
    </div>
    
    ${hasMeta ? `
    <div class="exam-meta">
        ${timeLimitText ? `<div class="meta-item"><strong>Time limit:</strong> ${timeLimitText}</div>` : ''}
        ${dueDateText ? `<div class="meta-item"><strong>Due date:</strong> ${dueDateText}</div>` : ''}
        ${pointsText ? `<div class="meta-item"><strong>Total points:</strong> ${pointsText}</div>` : ''}
        ${note && note.trim() ? `<div class="exam-note meta-item"><strong>Note:</strong> ${escapeHtml(note.trim())}</div>` : ''}
    </div>
    ` : ''}
    
    <hr class="exam-divider" />
</div>
`;
    }

    /* ---------------- Toolbar with Enhanced Controls ---------------- */
    function renderToolbar() {
        return `
<div class="quiz-toolbar">
    <div class="toolbar-group">
        <button id="btn-download" class="toolbar-btn" title="Download as PDF">
            <svg class="toolbar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            Download PDF
        </button>
        
        <button id="btn-print" class="toolbar-btn" title="Print">
            <svg class="toolbar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="6 9 6 2 18 2 18 9"/>
                <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
                <rect x="6" y="14" width="12" height="8"/>
            </svg>
            Print
        </button>
    </div>
    
    <div class="toolbar-group">
        <button id="btn-toggle-view" class="toolbar-btn toggle-view-btn" title="Toggle between student and teacher view">
            <svg class="toolbar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                <circle cx="12" cy="12" r="3"/>
            </svg>
            <span id="view-mode-label">Teacher View</span>
        </button>
        
        <button id="btn-close-quiz" class="toolbar-btn close-btn" title="Close quiz">
            <svg class="toolbar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
            Close
        </button>
    </div>
</div>
`;
    }

    /* ---------------- Question Renderers ---------------- */
    function renderTrueFalse(viewMode = 'student') {
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

    function renderOptions(q, viewMode = 'student') {
        const ansIdx = getAnswerIndex(q);
        const options = safeArray(q.options);
        const showAnswers = viewMode === 'teacher';

        const items = options.map((opt, i) => {
            const isCorrect = i === ansIdx;
            const shouldShowAnswer = showAnswers && isCorrect;
            
            return `
<div class="option ${shouldShowAnswer ? 'correct' : ''}">
    <span class="option-letter">${letterFrom(i)}.</span>
    <span class="option-text">${escapeHtml(opt ?? '')}</span>
    ${shouldShowAnswer ? `<span class="correct-badge" aria-label="Correct answer">✓</span>` : ''}
</div>
`;
        }).join('');

        return `
<div class="options-container">
    <div class="options">${items}</div>
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

    function renderCorrectAnswer(q, viewMode = 'student') {
        if (viewMode !== 'teacher') return '';
        
        const type = (q.type || '').toLowerCase();
        const opts = safeArray(q.options);
        const ans = q.answer;
        let answerText = '';

        if (type === 'mcq') {
            const idx = getAnswerIndex(q);
            if (idx >= 0 && idx < opts.length) {
                answerText = `<strong>${letterFrom(idx)}.</strong> ${escapeHtml(opts[idx])}`;
            } else if (typeof ans === 'string' && ans.trim()) {
                answerText = escapeHtml(ans.trim());
            }
        } else if (type === 'true_false') {
            if (typeof ans === 'boolean') {
                answerText = ans ? 'True' : 'False';
            } else if (typeof ans === 'string') {
                answerText = escapeHtml(ans.trim());
            }
        } else {
            if (ans != null && String(ans).trim()) {
                answerText = escapeHtml(String(ans).trim());
            }
        }

        if (!answerText) return '';
        
        return `
<div class="correct-answer-section">
    <div class="correct-answer-label">Correct Answer:</div>
    <div class="correct-answer-content">${answerText}</div>
</div>
`;
    }

    function renderQuestionPoints(q) {
        const points = q.points || q.marks || 1;
        return `<span class="question-points" aria-label="${points} point${points !== 1 ? 's' : ''}">${points} pts</span>`;
    }

    /* ---------------- Main Question Renderer ---------------- */
    function toHtml(q, idx, viewMode = 'student') {
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

        // Calculate question value
        const questionValue = q.points || q.marks || 1;

        return `
<article class="question-card" data-question-index="${idx}" data-question-type="${type}" data-question-value="${questionValue}">
    <div class="question-header">
        <div class="question-header-left">
            <h3 class="question-number">Question ${n}</h3>
            ${diffLabel ? `<span class="difficulty-badge" aria-label="Difficulty: ${diffLabel}">${diffLabel}</span>` : ''}
            ${renderQuestionPoints(q)}
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
            
            const filename = `${CONFIG.filenamePrefix}${cleanFilename}.pdf`;

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
                    .close-quiz-btn { display: none !important; }
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
        // Download PDF
        const downloadBtn = $('#btn-download');
        if (downloadBtn && !downloadBtn._wired) {
            downloadBtn.addEventListener('click', handleDownload);
            downloadBtn._wired = true;
        }

        // Print
        const printBtn = $('#btn-print');
        if (printBtn) {
            printBtn.addEventListener('click', () => window.print());
        }

        // Toggle View Mode
        const toggleBtn = $('#btn-toggle-view');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', handleToggleView);
        }

        // Close Quiz
        const closeBtn = $('#btn-close-quiz');
        if (closeBtn) {
            closeBtn.addEventListener('click', handleCloseQuiz);
        }
    }

    async function handleDownload() {
        const btn = $('#btn-download');
        if (!btn) return;

        const originalText = btn.textContent;
        const originalHTML = btn.innerHTML;
        
        try {
            // Show loading state
            btn.disabled = true;
            btn.innerHTML = `
                <span class="loading-spinner" style="display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,0.3);border-radius:50%;border-top-color:#fff;animation:spin 1s linear infinite;margin-right:8px;"></span>
                Generating PDF...
            `;

            const container = $(CONT_ID);
            const quizData = quizState.getQuiz();
            const title = quizData?.title || quizData?.metadata?.title || 'Quiz';
            
            await PDFGenerator.generate(container, title);
            
        } catch (error) {
            console.error('Download error:', error);
            alert(error.message || 'Failed to generate PDF. Please try again.');
        } finally {
            // Restore button state
            btn.disabled = false;
            btn.textContent = originalText;
            btn.innerHTML = originalHTML;
        }
    }

    function handleToggleView() {
        const newMode = ViewModeManager.toggleMode();
        const quizData = quizState.getQuiz();
        
        if (quizData) {
            renderQuiz(quizData, newMode);
            updateViewModeLabel(newMode);
        }
    }

    function handleCloseQuiz() {
        const sec = $(SEC_ID);
        const cont = $(CONT_ID);
        
        if (sec) {
            sec.style.display = 'none';
            sec.setAttribute('aria-hidden', 'true');
        }
        
        if (cont) {
            cont.innerHTML = '';
        }
        
        quizState.clear();
        
        // Clear event listeners
        const downloadBtn = $('#btn-download');
        if (downloadBtn && downloadBtn._wired) {
            downloadBtn._wired = false;
            downloadBtn.onclick = null;
        }
    }

    function updateViewModeLabel(mode) {
        const label = $('#view-mode-label');
        if (label) {
            label.textContent = mode === 'teacher' ? 'Student View' : 'Teacher View';
        }
        
        const toggleBtn = $('#btn-toggle-view');
        if (toggleBtn) {
            toggleBtn.setAttribute('title', `Switch to ${mode === 'teacher' ? 'student' : 'teacher'} view`);
            toggleBtn.setAttribute('aria-label', `Currently in ${mode} view. Click to switch.`);
        }
    }

    /* ---------------- Main Quiz Renderer ---------------- */
    function renderQuiz(quizData, viewMode = null) {
        try {
            const root = quizData?.data || quizData || {};
            const title = root.title || root.metadata?.title || 'Generated Quiz';
            const questions = safeArray(root.questions);
            const settings = extractSettings(root);
            
            const effectiveViewMode = viewMode || ViewModeManager.getMode();

            const sec = $(SEC_ID);
            const cont = $(CONT_ID);
            
            if (!sec || !cont) {
                throw new Error('Quiz section or container not found in HTML');
            }

            // Store quiz data
            quizState.setQuiz(quizData);

            // Show section
            unhide(sec);
            sec.setAttribute('aria-hidden', 'false');

            // Render content
            cont.innerHTML = questions.length
                ? renderExamHeader(title, settings, effectiveViewMode) + 
                  renderToolbar() +
                  questions.map((q, i) => toHtml(q, i, effectiveViewMode)).join('')
                : '<div class="no-questions" role="alert">No questions available for this quiz.</div>';

            // Setup events
            setupToolbarEvents();
            updateViewModeLabel(effectiveViewMode);

            // Add animation
            cont.style.opacity = '0';
            cont.style.transition = `opacity ${CONFIG.ui.animationDuration}ms ease`;
            
            requestAnimationFrame(() => {
                cont.style.opacity = '1';
            });

            // Scroll to quiz
            sec.scrollIntoView({ 
                behavior: CONFIG.ui.scrollBehavior, 
                block: 'start' 
            });

            // Dispatch custom event
            window.dispatchEvent(new CustomEvent('quiz:rendered', {
                detail: { 
                    quizId: root.id || root.quiz_id,
                    questionCount: questions.length,
                    viewMode: effectiveViewMode 
                }
            }));

        } catch (error) {
            console.error('Quiz rendering error:', error);
            alert('Failed to render quiz. Please check console for details.');
            throw error;
        }
    }

    /* ---------------- Public API ---------------- */
    window.renderGeneratedQuiz = function (payload) {
        return renderQuiz(payload);
    };

    window.getCurrentQuizState = function () {
        return quizState.getQuiz();
    };

    window.toggleQuizViewMode = function () {
        return handleToggleView();
    };

    window.closeQuiz = function () {
        return handleCloseQuiz();
    };

    /* ---------------- Initialize ---------------- */
    function initStyles() {
        if (!document.querySelector('#quiz-renderer-styles')) {
            const style = document.createElement('style');
            style.id = 'quiz-renderer-styles';
            style.textContent = `
                /* Quiz Section */
                #${SEC_ID} {
                    position: relative;
                    margin: 2rem 0;
                    padding: 1.5rem;
                    background: #ffffff;
                    border-radius: 12px;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
                    border: 1px solid #e5e7eb;
                }

                /* Toolbar */
                .quiz-toolbar {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 1.5rem;
                    padding: 0.75rem 1rem;
                    background: #f8fafc;
                    border-radius: 8px;
                    border: 1px solid #e2e8f0;
                    flex-wrap: wrap;
                    gap: 0.75rem;
                }

                .toolbar-group {
                    display: flex;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                }

                .toolbar-btn {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.5rem;
                    padding: 0.625rem 1rem;
                    background: #ffffff;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    color: #374151;
                    font-size: 0.875rem;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    text-decoration: none;
                }

                .toolbar-btn:hover {
                    background: #f3f4f6;
                    border-color: #9ca3af;
                    transform: translateY(-1px);
                }

                .toolbar-btn:active {
                    transform: translateY(0);
                }

                .toolbar-btn:disabled {
                    opacity: 0.6;
                    cursor: not-allowed;
                    transform: none;
                }

                .toolbar-icon {
                    width: 1.125rem;
                    height: 1.125rem;
                }

                .close-btn {
                    color: #dc2626;
                    border-color: #fca5a5;
                }

                .close-btn:hover {
                    background: #fef2f2;
                    border-color: #f87171;
                }

                .toggle-view-btn {
                    background: #dbeafe;
                    border-color: #93c5fd;
                    color: #1e40af;
                }

                .toggle-view-btn:hover {
                    background: #bfdbfe;
                    border-color: #60a5fa;
                }

                /* Exam Header */
                .exam-header {
                    margin-bottom: 2rem;
                }

                .exam-header-top {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 1rem;
                    flex-wrap: wrap;
                    gap: 1rem;
                }

                .exam-header h1 {
                    margin: 0;
                    color: #111827;
                    font-size: 1.875rem;
                    font-weight: 700;
                    line-height: 1.2;
                }

                .view-mode-badge {
                    padding: 0.375rem 0.75rem;
                    border-radius: 9999px;
                    font-size: 0.75rem;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                }

                .teacher-mode {
                    background: #fef3c7;
                    color: #92400e;
                    border: 1px solid #fbbf24;
                }

                .student-mode {
                    background: #dbeafe;
                    color: #1e40af;
                    border: 1px solid #93c5fd;
                }

                .exam-meta {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 1rem;
                    margin-top: 0.5rem;
                    padding: 0.75rem;
                    background: #f9fafb;
                    border-radius: 6px;
                    border: 1px solid #e5e7eb;
                }

                .meta-item {
                    font-size: 0.875rem;
                    color: #4b5563;
                }

                .meta-item strong {
                    color: #374151;
                    margin-right: 0.25rem;
                }

                .exam-divider {
                    margin: 1.5rem 0;
                    border: none;
                    height: 1px;
                    background: linear-gradient(90deg, transparent, #d1d5db, transparent);
                }

                /* Question Cards */
                .question-card {
                    margin-bottom: 1.5rem;
                    padding: 1.5rem;
                    background: #ffffff;
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                    transition: box-shadow 0.2s ease;
                }

                .question-card:hover {
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
                }

                .question-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    margin-bottom: 1rem;
                    flex-wrap: wrap;
                    gap: 0.75rem;
                }

                .question-header-left {
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    flex-wrap: wrap;
                }

                .question-number {
                    margin: 0;
                    font-size: 1.125rem;
                    font-weight: 600;
                    color: #111827;
                }

                .difficulty-badge {
                    padding: 0.25rem 0.5rem;
                    border-radius: 4px;
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

                .question-points {
                    padding: 0.25rem 0.5rem;
                    background: #e0e7ff;
                    color: #3730a3;
                    border-radius: 4px;
                    font-size: 0.75rem;
                    font-weight: 600;
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
                    .quiz-toolbar,
                    .close-quiz-btn,
                    .view-mode-badge,
                    .toggle-view-btn {
                        display: none !important;
                    }

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
                    .quiz-toolbar {
                        flex-direction: column;
                        align-items: stretch;
                    }

                    .toolbar-group {
                        width: 100%;
                        justify-content: center;
                    }

                    .toolbar-btn {
                        flex: 1;
                        justify-content: center;
                        min-width: 140px;
                    }

                    .exam-header-top {
                        flex-direction: column;
                        align-items: flex-start;
                    }

                    .question-header {
                        flex-direction: column;
                        align-items: flex-start;
                    }

                    .question-header-right {
                        align-self: stretch;
                    }
                }
            `;
            document.head.appendChild(style);
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initStyles);
    } else {
        initStyles();
    }

})();