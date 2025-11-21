// static/assignments.js
// Logic for the "Assignments" section

(() => {
  const $ = (sel) => document.querySelector(sel);
  const id = (s) => document.getElementById(s);

  const hasToast = typeof window.showToast === "function";
  const notify = (msg) => {
    if (hasToast) window.showToast(msg);
    else alert(msg);
  };

  function openModal(modal) {
    if (modal) modal.style.display = "flex";
  }

  function closeModal(modal) {
    if (modal) modal.style.display = "none";
  }
  function renderAssignment(questions) {
    const container = id("assignment-output");
    if (!container) return;

    if (!Array.isArray(questions) || !questions.length) {
      container.innerHTML =
        '<div class="muted">No assignment tasks generated yet.</div>';
      return;
    }

    container.innerHTML = questions
      .map((q, i) => {
        const text = (q.prompt || q.question_text || "").trim();
        const marks =
          typeof q.marks !== "undefined" ? `<span class="marks">${q.marks} marks</span>` : "";
        return `
        <div class="question-card assignment-task">
          <div class="question-header">
            <h3>Task ${i + 1}</h3>
            <span class="question-type">Assignment Task</span>
            ${marks}
          </div>
          <div class="question-text">
            ${text.replace(/\n/g, "<br>")}
          </div>
        </div>`;
      })
      .join("");
  }

  // Expose for debugging if needed
  window.renderAssignment = renderAssignment;

  /**
   * Card 1: Generate assignment from PDF (detect subtopics → long questions)
   */
  async function generateAssignmentFromPdf() {
    const fileInput = id("assign-pdf-file");
    const countInput = id("assign-pdf-count");
    const modal = id("modal-assign-pdf");

    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
      notify("Please select a PDF file.");
      return;
    }

    const nLong = parseInt(countInput?.value || "5", 10) || 5;

    try {
      // 1) Extract subtopics
      const fd = new FormData();
      fd.append("file", fileInput.files[0]);

      const res1 = await fetch("/api/custom/extract-subtopics", {
        method: "POST",
        body: fd,
      });
      const subData = await res1.json();

      if (!res1.ok || !subData || subData.success === false) {
        console.error("Subtopic extract error:", subData);
        notify("Subtopic extraction failed. Check console for details.");
        return;
      }

      const uploadId = subData.upload_id;
      const subtopics = subData.subtopics || [];

      if (!uploadId || !subtopics.length) {
        notify("No subtopics detected from the PDF.");
        return;
      }

      // For v1, just use all subtopics (or first 5)
      const chosenSubtopics = subtopics.slice(0, 5);

      // 2) Generate quiz from subtopics but treat as assignment
      const payload = {
        upload_id: uploadId,
        subtopics: chosenSubtopics,
        totals: { long: nLong }, // only long-answer tasks
        difficulty: { mode: "auto" },
        is_assignment: true,
      };

      const res2 = await fetch("/api/custom/quiz-from-subtopics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data2 = await res2.json();

      if (!res2.ok || !data2) {
        console.error("Assignment from PDF error:", data2);
        notify("Assignment generation failed. Check console for details.");
        return;
      }

      // Be flexible with response shape
      const quizObj = data2.quiz || data2;
      const questions =
        quizObj.questions || quizObj.items || data2.questions || [];

      if (!questions.length) {
        notify("No questions returned for assignment.");
        return;
      }

      renderAssignment(questions);
      notify("Assignment generated from PDF.");
      closeModal(modal);
    } catch (err) {
      console.error(err);
      notify("Unexpected error while generating assignment from PDF.");
    }
  }

  /**
   * Card 2: Generate assignment from typed topics
   */
  async function generateAssignmentFromTopics() {
    const txtEl = id("assign-topics-text");
    const countEl = id("assign-topics-count");
    const modal = id("modal-assign-topics");

    const topicText = (txtEl?.value || "").trim();
    const nLong = parseInt(countEl?.value || "4", 10) || 4;

    if (!topicText) {
      notify("Please enter at least one topic (one per line).");
      return;
    }

    const payload = {
      topic_text: topicText,
      totals: { long: nLong }, // only long-answer questions
      is_assignment: true,
    };

    try {
      const res = await fetch("/generate-question", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok || !data) {
        console.error("Assignment from topics error:", data);
        notify("Assignment generation failed. Check console for details.");
        return;
      }

      const questions = data.questions || data.items || [];
      if (!questions.length) {
        notify("No questions returned for assignment.");
        return;
      }

      renderAssignment(questions);
      notify("Assignment generated from topics.");
      closeModal(modal);
    } catch (err) {
      console.error(err);
      notify("Unexpected error while generating assignment from topics.");
    }
  }

  /**
   * Wire up buttons & modals
   */
  function setupPdfCard() {
    const openBtn = id("btn-open-assign-pdf");
    const modal = id("modal-assign-pdf");
    const closeBtn = id("btn-assign-pdf-close");
    const genBtn = id("btn-assign-pdf-detect");

    if (openBtn && modal) {
      openBtn.addEventListener("click", () => openModal(modal));
    }
    if (closeBtn && modal) {
      closeBtn.addEventListener("click", () => closeModal(modal));
    }
    if (genBtn) {
      genBtn.addEventListener("click", generateAssignmentFromPdf);
    }
  }

  function setupTopicsCard() {
    const openBtn = id("btn-open-assign-topics");
    const modal = id("modal-assign-topics");
    const closeBtn = id("btn-assign-topics-close");
    const genBtn = id("btn-assign-topics-generate");

    if (openBtn && modal) {
      openBtn.addEventListener("click", () => openModal(modal));
    }
    if (closeBtn && modal) {
      closeBtn.addEventListener("click", () => closeModal(modal));
    }
    if (genBtn) {
      genBtn.addEventListener("click", generateAssignmentFromTopics);
    }
  }

  function setupManualCard() {
    const manualBtn = id("btn-open-assign-manual");
    if (manualBtn) {
      manualBtn.addEventListener("click", () => {
        // Reuse your manual builder, but with mode=assignment
        window.location.href = "/teacher/manual?mode=assignment";
      });
    }
  }
  function initAssignPdfUploader() {
  const box = id("assign-uploader");
  const input = id("assign-pdf-file");
  const nameBox = id("assignFileNameDisplay");

  if (!box || !input) return;

  const updateName = () => {
    if (!nameBox) return;
    if (input.files && input.files[0]) {
      nameBox.textContent = input.files[0].name;
    } else {
      nameBox.textContent = "";
    }
  };

  box.addEventListener("click", () => input.click());

  box.addEventListener("dragover", (e) => {
    e.preventDefault();
    box.classList.add("dragover");
  });

  box.addEventListener("dragleave", () => {
    box.classList.remove("dragover");
  });

  box.addEventListener("drop", (e) => {
    e.preventDefault();
    box.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      input.files = e.dataTransfer.files;
      updateName();
      notify("PDF selected ✔");
    }
  });

  input.addEventListener("change", () => {
    updateName();
    if (input.files && input.files[0]) notify("PDF selected ✔");
  });
}

  document.addEventListener("DOMContentLoaded", () => {
    setupPdfCard();
    setupTopicsCard();
    setupManualCard();
    initAssignPdfUploader();  
  });
})();
