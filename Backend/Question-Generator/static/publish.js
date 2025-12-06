// static/publish.js
// Renders generated quiz data into #quiz-container and wires header buttons.
// Requires these elements in HTML:
// <section id="quiz-section" style="display:none">
//   <div class="quiz-out-head">
//     <button id="btn-copy-quiz"></button>
//     <button id="btn-save-json"></button>
//     <button id="btn-publish"></button>
//     <span id="publish-note"></span>
//   </div>
//   <div id="quiz-container" class="quiz-out"></div>
// </section>

(function () {
  const SEC_ID  = 'quiz-section';
  const CONT_ID = 'quiz-container';

  // -------- Utilities --------
  function $(id) { return document.getElementById(id); }
  function letterFrom(i) { return String.fromCharCode(65 + i); } // 0->A
  const noop = () => {};

  function safeArray(x) { return Array.isArray(x) ? x : []; }
  function unhideSection(el) {
    if (!el) return;
    el.style.removeProperty('display');
    if (getComputedStyle(el).display === 'none') {
      el.style.display = 'block';
    }
  }

  // Try to deduce correct option index from q.answer
  function detectCorrectIndex(q) {
    if (!q || !Array.isArray(q.options)) return -1;
    const ans = (q.answer || '').toString().trim();
    if (!ans) return -1;

    // "A" / "B" / "C" / "D" / "A." ...
    const m = ans.match(/^[A-D]/i);
    if (m) {
      const idx = m[0].toUpperCase().charCodeAt(0) - 65;
      if (idx >= 0 && idx < q.options.length) return idx;
    }

    // Full-text match
    const idx2 = q.options.findIndex(
      (o) => (o || '').toString().trim().toLowerCase() === ans.toLowerCase()
    );
    return idx2;
  }

  // -------- Renderers --------
  function renderOptions(q) {
    const correctIdx = detectCorrectIndex(q);
    const items = safeArray(q.options).map((opt, i) => {
      const isCorrect = i === correctIdx;
      return `
        <div class="option${isCorrect ? ' correct' : ''}">
          <div class="option-letter">${letterFrom(i)}.</div>
          <div class="option-text">${opt ?? ''}</div>
          ${isCorrect ? '<span class="correct-badge">Correct</span>' : ''}
        </div>`;
    }).join('');

    return `
      <div class="options-container">
        <div class="options-label">Choose one:</div>
        <div class="options">
          ${items || '<div class="no-questions">No options provided</div>'}
        </div>
      </div>`;
  }

  function renderTrueFalse(q) {
    const ans = (q.answer || '').toString().trim().toLowerCase();
    const isTrue  = ans === 'true';
    const isFalse = ans === 'false';

    return `
      <div class="options-container">
        <div class="options-label">Choose one:</div>
        <div class="options">
          <div class="option${isTrue ? ' correct' : ''}">
            <div class="option-letter">A.</div>
            <div class="option-text">True</div>
            ${isTrue ? '<span class="correct-badge">Correct</span>' : ''}
          </div>
          <div class="option${isFalse ? ' correct' : ''}">
            <div class="option-letter">B.</div>
            <div class="option-text">False</div>
            ${isFalse ? '<span class="correct-badge">Correct</span>' : ''}
          </div>
        </div>
      </div>`;
  }

  function pill(type) {
    return `<span class="question-type">${(type || 'question').toUpperCase()}</span>`;
  }

  function sectionAnswer(q) {
    if (!q.answer) return '';
    return `
      <div class="answer-section">
        <div class="answer-label">Suggested Answer</div>
        <div class="expected-answer">${q.answer}</div>
      </div>`;
  }

  function sectionCriteria(q) {
    if (!q.grading_criteria) return '';
    return `
      <div class="grading-criteria">
        <strong>Grading criteria:</strong> ${q.grading_criteria}
      </div>`;
  }

  function sectionExplanation(q) {
    if (!q.explanation) return '';
    return `
      <div class="explanation">
        <strong>Why:</strong> ${q.explanation}
      </div>`;
  }

  function sectionMeta(q) {
    if (!q.meta) return '';
    return `<div class="question-meta">${q.meta}</div>`;
  }

  // The core per-question HTML (matches your style.css classes)
  function toHtml(q, idx) {
    const n = idx + 1;
    const type = (q.type || '').toLowerCase();

    const header = `
      <div class="question-header">
        <h3>Q${n}.</h3>
        ${pill(type)}
      </div>`;

    const questionText = `
      <div class="question-text">
        ${q.question || q.prompt || ''}
      </div>`;

    let body = '';
    if (type === 'mcq' && Array.isArray(q.options)) {
      body = renderOptions(q);
    } else if (type === 'true_false') {
      body = renderTrueFalse(q);
    } else {
      // short/long/scenario/code/etc. — rely on answer/explanation blocks
      body = '';
    }

    return `
      <article class="question-card">
        ${header}
        ${questionText}
        ${sectionMeta(q)}
        ${body}
        ${sectionAnswer(q)}
        ${sectionCriteria(q)}
        ${sectionExplanation(q)}
      </article>`;
  }

  // -------- Backend helpers --------
  async function saveQuizToServer({ title, metadata, questions }) {
    const res = await fetch('/api/quizzes', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: title || 'Untitled Quiz',
        items: questions || [],
        metadata: metadata || {},
      })
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      throw new Error(`Save failed (${res.status}) ${txt}`);
    }
    return res.json();
  }

  async function publishQuizById(quizId) {
    const res = await fetch(`/api/quizzes/${encodeURIComponent(quizId)}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      throw new Error(`Publish failed (${res.status}) ${txt}`);
    }
    return res.json();
  }

  async function generatePDF(filenameHint) {
    const quizContent = $(CONT_ID);
    if (!quizContent) throw new Error('Quiz content not found');
    if (typeof html2pdf === 'undefined' || typeof html2pdf !== 'function') {
      console.warn('html2pdf not available, skipping PDF generation');
      return;
    }
    const opt = {
      margin: 10,
      filename: `${(filenameHint || 'quiz').replace(/\s+/g, '_')}.pdf`,
      image: { type: 'jpeg', quality: 0.98 },
      html2canvas: { scale: 2 },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };
    await html2pdf().set(opt).from(quizContent).save();
  }

  // -------- Public API --------
  window.LAST_GENERATED_QUIZ = window.LAST_GENERATED_QUIZ || null;

  // Accepts:
  //   { questions: [...], metadata?: {...}, title?: "..." }
  // or { data: { questions: [...], metadata?: {...}, title?: "..." } }
  window.renderGeneratedQuiz = function (payload) {
    try {
      console.log('📦 renderGeneratedQuiz called with:', payload);

      // Normalize incoming payload (Firestore or plain)
      function normalizePayload(src) {
        const root = src && src.data ? src.data : src;
        const questions = safeArray(root?.questions).map(q => ({
          ...q,
          question: q.question || q.prompt || '',
          meta: q.meta || `Difficulty: ${q.difficulty || 'unknown'}${q.tags ? ` | Tags: ${q.tags.join(', ')}` : ''}${q.id ? ` | ID: ${q.id}` : ''}`
        }));

        return {
          title: root?.title || root?.metadata?.title || 'Generated Quiz',
          metadata: root?.metadata || {},
          questions,
          quiz_id: src.quiz_id || root?.quiz_id || root?.metadata?.quiz_id
        };
      }

      const normalized = normalizePayload(payload);
      const title = normalized.title;
      const meta = normalized.metadata;
      const questions = normalized.questions;
      const existingId = normalized.quiz_id;

      const sec  = $(SEC_ID);
      const cont = $(CONT_ID);
      if (!sec || !cont) {
        alert('Quiz section/container not found in DOM.');
        return;
      }

      // Unhide section
      unhideSection(sec);

      // Persist id (if available)
      if (existingId) {
        window.CURRENT_QUIZ_ID = existingId;
        cont.dataset.quizId = existingId;
        localStorage.setItem('last_quiz_id', existingId);
        console.log('📝 Stored quiz ID for publishing:', existingId);
      }

      // Render body inside #quiz-container (header is already in HTML)
      cont.innerHTML = questions.length
        ? questions.map(toHtml).join('')
        : `<div class="no-questions">No questions returned.</div>`;

      // Wire header buttons
      const btnCopy = $('btn-copy-quiz');
      const btnJson = $('btn-save-json');
      const btnPub  = $('btn-publish');
      const note    = $('publish-note');

      if (btnPub) btnPub.disabled = false;

      if (btnCopy) {
        btnCopy.onclick = () => {
          const plain = questions.map((q, i) => {
            let lines = [`Q${i + 1}. ${q.question || q.prompt || ''}`];
            if (Array.isArray(q.options)) {
              lines = lines.concat(q.options.map((o, k) => `  ${letterFrom(k)}. ${o}`));
            }
            if (q.answer) lines.push(`Answer: ${q.answer}`);
            if (q.explanation) lines.push(`Why: ${q.explanation}`);
            return lines.join('\n');
          }).join('\n\n');

          navigator.clipboard.writeText(plain)
            .then(() => {
              if (note) { note.textContent = 'Copied!'; setTimeout(() => note.textContent = '', 1200); }
            })
            .catch(() => { if (note) { note.textContent = 'Copy failed'; setTimeout(() => note.textContent = '', 1200); } });
        };
      }

      if (btnJson) {
        btnJson.onclick = () => {
          const blob = new Blob(
            [JSON.stringify({ title, metadata: meta, questions }, null, 2)],
            { type: 'application/json' }
          );
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = (title.replace(/\s+/g, '_') || 'quiz') + '.json';
          a.click();
          URL.revokeObjectURL(a.href);
        };
      }

      if (btnPub && !btnPub._wired) {
        btnPub.onclick = async () => {
          try {
            // Pull id from multiple places
            let quizId = window.CURRENT_QUIZ_ID
              || $(CONT_ID)?.dataset.quizId
              || localStorage.getItem('last_quiz_id');

            // Also get the in-memory quiz we rendered
            const last = window.LAST_GENERATED_QUIZ || {};
            const _title = last.title || (last.metadata?.title) || title || 'Generated Quiz';
            const _meta = last.metadata || meta || {};
            const _questions = Array.isArray(last.questions) ? last.questions : questions;

            btnPub.disabled = true;
            const originalText = btnPub.textContent;
            btnPub.textContent = 'Saving...';

            // ✅ If no ID yet → SAVE first (so View has something to list)
            if (!quizId) {
              const saved = await saveQuizToServer({ title: _title, metadata: _meta, questions: _questions });
              quizId = saved.id || saved.quiz_id || saved._id || saved.key;
              if (!quizId) throw new Error('Save returned no id');
              window.CURRENT_QUIZ_ID = quizId;
              $(CONT_ID).dataset.quizId = quizId;
              localStorage.setItem('last_quiz_id', quizId);
            }

            // Optional PDF
            btnPub.textContent = 'Generating PDF...';
            await generatePDF(_title);

            // Optional publish step (skip if your backend doesn’t require it)
            btnPub.textContent = 'Publishing...';
            try {
              await publishQuizById(quizId);
            } catch (e) {
              console.warn('Publish endpoint failed or not needed, continuing:', e);
            }

            // Navigate to View + refresh
            btnPub.textContent = originalText;
            btnPub.disabled = false;

            if (typeof window.showSection === 'function') window.showSection('view');
            if (typeof window.loadQuizzes === 'function') {
              await window.loadQuizzes();
            } else {
              window.dispatchEvent(new CustomEvent('refresh-quizzes'));
              window.dispatchEvent(new CustomEvent('show-section:view'));
            }

            if (typeof showToast === 'function') showToast('Quiz saved!');
            else alert('Quiz saved!');
          } catch (err) {
            console.error('❌ Publish error:', err);
            if (typeof showToast === 'function') showToast('Failed to publish: ' + err.message, 'error');
            else alert('Failed to publish: ' + err.message);
          } finally {
            btnPub.disabled = false;
            btnPub.textContent = 'Publish';
          }
        };
        btnPub._wired = true;
      }

      // Save globally and scroll into view
      window.LAST_GENERATED_QUIZ = { title, metadata: meta, questions };
      sec.scrollIntoView({ behavior: 'smooth', block: 'start' });

      console.log('[publish] Styled rendering complete.');
    } catch (e) {
      console.error('[publish] renderGeneratedQuiz error:', e);
      alert('Could not render quiz (see console).');
    }
  };

  // Optional helper others may call
  window.getLastGeneratedQuiz = function () {
    return window.LAST_GENERATED_QUIZ;
  };

  // Helper to manually set quiz ID (for external use)
  window.setCurrentQuizId = function(quizId) {
    window.CURRENT_QUIZ_ID = quizId;
    const cont = $(CONT_ID);
    if (cont) {
      cont.dataset.quizId = quizId;
    }
    localStorage.setItem('last_quiz_id', quizId);
    console.log('📝 Manually set quiz ID:', quizId);
  };

  // Expose no-op globals if not present to avoid crashes
  window.showSection   = window.showSection   || noop;
  window.loadQuizzes   = window.loadQuizzes   || null; // if your view script sets it later, we call it
  window.showToast     = window.showToast     || null;
})();
