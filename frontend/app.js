/**
 * app.js — ClaimClear Frontend Application
 * Vanilla JavaScript, no frameworks.
 */

// ── Constants ────────────────────────────────────────────────────────────────
const API_BASE = (window.CLAIMCLEAR_API_URL || 'http://localhost:8000').replace(/\/$/, '');

// ── State ────────────────────────────────────────────────────────────────────
let denialFile = null;
let policyFile = null;
let currentAnalysis = null;
let appealLetterText = '';
let stepTimers = [];

// ── DOM helpers ──────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

// ═════════════════════════════════════════════════════════════════════════════
// DRAG AND DROP / FILE UPLOAD
// ═════════════════════════════════════════════════════════════════════════════

/**
 * Initialize drag-and-drop and click-to-upload for a card.
 * @param {string} cardId       - ID of the upload card div
 * @param {string} inputId      - ID of the hidden file input
 * @param {string} fileVarKey   - 'denial' or 'policy'
 */
function initDragDrop(cardId, inputId, fileVarKey) {
  const card = $(cardId);
  const input = $(inputId);
  const filenameDisplay = $(`${fileVarKey}-filename`);
  const filenameText = $(`${fileVarKey}-filename-text`);
  const removeBtn = $(`${fileVarKey}-remove`);

  if (!card || !input) return;

  // Click anywhere on card → trigger file input
  card.addEventListener('click', (e) => {
    if (e.target === removeBtn || removeBtn.contains(e.target)) return;
    input.click();
  });

  // Keyboard support
  card.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      input.click();
    }
  });

  // Drag events
  card.addEventListener('dragover', (e) => {
    e.preventDefault();
    card.classList.add('drag-over');
  });

  card.addEventListener('dragleave', (e) => {
    if (!card.contains(e.relatedTarget)) {
      card.classList.remove('drag-over');
    }
  });

  card.addEventListener('drop', (e) => {
    e.preventDefault();
    card.classList.remove('drag-over');
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFileSelected(file, fileVarKey, card, filenameDisplay, filenameText);
  });

  // File input change
  input.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) handleFileSelected(file, fileVarKey, card, filenameDisplay, filenameText);
  });

  // Remove button
  removeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (fileVarKey === 'denial') denialFile = null;
    else policyFile = null;
    input.value = '';
    card.classList.remove('file-selected', 'drag-over');
    filenameDisplay.classList.remove('visible');
    filenameText.textContent = '';
    checkReadyToAnalyze();
  });
}

/**
 * Called when a file is selected (via drop or input change).
 */
function handleFileSelected(file, fileVarKey, card, filenameDisplay, filenameText) {
  // Validate file type
  const isPDF = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
  const isTxt = file.type === 'text/plain' || file.name.toLowerCase().endsWith('.txt');

  if (fileVarKey === 'denial' && !isPDF && !isTxt) {
    showToast('Please upload a PDF or text file for the denial letter.', 'error');
    return;
  }
  if (fileVarKey === 'policy' && !isPDF) {
    showToast('Please upload a PDF file for the policy document.', 'error');
    return;
  }

  // Validate size (10MB)
  if (file.size > 10 * 1024 * 1024) {
    showToast(`File "${file.name}" exceeds the 10 MB limit. Please compress it and try again.`, 'error');
    return;
  }

  // Set state
  if (fileVarKey === 'denial') denialFile = file;
  else policyFile = file;

  // Update UI
  card.classList.add('file-selected');
  filenameText.textContent = `✓ ${file.name}`;
  filenameDisplay.classList.add('visible');

  checkReadyToAnalyze();
}

// ═════════════════════════════════════════════════════════════════════════════
// READY STATE CHECK
// ═════════════════════════════════════════════════════════════════════════════

