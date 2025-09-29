document.addEventListener("DOMContentLoaded", () => {
  // ---- Elements ----
  let currentMode = "quick";

  const quickForm     = document.getElementById("quick-form");
  const customForm    = document.getElementById("custom-form");
  const btnQuick      = document.getElementById("mode-quick");
  const btnCustom     = document.getElementById("mode-custom");
  const generateBtn   = document.getElementById("generate-btn");
  const outputDiv     = document.getElementById("output");
  const outputContent = document.getElementById("output-content");

  // ---- Mode switching ----
  btnQuick?.addEventListener("click", () => {
    currentMode = "quick";
    btnQuick.classList.add("active");
    btnCustom.classList.remove("active");
    quickForm.style.display  = "block";
    customForm.style.display = "none";
    clearOutput();
  });

  btnCustom?.addEventListener("click", () => {
    currentMode = "custom";
    btnCustom.classList.add("active");
    btnQuick.classList.remove("active");
    quickForm.style.display  = "none";
    customForm.style.display = "block";
    clearOutput();
  });

  // ---- Generate handler ----
  generateBtn?.addEventListener("click", async () => {
    const payload =
      currentMode === "quick"
        ? {
            topic: (document.getElementById("topic").value || "").trim(),
            num_questions: parseInt(document.getElementById("num_questions").value || "5", 10),
          }
        : {
            topic: (document.getElementById("custom-topic").value || "").trim(),
            num_questions: parseInt(document.getElementById("custom-num-questions").value || "5", 10),
            question_types: Array.from(
              document.querySelectorAll('input[name="question-type"]:checked')
            ).map(cb => cb.value),
          };
          // Add structured flag if checked
         const structured =
            currentMode === "quick"
                ? (document.getElementById("structured-toggle-quick")?.checked || false)
                : (document.getElementById("structured-toggle-custom")?.checked || false);

            payload.structured = structured;



    // basic validation
    if (!payload.topic) return alert("⚠️ Please enter a topic.");
    if (!Number.isFinite(payload.num_questions) || payload.num_questions < 3 || payload.num_questions > 20) {
      return alert("⚠️ Number of questions must be between 3 and 20.");
    }
    if (currentMode === "custom" && (!payload.question_types || payload.question_types.length === 0)) {
      return alert("⚠️ Please select at least one question type.");
    }

    setLoading(true);
    clearOutput();

    try {
      const res  = await fetch("/generate-quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (!data.ok) {
        showError(data.error || "Unknown error.");
        return;
      }

      // ---- Choose JSON vs text rendering ----
      if (data.format === "json" && data.json) {
        outputContent.innerHTML = renderJsonQuiz(data.json);
      } else {
        const raw = String(data.questions || "");
        const formattedHTML = formatQuizText(raw);
        if (!formattedHTML.trim()) {
          showError("No questions generated. Try another topic.");
          return;
        }
        outputContent.innerHTML = formattedHTML;
      }

      outputDiv.style.display = "block";
      outputDiv.scrollIntoView({ behavior: "smooth", block: "start" });

    } catch (err) {
      showError("Network error: " + (err?.message || err));
    } finally {
      setLoading(false);
    }
  });

  // ---- Helpers: UI ----
  function setLoading(isLoading) {
    if (!generateBtn) return;
    generateBtn.disabled = isLoading;
    generateBtn.textContent = isLoading ? "Generating..." : "Generate Quiz";
  }

  function clearOutput() {
    outputContent.innerHTML = "";
    outputDiv.style.display = "none";
  }

  function showError(msg) {
    outputContent.innerHTML = `<p class="error">❌ ${escapeHtml(msg)}</p>`;
    outputDiv.style.display = "block";
  }

  // ---- Formatter: parse plain text into pretty cards ----
  function formatQuizText(text) {
    let t = String(text)
      .replace(/\r/g, "")
      .replace(/(\s|^)(\d+)\.\s*(?=[(A-Za-z0-9])/g, "\n$2. ")
      .replace(/(?<!\n)([A-D])\.\s/g, "\n$1. ")
      .replace(/[ \t]+/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();

    const firstQ = t.search(/\n?1\.\s/);
    if (firstQ > 0) t = t.substring(firstQ).trim();

    const lines = t.split("\n").map(l => l.trim()).filter(Boolean);

    let html = "";
    let current = "";
    let qIndex = 0;

    const flush = () => {
      if (!current) return;
      html += `<div class="question-item">${current}</div>`;
      current = "";
    };

    for (const line of lines) {
      if (/^\d+\.\s/.test(line)) {
        flush();
        qIndex += 1;
        const title = sanitizeQuestionTitle(line, qIndex);
        current = `<h4>${escapeHtml(title)}</h4>`;
      } else if (/^[A-D]\.\s/.test(line)) {
        current += `<div class="option">${escapeHtml(line)}</div>`;
      } else {
        current += `<p>${escapeHtml(line)}</p>`;
      }
    }
    flush();

    return html;
  }

  function sanitizeQuestionTitle(line, fallbackNum) {
    const m = line.match(/^(\d+)\.\s*(.*)$/);
    if (!m) return `Q${fallbackNum}. ${line}`;
    const body = m[2] || "";
    return `Q${m[1]}. ${body}`;
  }

  // ---- SAFETY ----
  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = String(s ?? "");
    return d.innerHTML;
  }

  // ---- BADGE HTML ----
  function badge(label, color) {
    return `<span style="
      display:inline-block;margin:0 6px 8px 0;padding:2px 10px;
      border-radius:14px;font-size:.75rem;font-weight:700;
      background:${color};color:#fff;letter-spacing:.3px;">
      ${escapeHtml(label)}
    </span>`;
  }

  // ---- MAIN RENDERER: JSON -> Pretty HTML ----
  function renderJsonQuiz(obj) {
    if (!obj || !Array.isArray(obj.questions)) {
      return `<p class="error">Invalid JSON format.</p>`;
    }

    const topic = obj.topic ? `<p class="subtitle">Topic: ${escapeHtml(obj.topic)}</p>` : "";

    const html = obj.questions.map((q, i) => {
      const type = String(q.type || "question").toLowerCase();
      const difficulty = String(q.difficulty || "medium").toLowerCase();

      const typeColor = type === "mcq" ? "#667eea" : type === "short" ? "#38a169" : "#d69e2e";
      const diffColor = difficulty === "easy" ? "#48bb78" : difficulty === "hard" ? "#e53e3e" : "#3182ce";

      const head =
        `<h4>Q${i + 1}. ${escapeHtml(q.prompt || "")}</h4>
         ${badge(type.toUpperCase(), typeColor)}${badge(difficulty.toUpperCase(), diffColor)}`;

      const options = Array.isArray(q.options) && q.options.length
        ? q.options.map(opt => `<div class="option">${escapeHtml(opt)}</div>`).join("")
        : "";

      let answerBlock = "";
      if (type === "mcq") {
        const ans = q.answer ? String(q.answer).trim() : "";
        const strong = ans ? `<strong>Answer:</strong> ${escapeHtml(ans)}` : "<strong>Answer:</strong> –";
        answerBlock = `
          <div class="option" style="border-left-color:#38a169;background:#f0fff4;">
            ${strong}
          </div>`;
      } else if (q.answer) {
        answerBlock = `<p><strong>Reference Answer:</strong> ${escapeHtml(q.answer)}</p>`;
      }

      const expl = q.explanation
        ? `<p><em>${escapeHtml(q.explanation)}</em></p>`
        : "";

      return `
        <div class="question-item">
          ${head}
          ${options}
          ${answerBlock}
          ${expl}
        </div>
      `;
    }).join("");

    return topic + (html || `<p class="error">No questions returned.</p>`);
  }
});
