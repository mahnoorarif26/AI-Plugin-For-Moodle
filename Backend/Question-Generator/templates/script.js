// Function to show a temporary toast message
function showToast(message) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.className = 'toast show';
    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

const ui = {
    pdfFile: document.getElementById('pdfFile'),
    btnDetectSubtopics: document.getElementById('btn-detect-subtopics'),
    subtopicsSection: document.getElementById('subtopics-section'),
    subtopicList: document.getElementById('subtopic-list'),
    questionConfigSection: document.getElementById('question-config-section'),
    btnGenerateQuiz: document.getElementById('btn-generate-quiz'),
    quizOutputSection: document.getElementById('quiz-output-section'),
    quizContainer: document.getElementById('quiz-container'),
    // ... other elements like mcqCount, tfCount, etc.
};

let upload_id = null;
let detected_subtopics = [];

// --- STEP 1: UPLOAD AND DETECT SUBTOPICS ---
if (ui.pdfFile) {
    ui.pdfFile.addEventListener('change', () => {
        const file = ui.pdfFile.files[0];
        if (file && file.type === 'application/pdf') {
            ui.btnDetectSubtopics.disabled = false;
            showToast(`File selected: ${file.name}. Ready to detect subtopics.`);
        } else {
            ui.btnDetectSubtopics.disabled = true;
            showToast('Please select a PDF file.', 'error');
        }
    });
}

if (ui.btnDetectSubtopics) {
    ui.btnDetectSubtopics.addEventListener('click', async () => {
        const file = ui.pdfFile.files[0];
        if (!file) return showToast('Please select a PDF first.', 'error');

        ui.btnDetectSubtopics.disabled = true;
        ui.btnDetectSubtopics.textContent = 'Detecting...';
        ui.subtopicList.innerHTML = '<p class="loading">Analyzing document and extracting topics...</p>';
        
        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/custom/extract-subtopics', {
                method: 'POST',
                body: formData,
            });
            const data = await response.json();

            if (data.error) {
                ui.subtopicList.innerHTML = `<p style="color: red;">Error: ${data.error}</p>`;
                showToast(`Error: ${data.error}`, 'error');
            } else {
                upload_id = data.upload_id;
                detected_subtopics = data.subtopics;
                renderSubtopics(data.subtopics);
                ui.subtopicsSection.style.display = 'block';
                ui.questionConfigSection.style.display = 'block';
                showToast('Subtopics detected successfully!');
            }

        } catch (error) {
            ui.subtopicList.innerHTML = `<p style="color: red;">A network error occurred: ${error.message}</p>`;
            showToast('Generation failed.', 'error');
        } finally {
            ui.btnDetectSubtopics.disabled = false;
            ui.btnDetectSubtopics.textContent = 'Detect Subtopics';
        }
    });
}

function renderSubtopics(subtopics) {
    ui.subtopicList.innerHTML = '';
    subtopics.forEach((topic, index) => {
        const div = document.createElement('div');
        div.className = 'subtopic-item';
        div.innerHTML = `
            <label>
                <input type="checkbox" name="subtopic" value="${topic}" checked data-index="${index}">
                ${topic}
            </label>
        `;
        ui.subtopicList.appendChild(div);
    });

    // Checkbox listener to enable/disable generate button
    ui.subtopicList.addEventListener('change', () => {
        const selected = Array.from(ui.subtopicList.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
        ui.btnGenerateQuiz.disabled = selected.length === 0;
    });

    // Enable generate button initially since all are checked
    ui.btnGenerateQuiz.disabled = subtopics.length === 0;
}


// --- STEP 2: GENERATE FINAL QUIZ ---
if (ui.btnGenerateQuiz) {
    ui.btnGenerateQuiz.addEventListener('click', async () => {
        const selectedSubtopics = Array.from(ui.subtopicList.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
        
        if (!upload_id || selectedSubtopics.length === 0) {
            return showToast('Select at least one subtopic.', 'error');
        }

        const payload = {
            upload_id: upload_id,
            subtopics: selectedSubtopics,
            totals: {
                mcq: document.getElementById('mcqCount').value,
                true_false: document.getElementById('tfCount').value,
                short: document.getElementById('shortCount').value,
                essay: document.getElementById('essayCount').value,
            },
            difficulty: {
                mode: document.getElementById('difficultyModeCustom').value,
                easy: document.getElementById('easyPctC').value,
                medium: document.getElementById('medPctC').value,
                hard: document.getElementById('hardPctC').value,
            },
            // Assuming scenario_based and code_snippet are checkboxes/inputs somewhere
            scenario_based: false, 
            code_snippet: false,
        };

        ui.btnGenerateQuiz.disabled = true;
        ui.btnGenerateQuiz.textContent = 'Generating Quiz...';
        ui.quizContainer.innerHTML = '<p class="loading">Calling Groq API to generate questions...</p>';
        ui.quizOutputSection.style.display = 'block';

        try {
            const response = await fetch('/api/custom/quiz-from-subtopics', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await response.json();

            if (result.error) {
                ui.quizContainer.innerHTML = `<p style="color: red;">Error: ${result.error}</p>`;
                showToast(`Error: ${result.error}`, 'error');
            } else {
                renderQuiz(result.questions);
                showToast('Quiz generated and saved to Firestore!');
            }
        } catch (error) {
            ui.quizContainer.innerHTML = `<p style="color: red;">A network error occurred: ${error.message}</p>`;
            showToast('Quiz generation failed.', 'error');
        } finally {
            ui.btnGenerateQuiz.disabled = false;
            ui.btnGenerateQuiz.textContent = 'Generate Final Quiz';
        }
    });
}

function renderQuiz(questions) {
    ui.quizContainer.innerHTML = '';
    questions.forEach((q, index) => {
        const qDiv = document.createElement('div');
        qDiv.className = 'generated-question';
        let optionsHtml = '';
        if (q.type === 'mcq' && q.options) {
            optionsHtml = '<ul>' + q.options.map(opt => `<li>${opt}</li>`).join('') + '</ul>';
        }
        
        qDiv.innerHTML = `
            <p><strong>${index + 1}. (${q.type.toUpperCase()}) ${q.prompt || q.question_text}</strong></p>
            ${optionsHtml}
            <p style="color: green;">Correct Answer: ${q.correct_answer || 'N/A'}</p>
            <p style="color: #666; font-size: 0.8em;">Source Topic: ${q.source_topic || 'N/A'}</p>
            <hr style="margin: 10px 0;">
        `;
        ui.quizContainer.appendChild(qDiv);
    });
}

// ... other UI validation logic (like validate-mix) should go here.
// For instance:
if (document.getElementById('difficultyModeCustom')) {
    document.getElementById('difficultyModeCustom').addEventListener('change', (e) => {
        const isCustom = e.target.value === 'custom';
        document.getElementById('diffRowC1').style.display = isCustom ? 'grid' : 'none';
        document.getElementById('diffRowC2').style.display = isCustom ? 'grid' : 'none';
    });
}