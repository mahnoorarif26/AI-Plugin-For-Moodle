(function() {
    // Global notification function using toast if available
    const notify = (msg) => {
        if (typeof window.showToast === 'function') {
            window.showToast(msg);
        } else {
            // Fallback to alert with console log for debugging
            console.log('[CustomizeModal]', msg);
            alert(msg);
        }
    };

    // Reuse same settings saver as other flows
    async function saveQuizSettings(quizId, { timeLimit, dueDate, note }) {
        if (!quizId) {
            console.error('[customize] No quizId provided to saveQuizSettings');
            return;
        }
        
        try {
            const response = await fetch(`/api/quizzes/${quizId}/settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    time_limit: Number.isFinite(timeLimit) && timeLimit > 0 ? timeLimit : 0,
                    due_date: dueDate || null,
                    note: note || '',
                    allow_retakes: false,
                    shuffle_questions: true,
                }),
            });

            if (!response.ok) {
                const text = await response.text().catch(() => '');
                console.error('[customize] saveQuizSettings failed', response.status, text);
                notify('Failed to save quiz settings: ' + (text || `HTTP ${response.status}`));
            } else {
                console.log('[customize] Settings saved OK for quiz', quizId, 'time_limit=', timeLimit, 'due_date=', dueDate);
            }
        } catch (e) {
            console.error('[customize] Failed to save quiz settings:', e);
            notify('Error while saving quiz settings: ' + (e.message || e));
        }
    }

    class CustomizeModal {
        constructor() {
            this.modal = document.getElementById('modal-custom');
            this.openBtn = document.getElementById('btn-open-custom');
            this.btnCancel = document.getElementById('btn-cancel-custom');
            this.btnGen = document.getElementById('btn-generate-custom');
            this.progress = document.getElementById('progress-custom');

            this.fileInput = document.getElementById('fileInputCustom');
            this.uploader = document.getElementById('uploader-custom');
            this.fileNameDisplay = document.getElementById('fileNameDisplayCustom');

            this.mcq = document.getElementById('mcqCount');
            this.tf = document.getElementById('tfCount');
            this.shortQ = document.getElementById('shortCount');
            this.longQ = document.getElementById('longCount');

            this.diffMode = document.getElementById('difficultyModeCustom');
            this.easy = document.getElementById('easyPctC');
            this.med = document.getElementById('medPctC');
            this.hard = document.getElementById('hardPctC');
            this.diffRow1 = document.getElementById('diffRowC1');
            this.diffRow2 = document.getElementById('diffRowC2');
            this.btnValidateMix = document.getElementById('btn-validate-mix');

            this.btnDetect = document.getElementById('btn-detect-subtopics');
            this.subtopicsSection = document.getElementById('subtopics-section');
            this.subtopicsList = document.getElementById('subtopics-list');

            // NEW: settings inputs for custom quizzes
            this.customTimeLimit = document.getElementById('custom-time-limit');
            this.customDueDate = document.getElementById('custom-due-date');
            this.customNote = document.getElementById('custom-note');

            this._uploadId = null;
            this._detectedSubtopics = [];
            this._selectedSubtopics = [];
            this.currentPdfName = ''; // Track PDF name

            this.init();
        }

        init() {
            this.openBtn?.addEventListener('click', () => this.open());
            this.btnCancel?.addEventListener('click', () => this.close());
            this.modal?.addEventListener('click', (e) => {
                if (e.target === this.modal) this.close();
            });

            // uploader
            if (this.uploader && this.fileInput) {
                const updateName = () => {
                    if (!this.fileNameDisplay) return;
                    if (this.fileInput.files?.[0]) {
                        this.currentPdfName = this.fileInput.files[0].name;
                        this.fileNameDisplay.textContent = this.currentPdfName;
                        console.log('[customize] PDF selected:', this.currentPdfName);
                    } else {
                        this.currentPdfName = '';
                        this.fileNameDisplay.textContent = '';
                    }
                };

                this.uploader.addEventListener('click', () => this.fileInput.click());

                this.uploader.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    this.uploader.classList.add('dragover');
                });

                this.uploader.addEventListener('dragleave', () => {
                    this.uploader.classList.remove('dragover');
                });

                this.uploader.addEventListener('drop', (e) => {
                    e.preventDefault();
                    this.uploader.classList.remove('dragover');
                    if (e.dataTransfer.files?.[0]) {
                        this.fileInput.files = e.dataTransfer.files;
                        updateName();
                        notify('PDF selected ✓');
                    }
                });

                this.fileInput.addEventListener('change', () => {
                    updateName();
                    if (this.fileInput.files?.[0]) notify('PDF selected ✓');
                });
            }

            // difficulty rows toggle
            const toggleRows = () => {
                const custom = this.diffMode?.value === 'custom';
                if (this.diffRow1) this.diffRow1.style.display = custom ? 'grid' : 'none';
                if (this.diffRow2) this.diffRow2.style.display = custom ? 'grid' : 'none';
            };
            this.diffMode?.addEventListener('change', toggleRows);
            toggleRows();

            // validate difficulty mix
            this.btnValidateMix?.addEventListener('click', () => {
                const easy = +this.easy?.value || 0;
                const med = +this.med?.value || 0;
                const hard = +this.hard?.value || 0;
                const sum = easy + med + hard;
                
                if (sum === 100) {
                    notify('✓ Difficulty mix is perfect (100%)');
                } else {
                    notify('⚠ Current mix: ' + sum + '% (should be 100%)');
                }
            });

            // detect subtopics
            this.btnDetect?.addEventListener('click', async () => {
                if (!this.fileInput?.files?.[0]) {
                    return notify('Please select a PDF first.');
                }
                this.btnDetect.disabled = true;
                const originalText = this.btnDetect.textContent;
                this.btnDetect.textContent = 'Detecting…';

                try {
                    const fd = new FormData();
                    fd.append('file', this.fileInput.files[0]);

                    const res = await fetch(`${window.API_BASE || ''}/api/custom/extract-subtopics`, {
                        method: 'POST',
                        body: fd,
                    });
                    
                    if (!res.ok) {
                        const errorData = await res.json().catch(() => ({}));
                        throw new Error(errorData.error || `HTTP ${res.status}`);
                    }
                    
                    const data = await res.json();

                    this._uploadId = data.upload_id;
                    this._detectedSubtopics = data.subtopics || [];
                    this._selectedSubtopics = [];
                    this.renderSubtopics();
                    notify(`✓ Found ${this._detectedSubtopics.length} subtopics`);
                } catch (e) {
                    console.error('[customize] Detection error:', e);
                    notify('❌ Subtopic detection failed: ' + (e.message || 'Unknown error'));
                } finally {
                    this.btnDetect.disabled = false;
                    this.btnDetect.textContent = originalText;
                }
            });

            // generate quiz
            this.btnGen?.addEventListener('click', () => this.handleGenerate());
        }

        open() {
            console.log('[customize] Customize Now modal opened');
            this.modal?.classList.add('open');
        }

        close() {
            console.log('[customize] Customize Now modal closed');
            this.modal?.classList.remove('open');
        }

        setProgress(p) {
            if (!this.progress) return;
            const bar = this.progress.querySelector('div');
            if (!bar) return;
            
            this.progress.style.display = 'block';
            bar.style.width = Math.max(0, Math.min(100, p)) + '%';
            
            // Optional: Show percentage text
            const percentText = this.progress.querySelector('.progress-percent');
            if (percentText) {
                percentText.textContent = Math.round(p) + '%';
            }
        }

        resetProgress() {
            if (!this.progress) return;
            const bar = this.progress.querySelector('div');
            if (bar) bar.style.width = '0%';
            this.progress.style.display = 'none';
            
            // Optional: Hide percentage text
            const percentText = this.progress.querySelector('.progress-percent');
            if (percentText) {
                percentText.textContent = '';
            }
        }

        resetSubtopics() {
            this._uploadId = null;
            this._detectedSubtopics = [];
            this._selectedSubtopics = [];
            if (this.subtopicsSection) {
                this.subtopicsSection.style.display = 'none';
            }
            if (this.subtopicsList) {
                this.subtopicsList.innerHTML = '';
            }
        }

        renderSubtopics() {
            if (!this.subtopicsSection || !this.subtopicsList) return;
            
            if (!this._detectedSubtopics?.length) {
                this.subtopicsSection.style.display = 'none';
                this.subtopicsList.innerHTML = '';
                return;
            }

            this.subtopicsList.innerHTML = '';
            this._detectedSubtopics.forEach((topic, i) => {
                const row = document.createElement('div');
                row.className = 'subtopic-row';
                
                // Create checkbox with label
                const checkboxId = `subtopic-${i}-${Date.now()}`;
                row.innerHTML = `
                    <div class="subtopic-item">
                        <input type="checkbox" id="${checkboxId}" value="${topic.replace(/"/g, '&quot;')}" />
                        <label for="${checkboxId}">${topic}</label>
                    </div>
                `;

                const checkbox = row.querySelector('input[type="checkbox"]');
                checkbox.addEventListener('change', (e) => {
                    this.handleSubtopicSelection(topic, e.target.checked);
                });

                this.subtopicsList.appendChild(row);
            });
            
            this.subtopicsSection.style.display = 'block';
        }

        handleSubtopicSelection(subtopic, isSelected) {
            if (isSelected) {
                if (!this._selectedSubtopics.includes(subtopic)) {
                    this._selectedSubtopics.push(subtopic);
                }
            } else {
                this._selectedSubtopics = this._selectedSubtopics.filter(
                    (st) => st !== subtopic,
                );
            }
            console.log('[customize] Selected subtopics:', this._selectedSubtopics);
        }

        validateInputs() {
            // Check file
            if (!this.fileInput?.files?.[0]) {
                notify('Please select a PDF file.');
                return false;
            }

            // Check question counts
            const mcq = +this.mcq?.value || 0;
            const tf = +this.tf?.value || 0;
            const short = +this.shortQ?.value || 0;
            const long = +this.longQ?.value || 0;
            const total = mcq + tf + short + long;

            if (total <= 0) {
                notify('Please set at least one question count (MCQ, True/False, Short, or Long).');
                return false;
            }

            // Validate difficulty mix if custom
            if (this.diffMode?.value === 'custom') {
                const easy = +this.easy?.value || 0;
                const med = +this.med?.value || 0;
                const hard = +this.hard?.value || 0;
                const sum = easy + med + hard;
                
                if (sum !== 100) {
                    notify(`Difficulty mix must sum to 100% (currently ${sum}%).`);
                    return false;
                }
            }

            return true;
        }

        async handleGenerate() {
            if (!this.validateInputs()) return;

            const file = this.fileInput?.files?.[0];
            const hasSelectedSubtopics = this._selectedSubtopics.length > 0;

            if (hasSelectedSubtopics) {
                await this.generateFromSubtopics();
            } else {
                await this.generateRegularCustom();
            }
        }

        // ---------- SUBTOPICS-BASED GENERATION ----------
        async generateFromSubtopics() {
            if (!this._uploadId) {
                return notify('Please detect subtopics first.');
            }

            const mcq = +this.mcq?.value || 0;
            const tf = +this.tf?.value || 0;
            const short = +this.shortQ?.value || 0;
            const long = +this.longQ?.value || 0;

            let difficulty = { mode: 'auto' };
            if (this.diffMode?.value === 'custom') {
                const easy = +this.easy?.value || 0;
                const med = +this.med?.value || 0;
                const hard = +this.hard?.value || 0;
                difficulty = { mode: 'custom', easy, medium: med, hard };
            }

            const payload = {
                upload_id: this._uploadId,
                subtopics: this._selectedSubtopics,
                totals: { 
                    mcq, 
                    true_false: tf, 
                    short: short, 
                    long: long 
                },
                difficulty,
            };

            // Read settings from custom modal inputs
            const rawTL = this.customTimeLimit?.value?.trim() || '';
            const timeLimit = rawTL ? parseInt(rawTL, 10) : 0;
            const dueDate = this.customDueDate?.value || null;
            const note = this.customNote?.value || '';

            try {
                this.setProgress(10);
                notify('Generating quiz from subtopics...');
                
                const resp = await fetch(`${window.API_BASE || ''}/api/custom/quiz-from-subtopics`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                this.setProgress(65);

                if (!resp.ok) {
                    const errorData = await resp.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${resp.status}`);
                }
                
                const data = await resp.json();
                this.setProgress(100);

                if (!data || !Array.isArray(data.questions) || data.questions.length === 0) {
                    notify('⚠ Generated, but no questions returned.');
                    console.warn('[customize] Empty questions payload:', data);
                    return;
                }

                const quizId = data.quiz_id || data.id;

                // Save settings
                await saveQuizSettings(quizId, {
                    timeLimit: Number.isFinite(timeLimit) ? timeLimit : 0,
                    dueDate,
                    note,
                });

                const settingsForRenderer = {
                    time_limit: Number.isFinite(timeLimit) && timeLimit > 0 ? timeLimit : 0,
                    due_date: dueDate,
                    note: note,
                };

                const payloadForRenderer = {
                    data: {
                        ...data,
                        pdf_name: this.currentPdfName || data.pdf_name || 'Quiz',
                        settings: {
                            ...(data.settings || {}),
                            ...settingsForRenderer,
                        },
                        time_limit: settingsForRenderer.time_limit,
                        due_date: settingsForRenderer.due_date,
                        note: settingsForRenderer.note,
                    },
                };

                if (typeof window.renderGeneratedQuiz === 'function') {
                    if (window.showSection) window.showSection('generate');
                    window.renderGeneratedQuiz(payloadForRenderer);
                } else if (typeof window.renderQuiz === 'function') {
                    if (window.showSection) window.showSection('generate');
                    window.renderQuiz(data.questions, data.metadata || {});
                } else {
                    console.error('[customize] No renderer available');
                    notify('⚠ Renderer not available (check publish.js and script.js)');
                }

                this.close();
                notify(`✓ Custom quiz generated! (${data.questions.length} questions across ${this._selectedSubtopics.length} subtopics)`);
            } catch (err) {
                console.error('[customize] Subtopics generation error:', err);
                notify('❌ Failed: ' + (err.message || 'Server error'));
            } finally {
                setTimeout(() => this.resetProgress(), 600);
            }
        }

        // ---------- REGULAR CUSTOM GENERATION ----------
        async generateRegularCustom() {
            const file = this.fileInput?.files?.[0];

            const mcq = +this.mcq?.value || 0;
            const tf = +this.tf?.value || 0;
            const short = +this.shortQ?.value || 0;
            const long = +this.longQ?.value || 0;

            const totals = { mcq, true_false: tf, short: short, long: long };
            const totalRequested = mcq + tf + short + long;

            let difficulty = { mode: 'auto' };
            if (this.diffMode?.value === 'custom') {
                const easy = +this.easy?.value || 0;
                const med = +this.med?.value || 0;
                const hard = +this.hard?.value || 0;
                difficulty = { mode: 'custom', easy, medium: med, hard };
            }

            const qtypes = [];
            if (mcq > 0) qtypes.push('mcq');
            if (tf > 0) qtypes.push('true_false');
            if (short > 0) qtypes.push('short');
            if (long > 0) qtypes.push('long');

            const options = {
                num_questions: totalRequested,
                question_types: qtypes,
                difficulty,
                distribution: totals,
            };

            const fd = new FormData();
            fd.append('file', file);
            fd.append('options', JSON.stringify(options));

            // Read settings from custom modal
            const rawTL = this.customTimeLimit?.value?.trim() || '';
            const timeLimit = rawTL ? parseInt(rawTL, 10) : 0;
            const dueDate = this.customDueDate?.value || null;
            const note = this.customNote?.value || '';

            try {
                this.setProgress(10);
                notify('Generating custom quiz...');
                
                const res = await fetch(`${window.API_BASE || ''}/api/quiz/from-pdf`, {
                    method: 'POST',
                    body: fd,
                });
                this.setProgress(65);

                if (!res.ok) {
                    const errorData = await res.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${res.status}`);
                }

                const data = await res.json();
                this.setProgress(100);

                if (!data || !Array.isArray(data.questions) || data.questions.length === 0) {
                    notify('⚠ Generated, but no questions returned.');
                    console.warn('[customize] Empty questions payload:', data);
                    return;
                }

                const quizId = data.id || data.quiz_id;

                await saveQuizSettings(quizId, {
                    timeLimit: Number.isFinite(timeLimit) ? timeLimit : 0,
                    dueDate,
                    note,
                });

                const settingsForRenderer = {
                    time_limit: Number.isFinite(timeLimit) && timeLimit > 0 ? timeLimit : 0,
                    due_date: dueDate,
                    note: note,
                };

                const payloadForRenderer = {
                    data: {
                        ...data,
                        pdf_name: this.currentPdfName || data.pdf_name || 'Quiz',
                        settings: {
                            ...(data.settings || {}),
                            ...settingsForRenderer,
                        },
                        time_limit: settingsForRenderer.time_limit,
                        due_date: settingsForRenderer.due_date,
                        note: settingsForRenderer.note,
                    },
                };

                if (typeof window.renderGeneratedQuiz === 'function') {
                    if (window.showSection) window.showSection('generate');
                    window.renderGeneratedQuiz(payloadForRenderer);
                } else if (typeof window.renderQuiz === 'function') {
                    if (window.showSection) window.showSection('generate');
                    window.renderQuiz(data.questions, data.metadata || {});
                } else {
                    console.error('[customize] No renderer available');
                    notify('⚠ Renderer not available (check publish.js and script.js)');
                }

                this.close();
                notify(`✓ Custom quiz generated! (${data.questions.length} questions)`);
            } catch (err) {
                console.error('[customize] Generation error:', err);
                notify('❌ Failed: ' + (err.message || 'Server error'));
            } finally {
                setTimeout(() => this.resetProgress(), 600);
            }
        }
    }

    // Initialize the modal when DOM is ready
    document.addEventListener('DOMContentLoaded', function () {
        new CustomizeModal();
    });
})();