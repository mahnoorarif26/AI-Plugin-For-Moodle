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
    this.scenarioCount = document.getElementById('scenarioCount');
    this.codeCount = document.getElementById('codeCount');

    this.diffMode = document.getElementById('difficultyModeCustom');
    this.easy = document.getElementById('easyPctC');
    this.med = document.getElementById('medPctC');
    this.hard = document.getElementById('hardPctC');
    this.diffRow1 = document.getElementById('diffRowC1');
    this.diffRow2 = document.getElementById('diffRowC2');
    this.btnValidateMix = document.getElementById('btn-validate-mix');
    
    // subtopics elements
    this.btnDetect = document.getElementById('btn-detect-subtopics');
    this.subtopicsSection = document.getElementById('subtopics-section');
    this.subtopicsList = document.getElementById('subtopics-list');
    this.countPer = document.getElementById('count-per-subtopic');

    // internal state
    this._uploadId = null;
    this._detectedSubtopics = [];
    this._selectedSubtopics = [];

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
          this.resetSubtopics(); // Reset subtopics when new file is selected
          showToast('PDF selected ✔');
        }
      });
      this.fileInput.addEventListener('change', () => {
        if (this.fileInput.files?.[0]) {
          this.resetSubtopics(); // Reset subtopics when new file is selected
          showToast('PDF selected ✔');
        }
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
    
    // detect subtopics
    this.btnDetect?.addEventListener('click', async () => {
      if (!this.fileInput?.files?.[0]) {
        return showToast('Select a PDF first.');
      }
      this.btnDetect.disabled = true;
      this.btnDetect.textContent = 'Detecting…';

      try {
        const fd = new FormData();
        fd.append('file', this.fileInput.files[0]);

        const res = await fetch(`${API_BASE}/api/custom/extract-subtopics`, {
          method: 'POST',
          body: fd
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to detect subtopics');

        this._uploadId = data.upload_id;
        this._detectedSubtopics = data.subtopics || [];
        this._selectedSubtopics = []; // Reset selections
        this.renderSubtopics();
        showToast(`Found ${this._detectedSubtopics.length} subtopics`);
      } catch (e) {
        console.error(e);
        showToast(e.message || 'Subtopic detection failed');
      } finally {
        this.btnDetect.disabled = false;
        this.btnDetect.textContent = 'Detect Subtopics';
      }
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
      const id = `st_${i}`;
      const row = document.createElement('div');
      row.className = 'subtopic-row';
      row.innerHTML = `
        <label>
          <input type="checkbox" value="${t.replace(/"/g, '&quot;')}" id="${id}" />
          ${t}
        </label>`;
      
      // Add change event listener to track selected subtopics
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
      this._selectedSubtopics = this._selectedSubtopics.filter(st => st !== subtopic);
    }
    console.log('Selected subtopics:', this._selectedSubtopics);
  }

  async handleGenerate() {
    // validate file
    const file = this.fileInput?.files?.[0];
    if (!file) return showToast('Please select a PDF.');
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) return showToast('Only PDF (.pdf) is accepted.');

    // Check if subtopics are selected and use appropriate API
    const hasSelectedSubtopics = this._selectedSubtopics.length > 0;
    
    if (hasSelectedSubtopics) {
      // Use subtopics-based generation
      await this.generateFromSubtopics();
    } else {
      // Use regular customized generation
      await this.generateRegularCustom();
    }
  }

  async generateFromSubtopics() {
  if (!this._uploadId) {
    return showToast('Please detect subtopics first.');
  }

  // take counts from existing inputs (same ones you use for regular custom)
  const mcq    = +this.mcq?.value || 0;
  const tf     = +this.tf?.value || 0;
  const shortQ = +this.shortQ?.value || 0;
  const longQ  = +this.longQ?.value || 0;
  const total  = mcq + tf + shortQ + longQ;

  if (total <= 0) return showToast('Set at least one question count (MCQ/TF/Short/Long).');

  // difficulty
  let difficulty = { mode: 'auto' };
  if (this.diffMode?.value === 'custom') {
    const easy = +this.easy?.value || 0;
    const med  = +this.med?.value  || 0;
    const hard = +this.hard?.value || 0;
    const sum = easy + med + hard;
    if (sum !== 100) return showToast('Difficulty mix must sum to 100%.');
    difficulty = { mode: 'custom', easy, medium: med, hard };
  }

  const payload = {
    upload_id: this._uploadId,
    subtopics: this._selectedSubtopics,
    totals: { mcq, true_false: tf, short: shortQ, long: longQ },
    difficulty,
    scenario_based: (+this.scenarioCount?.value || 0) > 0,
    code_snippet:   (+this.codeCount?.value     || 0) > 0
  };

  try {
    this.setProgress(10);
    const resp = await fetch(`${API_BASE}/api/custom/quiz-from-subtopics`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
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
    showToast(`Customized quiz generated ✅ (${data.questions.length} questions across ${this._selectedSubtopics.length} subtopics)`);
  } catch (err) {
    console.error('Subtopics generation error:', err);
    showToast('Failed: ' + (err.message || 'Server error'));
  } finally {
    setTimeout(() => this.resetProgress(), 600);
  }
}

  async generateRegularCustom() {
    // read counts
    const mcq = +this.mcq?.value || 0;
    const tf = +this.tf?.value || 0;
    const shortQ = +this.shortQ?.value || 0;
    const longQ = +this.longQ?.value || 0;
    const scenarioCount = +this.scenarioCount?.value || 0;
    const codeCount = +this.codeCount?.value || 0;

    const total = mcq + tf + shortQ + longQ + scenarioCount + codeCount;
    if (total <= 0) return showToast('Set at least one question count.');

    // build types (only ones with count > 0)
    const question_types = [];
    if (mcq > 0) question_types.push('mcq');
    if (tf > 0) question_types.push('true_false');
    if (shortQ > 0) question_types.push('short');
    if (longQ > 0) question_types.push('long');

    // Add scenario and code flags
    const scenario_based = scenarioCount > 0;
    const code_snippet = codeCount > 0;

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

    const options = {
      num_questions: total,
      question_types,
      distribution: {
        mcq, true_false: tf, short: shortQ, long: longQ
      },
      scenario_based,
      code_snippet,
      difficulty 
    };

    const fd = new FormData();
    fd.append('file', file); 
    fd.append('options', JSON.stringify(options)); 

    try {
      this.setProgress(10);
      const resp = await fetch(API_BASE + '/api/quiz/from-pdf', { method: 'POST', body: fd });
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