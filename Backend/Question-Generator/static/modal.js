const notify = (msg) => {
  alert(msg);
};

class ModalManager {
  constructor() {
    this.modalAuto = document.getElementById('modal-auto'); // AI Modal
    this.openBtnAuto = document.getElementById('btn-open-auto');
    this.btnCancelAuto = document.getElementById('btn-cancel');
    this.btnGenAuto = document.getElementById('btn-generate');

    // Optional globals sanity
    if (typeof API_BASE === 'undefined' || typeof ENDPOINT === 'undefined') {
      console.warn('[modal] API_BASE or ENDPOINT is not defined globally.');
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
    console.log("[modal] AI Quiz modal opened");
    this.modalAuto?.classList.add('open');
  }

  close() {
    console.log("[modal] AI Quiz modal closed");
    this.modalAuto?.classList.remove('open');
  }

  initializeUploader() {
  const uploader = document.getElementById('uploader');
  const fileInput = document.getElementById('fileInput');
  const fileNameDisplay = document.getElementById('fileNameDisplay');

  if (!uploader || !fileInput) return;

  const updateName = (file) => {
    if (!fileNameDisplay) return;
    if (file) {
      fileNameDisplay.textContent = file.name;
    } else {
      fileNameDisplay.textContent = '';
    }
  };

  uploader.addEventListener('click', () => fileInput.click());

  uploader.addEventListener('dragover', e => {
    e.preventDefault();
    uploader.classList.add('dragover');
  });

  uploader.addEventListener('dragleave', () => {
    uploader.classList.remove('dragover');
  });

  uploader.addEventListener('drop', e => {
    e.preventDefault();
    uploader.classList.remove('dragover');
    if (e.dataTransfer.files?.length) {
      const file = e.dataTransfer.files[0];
      fileInput.files = e.dataTransfer.files;
      updateName(file);
      notify('PDF selected ✔');
    }
  });

  fileInput.addEventListener('change', () => {
    const file = fileInput.files?.[0] || null;
    updateName(file);
    if (file) notify('PDF selected ✔');
  });
}

  transformFirestoreData(apiData) {
    console.log('🔄 Transforming Firestore data:', apiData);
    
    const data = apiData.data || apiData;
    const transformed = {
      data: {
        ...data,
        questions: (data.questions || []).map(q => ({
          ...q,
          question: q.prompt || q.question || '',
          meta: q.meta || `Difficulty: ${q.difficulty || 'unknown'}${q.tags ? ` | Tags: ${q.tags.join(', ')}` : ''}${q.id ? ` | ID: ${q.id}` : ''}`
        }))
      }
    };
    
    console.log('✅ Transformed data:', transformed);
    return transformed;
  }

  async handleGenerate() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput?.files?.[0];
    if (!file) return notify('Please select a PDF.');
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) return notify('Only PDF (.pdf) is accepted.');

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
      const url = (typeof API_BASE !== 'undefined' && typeof ENDPOINT !== 'undefined')
        ? API_BASE + ENDPOINT
        : '/api/quiz/generate';

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

      const payloadForRenderer = this.transformFirestoreData(data);
      
      console.log('🎯 Calling renderGeneratedQuiz with:', payloadForRenderer);

      if (typeof window.renderGeneratedQuiz === 'function') {
        if (window.showSection) window.showSection('generate');
        window.renderGeneratedQuiz(payloadForRenderer);
        notify(`AI-powered quiz generated ✅ (${data.questions.length} questions)`);
      } else {
        console.error('[modal] window.renderGeneratedQuiz is not available.');
        notify('Error: Renderer not available');
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