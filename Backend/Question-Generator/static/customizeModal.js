// static/customizeModal.js

// Helper to show messages
const notify = (msg) => {
    if (typeof window.showToast === 'function') window.showToast(msg);
    else alert(msg);
};

// Reuse same settings saver as other flows
async function saveQuizSettings(quizId, { timeLimit, dueDate, note }) {
    if (!quizId) return;
    try {
        await fetch(`/api/quizzes/${quizId}/settings`, {
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
    } catch (e) {
        console.error('[customize] Failed to save quiz settings:', e);
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
                    this.fileNameDisplay.textContent = this.fileInput.files[0].name;
                } else {
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
                    notify('PDF selected ✔');
                }
            });

            this.fileInput.addEventListener('change', () => {
                updateName();
                if (this.fileInput.files?.[0]) notify('PDF selected ✔');
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
            const sum =
                (+this.easy?.value || 0) +
                (+this.med?.value || 0) +
                (+this.hard?.value || 0);
            if (typeof window.showToast === 'function') {
                window.showToast('Current mix: ' + sum + '%');
            } else {
                alert('Current mix: ' + sum + '%');
            }
        });

        // detect subtopics
        this.btnDetect?.addEventListener('click', async () => {
            if (!this.fileInput?.files?.[0]) {
                return notify('Select a PDF first.');
            }
            this.btnDetect.disabled = true;
            this.btnDetect.textContent = 'Detecting…';

            try {
                const fd = new FormData();
                fd.append('file', this.fileInput.files[0]);

                const res = await fetch(`${API_BASE}/api/custom/extract-subtopics`, {
                    method: 'POST',
                    body: fd,
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Failed to detect subtopics');

                this._uploadId = data.upload_id;
                this._detectedSubtopics = data.subtopics || [];
                this._selectedSubtopics = [];
                this.renderSubtopics();
                notify(`Found ${this._detectedSubtopics.length} subtopics`);
            } catch (e) {
                console.error(e);
                notify(e.message || 'Subtopic detection failed');
            } finally {
                this.btnDetect.disabled = false;
                this.btnDetect.textContent = 'Detect Subtopics';
            }
        });

        // generate quiz
        this.btnGen?.addEventListener('click', () => this.handleGenerate());
    }

    open() {
        console.log('Customize Now modal opened');
        this.modal?.classList.add('open');
    }

    close() {
        console.log('Customize Now modal closed');
        this.modal?.classList.remove('open');
    }

    setProgress(p) {
        if (!this.progress) return;
        const bar = this.progress.querySelector('div');
        this.progress.style.display = 'block';
        if (bar) bar.style.width = Math.max(0, Math.min(100, p)) + '%';
    }

    resetProgress() {
        if (!this.progress) return;
        const bar = this.progress.querySelector('div');
        this.progress.style.display = 'none';
        if (bar) bar.style.width = '0%';
    }

    resetSubtopics() {
        this._uploadId = null;
        this._detectedSubtopics = [];
        this._selectedSubtopics = [];
        this.subtopicsSection.style.display = 'none';
        this.subtopicsList.innerHTML = '';
    }

    renderSubtopics() {
        if (!this.subtopicsSection || !this.subtopicsList) return;
        if (!this._detectedSubtopics?.length) {
            this.subtopicsSection.style.display = 'none';
            this.subtopicsList.innerHTML = '';
            return;
        }

        this.subtopicsList.innerHTML = '';
        this._detectedSubtopics.forEach((t, i) => {
            const row = document.createElement('div');
            row.className = 'subtopic-row';
            row.innerHTML = `
<label>
  <input type="checkbox" value="${t.replace(/"/g, '"')}" />
  ${t}
</label>`;

            const checkbox = row.querySelector('input[type="checkbox"]');
            checkbox.addEventListener('change', (e) => {
                this.handleSubtopicSelection(t, e.target.checked);
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
        console.log('Selected subtopics:', this._selectedSubtopics);
    }

    async handleGenerate() {
        const file = this.fileInput?.files?.[0];
        if (!file) return notify('Please select a PDF.');
        const isPdf =
            file.type === 'application/pdf' ||
            file.name.toLowerCase().endsWith('.pdf');
        if (!isPdf) return notify('Only PDF (.pdf) is accepted.');

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
        const shortQ = +this.shortQ?.value || 0;
        const longQ = +this.longQ?.value || 0;
        const total = mcq + tf + shortQ + longQ;

        if (total <= 0) return notify('Set at least one question count (MCQ/TF/Short/Long).');

        let difficulty = { mode: 'auto' };
        if (this.diffMode?.value === 'custom') {
            const easy = +this.easy?.value || 0;
            const med = +this.med?.value || 0;
            const hard = +this.hard?.value || 0;
            const sum = easy + med + hard;
            if (sum !== 100) return notify('Difficulty mix must sum to 100%.');
            difficulty = { mode: 'custom', easy, medium: med, hard };
        }

        const payload = {
            upload_id: this._uploadId,
            subtopics: this._selectedSubtopics,
            totals: { mcq, true_false: tf, short: shortQ, long: longQ },
            difficulty,
        };

        // read settings from custom modal inputs
        const rawTL = this.customTimeLimit?.value?.trim() || '';
        const timeLimit = rawTL ? parseInt(rawTL, 10) : 0;
        const dueDate = this.customDueDate?.value || null;
        const note = this.customNote?.value || '';

        try {
            this.setProgress(10);
            const resp = await fetch(`${API_BASE}/api/custom/quiz-from-subtopics`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            this.setProgress(65);

            if (!resp.ok) {
                const t = await resp.text().catch(() => '');
                throw new Error(t || `HTTP ${resp.status}`);
            }
            const data = await resp.json();
            this.setProgress(100);

            if (!data || !Array.isArray(data.questions) || data.questions.length === 0) {
                notify('Generated, but no questions returned.');
                console.warn('Subtopics: Empty questions payload:', data);
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
                window.renderGeneratedQuiz(payloadForRenderer);
            } else if (typeof renderQuiz === 'function') {
                renderQuiz(data.questions, data.metadata || {});
            }

            this.close();
            notify(
                `Customized quiz generated (${data.questions.length} questions across ${this._selectedSubtopics.length} subtopics)`,
            );
        } catch (err) {
            console.error('Subtopics generation error:', err);
            notify('Failed: ' + (err.message || 'Server error'));
        } finally {
            setTimeout(() => this.resetProgress(), 600);
        }
    }

    // ---------- REGULAR CUSTOM GENERATION ----------
    async generateRegularCustom() {
        const file = this.fileInput?.files?.[0];
        if (!file) return notify('Please select a PDF.');
        const isPdf =
            file.type === 'application/pdf' ||
            file.name.toLowerCase().endsWith('.pdf');
        if (!isPdf) return notify('Only PDF (.pdf) is accepted.');

        const mcq = +this.mcq?.value || 0;
        const tf = +this.tf?.value || 0;
        const shortQ = +this.shortQ?.value || 0;
        const longQ = +this.longQ?.value || 0;

        const totals = { mcq, true_false: tf, short: shortQ, long: longQ };
        const totalRequested = mcq + tf + shortQ + longQ;
        if (totalRequested <= 0)
            return notify('Set at least one question count (MCQ/TF/Short/Long).');

        let difficulty = { mode: 'auto' };
        if (this.diffMode?.value === 'custom') {
            const easy = +this.easy?.value || 0;
            const med = +this.med?.value || 0;
            const hard = +this.hard?.value || 0;
            const sum = easy + med + hard;
            if (sum !== 100) return notify('Difficulty mix must sum to 100%.');
            difficulty = { mode: 'custom', easy, medium: med, hard };
        }

        const qtypes = [];
        if (mcq > 0) qtypes.push('mcq');
        if (tf > 0) qtypes.push('true_false');
        if (shortQ > 0) qtypes.push('short');
        if (longQ > 0) qtypes.push('long');

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
            const res = await fetch(`${API_BASE}/api/quiz/from-pdf`, {
                method: 'POST',
                body: fd,
            });
            this.setProgress(65);

            if (!res.ok) {
                const t = await res.text().catch(() => '');
                throw new Error(t || `HTTP ${res.status}`);
            }

            const data = await res.json();
            this.setProgress(100);

            if (!data || !Array.isArray(data.questions) || data.questions.length === 0) {
                notify('Generated, but no questions returned.');
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
                window.renderGeneratedQuiz(payloadForRenderer);
            } else if (typeof renderQuiz === 'function') {
                renderQuiz(data.questions, data.metadata || {});
            }

            this.close();
            notify(`Customized quiz generated (${data.questions.length} questions)`);
        } catch (err) {
            console.error('[customize] Generation error:', err);
            notify('Failed: ' + (err.message || 'Server error'));
        } finally {
            setTimeout(() => this.resetProgress(), 600);
        }
    }
}

document.addEventListener('DOMContentLoaded', function () {
    new CustomizeModal();
});