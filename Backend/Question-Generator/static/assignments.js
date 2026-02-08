(() => {
    const $ = (sel) => document.querySelector(sel);
    const id = (s) => document.getElementById(s);
    const $$ = (sel) => document.querySelectorAll(sel);

    const hasToast = typeof window.showToast === "function";
    const notify = (msg, type = 'info') => {
        if (hasToast) {
            window.showToast(msg, type);
        } else {
            alert(msg);
        }
    };

    const fmtDateTime =
        typeof window.__fmtDateTime === 'function'
            ? window.__fmtDateTime
            : (v) => {
                  try {
                      const d = new Date(v);
                      if (Number.isNaN(d.getTime())) return '';
                      return d.toLocaleString('en-US', {
                          year: 'numeric',
                          month: 'short',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit',
                          hour12: false,
                      });
                  } catch (e) {
                      return '';
                  }
              };

    // Debounce utility for performance
    const debounce = (func, wait) => {
        let timeout;
        return (...args) => {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    };

    // Loading state management
    const LoadingManager = {
        buttons: new Map(),
        
        setLoading(button, isLoading, loadingText = "Processing...") {
            if (!button) return;
            
            if (isLoading) {
                button.dataset.originalText = button.textContent;
                button.disabled = true;
                button.innerHTML = `<span class="loading-spinner" style="display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,0.3);border-radius:50%;border-top-color:#fff;animation:spin 1s ease-in-out infinite;"></span> ${loadingText}`;
                this.buttons.set(button, true);
            } else {
                button.disabled = false;
                button.textContent = button.dataset.originalText || button.textContent;
                this.buttons.delete(button);
            }
        },
        
        setLoadingAll(buttons, isLoading, loadingText) {
            buttons.forEach(btn => this.setLoading(btn, isLoading, loadingText));
        }
    };

    async function saveAssignmentSettings(assignmentId, { timeLimit, dueDate, note }) {
        if (!assignmentId) {
            console.warn('[assignments] No assignment ID provided for saving settings');
            return;
        }
        
        try {
            const response = await fetch(`/api/quizzes/${assignmentId}/settings`, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    time_limit: Number.isFinite(timeLimit) && timeLimit > 0 ? timeLimit : 0,
                    due_date: dueDate || null,
                    note: note || '',
                    allow_retakes: false,
                    shuffle_questions: true,
                }),
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (e) {
            console.error('[assignments] Failed to save assignment settings:', e);
            notify('Failed to save assignment settings. Please try again.', 'error');
            throw e;
        }
    }

    function openModal(modal) {
        if (modal) {
            modal.style.display = "flex";
            modal.setAttribute('aria-hidden', 'false');
            document.body.style.overflow = 'hidden'; // Prevent background scrolling
        }
    }

    function closeModal(modal) {
        if (modal) {
            modal.style.display = "none";
            modal.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = ''; // Restore scrolling
        }
    }

    // Close modal on ESC key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const openModals = $$('.modal[style*="display: flex"], .modal[style*="display:flex"]');
            openModals.forEach(modal => closeModal(modal));
        }
    });

    function closeAssignmentOutput() {
        const container = id("assignment-output");
        if (container) {
            container.style.display = "none";
            container.setAttribute('aria-hidden', 'true');
            notify("Assignment hidden", 'info');
        }
    }

    function showAssignmentOutput() {
        const container = id("assignment-output");
        if (container) {
            container.style.display = "block";
            container.setAttribute('aria-hidden', 'false');
            container.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    // Enhanced rendering with better accessibility and performance
    function renderAssignment(questions, settings = {}) {
        const container = id("assignment-output");
        if (!container) {
            console.warn('[assignments] Assignment output container not found');
            return;
        }

        if (!Array.isArray(questions) || !questions.length) {
            container.innerHTML = `
                <div class="empty-state" role="alert" aria-live="polite">
                    <div class="muted">No assignment tasks generated yet.</div>
                </div>`;
            return;
        }

        const timeLimitText =
            typeof settings.time_limit === 'number' && settings.time_limit > 0
                ? `${settings.time_limit} minutes`
                : '';
        const dueDateText = settings.due_date ? fmtDateTime(settings.due_date) : '';
        const noteText = settings.note && settings.note.trim();

        // Create template strings for better performance
        const headerTemplate = `
            <div class="assignment-header" role="banner">
                <div class="assignment-header-content">
                    <h2 id="assignment-title" class="assignment-title">🎓 Generated Assignment</h2>
                    <p class="assignment-subtitle" aria-describedby="assignment-title">${questions.length} tasks generated</p>
                    ${timeLimitText || dueDateText || noteText ? `
                    <div class="assignment-settings" role="group" aria-label="Assignment settings">
                        ${timeLimitText ? `<div><strong>Time limit:</strong> ${timeLimitText}</div>` : ''}
                        ${dueDateText ? `<div><strong>Due date:</strong> ${dueDateText}</div>` : ''}
                        ${noteText ? `<div><strong>Note:</strong> ${noteText}</div>` : ''}
                    </div>
                    ` : ''}
                </div>
                <button id="close-assignment-btn" class="btn btn-close-assignment" aria-label="Close assignment view">
                    <i class='bx bx-x' aria-hidden="true"></i> Close
                </button>
            </div>`;

        const typeIcons = {
            conceptual: '💡',
            scenario: '🎯',
            research: '🔬',
            project: '🛠️',
            case_study: '📋',
            comparative: '⚖️',
        };

        // Generate questions HTML efficiently
        const questionsHTML = questions.map((q, i) => {
            const text = (q.prompt || q.question_text || "").trim();
            const marks = typeof q.marks !== "undefined" ? q.marks : 10;
            const assignmentType = q.assignment_type || 'task';
            const typeLabel = assignmentType
                .replace(/_/g, ' ')
                .replace(/\b\w/g, (l) => l.toUpperCase());
            const icon = typeIcons[assignmentType] || '📝';

            let html = `
            <div class="question-card assignment-task assignment-${assignmentType}" role="article" aria-label="Task ${i + 1}: ${typeLabel}">
                <div class="question-header">
                    <div>
                        <h3 class="question-title">${icon} Task ${i + 1}</h3>
                        <span class="question-type" aria-label="Type: ${typeLabel}">${typeLabel}</span>
                    </div>
                    <span class="marks" aria-label="${marks} marks">
                        ${marks} marks
                    </span>
                </div>

                <div class="question-text" aria-label="Question text">
                    ${text.replace(/\n/g, "<br>")}
                </div>`;

            // Add optional sections only if they exist
            if (q.context) {
                html += `
                <div class="assignment-context" role="region" aria-label="Context">
                    <strong>📌 Context:</strong>
                    <p>${q.context.replace(/\n/g, "<br>")}</p>
                </div>`;
            }

            if (q.code_snippet) {
                html += `
                <div class="assignment-code" role="region" aria-label="Code snippet">
                    <div class="code-header">
                        <span class="code-icon" aria-hidden="true">💻</span>
                        <strong>Code to Analyze:</strong>
                    </div>
                    <pre><code>${escapeHtml(q.code_snippet)}</code></pre>
                </div>`;
            }

            if (q.requirements?.length) {
                html += `
                <div class="assignment-requirements" role="region" aria-label="Requirements">
                    <strong>✓ Requirements:</strong>
                    <ul>
                        ${q.requirements.map(r => `<li>${escapeHtml(r)}</li>`).join('')}
                    </ul>
                </div>`;
            }

            if (q.deliverables?.length) {
                html += `
                <div class="assignment-deliverables" role="region" aria-label="Expected deliverables">
                    <strong>📦 Expected Deliverables:</strong>
                    <ul>
                        ${q.deliverables.map(d => `<li>${escapeHtml(d)}</li>`).join('')}
                    </ul>
                </div>`;
            }

            if (q.grading_criteria) {
                html += `
                <div class="assignment-grading" role="region" aria-label="Grading criteria">
                    <strong>📊 Grading Criteria:</strong>
                    <p>${escapeHtml(q.grading_criteria)}</p>
                </div>`;
            }

            if (q.learning_objectives?.length) {
                html += `
                <div class="assignment-objectives" role="region" aria-label="Learning objectives">
                    <strong>🎯 Learning Objectives:</strong>
                    <ul>
                        ${q.learning_objectives.map(obj => `<li>${escapeHtml(obj)}</li>`).join('')}
                    </ul>
                </div>`;
            }

            const metaParts = [];
            if (q.word_count) metaParts.push(`📝 ${q.word_count}`);
            if (q.difficulty) metaParts.push(`⚡ ${q.difficulty}`);
            if (q.code_snippet) metaParts.push(`💻 Includes Code`);

            if (metaParts.length) {
                html += `
                <div class="assignment-meta" aria-label="Additional information">
                    ${metaParts.join(' • ')}
                </div>`;
            }

            html += '</div>';
            return html;
        }).join('');

        container.innerHTML = `
            ${headerTemplate}
            <div id="assignment-questions-container" class="questions-container" role="main">
                ${questionsHTML}
            </div>`;

        showAssignmentOutput();

        const closeBtn = id("close-assignment-btn");
        if (closeBtn) {
            closeBtn.addEventListener("click", closeAssignmentOutput);
        }

        // Add keyboard navigation for questions
        const questionCards = container.querySelectorAll('.question-card');
        questionCards.forEach((card, index) => {
            card.setAttribute('tabindex', '0');
            card.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    card.classList.toggle('expanded');
                }
            });
        });

        // Add print functionality
        const printBtn = document.createElement('button');
        printBtn.className = 'btn btn-print-assignment';
        printBtn.innerHTML = '<i class="bx bx-printer"></i> Print';
        printBtn.onclick = () => window.print();
        container.querySelector('.assignment-header').appendChild(printBtn);
    }

    function escapeHtml(unsafe) {
        if (!unsafe) return '';
        const div = document.createElement('div');
        div.textContent = unsafe;
        return div.innerHTML;
    }

    // Validate assignment settings
    function validateAssignmentSettings(timeLimit, dueDate) {
        const errors = [];
        
        if (timeLimit && (isNaN(timeLimit) || timeLimit < 0)) {
            errors.push('Time limit must be a positive number');
        }
        
        if (dueDate) {
            const due = new Date(dueDate);
            const now = new Date();
            if (due < now) {
                errors.push('Due date must be in the future');
            }
        }
        
        return errors;
    }

    async function generateAdvancedAssignmentFromPdf() {
        const fileInput = id("assign-pdf-file");
        const modal = id("modal-assign-pdf");
        const genBtn = id("btn-assign-pdf-detect");

        if (!fileInput || !fileInput.files || !fileInput.files[0]) {
            notify("Please select a PDF file.", 'warning');
            return;
        }

        // Validate file size (max 10MB)
        const file = fileInput.files[0];
        if (file.size > 10 * 1024 * 1024) {
            notify("File size must be less than 10MB.", 'error');
            return;
        }

        // Validate file type
        if (!file.type.includes('pdf') && !file.name.toLowerCase().endsWith('.pdf')) {
            notify("Please select a valid PDF file.", 'error');
            return;
        }

        LoadingManager.setLoading(genBtn, true, "Detecting topics...");

        try {
            const fd = new FormData();
            fd.append("file", file);

            const res1 = await fetch("/api/custom/extract-subtopics", {
                method: "POST",
                body: fd,
            });

            if (!res1.ok) {
                throw new Error(`Subtopic extraction failed: ${res1.status}`);
            }

            const subData = await res1.json();

            if (!subData || subData.success === false) {
                console.error("Subtopic extract error:", subData);
                notify("Subtopic extraction failed. Please try again.", 'error');
                return;
            }

            const uploadId = subData.upload_id;
            const subtopics = subData.subtopics || [];

            if (!uploadId || !subtopics.length) {
                notify("No subtopics detected from the PDF.", 'warning');
                return;
            }

            const chosenSubtopics = subtopics.slice(0, 5);
            LoadingManager.setLoading(genBtn, true, "Generating assignment...");

            const taskDistribution = {
                conceptual: parseInt(id("conceptual-count")?.value || "0", 10),
                scenario: parseInt(id("scenario-count")?.value || "0", 10),
                research: parseInt(id("research-count")?.value || "0", 10),
                project: parseInt(id("project-count")?.value || "0", 10),
                case_study: parseInt(id("case-study-count")?.value || "0", 10),
                comparative: parseInt(id("comparative-count")?.value || "0", 10),
            };

            const totalTasks = Object.values(taskDistribution).reduce((a, b) => a + b, 0);
            if (totalTasks === 0) {
                notify("Please select at least one assignment type (total must be > 0)", 'warning');
                return;
            }

            // Validate settings
            const tlInput = id("assign-time-limit");
            const ddInput = id("assign-due-date");
            const rawTL = tlInput?.value?.trim() || '';
            const timeLimit = rawTL ? parseInt(rawTL, 10) : 0;
            const dueDate = ddInput?.value || null;
            
            const validationErrors = validateAssignmentSettings(timeLimit, dueDate);
            if (validationErrors.length > 0) {
                validationErrors.forEach(error => notify(error, 'error'));
                return;
            }

            const difficulty = id("assign-difficulty")?.value || "auto";
            const scenarioStyle = id("assign-scenario-style")?.value || "auto";

            const payload = {
                upload_id: uploadId,
                subtopics: chosenSubtopics,
                task_distribution: taskDistribution,
                difficulty: difficulty,
                scenario_style: scenarioStyle,
            };

            const res2 = await fetch("/api/custom/advanced-assignment", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            if (!res2.ok) {
                throw new Error(`Assignment generation failed: ${res2.status}`);
            }

            const data2 = await res2.json();

            if (!data2 || !data2.success) {
                console.error("Advanced assignment error:", data2);
                notify("Assignment generation failed: " + (data2.error || "Unknown error"), 'error');
                return;
            }

            const questions = data2.questions || [];

            if (!questions.length) {
                notify("No questions returned for assignment.", 'warning');
                return;
            }

            const noteInput = id("assign-note");
            const note = noteInput?.value || '';
            const assignmentId = data2.assignment_id;

            await saveAssignmentSettings(assignmentId, {
                timeLimit: Number.isFinite(timeLimit) ? timeLimit : 0,
                dueDate,
                note,
            });

            renderAssignment(questions, {
                time_limit: Number.isFinite(timeLimit) && timeLimit > 0 ? timeLimit : 0,
                due_date: dueDate,
                note: note,
            });

            notify(` Generated ${questions.length} assignment tasks!`, 'success');
            closeModal(modal);
            
            // Reset form
            fileInput.value = '';
            id("assignFileNameDisplay").textContent = '';
            
        } catch (err) {
            console.error('PDF Assignment Generation Error:', err);
            notify("Unexpected error while generating assignment from PDF.", 'error');
        } finally {
            LoadingManager.setLoading(genBtn, false);
        }
    }

    async function generateAssignmentFromTopics() {
        const txtEl = id("assign-topics-text");
        const modal = id("modal-assign-topics");
        const genBtn = id("btn-assign-topics-generate");

        const topicText = (txtEl?.value || "").trim();

        if (!topicText) {
            notify("Please enter at least one topic (one per line).", 'warning');
            return;
        }

        LoadingManager.setLoading(genBtn, true, "Generating...");

        try {
            const taskDistribution = {
                conceptual: parseInt(id("topics-conceptual-count")?.value || "0", 10),
                scenario: parseInt(id("topics-scenario-count")?.value || "0", 10),
                research: parseInt(id("topics-research-count")?.value || "0", 10),
                project: parseInt(id("topics-project-count")?.value || "0", 10),
                case_study: parseInt(id("topics-case-study-count")?.value || "0", 10),
                comparative: parseInt(id("topics-comparative-count")?.value || "0", 10),
            };

            const totalTasks = Object.values(taskDistribution).reduce((a, b) => a + b, 0);
            if (totalTasks === 0) {
                notify("Please select at least one assignment type (total must be > 0)", 'warning');
                return;
            }

            // Validate settings
            const tlInput = id("topics-assign-time-limit");
            const ddInput = id("topics-assign-due-date");
            const rawTL = tlInput?.value?.trim() || '';
            const timeLimit = rawTL ? parseInt(rawTL, 10) : 0;
            const dueDate = ddInput?.value || null;
            
            const validationErrors = validateAssignmentSettings(timeLimit, dueDate);
            if (validationErrors.length > 0) {
                validationErrors.forEach(error => notify(error, 'error'));
                return;
            }

            const difficulty = id("topics-assign-difficulty")?.value || "auto";
            const scenarioStyle = id("topics-assign-scenario-style")?.value || "auto";

            const payload = {
                topic_text: topicText,
                task_distribution: taskDistribution,
                difficulty: difficulty,
                scenario_style: scenarioStyle,
            };

            const res = await fetch("/api/custom/advanced-assignment-topics", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            if (!res.ok) {
                throw new Error(`Assignment generation failed: ${res.status}`);
            }

            const data = await res.json();

            if (!data || !data.success) {
                console.error("Assignment from topics error:", data);
                notify("Assignment generation failed: " + (data.error || "Unknown error"), 'error');
                return;
            }

            const questions = data.questions || [];
            if (!questions.length) {
                notify("No questions returned for assignment.", 'warning');
                return;
            }

            const noteInput = id("topics-assign-note");
            const note = noteInput?.value || '';
            const assignmentId = data.assignment_id;

            await saveAssignmentSettings(assignmentId, {
                timeLimit: Number.isFinite(timeLimit) ? timeLimit : 0,
                dueDate,
                note,
            });

            renderAssignment(questions, {
                time_limit: Number.isFinite(timeLimit) && timeLimit > 0 ? timeLimit : 0,
                due_date: dueDate,
                note: note,
            });

            notify(` Generated ${questions.length} assignment tasks!`, 'success');
            closeModal(modal);
            
            // Reset form
            txtEl.value = '';
            
        } catch (err) {
            console.error('Topics Assignment Generation Error:', err);
            notify("Unexpected error while generating assignment from topics.", 'error');
        } finally {
            LoadingManager.setLoading(genBtn, false);
        }
    }

    function setupPdfCard() {
        const openBtn = id("btn-open-assign-pdf");
        const modal = id("modal-assign-pdf");
        const closeBtn = id("btn-assign-pdf-close");
        const cancelBtn = id("btn-assign-pdf-cancel-alt");
        const genBtn = id("btn-assign-pdf-detect");

        if (openBtn && modal) {
            openBtn.addEventListener("click", () => {
                openModal(modal);
                // Focus first input for accessibility
                modal.querySelector('input, select, textarea')?.focus();
            });
        }
        
        const closeButtons = [closeBtn, cancelBtn];
        closeButtons.forEach(btn => {
            if (btn && modal) {
                btn.addEventListener("click", () => closeModal(modal));
            }
        });

        // Close modal when clicking outside content
        if (modal) {
            modal.addEventListener("click", (e) => {
                if (e.target === modal) {
                    closeModal(modal);
                }
            });
        }

        if (genBtn) {
            genBtn.addEventListener("click", generateAdvancedAssignmentFromPdf);
        }
    }

    function setupTopicsCard() {
        const openBtn = id("btn-open-assign-topics");
        const modal = id("modal-assign-topics");
        const closeBtn = id("btn-assign-topics-close");
        const genBtn = id("btn-assign-topics-generate");

        if (openBtn && modal) {
            openBtn.addEventListener("click", () => {
                openModal(modal);
                // Focus textarea for accessibility
                id("assign-topics-text")?.focus();
            });
        }
        if (closeBtn && modal) {
            closeBtn.addEventListener("click", () => closeModal(modal));
        }

        // Close modal when clicking outside content
        if (modal) {
            modal.addEventListener("click", (e) => {
                if (e.target === modal) {
                    closeModal(modal);
                }
            });
        }

        if (genBtn) {
            genBtn.addEventListener("click", generateAssignmentFromTopics);
        }
    }

    function setupManualCard() {
        const manualBtn = id("btn-open-assign-manual");
        if (manualBtn) {
            manualBtn.addEventListener("click", () => {
                window.location.href = "/teacher/manual?mode=assignment";
            });
        }
    }

    function initAssignPdfUploader() {
        const box = id("assign-uploader");
        const input = id("assign-pdf-file");
        const nameBox = id("assignFileNameDisplay");

        if (!box || !input) return;

        const updateName = () => {
            if (!nameBox) return;
            if (input.files && input.files[0]) {
                const file = input.files[0];
                const fileSize = (file.size / (1024 * 1024)).toFixed(2);
                nameBox.innerHTML = `
                    <span>${file.name}</span>
                    <small style="color: #666; font-size: 0.9em;">(${fileSize} MB)</small>
                `;
            } else {
                nameBox.textContent = "";
            }
        };

        box.addEventListener("click", () => input.click());

        box.addEventListener("dragover", (e) => {
            e.preventDefault();
            e.stopPropagation();
            box.classList.add("dragover");
        });

        box.addEventListener("dragleave", (e) => {
            e.preventDefault();
            e.stopPropagation();
            box.classList.remove("dragover");
        });

        box.addEventListener("drop", (e) => {
            e.preventDefault();
            e.stopPropagation();
            box.classList.remove("dragover");
            
            if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                const file = e.dataTransfer.files[0];
                
                // Validate file type
                if (!file.type.includes('pdf') && !file.name.toLowerCase().endsWith('.pdf')) {
                    notify("Please drop a PDF file only.", 'error');
                    return;
                }
                
                // Validate file size
                if (file.size > 10 * 1024 * 1024) {
                    notify("File size must be less than 10MB.", 'error');
                    return;
                }
                
                input.files = e.dataTransfer.files;
                updateName();
                notify("PDF selected ✓", 'success');
            }
        });

        input.addEventListener("change", () => {
            updateName();
            if (input.files && input.files[0]) {
                notify("PDF selected ✓", 'success');
            }
        });
    }

    function setupTotalCounter() {
        const countInputs = document.querySelectorAll('[id$="-count"]:not([id^="topics-"])');
        const totalSpan = id('total-tasks-count');

        if (!totalSpan || countInputs.length === 0) return;

        const updateTotal = debounce(() => {
            let total = 0;
            countInputs.forEach((input) => {
                total += parseInt(input.value || 0);
            });
            totalSpan.textContent = total;

            const display = id('total-tasks-display');
            if (display) {
                if (total === 0) {
                    display.classList.add('error-state');
                    display.classList.remove('warning-state');
                } else if (total > 10) {
                    display.classList.add('warning-state');
                    display.classList.remove('error-state');
                } else {
                    display.classList.remove('error-state', 'warning-state');
                }
            }
        }, 150);

        countInputs.forEach((input) => {
            input.addEventListener('input', updateTotal);
            input.addEventListener('change', updateTotal);
        });

        updateTotal();
    }

    function setupTopicsTotalCounter() {
        const countInputs = document.querySelectorAll('[id^="topics-"][id$="-count"]');
        const totalSpan = id('topics-total-tasks-count');

        if (!totalSpan || countInputs.length === 0) return;

        const updateTotal = debounce(() => {
            let total = 0;
            countInputs.forEach((input) => {
                total += parseInt(input.value || 0);
            });
            totalSpan.textContent = total;

            const display = id('topics-total-tasks-display');
            if (display) {
                if (total === 0) {
                    display.classList.add('error-state');
                    display.classList.remove('warning-state');
                } else if (total > 10) {
                    display.classList.add('warning-state');
                    display.classList.remove('error-state');
                } else {
                    display.classList.remove('error-state', 'warning-state');
                }
            }
        }, 150);

        countInputs.forEach((input) => {
            input.addEventListener('input', updateTotal);
            input.addEventListener('change', updateTotal);
        });

        updateTotal();
    }

    // Add keyboard navigation for modals
    function setupModalKeyboardNavigation() {
        document.addEventListener('keydown', (e) => {
            const modal = document.querySelector('.modal[style*="display: flex"], .modal[style*="display:flex"]');
            if (!modal) return;

            const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
            const firstFocusable = focusable[0];
            const lastFocusable = focusable[focusable.length - 1];

            if (e.key === 'Tab') {
                if (e.shiftKey) {
                    if (document.activeElement === firstFocusable) {
                        e.preventDefault();
                        lastFocusable.focus();
                    }
                } else {
                    if (document.activeElement === lastFocusable) {
                        e.preventDefault();
                        firstFocusable.focus();
                    }
                }
            }
        });
    }

    // Initialize everything when DOM is loaded
    function init() {
        setupPdfCard();
        setupTopicsCard();
        setupManualCard();
        initAssignPdfUploader();
        setupTotalCounter();
        setupTopicsTotalCounter();
        setupModalKeyboardNavigation();

        const assignmentOutput = id("assignment-output");
        if (assignmentOutput) {
            assignmentOutput.style.display = "none";
            assignmentOutput.setAttribute('aria-hidden', 'true');
        }

        // Add CSS for loading spinner
        if (!document.querySelector('#assignment-spinner-styles')) {
            const style = document.createElement('style');
            style.id = 'assignment-spinner-styles';
            style.textContent = `
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
                .loading-spinner {
                    display: inline-block;
                    width: 16px;
                    height: 16px;
                    border: 2px solid rgba(255, 255, 255, 0.3);
                    border-radius: 50%;
                    border-top-color: #fff;
                    animation: spin 1s ease-in-out infinite;
                }
                .error-state {
                    background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%) !important;
                    border-color: #fca5a5 !important;
                    color: #991b1b !important;
                }
                .warning-state {
                    background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%) !important;
                    border-color: #fbbf24 !important;
                    color: #92400e !important;
                }
            `;
            document.head.appendChild(style);
        }
    }

    // Expose public API
    window.AssignmentManager = {
        renderAssignment,
        closeAssignmentOutput,
        showAssignmentOutput,
        generateAdvancedAssignmentFromPdf,
        generateAssignmentFromTopics,
        init
    };

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();