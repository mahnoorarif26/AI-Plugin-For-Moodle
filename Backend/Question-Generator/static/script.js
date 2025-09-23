class QuestionGenerator {
    constructor() {
        this.currentMode = 'quick';
        this.initEventListeners();
        this.initModeSelection();
    }

    initEventListeners() {
        // Quick quiz generation
        document.getElementById('generate-btn').addEventListener('click', () => this.generateQuestions());
        
        // Custom quiz generation
        document.getElementById('generate-custom-btn').addEventListener('click', () => this.generateCustomQuiz());
        
        // Copy to clipboard
        document.getElementById('copy-btn').addEventListener('click', () => this.copyToClipboard());
        
        // Enter key support
        document.getElementById('topic').addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && this.currentMode === 'quick') {
                this.generateQuestions();
            }
        });
        
        document.getElementById('custom-topic').addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && this.currentMode === 'custom') {
                this.generateCustomQuiz();
            }
        });
    }

    initModeSelection() {
        const modeCards = document.querySelectorAll('.mode-card');
        
        modeCards.forEach(card => {
            card.addEventListener('click', () => {
                const mode = card.dataset.mode;
                this.switchMode(mode);
            });
        });
    }

    switchMode(mode) {
        this.currentMode = mode;
        
        // Update active card
        document.querySelectorAll('.mode-card').forEach(card => {
            card.classList.remove('active');
        });
        document.querySelector(`[data-mode="${mode}"]`).classList.add('active');
        
        // Show/hide forms
        document.getElementById('quick-quiz-form').classList.toggle('active', mode === 'quick');
        document.getElementById('custom-quiz-form').style.display = mode === 'custom' ? 'block' : 'none';
        
        // Hide output when switching modes
        document.getElementById('output').style.display = 'none';
    }

    async generateQuestions() {
        const topic = document.getElementById('topic').value.trim();
        const numQuestions = document.getElementById('num_questions').value;

        if (!topic) {
            this.showError('Please enter a topic');
            return;
        }

        this.setLoadingState('generate-btn', true);

        try {
            const response = await fetch("/generate-question", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ topic, num_questions: numQuestions })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            this.displayQuestions(data.questions);
            
        } catch (error) {
            console.error('Error:', error);
            this.showError('Failed to generate questions. Please try again.');
        } finally {
            this.setLoadingState('generate-btn', false);
        }
    }

    async generateCustomQuiz() {
        const topic = document.getElementById('custom-topic').value.trim();
        const numQuestions = document.getElementById('custom-num-questions').value;
        const questionTypes = this.getSelectedQuestionTypes();

        if (!topic) {
            this.showError('Please enter a topic');
            return;
        }

        if (questionTypes.length === 0) {
            this.showError('Please select at least one question type');
            return;
        }

        this.setLoadingState('generate-custom-btn', true);

        try {
            const response = await fetch("/generate-custom-quiz", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ 
                    topic, 
                    num_questions: numQuestions,
                    question_types: questionTypes
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            if (data.error) {
                throw new Error(data.error);
            }
            this.displayCustomQuestions(data.questions);
            
        } catch (error) {
            console.error('Error:', error);
            this.showError(error.message || 'Failed to generate custom quiz. Please try again.');
        } finally {
            this.setLoadingState('generate-custom-btn', false);
        }
    }

    getSelectedQuestionTypes() {
        const checkboxes = document.querySelectorAll('input[name="question-type"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    }

    setLoadingState(buttonId, isLoading) {
        const button = document.getElementById(buttonId);
        const buttonText = button.querySelector('.button-text');
        const buttonLoader = button.querySelector('.button-loader');

        if (isLoading) {
            button.disabled = true;
            buttonText.style.display = 'none';
            buttonLoader.style.display = 'flex';
        } else {
            button.disabled = false;
            buttonText.style.display = 'block';
            buttonLoader.style.display = 'none';
        }
    }

    displayQuestions(questions) {
        const formattedQuestions = this.formatQuestions(questions);
        document.getElementById('output-content').innerHTML = formattedQuestions;
        document.getElementById('output').style.display = 'block';
    
        document.getElementById('output').scrollIntoView({ 
            behavior: 'smooth', 
            block: 'nearest' 
        });
    }

    displayCustomQuestions(questions) {
        const formattedQuestions = this.formatCustomQuestions(questions);
        document.getElementById('output-content').innerHTML = formattedQuestions;
        document.getElementById('output').style.display = 'block';
    
        document.getElementById('output').scrollIntoView({ 
            behavior: 'smooth', 
            block: 'nearest' 
        });
    }

    formatQuestions(questions) {
        const lines = questions.split('\n').filter(line => line.trim());
        let formatted = '';
        
        lines.forEach((line, index) => {
            if (line.match(/^\d+\./)) {
                formatted += `<div class="question-item">
                    <h4>${line}</h4>
                </div>`;
            } else if (line.trim()) {
                formatted += `<p>${line}</p>`;
            }
        });
        
        return formatted || `<p>${questions}</p>`;
    }

    formatCustomQuestions(questions) {
        const lines = questions.split('\n').filter(line => line.trim());
        let formatted = '';
        let currentQuestion = '';
        
        lines.forEach((line) => {
            if (line.match(/^\d+\./) || line.match(/^(MCQ|Short Answer|Long Answer)/i)) {
                if (currentQuestion) {
                    formatted += `</div>`;
                }
                
                // Add question type badge
                let typeBadge = '';
                if (line.includes('MCQ') || line.match(/multiple choice/i)) {
                    typeBadge = '<span class="question-type-badge">MCQ</span>';
                } else if (line.includes('Short Answer') || line.match(/short answer/i)) {
                    typeBadge = '<span class="question-type-badge" style="background: #38a169;">Short Answer</span>';
                } else if (line.includes('Long Answer') || line.match(/long answer/i)) {
                    typeBadge = '<span class="question-type-badge" style="background: #d69e2e;">Long Answer</span>';
                }
                
                currentQuestion = line;
                formatted += `<div class="question-item">
                    ${typeBadge}
                    <h4>${line}</h4>`;
            } else if (line.match(/^[A-D]\./)) {
                formatted += `<div class="question-options">
                    <div>${line}</div>`;
            } else if (line.match(/correct answer|answer:/i)) {
                formatted += `<div class="correct-answer">${line}</div>`;
            } else if (line.trim()) {
                formatted += `<p>${line}</p>`;
            }
        });
        
        if (currentQuestion) {
            formatted += `</div>`;
        }
        
        return formatted || `<p>${questions}</p>`;
    }

    async copyToClipboard() {
        try {
            const text = document.getElementById('output-content').innerText;
            await navigator.clipboard.writeText(text);
            
            // Visual feedback
            const copyBtn = document.getElementById('copy-btn');
            copyBtn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            `;
            copyBtn.classList.add('success');
            
            setTimeout(() => {
                copyBtn.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M8 16H6C4.89543 16 4 15.1046 4 14V6C4 4.89543 4.89543 4 6 4H14C15.1046 4 16 4.89543 16 6V8M10 20H18C19.1046 20 20 19.1046 20 18V10C20 8.89543 19.1046 8 18 8H10C8.89543 8 8 8.89543 8 10V18C8 19.1046 8.89543 20 10 20Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                `;
                copyBtn.classList.remove('success');
            }, 2000);
            
        } catch (err) {
            console.error('Failed to copy text: ', err);
        }
    }

    showError(message) {
        const existingError = document.querySelector('.error-message');
        if (existingError) {
            existingError.remove();
        }

        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.style.cssText = `
            background: #fed7d7;
            color: #c53030;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #f56565;
        `;
        errorDiv.textContent = message;

        const activeForm = this.currentMode === 'quick' ? 
            document.getElementById('quick-quiz-form') : 
            document.getElementById('custom-quiz-form');
        
        activeForm.insertBefore(errorDiv, activeForm.firstChild);

        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.remove();
            }
        }, 5000);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new QuestionGenerator();
});