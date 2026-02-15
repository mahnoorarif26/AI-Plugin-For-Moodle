// static/modal.js
// AI-Powered Quiz modal logic

const notify = (msg) => {
  alert(msg);
};

// Helper: save per-quiz settings to backend
async function saveQuizSettings(quizId, { timeLimit, dueDate, note }) {
  if (!quizId) {
    console.error('[modal] No quizId provided to saveQuizSettings');
    return;
  }

  // Allow 0 as "no time limit"
  const safeTimeLimit = Number.isFinite(timeLimit) ? timeLimit : 0;

  try {
    const res = await fetch(`/api/quizzes/${quizId}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        time_limit: safeTimeLimit,
        due_date: dueDate || null,
        note: note || '',
        allow_retakes: false,
        shuffle_questions: true,
      }),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      console.error('[modal] saveQuizSettings failed', res.status, text);
      alert('Failed to save quiz settings: ' + (text || `HTTP ${res.status}`));
    } else {
      console.log(
        '[modal] Settings saved OK for quiz',
        quizId,
        'time_limit=',
        safeTimeLimit,
        'due_date=',
        dueDate,
      );
    }
  } catch (e) {
    console.error('[modal] Failed to save quiz settings:', e);
    alert('Error while saving quiz settings: ' + (e.message || e));
  }
}

class ModalManager {
  constructor() {
    this.modalAuto = document.getElementById('modal-auto'); // AI Modal
    this.openBtnAuto = document.getElementById('btn-open-auto');
    this.btnCancelAuto = document.getElementById('btn-cancel');
    this.btnGenAuto = document.getElementById('btn-generate');
    this.currentPdfName = ''; // Track PDF name

    if (typeof API_BASE === 'undefined' || typeof ENDPOINT === 'undefined') {
      console.warn(
        '[modal] API_BASE or ENDPOINT is not defined globally. Falling back to /api/quiz/from-pdf',
      );
    }

    this.initializeEvents();
  }

  initializeEvents() {
    // Open/close events for AI modal
    this.openBtnAuto?.addEventListener('click', () => this.open());
    this.btnCancelAuto?.addEventListener('click', () => this.close());
    this.modalAuto?.addEventListener('click', (e) => {
      if (e.target === this.modalAuto) this.close();
    });

    // Generate quiz button event for AI modal
    this.btnGenAuto?.addEventListener('click', () => this.handleGenerate());

    // Initialize uploader for AI modal
    this.initializeUploader();
  }

  open() {
    console.log('[modal] AI Quiz modal opened');
    this.modalAuto?.classList.add('open');
  }

  close() {
    console.log('[modal] AI Quiz modal closed');
    this.modalAuto?.classList.remove('open');
  }

  initializeUploader() {
    const uploader = document.getElementById('uploader');
    const fileInput = document.getElementById('fileInput');
    const fileNameDisplay = document.getElementById('fileNameDisplay');

    if (!uploader || !fileInput) return;

    const updateName = () => {
      if (!fileNameDisplay) return;
      if (fileInput.files?.[0]) {
        this.currentPdfName = fileInput.files[0].name;
        fileNameDisplay.textContent = this.currentPdfName;
      } else {
        this.currentPdfName = '';
        fileNameDisplay.textContent = '';
      }
    };

    uploader.addEventListener('click', () => fileInput.click());

    uploader.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploader.classList.add('dragover');
    });

    uploader.addEventListener('dragleave', () => {
      uploader.classList.remove('dragover');
    });

    uploader.addEventListener('drop', (e) => {
      e.preventDefault();
      uploader.classList.remove('dragover');
      if (e.dataTransfer.files?.length) {
        fileInput.files = e.dataTransfer.files;
        updateName();
        notify('PDF selected ✓');
      }
    });

    fileInput.addEventListener('change', () => {
      updateName();
      if (fileInput.files?.[0]) notify('PDF selected');
    });
  }

  // Transform API quiz into the structure expected by renderGeneratedQuiz
  transformFirestoreData(apiData, settings) {
    console.log('📄 Transforming Firestore data:', apiData);

    const data = apiData?.data || apiData || {};
    const transformed = {
      data: {
        ...data,
        // Attach PDF name
        pdf_name: this.currentPdfName || data.pdf_name || 'Quiz',
        // Attach settings so publish.js can read time_limit, due_date, note
        settings: {
          ...(data.settings || {}),
          ...(settings || {}),
        },
        time_limit: settings?.time_limit ?? data.time_limit,
        due_date: settings?.due_date ?? data.due_date,
        note: settings?.note ?? data.note,
        questions: (data.questions || []).map((q) => ({
          ...q,
          question: q.prompt || q.question || '',
          meta:
            q.meta ||
            `Difficulty: ${q.difficulty || 'unknown'}${
              q.tags ? ` | Tags: ${q.tags.join(', ')}` : ''
            }${q.id ? ` | ID: ${q.id}` : ''}`,
        })),
      },
    };

    console.log(' Transformed data:', transformed);
    return transformed;
  }

  async handleGenerate() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput?.files?.[0];
    if (!file) return notify('Please select a PDF.');

    const isPdf =
      file.type === 'application/pdf' ||
      file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) return notify('Only PDF (.pdf) is accepted.');

    // Store PDF name
    this.currentPdfName = file.name;

    // Read settings from modal inputs (if present)
    const timeLimitInput = document.getElementById('auto-time-limit');
    const dueDateInput = document.getElementById('auto-due-date');
    const noteInput = document.getElementById('auto-note');

    const rawTimeLimit = timeLimitInput?.value?.trim() || '';
    const timeLimit = rawTimeLimit ? parseInt(rawTimeLimit, 10) : 0;
    const dueDate = dueDateInput?.value || null; // datetime-local string
    const note = noteInput?.value || '';

    const options = {
      num_questions: 8,
      question_types: ['mcq', 'short'],
      difficulty: { mode: 'auto' },
    };

    const fd = new FormData();
    fd.append('file', file);
    fd.append('options', JSON.stringify(options));

    try {
      setProgress?.(10);
      const url =
        typeof API_BASE !== 'undefined' && typeof ENDPOINT !== 'undefined'
          ? API_BASE + ENDPOINT
          : '/api/quiz/from-pdf';

      console.log('📤 Sending request to:', url);
      const res = await fetch(url, { method: 'POST', body: fd });
      setProgress?.(65);

      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setProgress?.(100);

      console.log('📥 Received API response:', data);

      if (!data || !Array.isArray(data.questions) || data.questions.length === 0) {
        notify('Generated, but no questions returned.');
        console.warn('[modal] Empty questions payload:', data);
        return;
      }

      // Determine quiz ID for saving settings
      const quizId = data.id || data.quiz_id;
      console.log('[modal] Using quizId for settings:', quizId);

      // Save settings to backend (time_limit, due_date, note)
      await saveQuizSettings(quizId, {
        timeLimit: Number.isFinite(timeLimit) ? timeLimit : 0,
        dueDate,
        note,
      });

      // Prepare settings object for renderer/publish.js
      const settingsForRenderer = {
        time_limit: Number.isFinite(timeLimit) && timeLimit > 0 ? timeLimit : 0,
        due_date: dueDate,
        note: note,
      };

      const payloadForRenderer = this.transformFirestoreData(
        data,
        settingsForRenderer,
      );

      console.log('🎯 Calling renderGeneratedQuiz with:', payloadForRenderer);

      if (typeof window.renderGeneratedQuiz === 'function') {
        if (window.showSection) window.showSection('generate');
        window.renderGeneratedQuiz(payloadForRenderer);
        notify(
          `AI-powered quiz generated  (${data.questions.length} questions)`,
        );
      } else if (typeof window.renderQuiz === 'function') {
        // Fallback to legacy renderer if publish.js is not loaded
        if (window.showSection) window.showSection('generate');
        renderQuiz(data.questions, data.metadata || {});
        notify(
          `AI-powered quiz generated  (${data.questions.length} questions)`,
        );
      } else {
        console.error('[modal] No renderer available (renderGeneratedQuiz or renderQuiz).');
        notify('Renderer not available (check publish.js and script.js)');
      }

      this.close();
    } catch (err) {
      console.error('[modal] Generation error:', err);
      notify('Failed: ' + (err.message || 'Server error'));
    } finally {
      setTimeout(() => resetProgress?.(), 600);
    }
  }
}

// Initialize modal manager for AI Quiz modal
document.addEventListener('DOMContentLoaded', function () {
  new ModalManager();
});

// Progress utility functions
function setProgress(percent) {
  const progress = document.getElementById('progress');
  if (progress) {
    progress.style.display = 'block';
    progress.querySelector('div').style.width = percent + '%';
  }
}

function resetProgress() {
  const progress = document.getElementById('progress');
  if (progress) {
    progress.style.display = 'none';
    progress.querySelector('div').style.width = '0%';
  }
}