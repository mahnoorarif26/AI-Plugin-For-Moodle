/* ===========================
    Modal Management
=========================== */
let __lastQuizData = null;

// Assuming showToast, setProgress, resetProgress, API_BASE, and ENDPOINT are defined globally or in index.html script tags
// And renderQuiz is defined below

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
    
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf){
      showToast('Only PDF (.pdf) is accepted.');
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

    // Build payload object
    const payload = {
      num_questions: qCount,                  // number
      question_types: types,                  // ["mcq","true_false","short","long"]
      difficulty: (difficultyMode?.value === 'auto')
        ? { mode: 'auto' }
        : {
            mode: 'custom',
            easy:   +easyPct?.value || 0,
            medium: +medPct?.value || 0,
            hard:   +hardPct?.value || 0
          }
    };

    // Optional: enforce custom mix sums to 100
    if (payload.difficulty.mode === 'custom') {
      const sum = payload.difficulty.easy + payload.difficulty.medium + payload.difficulty.hard;
      if (sum !== 100) {
        showToast('Difficulty mix must sum to 100%.');
        return;
      }
    }

    // Build multipart form-data (IMPORTANT: exactly these 2 keys)
    const fd = new FormData();
    fd.append('file', file);                  // <-- name must be 'file'
    fd.append('options', JSON.stringify(payload));  // <-- name must be 'options'

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

      if (!data || !Array.isArray(data.questions) || data.questions.length === 0){
        showToast('Generated, but no questions returned.');
        console.warn('Empty questions payload:', data);
      } else {
        __lastQuizData = data;
        renderQuiz(data.questions, data.metadata);
        
        // === NEW LOGIC: Display the Firebase ID ===
        const firebaseId = data.metadata?.firebase_quiz_id;
        let toastMessage = `Quiz generated ✅ (${data.questions.length} questions)`;
        if (firebaseId) {
          // Truncate the ID for a cleaner toast display
          const shortId = firebaseId.substring(0, 8); 
          toastMessage += ` (Saved to DB: ${shortId}...)`;
        }
        showToast(toastMessage);
        // ==========================================
        
        // Close the modal so they see the quiz
        this.close();
      }

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

function renderQuiz(questions, metadata){
  const section = document.getElementById('quiz-section');
  const container = document.getElementById('quiz-container');
  if (!section || !container) return;

  container.innerHTML = "";

  questions.forEach((q, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'quiz-item';

    // Normalize fields (defensive)
    const type = (q.type || q.question_type || '').toString().toLowerCase();
    const prompt = q.question || q.prompt || q.text || '';
    const diff = q.difficulty || q.level || '';
    const opts  = q.options || q.choices || [];
    const ans   = q.answer || q.correct || q.correct_option || '';
    const expl  = q.explanation || q.rationale || '';

    // Build HTML
    const metaBits = [];
    if (type) metaBits.push(type.toUpperCase());
    if (diff) metaBits.push(`Difficulty: ${diff}`);
    const meta = metaBits.length ? `<div class="quiz-meta">${metaBits.join(' • ')}</div>` : '';

    let optsHtml = '';
    if (Array.isArray(opts) && opts.length){
      const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
      optsHtml = `<ol class="quiz-opts">${opts.map((opt, idx) => {
        const letter = letters[idx] || String(idx + 1) + '.';
        const isCorrect = (typeof ans === 'string' && (ans.trim() === opt.trim() || ans.trim().toLowerCase() === letter.toLowerCase()))
                         || (typeof ans === 'number' && ans === idx)
                         || (Array.isArray(ans) && ans.includes(idx));
        return `<li${isCorrect ? ' class="correct"' : ''}>${letter}. ${escapeHtml(opt)}</li>`;
      }).join('')}</ol>`;
    }

    const answerBlock = ans ? `<div><b>Answer:</b> ${escapeHtml(formatAnswer(ans))}</div>` : '';
    const explanation = expl ? `<div><b>Explanation:</b> ${escapeHtml(expl)}</div>` : '';

    wrap.innerHTML = `
      <h4>Q${i+1}. ${escapeHtml(prompt)}</h4>
      ${meta}
      ${optsHtml}
      ${answerBlock}
      ${explanation}
    `;

    container.appendChild(wrap);
  });

  // Export buttons
  const copyBtn = document.getElementById('btn-copy-quiz');
  const saveBtn = document.getElementById('btn-save-json');
  // Re-attach event listeners correctly for dynamic content
  copyBtn?.removeEventListener('click', copyQuizAsText);
  saveBtn?.removeEventListener('click', saveQuizJson);
  copyBtn?.addEventListener('click', copyQuizAsText);
  saveBtn?.addEventListener('click', saveQuizJson);

  const metaEl = document.getElementById('quiz-metadata');
  if (metaEl && metadata){
    const model = metadata.model || 'Unknown Model';
    const totalQ = questions.length;
    const dbId = metadata.firebase_quiz_id ? ` (DB ID: ${metadata.firebase_quiz_id})` : '';
    metaEl.innerHTML = `<p>Generated ${totalQ} questions using ${model}.${dbId}</p>`;
  }

  const quizSection = document.getElementById('quiz-section');
  if (quizSection) {
    quizSection.style.display = 'block';
    quizSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function copyQuizAsText(){
  if (!__lastQuizData?.questions?.length) return;
  const lines = [];
  lines.push('--- Quiz Metadata ---');
  lines.push(`Model: ${__lastQuizData.metadata.model}`);
  if (__lastQuizData.metadata.firebase_quiz_id){
    lines.push(`Database ID: ${__lastQuizData.metadata.firebase_quiz_id}`);
  }
  lines.push('--- Questions ---');

  __lastQuizData.questions.forEach((q, i) => {
    lines.push(`Q${i+1}. ${q.question || q.prompt || q.text || ''}`);
    if (Array.isArray(q.options)){
      q.options.forEach((opt, idx) => lines.push(`   ${String.fromCharCode(65+idx)}. ${opt}`));
    }
    if (q.answer !== undefined) lines.push(`Answer: ${formatAnswer(q.answer)}`);
    if (q.explanation) lines.push(`Explanation: ${q.explanation}`);
    lines.push('');
  });
  const text = lines.join('\n');
  
  // Use document.execCommand('copy') as navigator.clipboard.writeText() may not work in iframes
  const textArea = document.createElement('textarea');
  textArea.value = text;
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  
  try {
    document.execCommand('copy');
    showToast('Copied quiz to clipboard');
  } catch (err) {
    console.error('Failed to copy text:', err);
    showToast('Failed to copy to clipboard.');
  }
  document.body.removeChild(textArea);
}

function saveQuizJson(){
  if (!__lastQuizData) return;
  const blob = new Blob([JSON.stringify(__lastQuizData, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'quiz.json';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  showToast('Saved quiz.json');
}

// helpers
function escapeHtml(str){
  return String(str).replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}
function formatAnswer(ans){
  if (Array.isArray(ans)) return ans.join(', ');
  if (typeof ans === 'number') return String.fromCharCode(65 + ans); // 0->A
  return String(ans);
}
