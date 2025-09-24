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
        
        // Clear any existing error messages
        this.clearErrors();
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
            
            if (data.error) {
                throw new Error(data.error);
            }
            
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
            button.classList.add('loading');
        } else {
            button.disabled = false;
            buttonText.style.display = 'block';
            buttonLoader.style.display = 'none';
            button.classList.remove('loading');
        }
    }

    displayQuestions(questions) {
        const formattedQuestions = this.formatQuestions(questions);
        document.getElementById('output-content').innerHTML = formattedQuestions;
        document.getElementById('output').style.display = 'block';
    
        this.scrollToOutput();
    }

    displayCustomQuestions(questions) {
        const formattedQuestions = this.formatCustomQuestions(questions);
        document.getElementById('output-content').innerHTML = formattedQuestions;
        document.getElementById('output').style.display = 'block';
    
        this.scrollToOutput();
    }

    f// In your QuestionGenerator class, replace these methods:
formatQuestions(questions) {
    // If the response contains markdown tables, use the table formatter
    if (questions.includes('|') && questions.includes('---')) {
        return this.formatMarkdownTable(questions);
    }
    
    const lines = questions.split('\n').filter(line => line.trim());
    let formatted = '';
    let currentQuestion = '';
    
    lines.forEach((line) => {
        if (line.match(/^\d+\./) || line.match(/^[Qq]uestion\s+\d+/i)) {
            if (currentQuestion) {
                formatted += `</div>`;
            }
            currentQuestion = line;
            formatted += `<div class="question-item">
                <h4>${this.escapeHtml(line)}</h4>`;
        } else if (line.trim()) {
            formatted += `<p>${this.escapeHtml(line)}</p>`;
        }
    });
    
    if (currentQuestion) {
        formatted += `</div>`;
    }
    
    return formatted || `<div class="question-item"><p>${this.escapeHtml(questions)}</p></div>`;
}

formatCustomQuestions(questions) {
    // If the response contains markdown tables, use the table formatter
    if (questions.includes('|') && questions.includes('---')) {
        return this.formatMarkdownTable(questions);
    }
    
    const lines = questions.split('\n').filter(line => line.trim());
    let formatted = '';
    let currentQuestion = '';
    let inOptions = false;
    
    lines.forEach((line) => {
        const trimmedLine = line.trim();
        
        if (trimmedLine.match(/^\d+\./) || trimmedLine.match(/^(MCQ|Short Answer|Long Answer)/i)) {
            if (currentQuestion) {
                if (inOptions) {
                    formatted += `</div>`;
                    inOptions = false;
                }
                formatted += `</div>`;
            }
            
            let typeBadge = '';
            if (trimmedLine.includes('MCQ') || trimmedLine.match(/multiple choice/i)) {
                typeBadge = '<span class="question-type-badge">MCQ</span>';
            } else if (trimmedLine.includes('Short Answer') || trimmedLine.match(/short answer/i)) {
                typeBadge = '<span class="question-type-badge" style="background: #38a169;">Short Answer</span>';
            } else if (trimmedLine.includes('Long Answer') || trimmedLine.match(/long answer/i)) {
                typeBadge = '<span class="question-type-badge" style="background: #d69e2e;">Long Answer</span>';
            }
            
            currentQuestion = trimmedLine;
            formatted += `<div class="question-item">
                ${typeBadge}
                <h4>${this.escapeHtml(trimmedLine)}</h4>`;
                
        } else if (trimmedLine.match(/^[A-D]\./)) {
            if (!inOptions) {
                formatted += `<div class="question-options">`;
                inOptions = true;
            }
            formatted += `<div>${this.escapeHtml(trimmedLine)}</div>`;
            
        } else if (trimmedLine.match(/correct answer|answer:/i)) {
            if (inOptions) {
                formatted += `</div>`;
                inOptions = false;
            }
            formatted += `<div class="correct-answer">${this.escapeHtml(trimmedLine)}</div>`;
            
        } else if (trimmedLine) {
            if (inOptions) {
                formatted += `</div>`;
                inOptions = false;
            }
            formatted += `<p>${this.escapeHtml(trimmedLine)}</p>`;
        }
    });
    
    if (inOptions) {
        formatted += `</div>`;
    }
    if (currentQuestion) {
        formatted += `</div>`;
    }
    
    return formatted || `<div class="question-item"><p>${this.escapeHtml(questions)}</p></div>`;
}

