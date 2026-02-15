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

        console.log("📊 API Response:", data); // Debug log

        if (!res.ok || data.success === false) {
            console.error("Failed to load items", data);
            listEl.innerHTML = `<div class="error">Failed to load ${label.toLowerCase()}.</div>`;
            return;
        }

        const items = data.items || [];
        
        // Debug each item
        items.forEach(item => {
            console.log(`📝 Item: ${item.title}, Questions: ${item.questions_count || (item.questions ? item.questions.length : 0)}`);
        });

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
    // Calculate questions count properly
    const questionsCount = item.questions_count || 
                          (item.counts ? Object.values(item.counts).reduce((a, b) => a + b, 0) : 0) ||
                          (item.questions ? item.questions.length : 0);

    const created = formatDate(item.created_at);
    const kind = item.kind || item.metadata?.kind || "quiz";
    const kindLabel = kind === "assignment" ? "Assignment" : "Quiz";

    const parts = [];
    parts.push(`${questionsCount} questions`);
    if (item.counts?.mcq) parts.push(`${item.counts.mcq} MCQ`);
    if (item.counts?.true_false) parts.push(`${item.counts.true_false} TF`);
    if (item.counts?.short) parts.push(`${item.counts.short} Short`);
    if (item.counts?.long) parts.push(`${item.counts.long} Long`);
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
            <button class="btn ghost small btn-submissions" data-id="${item.id}">
                Submissions
            </button>
            </div>
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

    document.addEventListener("DOMContentLoaded", () => {
        const btnQuizzes = document.getElementById("btn-view-quizzes");
        const btnAssignments = document.getElementById("btn-view-assignments");
        const viewContainer = document.getElementById("view-list-container");
        const heading = document.getElementById("view-list-title");

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
    });
})();