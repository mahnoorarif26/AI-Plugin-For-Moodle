(function(){
  const $ = sel => document.querySelector(sel);
  const list = $("#questions");
  const notify = (msg) => {
    if (typeof window.showToast === "function") {
      window.showToast(msg);
    } else {
      alert(msg);
    }
  };

  // 🔹 Detect if we are in assignment mode: /teacher/manual?mode=assignment
  const params = new URLSearchParams(window.location.search);
  const isAssignment = params.get("mode") === "assignment";

  const state = {
    // items: {type:'mcq'|'true_false'|'short', prompt, options?, answer?}
    items: []
  };

  const letter = i => String.fromCharCode(65+i);

  // 🔥 NEW: Debounced similarity check
  let similarityTimeout = null;
  
  async function checkSimilarQuestions(questionText, questionType, questionIndex) {
    if (!questionText || questionText.trim().length < 10) {
      hideSimilarQuestionsPanel();
      return;
    }
    
    try {
      const res = await fetch('/api/questions/similar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          question_text: questionText,
          type: questionType,
          exclude_ids: [`q${questionIndex}`]
        })
      });
      
      const data = await res.json();
      
      if (data.success && data.similar && data.similar.length > 0) {
        showSimilarQuestionsPanel(data.similar, questionIndex);
      } else {
        hideSimilarQuestionsPanel(questionIndex);
      }
    } catch (err) {
      console.error('Failed to check similar questions:', err);
    }
  }
  
  function showSimilarQuestionsPanel(similarQuestions, questionIndex) {
    // Remove any existing panel for this question
    const existingPanel = document.querySelector(`[data-similar-panel="${questionIndex}"]`);
    if (existingPanel) {
      existingPanel.remove();
    }
    
    const container = document.querySelector(`[data-p="${questionIndex}"]`)?.closest('.question-item');
    if (!container) return;
    
    const panel = document.createElement('div');
    panel.className = 'similar-questions-panel';
    panel.setAttribute('data-similar-panel', questionIndex);
    panel.innerHTML = `
      <div class="similar-header">
        <i class='bx bx-info-circle'></i>
        <strong>⚠️ Similar Questions Found</strong>
        <button class="close-similar" type="button">×</button>
      </div>
      <p class="similar-subtitle">These existing questions are similar to yours:</p>
      <ul class="similar-list">
        ${similarQuestions.map(q => `
          <li class="similar-item">
            <div class="similarity-bar" style="width: ${q.similarity_percent}%"></div>
            <div class="similar-content">
              <span class="similarity-score">${q.similarity_percent}% match</span>
              <p class="similar-text">${escapeHtml(q.question.text)}</p>
              <small class="similar-reason">${q.reason}</small>
            </div>
          </li>
        `).join('')}
      </ul>
      <button class="btn-outline continue-anyway" type="button">
        Continue Anyway
      </button>
    `;
    
    // Wire close button
    panel.querySelector('.close-similar').onclick = () => {
      panel.remove();
    };
    
    // Wire continue button
    panel.querySelector('.continue-anyway').onclick = () => {
      panel.remove();
    };
    
    container.appendChild(panel);
  }
  
  function hideSimilarQuestionsPanel(questionIndex) {
    if (questionIndex !== undefined) {
      const panel = document.querySelector(`[data-similar-panel="${questionIndex}"]`);
      if (panel) panel.remove();
    } else {
      // Remove all panels
      const panels = document.querySelectorAll('.similar-questions-panel');
      panels.forEach(p => p.remove());
    }
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function addQuestion(type){
    const q = {
      type,
      prompt:'',
      options: (type==='short' ? undefined : (type==='true_false' ? ['True','False'] : [])),
      answer:''
    };
    state.items.push(q);
    render();
  }

  function addOption(qi){
    const q = state.items[qi];
    if (!q.options) q.options = [];
    q.options.push('');
    render();
  }

  function removeQuestion(qi){
    state.items.splice(qi,1);
    render();
  }

  function render(){
    list.innerHTML = state.items.map((q,qi)=>{
      const header =
        `<div class="qhead">
           <span class="title-badge">${q.type === 'mcq' ? 'MCQ' : q.type === 'true_false' ? 'True/False' : 'Short Answer'}</span>
           <input type="number" class="question-marks" placeholder="Marks" min="1" value="1" style="width:80px;">
           <button class="btn-outline remove-btn" type="button" data-remove="${qi}">
             <i class='bx bx-trash'></i>
           </button>
         </div>`;

      const prompt =
        `<textarea data-p="${qi}" class="prompt" rows="2" placeholder="Question prompt...">${q.prompt||''}</textarea>`;

      let body = '';
      if(q.type==='mcq'){
        const opts = (q.options||[]).map((opt,oi)=>
          `<div class="opt">
             <input type="checkbox" name="q${qi}_correct" value="${letter(oi)}">
             <input data-opt="${qi}:${oi}" type="text" placeholder="Option ${letter(oi)}" value="${opt}"/>
           </div>`
        ).join('');
        body = `
          ${opts}
          <div class="row">
            <button class="btn-outline" data-addopt="${qi}" type="button">+ Add Option</button>
          </div>`;
      } else if (q.type==='true_false'){
        body = `
          <div class="opt">
            <input type="radio" name="q${qi}_correct" value="True" ${q.answer==='True'?'checked':''}>
            <label>True</label>
          </div>
          <div class="opt">
            <input type="radio" name="q${qi}_correct" value="False" ${q.answer==='False'?'checked':''}>
            <label>False</label>
          </div>`;
      } else {
        body = `<textarea data-ans="${qi}" placeholder="Expected answer (for grading)" rows="3" style="width:100%; margin-top:8px;">${q.answer||''}</textarea>`;
      }

      return `<div class="card question-item">${header}${prompt}${body}</div>`;
    }).join('');

    // Wire prompt events with similarity check
    list.querySelectorAll('.prompt').forEach(el=>{
      el.oninput = e => {
        const qi = +e.target.getAttribute('data-p');
        state.items[qi].prompt = e.target.value;
        
        // 🔥 NEW: Check for similar questions (debounced)
        clearTimeout(similarityTimeout);
        similarityTimeout = setTimeout(() => {
          checkSimilarQuestions(
            e.target.value,
            state.items[qi].type,
            qi
          );
        }, 1000); // Wait 1 second after user stops typing
      };
    });

    list.querySelectorAll('[data-addopt]').forEach(btn=>{
      btn.onclick = () => addOption(+btn.getAttribute('data-addopt'));
    });

    list.querySelectorAll('[data-opt]').forEach(inp=>{
      inp.oninput = e => {
        const [qi,oi] = e.target.getAttribute('data-opt').split(':').map(Number);
        state.items[qi].options[oi] = e.target.value;
      };
    });

    // Handle checkbox/radio changes for answers
    list.querySelectorAll('input[type="checkbox"]').forEach(cb=>{
      cb.onchange = e => {
        const qi = +e.target.closest('.question-item').querySelector('[data-p]').getAttribute('data-p');
        state.items[qi].answer = Array.from(list.querySelectorAll(`input[name="q${qi}_correct"]:checked`))
          .map(cb => cb.value).join(',');
      };
    });

    list.querySelectorAll('input[type="radio"]').forEach(radio=>{
      radio.onchange = e => {
        const qi = +e.target.closest('.question-item').querySelector('[data-p]').getAttribute('data-p');
        state.items[qi].answer = e.target.value;
      };
    });

    list.querySelectorAll('textarea[data-ans]').forEach(ta=>{
      ta.oninput = e => {
        const qi = +e.target.getAttribute('data-ans');
        state.items[qi].answer = e.target.value;
      };
    });

    list.querySelectorAll('[data-remove]').forEach(btn=>{
      btn.onclick = () => removeQuestion(+btn.getAttribute('data-remove'));
    });
  }

  // top buttons - using your HTML IDs
  $("#addMCQ").onclick = () => addQuestion('mcq');
  $("#addTF").onclick  = () => addQuestion('true_false');
  $("#addSA").onclick  = () => addQuestion('short');

  // save function - using your HTML ID "save" instead of "saveBtn"
  async function saveQuiz() {
    // validation
    for (const q of state.items){
      if (!q.prompt || !q.prompt.trim()){
        notify("Every question needs a prompt");
        return;
      }

      if (q.type === 'mcq'){
        const okOpts = Array.isArray(q.options) && q.options.length >= 2 && q.options.every(s => (s||'').trim().length);
        if (!okOpts){ 
          notify("Each MCQ needs at least two non-empty options"); 
          return; 
        }
        if (!q.answer || !q.answer.toString().trim()){ 
          notify("MCQ needs at least one correct answer selected"); 
          return; 
        }
      }

      if (q.type === 'true_false'){
        q.options = ['True','False'];
        if (q.answer !== 'True' && q.answer !== 'False'){
          notify("True/False needs the correct answer selected");
          return;
        }
      }

      if (q.type === 'short'){
        q.options = undefined;
        if (!q.answer || !q.answer.trim()){
          notify("Short answer question needs an expected answer");
          return;
        }
      }
    }

    // 🔹 IMPORTANT: mark whether this is a quiz or an assignment
    const payload = {
      title: $("#title").value,
      items: state.items,
      metadata: {
        description: $("#desc").value,
        time_limit: $("#timeLimit").value ? parseInt($("#timeLimit").value) : null,
        kind: isAssignment ? "assignment" : "quiz"
      }
    };

    try {
      const res = await fetch("/api/quizzes", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      if (res.ok && data) {
        const savedId = data.id || data.quiz_id || "(no id)";
        notify((isAssignment ? "Assignment" : "Quiz") + " saved! ID: " + savedId);
        
        // 🔥 NEW: Questions are automatically indexed by the backend
        // No need to manually index here - the /api/quizzes endpoint handles it
        
        // Redirect after successful save
        setTimeout(() => {
          window.location.href = "/teacher/generate";
        }, 1500);
      } else {
        notify("Save failed: " + (data?.error || JSON.stringify(data)));
      }
    } catch (err) {
      console.error("Save error:", err);
      notify("Save failed: " + (err.message || "Network error"));
    }
  }

  // Fixed: using "save" instead of "saveBtn"
  $("#save").onclick = saveQuiz;

  // initial one question
  addQuestion('mcq');
})();