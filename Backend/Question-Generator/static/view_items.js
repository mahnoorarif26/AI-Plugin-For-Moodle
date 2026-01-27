// static/view_items.js
// View Quizzes / View Assignments logic (teacher)

(() => {
    const id = (s) => document.getElementById(s);

    async function loadItems(kind) {
        const titleEl = id("view-list-title");
        const listEl = id("quiz-list");
        if (!titleEl || !listEl) return;

        const label = kind === "assignment" ? "Assignments" : "Quizzes";
        titleEl.textContent = label;

        listEl.innerHTML = `<div class="muted">Loading ${label.toLowerCase()}...</div>`;

        try {
            const params = kind ? `?kind=${encodeURIComponent(kind)}` : "";
            const res = await fetch(`/api/quizzes${params}`);
            const data = await res.json();

            if (!res.ok || data.success === false) {
                console.error("Failed to load items", data);
                listEl.innerHTML = `<div class="error">Failed to load ${label.toLowerCase()}.</div>`;
                return;
            }

            const items = data.items || [];
            if (!items.length) {
                listEl.innerHTML = `<div class="muted">No ${label.toLowerCase()} found.</div>`;
                return;
            }

            listEl.innerHTML = items.map(renderItemCard).join("");

            attachActionHandlers();
        } catch (err) {
            console.error("Error loading items:", err);
            listEl.innerHTML = `<div class="error">Unexpected error while loading ${label.toLowerCase()}.</div>`;
        }
    }

    function renderItemCard(item) {
        const counts = item.counts || {};
        const totalQuestions =
            (counts.mcq || 0) +
            (counts.true_false || 0) +
            (counts.short || 0) +
            (counts.long || 0);

        const created = formatDate(item.created_at);
        const kind = item.kind || "quiz";
        const kindLabel = kind === "assignment" ? "Assignment" : "Quiz";

        const parts = [];
        parts.push(`${totalQuestions} questions`);
        if (counts.mcq) parts.push(`${counts.mcq} MCQ`);
        if (counts.true_false) parts.push(`${counts.true_false} TF`);
        if (counts.short) parts.push(`${counts.short} Short`);
        if (counts.long) parts.push(`${counts.long} Long`);
        if (created) parts.push(`Created: ${created}`);
        const metaText = parts.join(" • ");

        return `
        <div class="quiz-card quiz-list-card" data-kind="${kind}" data-id="${item.id}">
            <div class="quiz-list-card-top">
            <div>
                <h3 class="quiz-list-title">${escapeHtml(item.title || "Untitled Quiz")}</h3>
                <p class="quiz-list-kind">${kindLabel}</p>
            </div>
            <span class="badge badge-${kind}">${kindLabel}</span>
            </div>

            <p class="quiz-list-meta">${metaText}</p>

            <div class="quiz-list-actions-row">
            <button class="generate-btn small btn-preview" data-id="${item.id}">
                Preview
            </button>
            <button class="btn ghost small btn-settings" data-id="${item.id}">
                Settings
            </button>
            <button class="btn ghost small btn-submissions" data-id="${item.id}">
                Submissions
            </button>
            </div>
        </div>
        `;
    }


    function attachActionHandlers() {
        document.querySelectorAll(".btn-preview").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const quizId = e.currentTarget.getAttribute("data-id");
                openPreview(quizId);
            });
        });

        document.querySelectorAll(".btn-settings").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const quizId = e.currentTarget.getAttribute("data-id");
                openSettings(quizId);
            });
        });

        document.querySelectorAll(".btn-submissions").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const quizId = e.currentTarget.getAttribute("data-id");
                openSubmissions(quizId);
            });
        });
    }

    function openPreview(quizId) {
        // Teacher preview page (no answers)
        window.open(`/teacher/preview/${quizId}`, "_blank");
    }

    async function openSettings(quizId) {
        const modal = id("quiz-settings-modal");
        if (!modal) {
            console.warn("Settings modal not found in DOM");
            return;
        }

        modal.dataset.quizId = quizId;
        modal.style.display = "block";

        // Reset inputs
        id("settings-time-limit").value = 30;
        id("settings-due-date").value = "";
        id("settings-note").value = "";

        try {
            const res = await fetch(`/api/quizzes/${quizId}/settings`);
            const data = await res.json();

            // backend returns: { success, data: {settings: {...}} } OR just settings
            const settings = data.settings || (data.data && data.data.settings) || {};

            if (settings.time_limit) {
                id("settings-time-limit").value = settings.time_limit;
            }
            if (settings.due_date) {
                // If backend stores ISO string, convert to local datetime-local format
                try {
                    const d = new Date(settings.due_date);
                    const isoLocal = d.toISOString().slice(0, 16);
                    id("settings-due-date").value = isoLocal;
                } catch (_) {}
            }
            if (settings.notification_message) {
                id("settings-note").value = settings.notification_message;
            }
        } catch (err) {
            console.error("Failed to load quiz settings", err);
            (window.showToast || alert)(
                "Failed to load settings for this quiz. Please try again."
            );
        }
    }

    async function saveSettings() {
        const modal = id("quiz-settings-modal");
        if (!modal) return;

        const quizId = modal.dataset.quizId;
        if (!quizId) return;

        const timeLimit = parseInt(id("settings-time-limit").value, 10) || 30;
        const dueDateRaw = id("settings-due-date").value || null;
        const note = id("settings-note").value || "";

        const payload = {
            time_limit: timeLimit,
            due_date: dueDateRaw,
            notification_message: note,
            // you can extend: allow_retakes, shuffle_questions etc.
        };

        try {
            const res = await fetch(`/api/quizzes/${quizId}/settings`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await res.json();

            if (res.ok && data.success !== false) {
                (window.showToast || alert)("Settings updated successfully.");
                modal.style.display = "none";
            } else {
                console.error("Settings update failed", data);
                (window.showToast || alert)(
                    data.message || "Failed to update settings."
                );
            }
        } catch (err) {
            console.error("Error updating settings:", err);
            (window.showToast || alert)(
                "Unexpected error while updating settings."
            );
        }
    }

    function formatDate(dateString) {
        if (!dateString) return "Unknown date";
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString() + " " + date.toLocaleTimeString();
        } catch (e) {
            return dateString;
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function openSubmissions(quizId){
        if (!quizId) return;
        window.open(`/teacher/submissions/${quizId}`, "_blank");
    }

    // Make functions globally available if you ever need them
    window.openPreview = openPreview;
    window.openSettings = openSettings;

    document.addEventListener("DOMContentLoaded", () => {
        const btnQuizzes = document.getElementById("btn-view-quizzes");
        const btnAssignments = document.getElementById("btn-view-assignments");
        const viewContainer = document.getElementById("view-list-container");
        const heading = document.getElementById("view-list-title");

        const modal = id("quiz-settings-modal");
        const btnClose = id("btn-settings-close");
        const btnSave = id("btn-settings-save");

        function showContainer() {
            viewContainer.style.display = "block";
        }

        if (btnQuizzes) {
            btnQuizzes.addEventListener("click", () => {
                heading.textContent = "Quizzes";
                showContainer();
                loadItems("quiz");
            });
        }

        if (btnAssignments) {
            btnAssignments.addEventListener("click", () => {
                heading.textContent = "Assignments";
                showContainer();
                loadItems("assignment");
            });
        }

        if (btnClose && modal) {
            btnClose.addEventListener("click", () => {
                modal.style.display = "none";
            });
        }

        if (btnSave && modal) {
            btnSave.addEventListener("click", saveSettings);
        }
    });
})();
