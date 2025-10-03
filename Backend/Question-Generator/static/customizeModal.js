class CustomizeModal {
  constructor() {
    this.modal = document.getElementById('modal-custom');
    this.openBtn = document.getElementById('btn-open-custom');
    this.btnCancel = document.getElementById('btn-cancel-custom');
    this.btnGen = document.getElementById('btn-generate-custom');
    this.progress = document.getElementById('progress-custom');

    // inputs
    this.fileInput = document.getElementById('fileInputCustom');
    this.uploader = document.getElementById('uploader-custom');

    this.mcq = document.getElementById('mcqCount');
    this.tf = document.getElementById('tfCount');
    this.shortQ = document.getElementById('shortCount');
    this.longQ = document.getElementById('longCount');

    this.cbScenario = document.getElementById('cbScenario');
    this.cbCode = document.getElementById('cbCode');

    this.diffMode = document.getElementById('difficultyModeCustom');
    this.easy = document.getElementById('easyPctC');
    this.med = document.getElementById('medPctC');
    this.hard = document.getElementById('hardPctC');
    this.diffRow1 = document.getElementById('diffRowC1');
    this.diffRow2 = document.getElementById('diffRowC2');
    this.btnValidateMix = document.getElementById('btn-validate-mix');

    this.init();
  }

  // Initialize event listeners after the class is fully constructed
  init() {
    // open/close modal
    this.openBtn?.addEventListener('click', () => this.open());
    this.btnCancel?.addEventListener('click', () => this.close());
    this.modal?.addEventListener('click', e => { if (e.target === this.modal) this.close(); });

    // uploader actions
    if (this.uploader && this.fileInput) {
      this.uploader.addEventListener('click', () => this.fileInput.click());
      this.uploader.addEventListener('dragover', e => { e.preventDefault(); this.uploader.classList.add('dragover'); });
      this.uploader.addEventListener('dragleave', () => this.uploader.classList.remove('dragover'));
      this.uploader.addEventListener('drop', e => {
        e.preventDefault();
        this.uploader.classList.remove('dragover');
        if (e.dataTransfer.files?.length) {
          this.fileInput.files = e.dataTransfer.files;
          showToast('PDF selected ✔');
        }
      });
      this.fileInput.addEventListener('change', () => {
        if (this.fileInput.files?.[0]) showToast('PDF selected ✔');
      });
    }

    // toggle difficulty rows based on selection
    const toggleRows = () => {
      const custom = this.diffMode?.value === 'custom';
      if (this.diffRow1) this.diffRow1.style.display = custom ? 'grid' : 'none';
      if (this.diffRow2) this.diffRow2.style.display = custom ? 'grid' : 'none';
    };
    this.diffMode?.addEventListener('change', toggleRows);
    toggleRows(); // Initial toggle based on current value

    // validate difficulty mix
    this.btnValidateMix?.addEventListener('click', () => {
      const sum = (+this.easy?.value || 0) + (+this.med?.value || 0) + (+this.hard?.value || 0);
      showToast('Current mix: ' + sum + '%');
    });

    // generate quiz
    this.btnGen?.addEventListener('click', () => this.handleGenerate());
  }

  open() {
    console.log("Customize Now modal opened");
    this.modal?.classList.add('open');
  }

  close() {
    console.log("Customize Now modal closed");
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

  async handleGenerate() {
    // validate file
    const file = this.fileInput?.files?.[0];
    if (!file) return showToast('Please select a PDF.');
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) return showToast('Only PDF (.pdf) is accepted.');

    // read counts
    const mcq = +this.mcq?.value || 0;
    const tf = +this.tf?.value || 0;
    const shortQ = +this.shortQ?.value || 0;
    const longQ = +this.longQ?.value || 0;

    const total = mcq + tf + shortQ + longQ;
    if (total <= 0) return showToast('Set at least one question count.');

    // build types (only ones with count > 0)
    const question_types = [];
    if (mcq > 0) question_types.push('mcq');
    if (tf > 0) question_types.push('true_false');
    if (shortQ > 0) question_types.push('short');
    if (longQ > 0) question_types.push('long');

    // difficulty
    let difficulty = { mode: 'auto' };
    if (this.diffMode?.value === 'custom') {
      const easy = +this.easy?.value || 0;
      const med = +this.med?.value || 0;
      const hard = +this.hard?.value || 0;
      const sum = easy + med + hard;
      if (sum !== 100) return showToast('Difficulty mix must sum to 100%.');
      difficulty = { mode: 'custom', easy, medium: med, hard };
    }

    // final options payload
    const options = {
      num_questions: total, // optional for your backend; keeps UI consistent
      question_types, // ["mcq","true_false","short","long"] (selected only)
      distribution: { // exact counts per type
        mcq, true_false: tf, short: shortQ, long: longQ
      },
      scenario_based: !!this.cbScenario?.checked,
      code_snippet: !!this.cbCode?.checked,
      difficulty // auto or custom %
    };

    // send request
    const fd = new FormData();
    fd.append('file', file); // name MUST be 'file'
    fd.append('options', JSON.stringify(options)); // name MUST be 'options'

    try {
      this.setProgress(10);
      const resp = await fetch(API_BASE + ENDPOINT, { method: 'POST', body: fd });
      this.setProgress(65);

      if (!resp.ok) {
        const t = await resp.text().catch(() => '');
        throw new Error(t || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      this.setProgress(100);

      if (!data || !Array.isArray(data.questions) || data.questions.length === 0) {
        showToast('Generated, but no questions returned.');
        console.warn('Empty questions payload:', data);
        return;
      }

      __lastQuizData = data;
      renderQuiz(data.questions, data.metadata);
      this.close();
      showToast(`Customized quiz generated ✅ (${data.questions.length} questions)`);
    } catch (err) {
      console.error('Customize generation error:', err);
      showToast('Failed: ' + (err.message || 'Server error'));
    } finally {
      setTimeout(() => this.resetProgress(), 600);
    }
  }
}

document.addEventListener('DOMContentLoaded', function () {
  new CustomizeModal(); 
});