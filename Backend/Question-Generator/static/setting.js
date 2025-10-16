// Helper Functions
const $ = (sel) => document.querySelector(sel);
const id = (s) => document.getElementById(s);

function showEl(el) { 
    if (!el) return; 
    el.hidden = false; 
    el.style.removeProperty('display'); 
}
function hideEl(el) { 
    if (!el) return; 
    el.hidden = true; 
    el.style.display = 'none'; 
}

// Toast notifications
function showToast(msg, type = 'info') {
    const box = id('toast');
    if (!box) return alert(msg);
    box.textContent = msg;
    box.className = `toast ${type}`;
    showEl(box);
    setTimeout(() => hideEl(box), 2200);
}

// Settings Modal Controls
let CURRENT_QUIZ_ID = null;

function initializeSettingsModal() {
    const settingsModal = id('settings-modal');
    const btnClose = id('btn-close-settings');
    const btnCancel = id('btn-cancel-settings');
    const btnSave = id('btn-save-settings');

    if (!settingsModal) {
        console.error('Settings modal not found!');
        return;
    }

    // Add event listeners for modal controls
    btnClose?.addEventListener('click', closeSettingsModal);
    btnCancel?.addEventListener('click', closeSettingsModal);
    btnSave?.addEventListener('click', saveSettings);

    console.log('Settings modal initialized');
}

function openSettingsModal(quizId, preset = {}) {
    console.log('Opening settings modal for quiz:', quizId);
    
    CURRENT_QUIZ_ID = quizId;

    // Get modal elements each time to ensure they're available
    const settingsModal = id('settings-modal');
    const fldTimeLimit = id('time-limit');
    const fldDueDate = id('due-date');
    const chkRetakes = id('allow-retakes');
    const chkShuffle = id('shuffle-questions');
    const taMessage = id('notification-message');

    if (!settingsModal) {
        console.error('Settings modal element not found!');
        showToast('Settings modal not available', 'error');
        return;
    }

    // Pre-fill with preset data or defaults
    if (fldTimeLimit) fldTimeLimit.value = preset.time_limit || 0;
    if (fldDueDate) fldDueDate.value = preset.due_date || '';
    if (chkRetakes) chkRetakes.checked = preset.allow_retakes || false;
    if (chkShuffle) chkShuffle.checked = preset.shuffle_questions !== false;
    if (taMessage) taMessage.value = preset.notification_message || '';

    showEl(settingsModal);
    console.log('Settings modal should be visible now');
}

function closeSettingsModal() {
    const settingsModal = id('settings-modal');
    if (settingsModal) hideEl(settingsModal);
    CURRENT_QUIZ_ID = null;
}

async function saveSettings() {
    if (!CURRENT_QUIZ_ID) {
        showToast('No quiz selected', 'error');
        return closeSettingsModal();
    }

    // Get current values
    const fldTimeLimit = id('time-limit');
    const fldDueDate = id('due-date');
    const chkRetakes = id('allow-retakes');
    const chkShuffle = id('shuffle-questions');
    const taMessage = id('notification-message');

    const payload = {
        time_limit: Number(fldTimeLimit?.value || 0),
        due_date: fldDueDate?.value || null,
        allow_retakes: chkRetakes ? chkRetakes.checked : false,
        shuffle_questions: chkShuffle ? chkShuffle.checked : false,
        notification_message: taMessage ? taMessage.value : ''
    };

    try {
        const res = await fetch(`/api/quizzes/${CURRENT_QUIZ_ID}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const errorText = await res.text().catch(() => res.statusText);
            throw new Error(errorText);
        }
        
        showToast('Settings saved successfully', 'success');
        closeSettingsModal();
    } catch (err) {
        console.error('Save settings error:', err);
        showToast('Failed to save settings', 'error');
    }
}

// Global event delegation for quiz actions
function setupGlobalEventDelegation() {
    console.log('Setting up global event delegation...');
    
    // Handle all quiz action buttons through event delegation
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('button');
        if (!btn) return;

        const quizId = btn.dataset.quizId;
        
        if (btn.classList.contains('btn-settings')) {
            console.log('Settings button clicked for quiz:', quizId);
            e.preventDefault();
            e.stopPropagation();
            
            if (!quizId) {
                showToast('Quiz ID not found', 'error');
                return;
            }
            
            // Try to fetch settings first, then open modal
            fetch(`/api/quizzes/${quizId}/settings`)
                .then(res => {
                    if (!res.ok) throw new Error('Failed to fetch settings');
                    return res.json();
                })
                .then(preset => {
                    openSettingsModal(quizId, preset);
                })
                .catch(err => {
                    console.log('Using default settings due to error:', err);
                    openSettingsModal(quizId, {});
                });
                
        } else if (btn.classList.contains('btn-send')) {
            console.log('Send button clicked for quiz:', quizId);
            if (quizId) {
                sendQuizToStudents(quizId);
            }
            
        } else if (btn.classList.contains('btn-view')) {
            console.log('View button clicked for quiz:', quizId);
            if (quizId) {
                window.open(`/teacher/preview/${quizId}`, '_blank');
            }
        }
    });
}

// Send quiz to students
async function sendQuizToStudents(quizId) {
    try {
        const response = await fetch(`/api/quizzes/${quizId}/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                notify_students: true,
                message: 'A new quiz has been assigned to you!'
            })
        });

        if (response.ok) {
            showToast('Quiz sent to students successfully!', 'success');
        } else {
            showToast('Failed to send quiz to students', 'error');
        }
    } catch (error) {
        console.error('Error sending quiz:', error);
        showToast('Error sending quiz to students', 'error');
    }
}

