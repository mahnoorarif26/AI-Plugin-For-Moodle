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
      console.warn(
        'Failed to save quiz settings, but quiz was generated successfully'
      );
    } else {
      console.log(
        '[modal] Settings saved OK for quiz',
        quizId,
        'time_limit=',
        safeTimeLimit,
        'due_date=',
        dueDate
      );
    }
  } catch (e) {
    console.error('[modal] Failed to save quiz settings:', e);
  }
}

class ModalManager {
  constructor() {
    this.modalAuto = document.getElementById('modal-auto');
    this.openBtnAuto = document.getElementById('btn-open-auto');
    this.btnCancelAuto = document.getElementById('btn-cancel');
    this.btnGenAuto = document.getElementById('btn-generate');
    this.currentPdfName = '';
    this.isGenerating = false;

    if (typeof API_BASE === 'undefined' || typeof ENDPOINT === 'undefined') {
      console.warn(
        '[modal] API_BASE or ENDPOINT is not defined globally. Falling back to /api/quiz/from-pdf'
      );
    }

    this.initializeEvents();
  }

  initializeEvents() {
    this.openBtnAuto?.addEventListener('click', () => this.open());
    this.btnCancelAuto?.addEventListener('click', () => this.close());

    this.modalAuto?.addEventListener('click', (e) => {
      if (e.target === this.modalAuto) this.close();
    });

    this.btnGenAuto?.addEventListener('click', () => this.handleGenerate());

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

  // Transform API quiz into the structure expected by editor
  transformFirestoreData(apiData, settings) {
    console.log('📄 Transforming Firestore data:', apiData);

    const data = apiData?.data || apiData || {};

    const transformed = {
      data: {
        ...data,
        pdf_name: this.currentPdfName || data.pdf_name || 'Quiz',
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

    console.log('✅ Transformed data:', transformed);
    return transformed;
  }

  waitForElement(selector, timeout = 5000) {
    return new Promise((resolve, reject) => {
      const element = document.querySelector(selector);
      if (element) {
        resolve(element);
        return;
      }

      const observer = new MutationObserver((mutations, obs) => {
        const foundElement = document.querySelector(selector);
        if (foundElement) {
          obs.disconnect();
          resolve(foundElement);
        }
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true,
      });

      setTimeout(() => {
        observer.disconnect();
        reject(new Error(`Element ${selector} not found within ${timeout}ms`));
      }, timeout);
    });
  }

  async ensureQuizSectionReady() {
    try {
      const quizSection = await this.waitForElement('#quiz-section');

      if (quizSection) {
        quizSection.style.display = 'block';
        quizSection.style.visibility = 'visible';
        quizSection.classList.add('active');
      }

      const quizContainer = await this.waitForElement('#quiz-container');

      if (quizContainer) {
        quizContainer.innerHTML = '<div class="loading">Loading quiz...</div>';
      }

      await new Promise((resolve) => setTimeout(resolve, 100));

      return true;
    } catch (error) {
      console.warn('[modal] Quiz section not ready:', error);
      return false;
    }
  }

  async handleGenerate() {
    if (this.isGenerating) {
      notify('Quiz generation already in progress...');
      return;
    }

    const fileInput = document.getElementById('fileInput');
    const file = fileInput?.files?.[0];

    if (!file) {
      notify('Please select a PDF.');
      return;
    }

    const isPdf =
      file.type === 'application/pdf' ||
      file.name.toLowerCase().endsWith('.pdf');

    if (!isPdf) {
      notify('Only PDF (.pdf) is accepted.');
      return;
    }

    this.currentPdfName = file.name;

    const timeLimitInput = document.getElementById('auto-time-limit');
    const dueDateInput = document.getElementById('auto-due-date');
    const noteInput = document.getElementById('auto-note');

    const rawTimeLimit = timeLimitInput?.value?.trim() || '';
    const timeLimit = rawTimeLimit ? parseInt(rawTimeLimit, 10) : 0;
    const dueDate = dueDateInput?.value || null;
    const note = noteInput?.value || '';

    const options = {
      num_questions: 8,
      question_types: ['mcq', 'short'],
      difficulty: { mode: 'auto' },
    };

    const fd = new FormData();
    fd.append('file', file);
    fd.append('options', JSON.stringify(options));

    this.isGenerating = true;

    if (this.btnGenAuto) {
      this.btnGenAuto.disabled = true;
      this.btnGenAuto.textContent = 'Generating...';
    }

    try {
      setProgress?.(10);

      await this.ensureQuizSectionReady();

      const url =
        typeof API_BASE !== 'undefined' && typeof ENDPOINT !== 'undefined'
          ? API_BASE + ENDPOINT
          : '/api/quiz/from-pdf';

      console.log('📤 Sending request to:', url);

      setProgress?.(30);

      const res = await fetch(url, {
        method: 'POST',
        body: fd,
      });

      setProgress?.(65);

      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || `HTTP ${res.status}`);
      }

      const data = await res.json();

      setProgress?.(90);

      console.log('📥 Received API response:', data);

      if (!data || !Array.isArray(data.questions) || data.questions.length === 0) {
        notify('Generated, but no questions returned.');
        console.warn('[modal] Empty questions payload:', data);
        return;
      }

      const quizId = data.id || data.quiz_id || data?.metadata?.quiz_id;
      console.log('[modal] Using quizId for settings:', quizId);

      const settingsForRenderer = {
        time_limit: Number.isFinite(timeLimit) && timeLimit > 0 ? timeLimit : 0,
        due_date: dueDate,
        note: note,
      };

      const payloadForRenderer = this.transformFirestoreData(
        data,
        settingsForRenderer
      );

      console.log('🎯 Prepared payload for editor:', payloadForRenderer);

      if (typeof window.showSection === 'function') {
        window.showSection('generate');
      }

      await new Promise((resolve) => setTimeout(resolve, 200));

      await saveQuizSettings(quizId, {
        timeLimit: Number.isFinite(timeLimit) ? timeLimit : 0,
        dueDate,
        note,
      });

      const quizPayload = {
        ...(data || {}),
        id: quizId,
        settings: settingsForRenderer,
      };

      sessionStorage.setItem('quiz_editor_data', JSON.stringify(quizPayload));

      setProgress?.(100);
      this.close();

      window.location.href = `/teacher/quiz-editor/${quizId || ''}`;
    } catch (err) {
      console.error('[modal] Generation error:', err);
      notify('❌ Failed: ' + (err.message || 'Server error'));
    } finally {
      this.isGenerating = false;

      if (this.btnGenAuto) {
        this.btnGenAuto.disabled = false;
        this.btnGenAuto.textContent = 'Generate Quiz';
      }

      setTimeout(() => resetProgress?.(), 600);
    }
  }
}

// Initialize modal manager
document.addEventListener('DOMContentLoaded', function () {
  setTimeout(() => {
    new ModalManager();
  }, 100);
});

// Progress utility functions
function setProgress(percent) {
  const progress = document.getElementById('progress');
  if (progress) {
    progress.style.display = 'block';
    const bar = progress.querySelector('div');
    if (bar) bar.style.width = percent + '%';
  }
}

function resetProgress() {
  const progress = document.getElementById('progress');
  if (progress) {
    progress.style.display = 'none';
    const bar = progress.querySelector('div');
    if (bar) bar.style.width = '0%';
  }
}