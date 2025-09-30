/* ===========================
   Modal Management
=========================== */

class ModalManager {
  constructor() {
    this.modal = document.getElementById('modal-auto');
    this.openBtn = document.getElementById('btn-open-auto');
    this.btnCancel = document.getElementById('btn-cancel');
    this.btnGen = document.getElementById('btn-generate');
    
    this.initializeEvents();
  }
  
  initializeEvents() {
    // Open/close events
    this.openBtn?.addEventListener('click', () => this.open());
    this.btnCancel?.addEventListener('click', () => this.close());
    this.modal?.addEventListener('click', (e) => { 
      if (e.target === this.modal) this.close(); 
    });
    
    // Generate button event
    this.btnGen?.addEventListener('click', () => this.handleGenerate());
    
    // Initialize uploader
    this.initializeUploader();
    
    // Initialize difficulty controls
    this.initializeDifficulty();
  }
  
  open() {
    if (this.modal) {
      this.modal.classList.add('open');
    }
  }
  
  close() {
    if (this.modal) {
      this.modal.classList.remove('open');
    }
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
  
  initializeDifficulty() {
    const difficultyMode = document.getElementById('difficultyMode');
    const diffRow = document.getElementById('diffRow');
    const diffRow2 = document.getElementById('diffRow2');
    const btnValidate = document.getElementById('btn-validate');
    
    if (!difficultyMode || !diffRow || !diffRow2) return;
    
    const toggleDiffRows = () => {
      const custom = difficultyMode.value === 'custom';
      diffRow.style.display = custom ? 'grid' : 'none';
      diffRow2.style.display = custom ? 'grid' : 'none';
    };
    
    difficultyMode.addEventListener('change', toggleDiffRows);
    toggleDiffRows(); // Initial call
    
    btnValidate?.addEventListener('click', () => {
      const easyPct = document.getElementById('easyPct');
      const medPct = document.getElementById('medPct');
      const hardPct = document.getElementById('hardPct');
      
      const sum = (+easyPct.value||0) + (+medPct.value||0) + (+hardPct.value||0);
      showToast('Current mix: ' + sum + '%');
    });
  }
  
  async handleGenerate() {
    const fileInput = document.getElementById('fileInput');
    const numQuestions = document.getElementById('numQuestions');
    const difficultyMode = document.getElementById('difficultyMode');
    const easyPct = document.getElementById('easyPct');
    const medPct = document.getElementById('medPct');
    const hardPct = document.getElementById('hardPct');
    const tMCQ = document.getElementById('tMCQ');
    const tTF = document.getElementById('tTF');
    const tShort = document.getElementById('tShort');
    const tLong = document.getElementById('tLong');
    
    // Validation
    const file = fileInput?.files?.[0];
    if(!file){ 
      showToast('Please select a PDF.'); 
      return; 
    }
    
    if(file.type !== 'application/pdf'){ 
      showToast('Only PDF is accepted.'); 
      return; 
    }

    const qCount = numQuestions?.value ? parseInt(numQuestions.value, 10) : null;
    if(qCount !== null && (qCount < 1 || qCount > 100)){ 
      showToast('Questions must be 1–100.'); 
      return; 
    }

    const types = [];
    if(tMCQ?.checked) types.push('mcq');
    if(tTF?.checked) types.push('true_false');
    if(tShort?.checked) types.push('short');
    if(tLong?.checked) types.push('long');
    
    if(types.length === 0){ 
      showToast('Select at least one question type.'); 
      return; 
    }

    const payload = {
      num_questions: qCount,
      question_types: types,
      difficulty: (difficultyMode?.value === 'auto')
        ? { mode: 'auto' }
        : { 
            mode: 'custom', 
            easy: +easyPct?.value||0, 
            medium: +medPct?.value||0, 
            hard: +hardPct?.value||0 
          }
    };

    // If custom difficulty, enforce sum = 100
    if(payload.difficulty.mode === 'custom'){
      const sum = payload.difficulty.easy + payload.difficulty.medium + payload.difficulty.hard;
      if(sum !== 100){ 
        showToast('Difficulty mix must sum to 100%.'); 
        return; 
      }
    }

    // Build multipart form-data
    const fd = new FormData();
    fd.append('file', file);
    fd.append('options', JSON.stringify(payload));

    try {
      setProgress(8);
      const res = await fetch(API_BASE + ENDPOINT, { 
        method: 'POST', 
        body: fd 
      });
      setProgress(66);

      if(!res.ok){
        const text = await res.text().catch(() => '');
        throw new Error(text || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setProgress(100);
      showToast('Quiz generated ✅');
      
      // You can handle the response data here
      console.log('Generated quiz:', data);
      
      // Optional: close modal after success
      // this.close();

    } catch(err) {
      console.error('Generation error:', err);
      showToast('Failed: ' + (err.message || 'Server error'));
    } finally {
      setTimeout(resetProgress, 500);
    }
  }
}

// Initialize modal manager when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  new ModalManager();
});