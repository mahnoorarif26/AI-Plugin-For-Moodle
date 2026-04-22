/**
 * Duplicate Detection System for AI-Generated Quizzes
 * Automatically checks for similar questions when quiz is generated
 */

async function checkQuizDuplicates(questions) {
    try {
        const response = await fetch('/api/questions/check-duplicates', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ questions })
        });
        
        const data = await response.json();
        
        if (data.has_duplicates) {
            showDuplicateWarning(data);
        }
        
        return data;
    } catch (error) {
        console.error('Duplicate check failed:', error);
        return null;
    }
}

function showDuplicateWarning(duplicateData) {
    const html = `
        <div class="duplicate-warning" style="
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            border: 2px solid #f59e0b;
            border-radius: 12px;
            padding: 20px;
            margin: 15px 0;
            animation: slideDown 0.3s ease-out;
        ">
            <div style="display: flex; align-items: start; gap: 15px;">
                <span style="font-size: 2em;">⚠️</span>
                <div style="flex: 1;">
                    <h4 style="margin: 0 0 10px 0; color: #92400e; font-size: 1.2em;">
                        ${duplicateData.duplicate_count} Potential Duplicate${duplicateData.duplicate_count > 1 ? 's' : ''} Detected
                    </h4>
                    <p style="margin: 0 0 15px 0; color: #78350f; font-size: 0.95em;">
                        Some AI-generated questions are similar to existing questions in your database:
                    </p>
                    <ul style="margin: 0; padding-left: 20px; color: #78350f;">
                        ${duplicateData.report.slice(0, 3).map(dup => `
                            <li style="margin: 8px 0; line-height: 1.5;">
                                <strong style="color: #92400e;">Question ${dup.question_index + 1}</strong>: 
                                <span style="background: #fbbf24; color: #78350f; padding: 2px 8px; border-radius: 4px; font-weight: 600;">
                                    ${dup.highest_similarity}% similar
                                </span>
                                <br>
                                <small style="color: #b45309; font-style: italic;">"${dup.question_text}..."</small>
                            </li>
                        `).join('')}
                    </ul>
                    ${duplicateData.duplicate_count > 3 ? 
                        `<p style="margin: 10px 0 0 0; font-size: 0.9em; color: #92400e; font-style: italic;">
                            ...and ${duplicateData.duplicate_count - 3} more potential duplicate${duplicateData.duplicate_count - 3 > 1 ? 's' : ''}
                        </p>` : ''
                    }
                    <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #fdba74;">
                        <small style="color: #b45309;">
                            💡 <strong>Tip:</strong> Consider reviewing these questions or regenerating with different parameters to ensure uniqueness.
                        </small>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Insert warning before quiz output
    const quizSection = document.getElementById('quiz-section');
    if (quizSection) {
        // Remove any existing duplicate warnings first
        const existingWarnings = quizSection.querySelectorAll('.duplicate-warning');
        existingWarnings.forEach(w => w.remove());
        
        const warningDiv = document.createElement('div');
        warningDiv.innerHTML = html;
        quizSection.insertBefore(warningDiv, quizSection.firstChild);
    }
}

// Add animation CSS
const style = document.createElement('style');
style.textContent = `
    @keyframes slideDown {
        from {
            opacity: 0;
            transform: translateY(-20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    .duplicate-warning {
        box-shadow: 0 4px 12px rgba(245, 158, 11, 0.2);
    }
    
    .duplicate-warning:hover {
        box-shadow: 0 6px 16px rgba(245, 158, 11, 0.3);
    }
`;
document.head.appendChild(style);

// Hook into existing render functions
if (typeof window.renderGeneratedQuiz !== 'undefined') {
    const originalRenderQuiz = window.renderGeneratedQuiz;
    
    window.renderGeneratedQuiz = async function(data) {
        // Call original render
        if (originalRenderQuiz) {
            originalRenderQuiz(data);
        }
        
        // Check for duplicates after rendering
        if (data.questions && data.questions.length > 0) {
            console.log('🔍 Checking for duplicate questions...');
            const result = await checkQuizDuplicates(data.questions);
            if (result && result.has_duplicates) {
                console.log(`⚠️ Found ${result.duplicate_count} potential duplicates`);
            } else {
                console.log('✅ No duplicates detected');
            }
        }
    };
}

// Also hook into assignment rendering if needed
if (typeof window.renderAssignment !== 'undefined') {
    const originalRenderAssignment = window.renderAssignment;
    
    window.renderAssignment = async function(questions) {
        // Call original render
        if (originalRenderAssignment) {
            originalRenderAssignment(questions);
        }
        
        // Check for duplicates in assignments
        if (questions && questions.length > 0) {
            console.log('🔍 Checking assignment for duplicate questions...');
            await checkQuizDuplicates(questions);
        }
    };
}

console.log('✅ Duplicate detector loaded and ready');