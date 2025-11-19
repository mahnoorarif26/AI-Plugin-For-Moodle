(function(){
  const $ = sel => document.querySelector(sel);
  const list = $("#questions");

  // 🔹 Detect if we are in assignment mode: /teacher/manual?mode=assignment
  const params = new URLSearchParams(window.location.search);
  const isAssignment = params.get("mode") === "assignment";

  const state = {
    // items: {type:'mcq'|'true_false'|'short', prompt, options?, answer?}
    items: []
  };

  const letter = i => String.fromCharCode(65+i);

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
           <select data-q="${qi}" class="qtype">
             <option value="mcq" ${q.type==='mcq'?'selected':''}>MCQ</option>
             <option value="true_false" ${q.type==='true_false'?'selected':''}>True/False</option>
             <option value="short" ${q.type==='short'?'selected':''}>Short Answer</option>
           </select>
           <button class="danger" data-remove="${qi}"><i class='bx bx-trash'></i></button>
         </div>`;

      const prompt =
        `<textarea data-p="${qi}" class="prompt" rows="2" placeholder="Question prompt...">${q.prompt||''}</textarea>`;

      let body = '';
      if(q.type==='mcq'){
        const opts = (q.options||[]).map((opt,oi)=>
          `<div class="opt">
             <span class="pill">${letter(oi)}.</span>
             <input data-opt="${qi}:${oi}" type="text" value="${opt}"/>
           </div>`
        ).join('');
        body = `
          ${opts}
          <div class="row">
            <button class="btn-outline" data-addopt="${qi}">+ Add option</button>
            <input data-ans="${qi}" type="text" placeholder="Correct answer (A/B/C or full text)" value="${q.answer||''}" />
          </div>`;
      } else if (q.type==='true_false'){
        body = `
          <div class="row"><span class="pill">Correct:</span>
            <select data-ans="${qi}">
              <option value="">--</option>
              <option value="True"  ${q.answer==='True'?'selected':''}>True</option>
              <option value="False" ${q.answer==='False'?'selected':''}>False</option>
            </select>
          </div>`;
      } else {
        body = `<input data-ans="${qi}" type="text" placeholder="Expected answer (optional)" value="${q.answer||''}" />`;
      }

      return `<div class="card">${header}${prompt}${body}</div>`;
    }).join('');

    // wire events
    list.querySelectorAll('.prompt').forEach(el=>{
      el.oninput = e => {
        const qi = +e.target.getAttribute('data-p');
        state.items[qi].prompt = e.target.value;
      };
    });

    list.querySelectorAll('select.qtype').forEach(el=>{
      el.onchange = e => {
        const qi = +e.target.getAttribute('data-q');
        const val = e.target.value;
        const q = state.items[qi];
        q.type = val;

        if (val === 'short') {
          q.options = undefined;
          q.answer = q.answer || '';
        } else if (val === 'true_false') {
          // lock to fixed options; UI only needs the answer select
          q.options = ['True','False'];
          if (q.answer !== 'True' && q.answer !== 'False') q.answer = '';
        } else if (val === 'mcq') {
          // ensure an editable options array exists
          if (!Array.isArray(q.options)) q.options = [];
        }
        render();
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

    list.querySelectorAll('[data-ans]').forEach(inp=>{
      inp.onchange = e => {
        const qi = +e.target.getAttribute('data-ans');
        state.items[qi].answer = e.target.value;
      };
    });

    list.querySelectorAll('[data-remove]').forEach(btn=>{
      btn.onclick = () => removeQuestion(+btn.getAttribute('data-remove'));
    });
  }

  // top buttons
  $("#addMCQ").onclick = () => addQuestion('mcq');
  $("#addTF").onclick  = () => addQuestion('true_false');
  $("#addSA").onclick  = () => addQuestion('short');

  $("#save").onclick = async () => {
    const rawTitle = $("#title").value.trim();
    const title = rawTitle || (isAssignment ? "Untitled Assignment" : "Untitled Quiz");

    // validation
    for (const q of state.items){
      if (!q.prompt || !q.prompt.trim()){
        alert("Every question needs a prompt");
        return;
      }

      if (q.type === 'mcq'){
        const okOpts = Array.isArray(q.options) && q.options.length >= 2 && q.options.every(s => (s||'').trim().length);
        if (!okOpts){ alert("Each MCQ needs at least two non-empty options"); return; }
        if (!q.answer || !q.answer.toString().trim()){ alert("MCQ needs a correct answer (A/B/C or option text)"); return; }
      }

      if (q.type === 'true_false'){
        // no options requirement; normalize to fixed options
        q.options = ['True','False'];
        if (q.answer !== 'True' && q.answer !== 'False'){
          alert("True/False needs the correct answer selected");
          return;
        }
      }

      if (q.type === 'short'){
        q.options = undefined; // ensure clean payload
      }
    }

    // 🔹 IMPORTANT: mark whether this is a quiz or an assignment
    const payload = {
      title,
      items: state.items,
      metadata: {
        description: $("#desc").value,
        kind: isAssignment ? "assignment" : "quiz"
      }
    };

    const res = await fetch("/api/quizzes", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if(res.ok && data){
      // support both {id: ...} and {quiz_id: ...} just in case
      const savedId = data.id || data.quiz_id || "(no id)";
      alert((isAssignment ? "Assignment" : "Quiz") + " saved! ID: " + savedId);
    } else {
      alert("Save failed: " + JSON.stringify(data));
    }
  };

  // initial one question
  addQuestion('mcq');
})();
