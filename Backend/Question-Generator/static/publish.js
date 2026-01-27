// static/publish.js
// Student-friendly quiz renderer (Download-only, Manual Attempt)
// Generates exam-style PDF (no answers, no metadata, no solutions)

(function () {
  const SEC_ID  = 'quiz-section';
  const CONT_ID = 'quiz-container';

  /* ---------------- Utilities ---------------- */
  function $(id) {
    return document.getElementById(id);
  }

  function safeArray(x) {
    return Array.isArray(x) ? x : [];
  }

  function letterFrom(i) {
    return String.fromCharCode(65 + i); // 0 -> A
  }

  function unhide(el) {
    if (!el) return;
    el.style.removeProperty('display');
    if (getComputedStyle(el).display === 'none') {
      el.style.display = 'block';
    }
  }

  /* ---------------- Exam Header ---------------- */
  function renderExamHeader(title) {
    return `
      <div class="exam-header">
        <h1>${title || 'Quiz / Examination'}</h1>

        <div class="exam-meta">
          <div><strong>Course:</strong> _______________________</div>
          <div><strong>Date:</strong> _______________________</div>
        </div>

        <div class="exam-student">
          <div><strong>Name:</strong> _____________________________</div>
          <div><strong>Roll No / ID:</strong> _____________________</div>
          <div><strong>Section:</strong> _________________________</div>
        </div>

        <hr />
      </div>
    `;
  }

  /* ---------------- Renderers ---------------- */
  function renderOptions(q) {
    const items = safeArray(q.options).map((opt, i) => `
      <div class="option">
        <span class="option-letter">${letterFrom(i)}.</span>
        <span class="option-text">${opt ?? ''}</span>
      </div>
    `).join('');

    return `
      <div class="options-container">
        ${items}
      </div>
    `;
  }

  function renderTrueFalse() {
    return `
      <div class="options-container">
        <div class="option"><span class="option-letter">A.</span> True</div>
        <div class="option"><span class="option-letter">B.</span> False</div>
      </div>
    `;
  }

  function renderWrittenSpace(lines = 4) {
    return `
      <div class="written-answer-space">
        ${Array.from({ length: lines }).map(() => `<div class="answer-line"></div>`).join('')}
      </div>
    `;
  }

  function toHtml(q, idx) {
    const n = idx + 1;
    const type = (q.type || '').toLowerCase();

    let body = '';
    if (type === 'mcq' && Array.isArray(q.options)) {
      body = renderOptions(q);
    } else if (type === 'true_false') {
      body = renderTrueFalse();
    } else {
      body = renderWrittenSpace(5);
    }

    return `
      <article class="question-card">
        <h3>Q${n}.</h3>
        <div class="question-text">${q.question || q.prompt || ''}</div>
        ${body}
      </article>
    `;
  }

  /* ---------------- PDF Generation ---------------- */
  async function generatePDF(filenameHint) {
    const quizContent = $(CONT_ID);
    if (!quizContent) throw new Error('Quiz container not found');

    if (typeof html2pdf === 'undefined') {
      window.print();
      return;
    }

    const opt = {
      margin: [12, 12, 12, 12],
      filename: `${(filenameHint || 'quiz').replace(/\s+/g, '_')}.pdf`,
      image: { type: 'jpeg', quality: 0.98 },
      html2canvas: { scale: 2 },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      pagebreak: { mode: ['avoid-all', 'css'] }
    };

    await html2pdf().set(opt).from(quizContent).save();
  }

  /* ---------------- Public API ---------------- */
  window.renderGeneratedQuiz = function (payload) {
    try {
      const root = payload?.data || payload || {};
      const title = root.title || root.metadata?.title || 'Quiz';
      const questions = safeArray(root.questions);

      const sec  = $(SEC_ID);
      const cont = $(CONT_ID);
      if (!sec || !cont) {
        alert('Quiz section not found in HTML');
        return;
      }

      unhide(sec);

      cont.innerHTML = questions.length
        ? renderExamHeader(title) + questions.map(toHtml).join('')
        : `<div class="no-questions">No questions available</div>`;

      const btn = $('btn-download');
      if (btn && !btn._wired) {
        btn.onclick = async () => {
          try {
            btn.disabled = true;
            const old = btn.textContent;
            btn.textContent = 'Preparing PDF...';
            await generatePDF(title);
            btn.textContent = old;
          } catch (e) {
            alert('Failed to download quiz');
          } finally {
            btn.disabled = false;
          }
        };
        btn._wired = true;
      }

      sec.scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (e) {
      console.error('renderGeneratedQuiz error:', e);
      alert('Failed to render quiz');
    }
  };

})();