// ADD THESE NEW METHODS TO YOUR QuestionGenerator CLASS:
formatMarkdownTable(questions) {
    const lines = questions.split('\n').filter(line => line.trim());
    let formatted = '';
    let inTable = false;
    let tableRows = [];
    
    lines.forEach((line) => {
        const trimmedLine = line.trim();
        
        // Detect table start
        if (trimmedLine.includes('|') && trimmedLine.includes('---')) {
            inTable = true;
            return;
        }
        
        // Process table rows
        if (inTable && trimmedLine.includes('|')) {
            tableRows.push(trimmedLine);
        } else if (inTable && !trimmedLine.includes('|')) {
            // Table ended, process the collected rows
            formatted += this.processTableRows(tableRows);
            tableRows = [];
            inTable = false;
            
            // Process non-table content
            if (trimmedLine) {
                formatted += `<div class="question-item"><p>${this.escapeHtml(trimmedLine)}</p></div>`;
            }
        } else if (!inTable && trimmedLine) {
            // Regular content
            if (trimmedLine.match(/^\d+\./) || trimmedLine.match(/^[Qq]uestion\s+\d+/i)) {
                formatted += `<div class="question-item"><h4>${this.escapeHtml(trimmedLine)}</h4>`;
            } else {
                formatted += `<p>${this.escapeHtml(trimmedLine)}</p>`;
            }
        }
    });
    
    // Process any remaining table rows
    if (tableRows.length > 0) {
        formatted += this.processTableRows(tableRows);
    }
    
    return formatted || `<div class="question-item"><p>${this.escapeHtml(questions)}</p></div>`;
}

processTableRows(rows) {
    if (rows.length === 0) return '';
    
    let formatted = '<div class="question-table">';
    
    rows.forEach((row, index) => {
        if (index === 0) {
            // Header row
            formatted += '<div class="table-header">';
            const cells = row.split('|').filter(cell => cell.trim());
            cells.forEach(cell => {
                formatted += `<div class="table-cell header-cell">${this.escapeHtml(cell.trim())}</div>`;
            });
            formatted += '</div>';
        } else {
            // Data row
            formatted += '<div class="table-row">';
            const cells = row.split('|').filter(cell => cell.trim());
            cells.forEach((cell, cellIndex) => {
                const cellContent = cell.trim();
                const isQuestion = cellIndex === 0 && cellContent.match(/^\d+\./);
                const isCorrectAnswer = cellContent.match(/^\*\*[A-D]\*\*$/);
                
                let cellClass = 'table-cell';
                if (isQuestion) cellClass += ' question-cell';
                if (isCorrectAnswer) cellClass += ' correct-answer-cell';
                
                formatted += `<div class="${cellClass}">${this.formatTableCell(cellContent)}</div>`;
            });
            formatted += '</div>';
        }
    });
    
    formatted += '</div>';
    return formatted;
}

