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

  // NEW: Function to close/hide the assignment output
  function closeAssignmentOutput() {
    const container = id("assignment-output");
    if (container) {
      container.style.display = "none";
      notify("Assignment hidden");
    }
  }

  // NEW: Function to show the assignment output
  function showAssignmentOutput() {
    const container = id("assignment-output");
    if (container) {
      container.style.display = "block";
    }
  }

  // Enhanced rendering for advanced assignment types with code display
  function renderAssignment(questions) {
    const container = id("assignment-output");
    if (!container) return;

    if (!Array.isArray(questions) || !questions.length) {
      container.innerHTML =
        '<div class="muted">No assignment tasks generated yet.</div>';
      return;
    }

    // Add close button to the assignment output
    container.innerHTML = `
      <div class="assignment-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 15px; background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border-radius: 10px; color: #92400e; border: 2px solid #fdba74;">
        <div>
          <h2 style="margin: 0; font-size: 1.5em; color: #92400e;">🎓 Generated Assignment</h2>
          <p style="margin: 5px 0 0 0; color: #b45309; opacity: 0.9;">${questions.length} tasks generated</p>
        </div>
        <button id="close-assignment-btn" class="btn" style="background: linear-gradient(to right, #ffb366, #fb9026); border: none; color: white; padding: 8px 16px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 8px; font-weight: 600; transition: all 0.3s ease;">
          <i class='bx bx-x' style="font-size: 1.2em;"></i> Close
        </button>
      </div>
      <div id="assignment-questions-container">
        ${questions
          .map((q, i) => {
            const text = (q.prompt || q.question_text || "").trim();
            const marks = typeof q.marks !== "undefined" ? q.marks : 10;
            const assignmentType = q.assignment_type || 'task';
            const typeLabel = assignmentType.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());
            
            // Type-specific icons
            const typeIcons = {
              conceptual: '💡',
              scenario: '🎯',
              research: '🔬',
              project: '🛠️',
              case_study: '📋',
              comparative: '⚖️'
            };
            const icon = typeIcons[assignmentType] || '📝';

            let html = `
            <div class="question-card assignment-task assignment-${assignmentType}">
              <div class="question-header" style="display: flex; justify-content: space-between; align-items: start;">
                <div>
                  <h3>${icon} Task ${i + 1}</h3>
                  <span class="question-type">${typeLabel}</span>
                </div>
                <span class="marks" style="background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%); color: white; padding: 8px 16px; border-radius: 8px; font-weight: 700; font-size: 0.95em; box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);">
                  ${marks} marks
                </span>
              </div>
              
              <div class="question-text" style="margin: 15px 0; line-height: 1.7; font-size: 1.05em;">
                ${text.replace(/\n/g, "<br>")}
              </div>`;

            // Context section
            if (q.context) {
              html += `
              <div class="assignment-context">
                <strong style="color: #92400e;">📌 Context:</strong>
                <p style="color: #78350f; margin-top: 8px; line-height: 1.6;">${q.context.replace(/\n/g, "<br>")}</p>
              </div>`;
            }

            // Code snippet section (for technical questions)
            if (q.code_snippet) {
              html += `
              <div class="assignment-code" style="background: #1f2937; padding: 20px; border-radius: 10px; margin: 15px 0; border-left: 4px solid #f59e0b; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                  <span style="color: #fbbf24; font-size: 1.2em;">💻</span>
                  <strong style="color: #fbbf24;">Code to Analyze:</strong>
                </div>
                <pre style="margin: 0; overflow-x: auto; background: #111827; padding: 15px; border-radius: 6px;"><code style="color: #e5e7eb; font-family: 'Courier New', monospace; font-size: 0.9em; line-height: 1.5;">${escapeHtml(q.code_snippet)}</code></pre>
              </div>`;
            }

            // Requirements section
            if (q.requirements && Array.isArray(q.requirements) && q.requirements.length > 0) {
              html += `
              <div class="assignment-requirements">
                <strong style="color: #0369a1;">✓ Requirements:</strong>
                <ul style="margin: 10px 0 0 20px; color: #0c4a6e;">
                  ${q.requirements.map(r => `<li style="margin: 6px 0; line-height: 1.5;">${r}</li>`).join('')}
                </ul>
              </div>`;
            }

            // Deliverables section (for technical assignments)
            if (q.deliverables && Array.isArray(q.deliverables) && q.deliverables.length > 0) {
              html += `
              <div style="background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); padding: 15px; border-radius: 10px; margin: 15px 0; border-left: 4px solid #f59e0b;">
                <strong style="color: #92400e;">📦 Expected Deliverables:</strong>
                <ul style="margin: 10px 0 0 20px; color: #78350f;">
                  ${q.deliverables.map(d => `<li style="margin: 6px 0; line-height: 1.5;">${d}</li>`).join('')}
                </ul>
              </div>`;
            }

            // Grading criteria
            if (q.grading_criteria) {
              html += `
              <div class="assignment-grading">
                <strong style="color: #667eea;">📊 Grading Criteria:</strong>
                <p style="color: #4b5563; margin-top: 8px; line-height: 1.6;">${q.grading_criteria}</p>
              </div>`;
            }

            // Learning objectives
            if (q.learning_objectives && Array.isArray(q.learning_objectives) && q.learning_objectives.length > 0) {
              html += `
              <div class="assignment-objectives">
                <strong style="color: #15803d;">🎯 Learning Objectives:</strong>
                <ul style="margin: 10px 0 0 20px; color: #166534;">
                  ${q.learning_objectives.map(obj => `<li style="margin: 6px 0; line-height: 1.5;">${obj}</li>`).join('')}
                </ul>
              </div>`;
            }

            // Meta information
            const metaParts = [];
            if (q.word_count) metaParts.push(`📝 ${q.word_count}`);
            if (q.difficulty) metaParts.push(`⚡ ${q.difficulty}`);
            if (q.code_snippet) metaParts.push(`💻 Includes Code`);
            
            if (metaParts.length > 0) {
              html += `
              <div class="assignment-meta">
                ${metaParts.join(' • ')}
              </div>`;
            }

            html += `</div>`;
            return html;
          })
          .join("")}
      </div>
    `;

    // Show the assignment output
    showAssignmentOutput();

    // Add event listener to the close button
    const closeBtn = id("close-assignment-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", closeAssignmentOutput);
    }
  }

  // Helper function to escape HTML in code snippets
  function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Expose for debugging
  window.renderAssignment = renderAssignment;
  window.closeAssignmentOutput = closeAssignmentOutput; // NEW: Expose close function
  window.showAssignmentOutput = showAssignmentOutput;   // NEW: Expose show function

  /**
   * Generate ADVANCED assignment from PDF
   */
  async function generateAdvancedAssignmentFromPdf() {
    const fileInput = id("assign-pdf-file");
    const modal = id("modal-assign-pdf");
    const genBtn = id("btn-assign-pdf-detect");

    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
      notify("Please select a PDF file.");
      return;
    }

    // Disable button during generation
    if (genBtn) {
      genBtn.disabled = true;
      genBtn.textContent = "Detecting topics...";
    }

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

      // Use all or first 5 subtopics
      const chosenSubtopics = subtopics.slice(0, 5);

      if (genBtn) genBtn.textContent = "Generating assignment...";

      // 2) Get task distribution from modal
      const taskDistribution = {
        conceptual: parseInt(id("conceptual-count")?.value || "0", 10),
        scenario: parseInt(id("scenario-count")?.value || "0", 10),
        research: parseInt(id("research-count")?.value || "0", 10),
        project: parseInt(id("project-count")?.value || "0", 10),
        case_study: parseInt(id("case-study-count")?.value || "0", 10),
        comparative: parseInt(id("comparative-count")?.value || "0", 10),
      };

      const totalTasks = Object.values(taskDistribution).reduce((a, b) => a + b, 0);
      if (totalTasks === 0) {
        notify("Please select at least one assignment type (total must be > 0)");
        return;
      }

      const difficulty = id("assign-difficulty")?.value || "auto";
      const scenarioStyle = id("assign-scenario-style")?.value || "auto";

      const payload = {
        upload_id: uploadId,
        subtopics: chosenSubtopics,
        task_distribution: taskDistribution,
        difficulty: difficulty,
        scenario_style: scenarioStyle,
      };

      const res2 = await fetch("/api/custom/advanced-assignment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data2 = await res2.json();

      if (!res2.ok || !data2 || !data2.success) {
        console.error("Advanced assignment error:", data2);
        notify("Assignment generation failed: " + (data2.error || "Unknown error"));
        return;
      }

      const questions = data2.questions || [];

      if (!questions.length) {
        notify("No questions returned for assignment.");
        return;
      }

      renderAssignment(questions);
      notify(` Generated ${questions.length} assignment tasks!`);
      closeModal(modal);
    } catch (err) {
      console.error(err);
      notify("Unexpected error while generating assignment from PDF.");
    } finally {
      // Re-enable button
      if (genBtn) {
        genBtn.disabled = false;
        genBtn.textContent = " Generate";
      }
    }
  }

  /**
   * Generate ADVANCED assignment from typed topics
   */
  async function generateAssignmentFromTopics() {
    const txtEl = id("assign-topics-text");
    const modal = id("modal-assign-topics");
    const genBtn = id("btn-assign-topics-generate");

    const topicText = (txtEl?.value || "").trim();

    if (!topicText) {
      notify("Please enter at least one topic (one per line).");
      return;
    }

    // Disable button during generation
    if (genBtn) {
      genBtn.disabled = true;
      genBtn.textContent = "Generating...";
    }

    try {
      // Get task distribution from modal
      const taskDistribution = {
        conceptual: parseInt(id("topics-conceptual-count")?.value || "0", 10),
        scenario: parseInt(id("topics-scenario-count")?.value || "0", 10),
        research: parseInt(id("topics-research-count")?.value || "0", 10),
        project: parseInt(id("topics-project-count")?.value || "0", 10),
        case_study: parseInt(id("topics-case-study-count")?.value || "0", 10),
        comparative: parseInt(id("topics-comparative-count")?.value || "0", 10),
      };

      const totalTasks = Object.values(taskDistribution).reduce((a, b) => a + b, 0);
      if (totalTasks === 0) {
        notify("Please select at least one assignment type (total must be > 0)");
        return;
      }

      const difficulty = id("topics-assign-difficulty")?.value || "auto";
      const scenarioStyle = id("topics-assign-scenario-style")?.value || "auto";

      const payload = {
        topic_text: topicText,
        task_distribution: taskDistribution,
        difficulty: difficulty,
        scenario_style: scenarioStyle,
      };

      const res = await fetch("/api/custom/advanced-assignment-topics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok || !data || !data.success) {
        console.error("Assignment from topics error:", data);
        notify("Assignment generation failed: " + (data.error || "Unknown error"));
        return;
      }

      const questions = data.questions || [];
      if (!questions.length) {
        notify("No questions returned for assignment.");
        return;
      }

      renderAssignment(questions);
      notify(` Generated ${questions.length} assignment tasks!`);
      closeModal(modal);
    } catch (err) {
      console.error(err);
      notify("Unexpected error while generating assignment from topics.");
    } finally {
      // Re-enable button
      if (genBtn) {
        genBtn.disabled = false;
        genBtn.textContent = "Generate";
      }
    }
  }

  /**
   * Wire up buttons & modals
   */
  function setupPdfCard() {
    const openBtn = id("btn-open-assign-pdf");
    const modal = id("modal-assign-pdf");
    const closeBtn = id("btn-assign-pdf-close");
    const cancelBtn = id("btn-assign-pdf-cancel-alt");
    const genBtn = id("btn-assign-pdf-detect");

    if (openBtn && modal) {
      openBtn.addEventListener("click", () => openModal(modal));
    }
    if (closeBtn && modal) {
      closeBtn.addEventListener("click", () => closeModal(modal));
    }
    if (cancelBtn && modal) {
      cancelBtn.addEventListener("click", () => closeModal(modal));
    }
    if (genBtn) {
      genBtn.addEventListener("click", generateAdvancedAssignmentFromPdf);
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
        notify("PDF selected ✓");
      }
    });

    input.addEventListener("change", () => {
      updateName();
      if (input.files && input.files[0]) notify("PDF selected ✓");
    });
  }

  // Real-time total counter for PDF modal
  function setupTotalCounter() {
    const countInputs = document.querySelectorAll('[id$="-count"]:not([id^="topics-"])');
    const totalSpan = id('total-tasks-count');
    
    if (!totalSpan || countInputs.length === 0) return;

    function updateTotal() {
      let total = 0;
      countInputs.forEach(input => {
        total += parseInt(input.value || 0);
      });
      totalSpan.textContent = total;
      
      // Update display style
      const display = id('total-tasks-display');
      if (display) {
        if (total === 0) {
          display.style.background = 'linear-gradient(135deg, #fee2e2 0%, #fecaca 100%)';
          display.style.borderColor = '#fca5a5';
          display.style.color = '#991b1b';
        } else {
          display.style.background = 'linear-gradient(135deg, #fff7ed 0%, #fed7aa 100%)';
          display.style.borderColor = '#fdba74';
          display.style.color = '#92400e';
        }
      }
    }

    countInputs.forEach(input => {
      input.addEventListener('input', updateTotal);
    });

    updateTotal(); // Initial update
  }

  // Real-time total counter for Topics modal
  function setupTopicsTotalCounter() {
    const countInputs = document.querySelectorAll('[id^="topics-"][id$="-count"]');
    const totalSpan = id('topics-total-tasks-count');
    
    if (!totalSpan || countInputs.length === 0) return;

    function updateTotal() {
      let total = 0;
      countInputs.forEach(input => {
        total += parseInt(input.value || 0);
      });
      totalSpan.textContent = total;
      
      // Update display style
      const display = id('topics-total-tasks-display');
      if (display) {
        if (total === 0) {
          display.style.background = 'linear-gradient(135deg, #fee2e2 0%, #fecaca 100%)';
          display.style.borderColor = '#fca5a5';
          display.style.color = '#991b1b';
        } else {
          display.style.background = 'linear-gradient(135deg, #fff7ed 0%, #fed7aa 100%)';
          display.style.borderColor = '#fdba74';
          display.style.color = '#92400e';
        }
      }
    }

    countInputs.forEach(input => {
      input.addEventListener('input', updateTotal);
    });

    updateTotal(); // Initial update
  }

  // Initialize everything when DOM is loaded
  document.addEventListener("DOMContentLoaded", () => {
    setupPdfCard();
    setupTopicsCard();
    setupManualCard();
    initAssignPdfUploader();
    setupTotalCounter();         // For PDF modal
    setupTopicsTotalCounter();   // For Topics modal
    
    // Ensure assignment output is initially hidden
    const assignmentOutput = id("assignment-output");
    if (assignmentOutput) {
      assignmentOutput.style.display = "none";
    }
  });
})();