// Quiz Loader (View Quizzes)
async function loadQuizzes() {
    const listBox = id('quiz-list');
    const emptyBox = id('quiz-empty');
    if (!listBox) return;

    listBox.innerHTML = '<div class="muted">Loading…</div>';
    if (emptyBox) hideEl(emptyBox);

    try {
        const res = await fetch('/api/quizzes');
        if (!res.ok) throw new Error(await res.text().catch(() => res.statusText));
        const items = await res.json();

        if (!Array.isArray(items) || items.length === 0) {
            listBox.innerHTML = '';
            if (emptyBox) showEl(emptyBox);
            return;
        }

        listBox.innerHTML = items.map(qz => {
            const total =
                (typeof qz.questions_count === 'number' ? qz.questions_count : null) ??
                (qz.counts ? Object.values(qz.counts).reduce((a, b) => a + (b || 0), 0) : 0);

            const created = qz.created_at ? new Date(qz.created_at).toLocaleString() : '';

            return `
                <div class="quiz-item" data-quiz-id="${qz.id}">
                    <div class="quiz-info">
                        <div class="quiz-title">${qz.title || 'AI Generated Quiz'}</div>
                        <div class="quiz-meta">
                            ${total} questions${created ? ` • ${created}` : ''}
                        </div>
                    </div>
                    <div class="quiz-actions">
                        <button class="btn btn-view" data-quiz-id="${qz.id}">
                            <i class='bx bx-show'></i> View
                        </button>
                        <button class="btn btn-settings" data-quiz-id="${qz.id}">
                            <i class='bx bx-cog'></i> Settings
                        </button>
                        <button class="btn btn-send" data-quiz-id="${qz.id}">
                            <i class='bx bx-send'></i> Send
                        </button>
                    </div>
                </div>
            `;
        }).join('');

    } catch (e) {
        console.error(e);
        listBox.innerHTML = '<div class="muted">Failed to load quizzes.</div>';
    }
}

// Router (Show Sections)
function showSection(route) {
    const sections = {
        home: id('section-home'),
        generate: id('section-generate'),
        view: id('section-view'),
        grades: id('section-grades'),
    };

    Object.values(sections).forEach(hideEl);
    const sectionToShow = sections[route] || sections.home;
    if (sectionToShow) showEl(sectionToShow);
    
    if (route === 'view') loadQuizzes();
}

// Initialize everything when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, initializing app...');
    
    // Initialize settings modal
    initializeSettingsModal();
    
    // Setup global event delegation
    setupGlobalEventDelegation();
    
    // Setup navigation
    document.querySelectorAll('.topnav .link').forEach(btn => {
        btn.addEventListener('click', () => showSection(btn.dataset.route));
    });

    // Initial Route Setup
    const params = new URLSearchParams(location.search);
    showSection(params.get('route') || 'home');

    // Rotating Text on Home
    (function initRotator() {
        const container = id('rotate-text');
        if (!container) return;
        const items = Array.from(container.querySelectorAll('span'));
        if (items.length <= 1) return;

        let idx = 0;
        items.forEach((el, i) => { 
            if (i !== 0) { 
                el.style.display = 'none'; 
                el.style.opacity = 0; 
            } 
        });

        setInterval(() => {
            const cur = items[idx];
            if (!cur) return;
            cur.style.opacity = 0;
            setTimeout(() => {
                cur.style.display = 'none';
                idx = (idx + 1) % items.length;
                const nxt = items[idx];
                nxt.style.display = '';
                requestAnimationFrame(() => { nxt.style.opacity = 1; });
            }, 200);
        }, 2800);
    })();
});