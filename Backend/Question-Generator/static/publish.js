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

  /* ---------------- Helper Functions ---------------- */
  function prettyType(t) {
    const x = String(t || '').toLowerCase();
    if (x === 'mcq') return 'Multiple Choice';
    if (x === 'true_false') return 'True / False';
    if (x === 'short') return 'Short';
    if (x === 'long') return 'Long';
    return (t || 'Question');
  }

  function prettyDifficulty(d) {
    const x = String(d || '').toLowerCase();
    if (x === 'easy') return 'Easy';
    if (x === 'medium') return 'Medium';
    if (x === 'hard') return 'Hard';
    return '';
  }

  function getAnswerIndex(q) {
    // MCQ answer may be number or string
    const a = q?.answer;
    if (Number.isFinite(a)) return a;
    const n = parseInt(a, 10);
    return Number.isFinite(n) ? n : -1;
  }

  /* ---------------- Exam Header ---------------- */
  function renderExamHeader(title) {
    return `
      <div class="exam-header">
        <h1>${title || 'Quiz'}</h1>
        <hr />
      </div>
    `;
  }

  /* ---------------- Close Quiz Function ---------------- */
  function setupCloseButton() {
    // Get the existing quiz header div
    const quizHead = document.querySelector('.quiz-out-head');
    if (!quizHead) return;
    
    // Check if close button already exists
    let closeBtn = quizHead.querySelector('.close-quiz-btn');
    if (!closeBtn) {
      // Create close button
      closeBtn = document.createElement('button');
      closeBtn.className = 'close-quiz-btn';
      closeBtn.title = 'Close Quiz';
      closeBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      `;
      
      // Add button to header
      quizHead.appendChild(closeBtn);
      
      // Add styles if not already present
      if (!document.querySelector('#close-quiz-styles')) {
        const style = document.createElement('style');
        style.id = 'close-quiz-styles';
        style.textContent = `
          .quiz-out-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
          }
          .close-quiz-btn {
            background: none;
            border: none;
            cursor: pointer;
            padding: 8px;
            border-radius: 4px;
            color: #666;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-left: auto;
          }
          .close-quiz-btn:hover {
            background-color: rgba(0, 0, 0, 0.05);
            color: #333;
          }
          .close-quiz-btn:active {
            background-color: rgba(0, 0, 0, 0.1);
          }
        `;
        document.head.appendChild(style);
      }
    }
    
    // Add click handler
    closeBtn.onclick = function() {
      const sec = $(SEC_ID);
      if (sec) {
        sec.style.display = 'none';
      }
      // Clear the content
      const cont = $(CONT_ID);
      if (cont) {
        cont.innerHTML = '';
      }
      // Reset download button state
      const btn = $('btn-download');
      if (btn && btn._wired) {
        btn._wired = false;
        btn.onclick = null;
      }
    };
  }

  /* ---------------- Renderers ---------------- */
  function renderTrueFalse() {
    return `
      <div class="options-container">
        <div class="option">
          <span class="option-letter">A.</span>
          <span class="option-text">True</span>
        </div>
        <div class="option">
          <span class="option-letter">B.</span>
          <span class="option-text">False</span>
        </div>
      </div>
    `;
  }

  function renderOptions(q) {
    const ansIdx = getAnswerIndex(q);

    const items = safeArray(q.options).map((opt, i) => {
      const isCorrect = i === ansIdx;
      return `
        <div class="option ${isCorrect ? 'correct' : ''}">
          <span class="option-letter">${letterFrom(i)}.</span>
          <span class="option-text">${opt ?? ''}</span>
          ${isCorrect ? `<span class="correct-badge">Correct</span>` : ''}
        </div>
      `;
    }).join('');

    return `
      <div class="options-container">
        <div class="options">${items}</div>
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

  function renderCorrectAnswer(q) {
    const type = (q.type || '').toLowerCase();
    const opts = safeArray(q.options);
    const ans = q.answer;

    let answerText = '';

    if (type === 'mcq') {
      const idx = getAnswerIndex(q);
      if (idx >= 0 && idx < opts.length) {
        answerText = `${letterFrom(idx)}. ${opts[idx]}`;
      } else if (typeof ans === 'string' && ans.trim()) {
        answerText = ans.trim();
      }
    } else if (type === 'true_false') {
      if (typeof ans === 'boolean') answerText = ans ? 'True' : 'False';
      else if (typeof ans === 'string') answerText = ans.trim();
    } else {
      if (ans != null && String(ans).trim()) answerText = String(ans).trim();
    }

    if (!answerText) return '';
    return `<div class="correct-answer"><strong>Correct Answer:</strong> ${answerText}</div>`;
  }

  function toHtml(q, idx) {
    const n = idx + 1;
    const type = (q.type || '').toLowerCase();

    const typeLabel = prettyType(q.type);
    const diffLabel = prettyDifficulty(q.difficulty);

    let body = '';
    if (type === 'mcq' && Array.isArray(q.options)) {
      body = renderOptions(q);
    } else if (type === 'true_false') {
      body = renderTrueFalse();
    } else {
      // short/long => show expected answer section instead of blank lines
      const expected = (q.answer ?? q.expected_answer ?? '').toString();
      body = `
        <div class="answer-section">
          <div class="answer-label">Expected Answer:</div>
          <div class="expected-answer">${expected || '—'}</div>
        </div>
      `;
    }

    const explanation = (q.explanation || '').trim();

    return `
      <article class="question-card">
        <div class="question-header">
          <div>
            <h3>Question ${n}</h3>
            ${diffLabel ? `<div class="difficulty-badge">${diffLabel}</div>` : ''}
          </div>
          <div class="question-type">${typeLabel}</div>
        </div>

        <div class="question-text">${q.question || q.prompt || ''}</div>

        ${body}

        ${explanation ? `<div class="explanation"><strong>Explanation:</strong><br/>${explanation}</div>` : ''}
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

      // Setup the close button in the existing header
      setupCloseButton();

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