// static/publish.js
// Renders generated quiz data into #quiz-container and wires header buttons.
// Requires these elements in HTML:
// <section id="quiz-section" style="display:none">
//   <div class="quiz-out-head"> ... buttons with ids: btn-copy-quiz, btn-save-json, btn-publish ... </div>
//   <div id="quiz-container" class="quiz-out"></div>
// </section>

(function () {
  const SEC_ID  = 'quiz-section';
  const CONT_ID = 'quiz-container';

  // -------- Utilities --------
  function $(id) { return document.getElementById(id); }
  function letterFrom(i) { return String.fromCharCode(65 + i); } // 0->A

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
    // Mark "True" or "False" as correct if answer provided
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

    // 🔧 FIX: Use 'prompt' if 'question' is not available
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

  // -------- Public API --------
  window.LAST_GENERATED_QUIZ = window.LAST_GENERATED_QUIZ || null;

  // Payload shape accepted:
  //   { questions: [...], metadata?: {...}, title?: "..." }
  // or { data: { questions: [...], metadata?: {...}, title?: "..." } }
  window.renderGeneratedQuiz = function (payload) {
    try {
      console.log('📦 renderGeneratedQuiz called with:', payload);
      
      // 🔧 ADD: Transform Firestore data to match renderer expectations
      function transformFirestoreQuestions(quizData) {
        const data = quizData && quizData.data ? quizData.data : quizData;
        const questions = safeArray(data?.questions);
        
        return {
          ...data,
          questions: questions.map(q => ({
            ...q,
            question: q.question || q.prompt || '', // Map prompt to question
            meta: q.meta || `Difficulty: ${q.difficulty || 'unknown'}${q.tags ? ` | Tags: ${q.tags.join(', ')}` : ''}${q.id ? ` | ID: ${q.id}` : ''}`
          }))
        };
      }

      const transformedData = transformFirestoreQuestions(payload);
      const data = transformedData && transformedData.data ? transformedData.data : transformedData;
      const questions = safeArray(data?.questions);
      const meta = data?.metadata || {};
      const title = data?.title || meta.title || 'Generated Quiz';

      console.log('🔄 Transformed data:', transformedData);
      console.log('❓ Questions to render:', questions);

      const sec  = $(SEC_ID);
      const cont = $(CONT_ID);
      if (!sec || !cont) {
        alert('Quiz section/container not found in DOM.');
        return;
      }

      // Unhide section
      unhideSection(sec);

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

     // You can replace this with your own publish handler.
      // In the renderGeneratedQuiz function, replace the btnPub section:

      if (btnPub && !btnPub._wired) {
        btnPub.onclick = async () => {
          try {
            // Show loading state
            btnPub.disabled = true;
            btnPub.textContent = 'Generating PDF...';
            
            // Get the quiz container content
            const quizContent = document.getElementById('quiz-container');
            
            if (!quizContent) {
              throw new Error('Quiz content not found');
            }

            // PDF options
            const opt = {
              margin: 10,
              filename: `${title.replace(/\s+/g, '_')}_quiz.pdf`,
              image: { type: 'jpeg', quality: 0.98 },
              html2canvas: { scale: 2 },
              jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
            };

            // Generate PDF
            await html2pdf().set(opt).from(quizContent).save();
            
            // Show success message
            showToast('PDF generated and saved!');
            
            // Navigate to View Quizzes section
            showSection('view');
            
            // Add the quiz to the View Quizzes list
            addQuizToViewList({
              id: window.LAST_GENERATED_QUIZ?.id || Date.now().toString(),
              title: title,
              filename: opt.filename,
              createdAt: new Date().toISOString(),
              questionCount: questions.length,
              sourceFile: window.LAST_GENERATED_QUIZ?.metadata?.source_file || 'Unknown'
            });
            
          } catch (error) {
            console.error('PDF generation failed:', error);
            showToast('Failed to generate PDF: ' + error.message);
          } finally {
            // Reset button state
            btnPub.disabled = false;
            btnPub.textContent = 'Publish';
          }
        };
        btnPub._wired = true;
      }

       // Function to show specific section
        function showSection(sectionName) {
          const sections = {
            home: document.getElementById('section-home'),
            generate: document.getElementById('section-generate'),
            view: document.getElementById('section-view'),
            grades: document.getElementById('section-grades'),
          };

          Object.values(sections).forEach(s => s.style.display = 'none');
          if (sections[sectionName]) {
            sections[sectionName].style.display = '';
          }
        }

        // Function to add quiz to View Quizzes list
          function addQuizToViewList(quizData) {
            const quizList = document.getElementById('quiz-list');
            if (!quizList) return;

            const quizItem = document.createElement('div');
            quizItem.className = 'quiz-item';
            quizItem.innerHTML = `
              <div class="quiz-header">
                <h3>${quizData.title}</h3>
                <span class="quiz-status published">Published</span>
              </div>
              <div class="quiz-details">
                <p><strong>Source:</strong> ${quizData.sourceFile}</p>
                <p><strong>Questions:</strong> ${quizData.questionCount}</p>
                <p><strong>Created:</strong> ${new Date(quizData.createdAt).toLocaleDateString()}</p>
                <p><strong>PDF:</strong> ${quizData.filename}</p>
              </div>
              <div class="quiz-actions">
                <button class="btn" onclick="downloadQuiz('${quizData.id}')">Download PDF</button>
                <button class="btn" onclick="viewQuiz('${quizData.id}')">View Details</button>
                <button class="btn danger" onclick="deleteQuiz('${quizData.id}')">Delete</button>
              </div>
            `;

            // Add to the beginning of the list
            quizList.insertBefore(quizItem, quizList.firstChild);
          }

          // Mock functions for quiz management (replace with your actual implementation)
          function downloadQuiz(quizId) {
            showToast('Downloading quiz PDF...');
            // Implement actual download logic here
          }

          function viewQuiz(quizId) {
            showToast('Viewing quiz details...');
            // Implement actual view logic here
          }

          function deleteQuiz(quizId) {
            if (confirm('Are you sure you want to delete this quiz?')) {
              const quizItem = document.querySelector(`[onclick*="${quizId}"]`)?.closest('.quiz-item');
              if (quizItem) {
                quizItem.remove();
                showToast('Quiz deleted successfully');
              }
            }
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
})();