formatTableCell(content) {
    // Format markdown elements
    let formattedContent = content
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') // Bold
        .replace(/\*(.*?)\*/g, '<em>$1</em>') // Italic
        .replace(/`(.*?)`/g, '<code>$1</code>') // Code
        .replace(/<br\s*\/?>/g, '<br>'); // Line breaks
    
    return this.escapeHtml(formattedContent);
}

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    scrollToOutput() {
        const outputElement = document.getElementById('output');
        outputElement.scrollIntoView({ 
            behavior: 'smooth', 
            block: 'nearest' 
        });
        
        // Add subtle animation to highlight the new content
        outputElement.style.animation = 'none';
        setTimeout(() => {
            outputElement.style.animation = 'fadeInUp 0.5s ease-out';
        }, 10);
    }

    async copyToClipboard() {
        try {
            const text = document.getElementById('output-content').innerText;
            await navigator.clipboard.writeText(text);
            
            this.showCopySuccess();
            
        } catch (err) {
            console.error('Failed to copy text: ', err);
            this.showError('Failed to copy to clipboard. Please try again.');
        }
    }

    showCopySuccess() {
        const copyBtn = document.getElementById('copy-btn');
        const originalHTML = copyBtn.innerHTML;
        
        copyBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            Copied!
        `;
        copyBtn.classList.add('success');
        copyBtn.style.background = '#38a169';
        copyBtn.style.color = 'white';
        
        setTimeout(() => {
            copyBtn.innerHTML = originalHTML;
            copyBtn.classList.remove('success');
            copyBtn.style.background = '';
            copyBtn.style.color = '';
        }, 2000);
    }

    showError(message) {
        this.clearErrors();
        
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
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

    clearErrors() {
        const existingErrors = document.querySelectorAll('.error-message');
        existingErrors.forEach(error => error.remove());
    }

    // Utility method to format question text with better readability
    formatQuestionText(text) {
        return text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') // Bold text
            .replace(/\*(.*?)\*/g, '<em>$1</em>') // Italic text
            .replace(/\n{2,}/g, '</p><p>') // Multiple newlines to paragraph breaks
            .replace(/\n/g, '<br>'); // Single newlines to line breaks
    }

    // Method to handle API response errors
    handleApiError(error) {
        console.error('API Error:', error);
        
        if (error.message.includes('Failed to fetch')) {
            this.showError('Network error. Please check your connection and try again.');
        } else if (error.message.includes('429')) {
            this.showError('Too many requests. Please wait a moment and try again.');
        } else {
            this.showError('An unexpected error occurred. Please try again.');
        }
    }

    // Method to validate input
    validateInput(topic, numQuestions) {
        if (!topic || topic.trim().length === 0) {
            return 'Please enter a valid topic';
        }
        
        if (topic.length > 500) {
            return 'Topic is too long. Please keep it under 500 characters.';
        }
        
        if (numQuestions < 1 || numQuestions > 50) {
            return 'Number of questions must be between 1 and 50.';
        }
        
        return null;
    }

    // Method to add question numbering
    addQuestionNumbers(text) {
        const lines = text.split('\n');
        let questionCount = 0;
        let result = [];
        
        lines.forEach(line => {
            if (line.trim().match(/^[Qq]uestion\s+\d+[:.]?/i) || line.trim().match(/^\d+\./)) {
                questionCount++;
                result.push(line);
            } else if (line.trim().match(/^[A-D]\./)) {
                result.push(`    ${line.trim()}`);
            } else {
                result.push(line);
            }
        });
        
        return result.join('\n');
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    const questionGenerator = new QuestionGenerator();
    
    // Add global error handler
    window.addEventListener('error', (event) => {
        console.error('Global error:', event.error);
    });
    
    // Add unhandled promise rejection handler
    window.addEventListener('unhandledrejection', (event) => {
        console.error('Unhandled promise rejection:', event.reason);
    });
    
    // Export for debugging (optional)
    window.questionGenerator = questionGenerator;
});

// Additional utility functions
const QuizUtils = {
    // Sanitize user input
    sanitizeInput: function(input) {
        return input.trim().replace(/[<>]/g, '');
    },
    
    // Format numbers with leading zeros
    formatNumber: function(num, digits = 2) {
        return num.toString().padStart(digits, '0');
    },
    
    // Debounce function for input events
    debounce: function(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    // Throttle function for scroll events
    throttle: function(func, limit) {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
};

// CSS utility for dynamic styling
const StyleManager = {
    addStyles: function(styles) {
        const styleSheet = document.createElement('style');
        styleSheet.textContent = styles;
        document.head.appendChild(styleSheet);
    },
    
    updateTheme: function(theme) {
        const root = document.documentElement;
        Object.keys(theme).forEach(key => {
            root.style.setProperty(`--${key}`, theme[key]);
        });
    }
};

// Add some additional dynamic styles
StyleManager.addStyles(`
    .question-item.fade-in {
        animation: slideInUp 0.6s ease-out;
    }
    
    .question-item.highlight {
        background: #fffaf0;
        border-color: #ed8936;
        box-shadow: 0 4px 12px rgba(237, 137, 54, 0.1);
    }
    
    @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.02); }
        100% { transform: scale(1); }
    }
    
    .pulse {
        animation: pulse 0.3s ease-in-out;
    }
`);

// Export utilities for global access (optional)
window.QuizUtils = QuizUtils;
window.StyleManager = StyleManager;