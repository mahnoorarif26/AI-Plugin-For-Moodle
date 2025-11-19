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

            // FIX: Use data.items instead of data.quizzes
            const items = data.items || [];
            if (!items.length) {
                listEl.innerHTML = `<div class="muted">No ${label.toLowerCase()} found.</div>`;
                return;
            }

            listEl.innerHTML = items.map(renderItemCard).join("");
            
            // Add click handlers for open buttons
            attachOpenHandlers();
        } catch (err) {
            console.error("Error loading items:", err);
            listEl.innerHTML = `<div class="error">Unexpected error while loading ${label.toLowerCase()}.</div>`;
        }
    }

    function renderItemCard(item) {
        const counts = item.counts || {};
        const totalQuestions = counts.mcq + counts.true_false + counts.short + counts.long;
        const created = formatDate(item.created_at);
        const kind = item.kind || "quiz";

        return `
            <div class="quiz-list-item" data-kind="${kind}" data-id="${item.id}">
                <div class="quiz-list-header">
                    <h4>${escapeHtml(item.title || "Untitled Quiz")}</h4>
                    <span class="badge badge-${kind}">${kind}</span>
                </div>
                <div class="quiz-list-meta">
                    <span>${totalQuestions} questions</span>
                    <span class="question-types">
                        ${counts.mcq ? `${counts.mcq} MCQ` : ''}
                        ${counts.true_false ? `${counts.true_false} TF` : ''}
                        ${counts.short ? `${counts.short} Short` : ''}
                        ${counts.long ? `${counts.long} Long` : ''}
                    </span>
                    <span>Created: ${created}</span>
                </div>
                <div class="quiz-list-actions">
                    <button class="btn small btn-open" data-id="${item.id}">
                        Open
                    </button>
                    <button class="btn small btn-secondary" onclick="viewSubmissions('${item.id}')">
                        Submissions
                    </button>
                </div>
            </div>
        `;
    }

    function attachOpenHandlers() {
        document.querySelectorAll('.btn-open').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const quizId = e.target.getAttribute('data-id');
                openQuiz(quizId);
            });
        });
    }

    function openQuiz(quizId) {
        // Open quiz in new tab for student view, or teacher preview
        window.open(`/student/quiz/${quizId}`, '_blank');
    }

    function viewSubmissions(quizId) {
        // Open submissions page
        window.open(`/teacher/submissions/${quizId}`, '_blank');
    }

    function formatDate(dateString) {
        if (!dateString) return 'Unknown date';
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        } catch (e) {
            return dateString;
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Make functions globally available
    window.openQuiz = openQuiz;
    window.viewSubmissions = viewSubmissions;

    document.addEventListener("DOMContentLoaded", () => {
        const btnQuizzes = id("btn-view-quizzes");
        const btnAssignments = id("btn-view-assignments");

        if (btnQuizzes) {
            btnQuizzes.addEventListener("click", () => loadItems("quiz"));
        }
        if (btnAssignments) {
            btnAssignments.addEventListener("click", () => loadItems("assignment"));
        }

        // Load quizzes by default when page loads
        loadItems("quiz");
    });
})();