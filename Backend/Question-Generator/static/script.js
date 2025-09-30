/* ===========================
   CONFIG
=========================== */
const API_BASE = window.location.origin; // Use same origin as the page
const ENDPOINT = "/api/quiz/from-pdf";   // Your Flask endpoint

/* ===========================
   Helpers
=========================== */
function showToast(msg, ms=2500){
  const toastEl = document.getElementById('toast');
  if (!toastEl) return;
  
  toastEl.textContent = msg;
  toastEl.style.display = 'block';
  setTimeout(()=> {
    toastEl.style.display = 'none';
  }, ms);
}

function setProgress(p){
  const progress = document.getElementById('progress');
  const bar = progress?.querySelector('div');
  if (!progress || !bar) return;
  
  progress.style.display='block'; 
  bar.style.width = Math.max(0,Math.min(100,p))+'%';
}

function resetProgress(){
  const progress = document.getElementById('progress');
  const bar = progress?.querySelector('div');
  if (!progress || !bar) return;
  
  progress.style.display='none'; 
  bar.style.width='0%';
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  console.log('AI Quiz Generator initialized');
});