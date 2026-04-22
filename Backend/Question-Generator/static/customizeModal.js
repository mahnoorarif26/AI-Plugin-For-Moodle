(function() {
    // Global notification function using toast if available, fallback to alert
    const notify = (msg, isError = false) => {
        const prefix = isError ? '❌ ' : '✓ ';
        const fullMsg = prefix + msg;
        
        if (typeof window.showToast === 'function') {
            window.showToast(fullMsg, isError ? 'error' : 'success');
        } else {
            // Always show alert for errors, even if toast is available
            if (isError) {
                alert(fullMsg);
            } else {
                console.log('[CustomizeModal]', fullMsg);
                alert(fullMsg);
            }
        }
    };

    // Show error alert
    const showError = (msg) => {
        console.error('[CustomizeModal]', msg);
        alert('❌ ERROR: ' + msg);
    };

    // Reuse same settings saver as other flows
    async function saveQuizSettings(quizId, { timeLimit, dueDate, note }) {
        if (!quizId) {
            showError('No quiz ID provided to save settings');
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
                const errorMsg = `Failed to save quiz settings: ${response.status} ${text}`;
                console.error('[customize]', errorMsg);
                // Don't show alert here - just log, as quiz was already generated
                console.warn(errorMsg);
            } else {
                console.log('[customize] Settings saved OK for quiz', quizId);
            }
        } catch (e) {
            console.error('[customize] Failed to save quiz settings:', e);
            // Don't show alert for this - non-critical error
        }
    }

    class CustomizeModal {
        constructor() {
            // Get modal elements
            this.modal = document.getElementById('modal-custom');
            this.openBtn = document.getElementById('btn-open-custom');
            this.btnCancel = document.getElementById('btn-cancel-custom');
            this.btnGen = document.getElementById('btn-generate-custom');
            this.progress = document.getElementById('progress-custom');

            // File upload elements
            this.fileInput = document.getElementById('fileInputCustom');
            this.uploader = document.getElementById('uploader-custom');
            this.fileNameDisplay = document.getElementById('fileNameDisplayCustom');

            // Question count inputs
            this.mcq = document.getElementById('mcqCount');
            this.tf = document.getElementById('tfCount');
            this.shortQ = document.getElementById('shortCount');
            this.longQ = document.getElementById('longCount');

            // Difficulty inputs
            this.diffMode = document.getElementById('difficultyModeCustom');
            this.easy = document.getElementById('easyPctC');
            this.med = document.getElementById('medPctC');
            this.hard = document.getElementById('hardPctC');
            this.diffRow1 = document.getElementById('diffRowC1');
            this.diffRow2 = document.getElementById('diffRowC2');
            this.btnValidateMix = document.getElementById('btn-validate-mix');

            // Subtopic elements
            this.btnDetect = document.getElementById('btn-detect-subtopics');
            this.subtopicsSection = document.getElementById('subtopics-section');
            this.subtopicsList = document.getElementById('subtopics-list');

            // Settings inputs
            this.customTimeLimit = document.getElementById('custom-time-limit');
            this.customDueDate = document.getElementById('custom-due-date');
            this.customNote = document.getElementById('custom-note');

            // State
            this._uploadId = null;
            this._detectedSubtopics = [];
            this._selectedSubtopics = [];
            this.currentPdfName = '';
            this.isGenerating = false;

            // Validate required elements
            this.validateElements();

            // Initialize
            this.init();
        }

        validateElements() {
            const required = [
                { el: this.modal, name: 'modal-custom' },
                { el: this.fileInput, name: 'fileInputCustom' },
                { el: this.uploader, name: 'uploader-custom' },
                { el: this.btnGen, name: 'btn-generate-custom' }
            ];

            const missing = required.filter(item => !item.el).map(item => item.name);
            
            if (missing.length > 0) {
                showError(`Missing required elements: ${missing.join(', ')}`);
            }
        }

        init() {
            // Open/close events
            this.openBtn?.addEventListener('click', () => this.open());
            this.btnCancel?.addEventListener('click', () => this.close());
            this.modal?.addEventListener('click', (e) => {
                if (e.target === this.modal) this.close();
            });

            // Initialize uploader
            this.initUploader();

            // Difficulty mode toggle
            this.initDifficultyToggle();

            // Validate mix button
            this.btnValidateMix?.addEventListener('click', () => this.validateDifficultyMix());

            // Detect subtopics button
            this.btnDetect?.addEventListener('click', () => this.detectSubtopics());

            // Generate button
            this.btnGen?.addEventListener('click', () => this.handleGenerate());
        }

        initUploader() {
            if (!this.uploader || !this.fileInput) {
                showError('File uploader elements not found');
                return;
            }

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
                    const file = e.dataTransfer.files[0];
                    
                    // Validate file type
                    if (!this.isValidPdf(file)) {
                        showError('Only PDF files are accepted');
                        return;
                    }
                    
                    this.fileInput.files = e.dataTransfer.files;
                    updateName();
                    notify('PDF selected ✓');
                }
            });

            this.fileInput.addEventListener('change', () => {
                if (this.fileInput.files?.[0]) {
                    const file = this.fileInput.files[0];
                    
                    // Validate file type
                    if (!this.isValidPdf(file)) {
                        showError('Only PDF files are accepted');
                        this.fileInput.value = '';
                        this.currentPdfName = '';
                        if (this.fileNameDisplay) {
                            this.fileNameDisplay.textContent = '';
                        }
                        return;
                    }
                    
                    updateName();
                    notify('PDF selected ✓');
                }
            });
        }

        isValidPdf(file) {
            return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
        }

        initDifficultyToggle() {
            if (!this.diffMode) return;

            const toggleRows = () => {
                const custom = this.diffMode.value === 'custom';
                if (this.diffRow1) this.diffRow1.style.display = custom ? 'grid' : 'none';
                if (this.diffRow2) this.diffRow2.style.display = custom ? 'grid' : 'none';
            };
            
            this.diffMode.addEventListener('change', toggleRows);
            toggleRows();
        }

        validateDifficultyMix() {
            const easy = +this.easy?.value || 0;
            const med = +this.med?.value || 0;
            const hard = +this.hard?.value || 0;
            const sum = easy + med + hard;
            
            if (sum === 100) {
                notify('✓ Difficulty mix is perfect (100%)');
            } else {
                showError(`Difficulty mix must sum to 100% (currently ${sum}%)`);
            }
        }

        async detectSubtopics() {
            if (!this.fileInput?.files?.[0]) {
                showError('Please select a PDF file first.');
                return;
            }

            // Validate file type
            if (!this.isValidPdf(this.fileInput.files[0])) {
                showError('Only PDF files are accepted');
                return;
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
                    let errorMsg = `HTTP ${res.status}`;
                    try {
                        const errorData = await res.json();
                        errorMsg = errorData.error || errorMsg;
                    } catch {
                        const text = await res.text();
                        if (text) errorMsg = text;
                    }
                    throw new Error(errorMsg);
                }
                
                const data = await res.json();

                if (!data.subtopics || !Array.isArray(data.subtopics)) {
                    throw new Error('Invalid response format: missing subtopics array');
                }

                this._uploadId = data.upload_id;
                this._detectedSubtopics = data.subtopics;
                this._selectedSubtopics = [];
                
                this.renderSubtopics();
                notify(`✓ Found ${this._detectedSubtopics.length} subtopics`);
                
            } catch (e) {
                console.error('[customize] Detection error:', e);
                showError('Subtopic detection failed: ' + (e.message || 'Unknown error'));
            } finally {
                this.btnDetect.disabled = false;
                this.btnDetect.textContent = originalText;
            }
        }

        renderSubtopics() {
            if (!this.subtopicsSection || !this.subtopicsList) {
                showError('Subtopics section elements not found');
                return;
            }
            
            if (!this._detectedSubtopics?.length) {
                this.subtopicsSection.style.display = 'none';
                this.subtopicsList.innerHTML = '';
                return;
            }

            this.subtopicsList.innerHTML = '';
            
            this._detectedSubtopics.forEach((topic, i) => {
                if (!topic) return; // Skip empty topics
                
                const row = document.createElement('div');
                row.className = 'subtopic-row';
                
                const checkboxId = `subtopic-${i}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
                
                row.innerHTML = `
                    <div class="subtopic-item">
                        <input type="checkbox" id="${checkboxId}" value="${topic.replace(/"/g, '&quot;')}" />
                        <label for="${checkboxId}">${this.escapeHtml(topic)}</label>
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

        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
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
        }

        resetProgress() {
            if (!this.progress) return;
            const bar = this.progress.querySelector('div');
            if (bar) bar.style.width = '0%';
            this.progress.style.display = 'none';
        }

        validateInputs() {
            // Check file
            if (!this.fileInput?.files?.[0]) {
                showError('Please select a PDF file.');
                return false;
            }

            // Validate file type
            if (!this.isValidPdf(this.fileInput.files[0])) {
                showError('Only PDF files are accepted');
                return false;
            }

            // Check question counts
            const mcq = +this.mcq?.value || 0;
            const tf = +this.tf?.value || 0;
            const short = +this.shortQ?.value || 0;
            const long = +this.longQ?.value || 0;
            const total = mcq + tf + short + long;

            if (total <= 0) {
                showError('Please set at least one question count (MCQ, True/False, Short, or Long).');
                return false;
            }

            // Validate counts are not negative
            if (mcq < 0 || tf < 0 || short < 0 || long < 0) {
                showError('Question counts cannot be negative.');
                return false;
            }

            // Validate difficulty mix if custom
            if (this.diffMode?.value === 'custom') {
                const easy = +this.easy?.value || 0;
                const med = +this.med?.value || 0;
                const hard = +this.hard?.value || 0;
                const sum = easy + med + hard;
                
                if (sum !== 100) {
                    showError(`Difficulty mix must sum to 100% (currently ${sum}%).`);
                    return false;
                }

                // Validate percentages are not negative
                if (easy < 0 || med < 0 || hard < 0) {
                    showError('Difficulty percentages cannot be negative.');
                    return false;
                }
            }

            return true;
        }

        async handleGenerate() {
            // Prevent multiple simultaneous generations
            if (this.isGenerating) {
                showError('Quiz generation already in progress. Please wait.');
                return;
            }

            if (!this.validateInputs()) return;

            this.isGenerating = true;
            this.btnGen.disabled = true;
            this.btnGen.textContent = 'Generating...';

            try {
                const file = this.fileInput?.files?.[0];
                const hasSelectedSubtopics = this._selectedSubtopics.length > 0;

                if (hasSelectedSubtopics && this._uploadId) {
                    await this.generateFromSubtopics();
                } else if (hasSelectedSubtopics && !this._uploadId) {
                    showError('Please detect subtopics first before selecting them.');
                } else {
                    await this.generateRegularCustom();
                }
            } catch (error) {
                console.error('[customize] Generation error:', error);
                showError('Failed to generate quiz: ' + (error.message || 'Unknown error'));
            } finally {
                this.isGenerating = false;
                this.btnGen.disabled = false;
                this.btnGen.textContent = 'Generate Custom Quiz';
                setTimeout(() => this.resetProgress(), 600);
            }
        }

        async generateFromSubtopics() {
            if (!this._uploadId) {
                throw new Error('Upload ID not found. Please detect subtopics again.');
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

            // Read settings
            const rawTL = this.customTimeLimit?.value?.trim() || '';
            const timeLimit = rawTL ? parseInt(rawTL, 10) : 0;
            
            if (rawTL && isNaN(timeLimit)) {
                throw new Error('Time limit must be a valid number');
            }
            
            const dueDate = this.customDueDate?.value || null;
            const note = this.customNote?.value || '';

            this.setProgress(10);
            notify('Generating quiz from subtopics...');

            const resp = await fetch(`${window.API_BASE || ''}/api/custom/quiz-from-subtopics`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            
            this.setProgress(65);

            if (!resp.ok) {
                let errorMsg = `HTTP ${resp.status}`;
                try {
                    const errorData = await resp.json();
                    errorMsg = errorData.error || errorMsg;
                } catch {
                    const text = await resp.text();
                    if (text) errorMsg = text;
                }
                throw new Error(errorMsg);
            }
            
            const data = await resp.json();
            this.setProgress(100);

            if (!data || !Array.isArray(data.questions)) {
                throw new Error('Invalid response format from server');
            }

            if (data.questions.length === 0) {
                throw new Error('No questions were generated');
            }

            const quizId = data.quiz_id || data.id;
            if (!quizId) {
                throw new Error('No quiz ID returned from server');
            }

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

            // Render the quiz
            await this.renderQuiz(payloadForRenderer, data);

            this.close();
            notify(`✓ Custom quiz generated! (${data.questions.length} questions across ${this._selectedSubtopics.length} subtopics)`);
        }

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

            // Read settings
            const rawTL = this.customTimeLimit?.value?.trim() || '';
            const timeLimit = rawTL ? parseInt(rawTL, 10) : 0;
            
            if (rawTL && isNaN(timeLimit)) {
                throw new Error('Time limit must be a valid number');
            }
            
            const dueDate = this.customDueDate?.value || null;
            const note = this.customNote?.value || '';

            this.setProgress(10);
            notify('Generating custom quiz...');

            const res = await fetch(`${window.API_BASE || ''}/api/quiz/from-pdf`, {
                method: 'POST',
                body: fd,
            });
            
            this.setProgress(65);

            if (!res.ok) {
                let errorMsg = `HTTP ${res.status}`;
                try {
                    const errorData = await res.json();
                    errorMsg = errorData.error || errorMsg;
                } catch {
                    const text = await res.text();
                    if (text) errorMsg = text;
                }
                throw new Error(errorMsg);
            }

            const data = await res.json();
            this.setProgress(100);

            if (!data || !Array.isArray(data.questions)) {
                throw new Error('Invalid response format from server');
            }

            if (data.questions.length === 0) {
                throw new Error('No questions were generated');
            }

            const quizId = data.id || data.quiz_id;
            if (!quizId) {
                throw new Error('No quiz ID returned from server');
            }

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

            // Render the quiz
            await this.renderQuiz(payloadForRenderer, data);

            this.close();
            notify(`✓ Custom quiz generated! (${data.questions.length} questions)`);
        }

        async renderQuiz(payloadForRenderer, data) {
            // Check if renderer exists
            if (typeof window.renderGeneratedQuiz !== 'function' && 
                typeof window.renderQuiz !== 'function') {
                throw new Error('No quiz renderer available. Check if publish.js is loaded.');
            }

            // Show generate section first
            if (typeof window.showSection === 'function') {
                window.showSection('generate');
            }

            // Small delay to ensure DOM is ready
            await new Promise(resolve => setTimeout(resolve, 100));

            // Try to render
            if (typeof window.renderGeneratedQuiz === 'function') {
                window.renderGeneratedQuiz(payloadForRenderer);
            } else if (typeof window.renderQuiz === 'function') {
                window.renderQuiz(data.questions, data.metadata || {});
            }
        }
    }

    // Initialize the modal when DOM is ready
    document.addEventListener('DOMContentLoaded', function () {
        try {
            new CustomizeModal();
        } catch (error) {
            showError('Failed to initialize Customize Modal: ' + error.message);
        }
    });
})();