function checkReadyToAnalyze() {
  const btn = $('analyze-btn');
  if (!btn) return;

  if (denialFile && policyFile) {
    btn.disabled = false;
    btn.setAttribute('aria-disabled', 'false');
    btn.classList.add('ready-pulse');
  } else {
    btn.disabled = true;
    btn.setAttribute('aria-disabled', 'true');
    btn.classList.remove('ready-pulse');
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// SAMPLE DENIAL LETTER
// ═════════════════════════════════════════════════════════════════════════════

async function loadSampleDenial() {
  try {
    const res = await fetch(`${API_BASE}/sample-denial`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    // Create a text file object from the sample text
    const blob = new Blob([data.text], { type: 'text/plain' });
    const file = new File([blob], 'sample_denial.txt', { type: 'text/plain' });

    denialFile = file;

    // Update denial card UI
    const card = $('denial-card');
    const filenameDisplay = $('denial-filename');
    const filenameText = $('denial-filename-text');

    card.classList.add('file-selected');
    filenameText.textContent = '✓ sample_denial.txt (loaded)';
    filenameDisplay.classList.add('visible');

    checkReadyToAnalyze();
    showToast('✓ Sample denial letter loaded! Now upload your policy PDF.', 'success');

  } catch (err) {
    console.error('Failed to load sample denial:', err);
    showToast('Could not load sample denial. Is the backend running?', 'error');
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// LOADING OVERLAY
// ═════════════════════════════════════════════════════════════════════════════

function showLoading(show) {
  const overlay = $('loading');
  if (!overlay) return;

  // Clear any existing step timers
  stepTimers.forEach(clearTimeout);
  stepTimers = [];

  if (show) {
    overlay.hidden = false;
    document.body.style.overflow = 'hidden';

    // Reset steps
    for (let i = 1; i <= 5; i++) {
      const step = $(`step-${i}`);
      if (step) step.className = (i === 1) ? 'active' : '';
    }

    // Step progression timings (ms)
    const timings = [3000, 6000, 10000, 14000];
    timings.forEach((delay, idx) => {
      const t = setTimeout(() => {
        const prev = $(`step-${idx + 1}`);
        const curr = $(`step-${idx + 2}`);
        if (prev) prev.className = 'done';
        if (curr) curr.className = 'active';
      }, delay);
      stepTimers.push(t);
    });
  } else {
    overlay.hidden = true;
    document.body.style.overflow = '';
    // Mark all steps done
    for (let i = 1; i <= 5; i++) {
      const step = $(`step-${i}`);
      if (step) step.className = 'done';
    }
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// MAIN ANALYZE FUNCTION
// ═════════════════════════════════════════════════════════════════════════════

async function analyzeDocuments() {
  if (!denialFile || !policyFile) {
    showToast('Please upload both files first.', 'error');
    return;
  }

  showLoading(true);
  currentAnalysis = null;
  appealLetterText = '';

  const formData = new FormData();
  formData.append('denial_letter', denialFile);
  formData.append('policy_document', policyFile);

  try {
    const res = await fetch(`${API_BASE}/analyze`, {
      method: 'POST',
      body: formData,
    });

    const data = await res.json();

    if (!res.ok) {
      const errData = data;
      renderError({
        error: errData.error || `HTTP ${res.status}`,
        detail: errData.detail || 'An error occurred during analysis.',
        suggestion: errData.suggestion || 'Please try again or check your uploaded files.',
      });
      return;
    }

    currentAnalysis = data;
    await renderResults(data);

  } catch (err) {
    console.error('Analysis fetch error:', err);
    renderError({
      error: 'Network Error',
      detail: 'Cannot reach the ClaimClear server.',
      suggestion: `Make sure the backend is running on ${API_BASE}. Run: uvicorn main:app --reload --port 8000`,
    });
  } finally {
    showLoading(false);
    // Scroll to results
    const results = $('results');
    if (results && !results.hidden) {
      setTimeout(() => results.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
    }
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// APPEAL GENERATION
// ═════════════════════════════════════════════════════════════════════════════

async function generateAppeal(analysis) {
  const appealDiv = $('appeal-letter');
  if (!appealDiv) return;

  appealDiv.textContent = 'Generating appeal letter...';

  try {
    const res = await fetch(`${API_BASE}/appeal`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(analysis),
    });

    if (!res.ok) {
      appealDiv.textContent = 'Could not generate appeal letter. Please try again.';
      return;
    }

    const data = await res.json();
    appealLetterText = data.appeal_letter || '';
    appealDiv.textContent = appealLetterText;

  } catch (err) {
    console.error('Appeal generation error:', err);
    appealDiv.textContent = 'Appeal letter generation failed. Please check the backend is running.';
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// RENDER RESULTS
// ═════════════════════════════════════════════════════════════════════════════

async function renderResults(data) {
  const resultsSection = $('results');
  if (!resultsSection) return;

  resultsSection.hidden = false;
  resultsSection.classList.add('visible');

  // ── Summary Card ────────────────────────────────────────────────────────
  const summaryCard = $('summary-card');
  const statusBadge = $('status-badge');

  if (data.denial_valid) {
    summaryCard?.classList.add('denial-valid');
    if (statusBadge) {
      statusBadge.className = 'status-badge valid-denial';
      statusBadge.textContent = '⬤ VALID DENIAL';
    }
  } else {
    summaryCard?.classList.remove('denial-valid');
    if (statusBadge) {
      statusBadge.className = 'status-badge appealable';
      statusBadge.textContent = '⬤ APPEALABLE';
    }
  }

  // Meta pills
  const de = data.denial_extract;
  const metaInsurer = $('meta-insurer');
  const metaClaim = $('meta-claim');
  const metaType = $('meta-type');
  const procTime = $('processing-time');

  if (metaInsurer) metaInsurer.textContent = de.insurer_name !== 'NOT FOUND' ? de.insurer_name : 'Insurer';
  if (metaClaim)   metaClaim.textContent = `Claim #${de.claim_number}`;
  if (metaType) {
    metaType.textContent = de.claim_type.charAt(0).toUpperCase() + de.claim_type.slice(1);
    metaType.className = `meta-pill type-${de.claim_type}`;
  }
  if (procTime) procTime.textContent = `Analyzed in ${data.processing_time_seconds}s`;

  // ── Plain English Summary ────────────────────────────────────────────────
  const plainEnglishDiv = $('plain-english');
  if (plainEnglishDiv) plainEnglishDiv.textContent = data.plain_english_summary;

  // ── Confidence Bar ───────────────────────────────────────────────────────
  const pct = Math.round(data.confidence * 100);
  const confPct = $('confidence-pct');
  const confFill = $('confidence-bar-fill');
  const confTrack = $('confidence-bar-track');

  if (confPct) confPct.textContent = `${pct}%`;
  if (confTrack) confTrack.setAttribute('aria-valuenow', pct);

  if (confFill) {
    setTimeout(() => {
      confFill.style.width = `${pct}%`;
      if (data.confidence > 0.7) confFill.classList.remove('medium', 'low');
      else if (data.confidence >= 0.4) {
        confFill.classList.add('medium');
        confFill.classList.remove('low');
      } else {
        confFill.classList.add('low');
        confFill.classList.remove('medium');
      }
    }, 300);
  }

  // ── Evidence Checklist ───────────────────────────────────────────────────
  const evidenceList = $('evidence-checklist');
  if (evidenceList) {
    evidenceList.innerHTML = '';

    // Sort: HIGH → MED → LOW
    const priorityOrder = { HIGH: 0, MED: 1, LOW: 2 };
    const sorted = [...data.evidence_needed].sort(
      (a, b) => (priorityOrder[a.priority] ?? 9) - (priorityOrder[b.priority] ?? 9)
    );

    sorted.forEach((item) => {
      const div = document.createElement('div');
      div.className = 'evidence-item';
      div.innerHTML = `
        <span class="priority-badge ${item.priority}" role="img" aria-label="${item.priority} priority">${item.priority}</span>
        <div class="evidence-content">
          <div class="evidence-doc">${escapeHtml(item.document)}</div>
          <div class="evidence-reason">${escapeHtml(item.reason)}</div>
        </div>
      `;
      evidenceList.appendChild(div);
    });
  }

  // ── Rebuttals ────────────────────────────────────────────────────────────
  const rebuttalsList = $('rebuttals-list');
  if (rebuttalsList) {
    rebuttalsList.innerHTML = '';

    data.rebuttals.forEach((r, idx) => {
      const card = document.createElement('div');
      card.className = 'rebuttal-card';

      const verifiedHtml = r.clause_verified
        ? `<span class="verified-badge verified" title="This clause was verified in your policy document">✓ Verified</span>`
        : (r.supporting_clause === 'NO_SUPPORTING_CLAUSE_FOUND'
            ? `<span class="verified-badge unverified" title="No supporting clause found in the policy">⚠ No clause</span>`
            : `<span class="verified-badge unverified" title="Could not verify this clause in source document">⚠ Unverified</span>`
          );

      const quoteHtml = (
        r.supporting_clause &&
        r.supporting_clause !== 'NO_SUPPORTING_CLAUSE_FOUND'
      ) ? `<blockquote class="policy-quote">"${escapeHtml(r.supporting_clause)}"</blockquote>` : '';

      card.innerHTML = `
        <div class="rebuttal-header">
          <span class="rebuttal-number" aria-label="Argument ${idx + 1}">${idx + 1}</span>
          <p class="rebuttal-argument">${escapeHtml(r.argument)}</p>
          ${verifiedHtml}
        </div>
        ${quoteHtml}
      `;
      rebuttalsList.appendChild(card);
    });
  }

  // ── Generate Appeal Letter ───────────────────────────────────────────────
  await generateAppeal(data);

  // ── Disclaimer ───────────────────────────────────────────────────────────
  // Already in HTML, no additional render needed.
}

// ═════════════════════════════════════════════════════════════════════════════
// COPY APPEAL LETTER
// ═════════════════════════════════════════════════════════════════════════════

function copyAppealLetter() {
  const copyBtn = $('copy-btn');
  const textToCopy = appealLetterText || ($('appeal-letter')?.textContent ?? '');

  if (!textToCopy.trim()) {
    showToast('No appeal letter to copy yet.', 'error');
    return;
  }

  navigator.clipboard.writeText(textToCopy)
    .then(() => {
      if (copyBtn) {
        const original = copyBtn.innerHTML;
        copyBtn.innerHTML = '✓ Copied!';
        copyBtn.classList.add('copied');
        setTimeout(() => {
          copyBtn.innerHTML = original;
          copyBtn.classList.remove('copied');
        }, 2000);
      }
    })
    .catch(() => {
      // Fallback for older browsers
      const ta = document.createElement('textarea');
      ta.value = textToCopy;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try { document.execCommand('copy'); } catch (_) {}
      document.body.removeChild(ta);
      if (copyBtn) {
        copyBtn.innerHTML = '✓ Copied!';
        copyBtn.classList.add('copied');
        setTimeout(() => {
          copyBtn.innerHTML = '📋 Copy Letter';
          copyBtn.classList.remove('copied');
        }, 2000);
      }
    });
}

// ═════════════════════════════════════════════════════════════════════════════
// RENDER ERROR
// ═════════════════════════════════════════════════════════════════════════════

function renderError(errorObj) {
  const resultsSection = $('results');
  const resultsInner = resultsSection?.querySelector('.results-inner');
  if (!resultsSection || !resultsInner) return;

  resultsSection.hidden = false;
  resultsSection.classList.add('visible');

  // Clear previous content
  resultsInner.innerHTML = '';

  const card = document.createElement('div');
  card.className = 'error-card';
  card.setAttribute('role', 'alert');
  card.innerHTML = `
    <div class="error-title">❌ ${escapeHtml(errorObj.error)}</div>
    <div class="error-detail">${escapeHtml(errorObj.detail)}</div>
    <div class="error-suggestion">💡 ${escapeHtml(errorObj.suggestion)}</div>
    <br/>
    <button class="btn-primary" onclick="window.location.reload()">↩ Try Again</button>
  `;
  resultsInner.appendChild(card);
}

// ═════════════════════════════════════════════════════════════════════════════
// UTILITIES
// ═════════════════════════════════════════════════════════════════════════════

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str ?? '');
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function showToast(message, type = 'info') {
  const existing = document.querySelector('.cc-toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = 'cc-toast';

  const colors = {
    success: 'var(--accent-green)',
    error: 'var(--accent-red)',
    info: 'var(--accent-blue)',
  };

  Object.assign(toast.style, {
    position: 'fixed',
    bottom: '24px',
    left: '50%',
    transform: 'translateX(-50%) translateY(20px)',
    background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
    borderLeft: `4px solid ${colors[type] || colors.info}`,
    border: `1px solid var(--border)`,
    borderLeftWidth: '4px',
    borderLeftColor: colors[type] || colors.info,
    padding: '14px 22px',
    borderRadius: '8px',
    fontSize: '0.875rem',
    fontFamily: "'Inter', sans-serif",
    fontWeight: '500',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    zIndex: '99999',
    maxWidth: '400px',
    opacity: '0',
    transition: 'all 0.3s ease',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  });

  toast.textContent = message;
  document.body.appendChild(toast);

  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(-50%) translateY(0)';
  });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(-50%) translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ═════════════════════════════════════════════════════════════════════════════
// INIT
// ═════════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {

  // Initialize drag-drop for both upload cards
  initDragDrop('denial-card', 'denial-input', 'denial');
  initDragDrop('policy-card', 'policy-input', 'policy');

  // Analyze button
  const analyzeBtn = $('analyze-btn');
  if (analyzeBtn) analyzeBtn.addEventListener('click', analyzeDocuments);

  // Sample denial link
  const sampleLink = $('sample-link');
  if (sampleLink) sampleLink.addEventListener('click', loadSampleDenial);

  // Copy button
  const copyBtn = $('copy-btn');
  if (copyBtn) copyBtn.addEventListener('click', copyAppealLetter);

  // Start over button
  const startOverBtn = $('start-over-btn');
  if (startOverBtn) startOverBtn.addEventListener('click', () => window.location.reload());

  // Prevent form submission on Enter
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') {
      // Only prevent if inside upload section
      if (e.target.closest && e.target.closest('#upload')) e.preventDefault();
    }
  });

  console.log(`ClaimClear frontend initialized. API: ${API_BASE}`);
});
