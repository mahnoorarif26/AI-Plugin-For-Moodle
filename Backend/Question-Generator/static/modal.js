class ModalManager {
  constructor() {
    this.modalAuto = document.getElementById('modal-auto'); // AI Modal
    this.openBtnAuto = document.getElementById('btn-open-auto');
    this.btnCancelAuto = document.getElementById('btn-cancel');
    this.btnGenAuto = document.getElementById('btn-generate');
    
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
    console.log("AI Quiz modal opened");
    this.modalAuto?.classList.add('open');
  }

  close() {
    console.log("AI Quiz modal closed");
    this.modalAuto?.classList.remove('open');
  }

  initializeUploader() {
    const uploader = document.getElementById('uploader');
    const fileInput = document.getElementById('fileInput');
    
    if (!uploader || !fileInput) return;
    
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
      if(e.dataTransfer.files?.length){ 
        fileInput.files = e.dataTransfer.files; 
        showToast('PDF selected ✔'); 
      }
    });
    
    fileInput.addEventListener('change', () => { 
      if(fileInput.files?.[0]) showToast('PDF selected ✔'); 
    });
  }

  async handleGenerate() {
    // Handle file validation and quiz generation logic
    const fileInput = document.getElementById('fileInput');
    const file = fileInput?.files?.[0];
    if (!file) return showToast('Please select a PDF.');
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) return showToast('Only PDF (.pdf) is accepted.');

    // Prepare the options for the AI-powered quiz
    const options = {
      num_questions: 8,  // Hardcoded for AI Quiz
      question_types: ['mcq', 'short'],  // Always MCQ and Short
      difficulty: { mode: 'auto' },  // Auto difficulty mode
    };

    // Build multipart form-data
    const fd = new FormData();
    fd.append('file', file);
    fd.append('options', JSON.stringify(options));

    try {
      setProgress(10);
      const res = await fetch(API_BASE + ENDPOINT, { method: 'POST', body: fd });
      setProgress(65);

      if(!res.ok){
        const text = await res.text().catch(() => '');
        throw new Error(text || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setProgress(100);

      if (!data || !Array.isArray(data.questions) || data.questions.length === 0){
        showToast('Generated, but no questions returned.');
        console.warn('Empty questions payload:', data);
        return;
      }

      __lastQuizData = data; // Assign the API response to __lastQuizData
      renderQuiz(data.questions, data.metadata);
      this.close();
      showToast(`AI-powered quiz generated ✅ (${data.questions.length} questions)`);
    } catch (err) {
      console.error('Generation error:', err);
      showToast('Failed: ' + (err.message || 'Server error'));
    } finally {
      setTimeout(() => resetProgress(), 600);
    }
  }
}

// Initialize modal manager for AI Quiz modal
document.addEventListener('DOMContentLoaded', function () {
  new ModalManager(); // AI Quiz modal
});