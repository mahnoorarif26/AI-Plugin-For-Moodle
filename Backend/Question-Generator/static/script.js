class QuestionGenerator {
    constructor() {
        this.generateBtn = document.getElementById('generate-btn');
        this.copyBtn = document.getElementById('copy-btn');
        this.outputContainer = document.getElementById('output');
        this.outputContent = document.getElementById('output-content');
        this.buttonText = document.querySelector('.button-text');
        this.buttonLoader = document.querySelector('.button-loader');
        
        this.initEventListeners();
    }

    initEventListeners() {
        this.generateBtn.addEventListener('click', () => this.generateQuestions());
        this.copyBtn.addEventListener('click', () => this.copyToClipboard());
        
        // Enter key support
        document.getElementById('topic').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.generateQuestions();
            }
        });
    }

    async generateQuestions() {
        const topic = document.getElementById('topic').value.trim();
        const numQuestions = document.getElementById('num_questions').value;

        if (!topic) {
            this.showError('Please enter a topic');
            return;
        }

        this.setLoadingState(true);

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
            this.setLoadingState(false);
        }
    }

    setLoadingState(isLoading) {
        if (isLoading) {
            this.generateBtn.disabled = true;
            this.buttonText.style.display = 'none';
            this.buttonLoader.style.display = 'flex';
        } else {
            this.generateBtn.disabled = false;
            this.buttonText.style.display = 'block';
            this.buttonLoader.style.display = 'none';
        }
    }

    displayQuestions(questions) {
        // Format the questions with better styling
        const formattedQuestions = this.formatQuestions(questions);
        this.outputContent.innerHTML = formattedQuestions;
        this.outputContainer.style.display = 'block';
        
        // Scroll to output
        this.outputContainer.scrollIntoView({ 
            behavior: 'smooth', 
            block: 'nearest' 
        });
    }

    formatQuestions(questions) {
        // Split questions by line and format each one
        const lines = questions.split('\n').filter(line => line.trim());
        let formatted = '';
        
        lines.forEach((line, index) => {
            if (line.match(/^\d+\./)) {
                // Question line
                formatted += `<div class="question-item">
                    <h4>${line}</h4>
                </div>`;
            } else if (line.trim()) {
                // Answer or explanation
                formatted += `<p>${line}</p>`;
            }
        });
        
        return formatted || `<p>${questions}</p>`;
    }

    async copyToClipboard() {
        try {
            const text = this.outputContent.innerText;
            await navigator.clipboard.writeText(text);
            
            // Visual feedback
            this.copyBtn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            `;
            this.copyBtn.classList.add('success');
            
            setTimeout(() => {
                this.copyBtn.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M8 16H6C4.89543 16 4 15.1046 4 14V6C4 4.89543 4.89543 4 6 4H14C15.1046 4 16 4.89543 16 6V8M10 20H18C19.1046 20 20 19.1046 20 18V10C20 8.89543 19.1046 8 18 8H10C8.89543 8 8 8.89543 8 10V18C8 19.1046 8.89543 20 10 20Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                `;
                this.copyBtn.classList.remove('success');
            }, 2000);
            
        } catch (err) {
            console.error('Failed to copy text: ', err);
        }
    }

    showError(message) {
        // Remove any existing error messages
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

        const formContainer = document.querySelector('.form-container');
        formContainer.insertBefore(errorDiv, formContainer.firstChild);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.remove();
            }
        }, 5000);
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new QuestionGenerator();
});