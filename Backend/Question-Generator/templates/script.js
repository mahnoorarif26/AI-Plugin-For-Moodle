async function generateQuestion() {
    const btn = document.getElementById('generateBtn');
    const resultDiv = document.getElementById('result');
    const topic = document.getElementById('topicInput').value.trim();

    if (!topic) {
        resultDiv.innerHTML = `<p style="color: red;">⚠ Please enter a topic first!</p>`;
        return;
    }
    
    btn.disabled = true;
    btn.textContent = 'Generating...';
    resultDiv.innerHTML = '<p class="loading">Generating questions...</p>';
    
    try {
        const response = await fetch('/generate-question', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic }) 
        });
        
        const data = await response.json();
        
        if (data.success) {
            resultDiv.innerHTML = `
                <h3>Generated Questions on "${topic}":</h3>
                <p>${data.question.replace(/\n/g, '<br>')}</p>
            `;
        } else {
            resultDiv.innerHTML = `<p style="color: red;">Error: ${data.error}</p>`;
        }
        
    } catch (error) {
        resultDiv.innerHTML = `<p style="color: red;">Error: ${error.message}</p>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate Questions';
    }
}
