const API_BASE_URL = "http://localhost:8001";

const messagesArea = document.getElementById('messagesArea');
const welcomeScreen = document.getElementById('welcomeScreen');
const typingIndicator = document.getElementById('typingIndicator');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const startChatBtn = document.getElementById('startChatBtn');
const responseHelperBar = document.getElementById('responseHelperBar');
const quickReplyRow = document.getElementById('quickReplyRow');
const dateHelperRow = document.getElementById('dateHelperRow');
const datePickerInput = document.getElementById('datePickerInput');
const useDateBtn = document.getElementById('useDateBtn');
const gmailStatusBadge = document.getElementById('gmailStatusBadge');
const gmailStatusText = document.getElementById('gmailStatusText');
const gmailConnectBtn = document.getElementById('gmailConnectBtn');
const gmailScanBtn = document.getElementById('gmailScanBtn');
const gmailDisconnectBtn = document.getElementById('gmailDisconnectBtn');
const gmailResult = document.getElementById('gmailResult');
const gmailConnectPanel = document.getElementById('gmailConnectPanel');
const gmailConnectTitle = document.getElementById('gmailConnectTitle');
const gmailConnectMessage = document.getElementById('gmailConnectMessage');
const gmailConnectLink = document.getElementById('gmailConnectLink');
const gmailConnectDismissBtn = document.getElementById('gmailConnectDismissBtn');

let chatHistory = [];
let isLoading = false;
let gmailConnected = false;
let gmailConnectPoll = null;
let scanAnimationTimer = null;
let hasStartedChat = false;

function hideResponseHelpers() {
    responseHelperBar.classList.add('hidden');
    quickReplyRow.innerHTML = '';
    dateHelperRow.classList.add('hidden');
}

function showDateHelper() {
    responseHelperBar.classList.remove('hidden');
    dateHelperRow.classList.remove('hidden');
}

function showQuickReplies(options) {
    quickReplyRow.innerHTML = options.map((option) => `
        <button class="quick-reply-btn" type="button" data-quick-reply="${escapeHtml(option)}">${escapeHtml(option)}</button>
    `).join('');
    responseHelperBar.classList.remove('hidden');
}

function getQuickRepliesForAssistantMessage(content) {
    const normalized = content.toLowerCase();

    if (normalized.includes('please send the scheduled flight date in `yyyy-mm-dd` format')) {
        return { date: true, replies: [] };
    }

    if (normalized.includes('what happened with your flight')) {
        return {
            date: false,
            replies: ['Delayed', 'Cancelled', 'Denied boarding', 'Missed connection'],
        };
    }

    if (normalized.includes('what happened after the cancellation')) {
        return {
            date: false,
            replies: ['Rebooked, arrived 4 hours later', 'Rebooked next day', 'No replacement flight'],
        };
    }

    if (normalized.includes('how long was the delay') || normalized.includes('how much later did you arrive')) {
        return {
            date: false,
            replies: ['2 hours', '3 hours', '4 hours', '5+ hours'],
        };
    }

    return { date: false, replies: [] };
}

function refreshResponseHelpersForAssistantMessage(content) {
    hideResponseHelpers();
    const helperConfig = getQuickRepliesForAssistantMessage(content);
    if (helperConfig.date) {
        showDateHelper();
    }
    if (helperConfig.replies.length) {
        showQuickReplies(helperConfig.replies);
    }
}

function encodeActionPayload(payload) {
    return btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
}

function decodeActionPayload(payload) {
    return JSON.parse(decodeURIComponent(escape(atob(payload))));
}

// ── Textarea auto-resize ──────────────────────────────────────────────────────

chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 128) + 'px';
});

chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

sendBtn.addEventListener('click', sendMessage);

// ── Utilities ─────────────────────────────────────────────────────────────────

function escapeHtml(text) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(String(text ?? '')));
    return div.innerHTML;
}

function formatText(text) {
    // Render **bold**, *italic*, and line breaks from plain text
    return escapeHtml(text)
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');
}

function scrollToBottom() {
    messagesArea.scrollTo({ top: messagesArea.scrollHeight, behavior: 'smooth' });
}

function setGmailStatus(connected, configured, message = '') {
    gmailConnected = Boolean(connected);
    gmailStatusBadge.textContent = gmailConnected ? 'Connected' : (configured ? 'Not connected' : 'Not configured');
    gmailStatusBadge.className = `inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
        gmailConnected
            ? 'bg-emerald-100 text-emerald-700'
            : configured
                ? 'bg-amber-100 text-amber-700'
                : 'bg-slate-100 text-slate-600'
    }`;

    if (!configured) {
        gmailStatusText.textContent = 'Add Google OAuth credentials in backend/.env to enable Gmail inbox scanning.';
    } else if (gmailConnected) {
        gmailStatusText.textContent = message || 'Gmail is connected and ready to scan recent airline emails.';
    } else {
        gmailStatusText.textContent = message || 'Gmail is configured but not connected yet.';
    }

    gmailScanBtn.disabled = !gmailConnected;
    gmailDisconnectBtn.disabled = !gmailConnected;
}

function showGmailResult(html) {
    gmailResult.classList.remove('hidden');
    gmailResult.innerHTML = html;
}

function clearGmailResult() {
    gmailResult.classList.add('hidden');
    gmailResult.innerHTML = '';
}

function showGmailConnectPanel(title, message, authorizationUrl) {
    gmailConnectTitle.textContent = title;
    gmailConnectMessage.textContent = message;
    gmailConnectLink.href = authorizationUrl;
    gmailConnectPanel.classList.remove('hidden');
}

function hideGmailConnectPanel() {
    gmailConnectPanel.classList.add('hidden');
}

function renderGmailConnectState(stage) {
    const chips = [
        { label: 'Launching sign-in', active: stage >= 1, done: stage > 1 },
        { label: 'Waiting for Google permission', active: stage >= 2, done: stage > 2 },
        { label: 'Refreshing Gmail status', active: stage >= 3, done: stage > 3 },
    ];

    return chips.map((chip) => {
        const dotClass = chip.done
            ? 'status-dot status-dot-done'
            : chip.active
                ? 'status-dot status-dot-active'
                : 'status-dot';
        return `<div class="status-chip"><span class="${dotClass}"></span>${chip.label}</div>`;
    }).join('');
}

function setGmailConnectProgress(stage, title, message) {
    gmailConnectTitle.textContent = title;
    gmailConnectMessage.textContent = message;
    const grid = gmailConnectPanel.querySelector('.grid');
    if (grid) {
        grid.innerHTML = renderGmailConnectState(stage);
    }
}

function stopConnectPolling() {
    if (gmailConnectPoll) {
        clearInterval(gmailConnectPoll);
        gmailConnectPoll = null;
    }
}

async function beginGmailConnect() {
    const authorizationUrl = `${API_BASE_URL}/api/gmail/connect`;
    clearGmailResult();
    showGmailConnectPanel(
        'Opening Google sign-in',
        'A Google sign-in window should appear. If it does not, use the backup link below.',
        authorizationUrl
    );
    setGmailConnectProgress(1, 'Opening Google sign-in', 'A Google sign-in window should appear. If it does not, use the backup link below.');

    const popup = window.open(authorizationUrl, '_blank', 'noopener,noreferrer');

    if (!popup) {
        setGmailConnectProgress(
            1,
            'Popup blocked',
            'Your browser blocked the Google sign-in window. Use "Open Google sign-in" below to continue.'
        );
    } else {
        setGmailConnectProgress(
            2,
            'Waiting for Google permission',
            'Finish the Google consent flow in the new tab or window. We will keep checking the connection here.'
        );
    }

    stopConnectPolling();
    gmailConnectPoll = setInterval(async () => {
        await refreshGmailStatus({ silent: true });
        if (gmailConnected) {
            stopConnectPolling();
            setGmailConnectProgress(
                3,
                'Gmail connected',
                'Connection confirmed. You can scan the inbox now.'
            );
            setTimeout(() => {
                hideGmailConnectPanel();
            }, 1200);
        }
    }, 2000);
}

function renderScanAnimation(phaseIndex = 0) {
    const phases = [
        'Checking Gmail connection',
        'Searching recent airline emails',
        'Extracting flight details',
        'Analyzing claim eligibility',
    ];

    const phaseMarkup = phases.map((phase, index) => {
        let dotClass = 'scan-step-dot';
        let textClass = 'text-slate-400';
        if (index < phaseIndex) {
            dotClass += ' scan-step-dot-done';
            textClass = 'text-emerald-700';
        } else if (index === phaseIndex) {
            dotClass += ' scan-step-dot-active';
            textClass = 'text-slate-700';
        }

        return `
            <div class="scan-step">
                <span class="${dotClass}"></span>
                <span class="text-xs font-medium ${textClass}">${phase}</span>
            </div>
        `;
    }).join('');

    return `
        <div class="gmail-scan-shell">
            <div class="gmail-scan-header">
                <div class="scanner-beacon">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
                <div>
                    <p class="text-sm font-semibold text-slate-900">Scanning your inbox</p>
                    <p class="text-xs text-slate-500 mt-1">Looking for recent disruption emails and preparing a claim summary.</p>
                </div>
            </div>
            <div class="gmail-progress-track mt-4">
                <div class="gmail-progress-bar" style="width: ${Math.min(((phaseIndex + 1) / phases.length) * 100, 96)}%"></div>
            </div>
            <div class="mt-4 space-y-2">
                ${phaseMarkup}
            </div>
        </div>
    `;
}

function startScanAnimation() {
    let phaseIndex = 0;
    showGmailResult(renderScanAnimation(phaseIndex));
    if (scanAnimationTimer) {
        clearInterval(scanAnimationTimer);
    }
    scanAnimationTimer = setInterval(() => {
        phaseIndex = Math.min(phaseIndex + 1, 3);
        showGmailResult(renderScanAnimation(phaseIndex));
    }, 1400);
}

function stopScanAnimation() {
    if (scanAnimationTimer) {
        clearInterval(scanAnimationTimer);
        scanAnimationTimer = null;
    }
}

// ── Analysis result card ──────────────────────────────────────────────────────

function renderAnalysisCard(analysis) {
    if (!analysis) return '';

    const isError = analysis.regulation_reference === 'Error' || analysis.error;
    const isProviderUnavailable = analysis.regulation_reference === 'Live flight provider unavailable';

    if (isError) {
        return `<div class="mt-3 bg-red-50 border border-red-200 rounded-xl p-4">
            <div class="flex items-center gap-2 mb-1">
                <svg class="w-4 h-4 text-red-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <span class="text-sm font-semibold text-red-700">Analysis error</span>
            </div>
            <p class="text-xs text-red-600">${escapeHtml(analysis.reasoning || analysis.error || 'Unknown error')}</p>
        </div>`;
    }

    if (isProviderUnavailable) {
        const steps = (analysis.next_steps || []).map(s =>
            `<li class="text-xs text-sky-700 flex items-start gap-1.5">
                <span class="mt-0.5 w-1.5 h-1.5 rounded-full bg-sky-500 flex-shrink-0 inline-block"></span>
                ${escapeHtml(s)}
            </li>`
        ).join('');

        return `<div class="mt-3 bg-sky-50 border border-sky-200 rounded-xl p-4">
            <div class="flex items-center gap-2 mb-2">
                <svg class="w-5 h-5 text-sky-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <span class="text-sm font-semibold text-sky-800">Flight found, but live verification is unavailable</span>
            </div>
            <p class="text-xs text-sky-700 mb-2">${escapeHtml(analysis.reasoning || 'The flight provider could not verify this flight right now.')}</p>
            ${steps ? `<ul class="space-y-1">${steps}</ul>` : ''}
        </div>`;
    }

    if (analysis.eligible) {
        const steps = (analysis.next_steps || []).map(s =>
            `<li class="text-xs text-green-700 flex items-start gap-1.5">
                <span class="mt-0.5 w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0 inline-block"></span>
                ${escapeHtml(s)}
            </li>`
        ).join('');

        const letterSection = analysis.claim_letter
            ? `<details class="mt-3">
                <summary class="text-xs font-semibold text-green-700 cursor-pointer select-none hover:underline">
                    View claim letter draft ↓
                </summary>
                <pre class="mt-2 bg-white border border-green-100 rounded-lg p-3 text-xs text-slate-700 whitespace-pre-wrap overflow-auto max-h-52 leading-relaxed">${escapeHtml(analysis.claim_letter)}</pre>
               </details>`
            : '';

        return `<div class="mt-3 bg-green-50 border border-green-200 rounded-xl p-4">
            <div class="flex items-center gap-2 mb-2">
                <svg class="w-5 h-5 text-green-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <span class="text-sm font-semibold text-green-800">Eligible — €${analysis.compensation_eur} compensation</span>
            </div>
            <p class="text-xs text-green-700 mb-2">${escapeHtml(analysis.regulation_reference || '')}</p>
            ${steps ? `<ul class="space-y-1 mb-1">${steps}</ul>` : ''}
            ${letterSection}
            ${analysis.confidence != null ? `<p class="text-xs text-green-600 mt-2 opacity-60">Confidence: ${(analysis.confidence * 100).toFixed(0)}%</p>` : ''}
        </div>`;
    }

    // Not eligible
    const steps = (analysis.next_steps || []).map(s =>
        `<li class="text-xs text-amber-700 flex items-start gap-1.5">
            <span class="mt-0.5 w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0 inline-block"></span>
            ${escapeHtml(s)}
        </li>`
    ).join('');

    return `<div class="mt-3 bg-amber-50 border border-amber-200 rounded-xl p-4">
        <div class="flex items-center gap-2 mb-2">
            <svg class="w-5 h-5 text-amber-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
            </svg>
            <span class="text-sm font-semibold text-amber-800">Not eligible for compensation</span>
        </div>
        <p class="text-xs text-amber-700 mb-2">${escapeHtml(analysis.regulation_reference || '')}</p>
        ${steps ? `<ul class="space-y-1">${steps}</ul>` : ''}
    </div>`;
}

function renderFlightConfirmationCard(action) {
    if (!action || action.type !== 'flight_confirmation') return '';

    const verified = action.verified_flight || {};
    const claim = action.claim_data || {};
    const encoded = encodeActionPayload(claim);

    return `
        <div class="mt-3 rounded-2xl border border-blue-200 bg-blue-50/80 p-4">
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Flight check</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">${escapeHtml(action.prompt || 'Is this your flight?')}</p>
            <div class="mt-3 grid gap-2 sm:grid-cols-2">
                <div class="rounded-xl bg-white p-3 ring-1 ring-blue-100">
                    <span class="label">Flight</span>
                    <span class="value text-base">${escapeHtml(claim.flight_number || verified.flight || 'Unknown')}</span>
                </div>
                <div class="rounded-xl bg-white p-3 ring-1 ring-blue-100">
                    <span class="label">Date</span>
                    <span class="value text-base">${escapeHtml(claim.flight_date || verified.date || 'Unknown')}</span>
                </div>
                <div class="rounded-xl bg-white p-3 ring-1 ring-blue-100">
                    <span class="label">Airline</span>
                    <span class="value text-base">${escapeHtml(verified.airline || 'Unknown')}</span>
                </div>
                <div class="rounded-xl bg-white p-3 ring-1 ring-blue-100">
                    <span class="label">Verified Delay</span>
                    <span class="value text-base">${escapeHtml(verified.delay_minutes == null ? 'Unknown' : `${verified.delay_minutes} minutes`)}</span>
                </div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
                <button class="flight-action-btn rounded-xl bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700 transition-colors" data-action="confirm-flight" data-payload="${encoded}">
                    Yes, this is my flight
                </button>
                <button class="flight-action-btn rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors" data-action="reject-flight" data-payload="${encoded}">
                    No, show another
                </button>
            </div>
        </div>
    `;
}

function renderGmailScanResult(data) {
    const analysisCard = data.analysis ? renderAnalysisCard(data.analysis) : '';
    const source = data.source_email || {};
    const claim = data.claim_data || {};

    return `
        <div class="space-y-2">
            <div>
                <p class="text-sm font-semibold text-slate-800">${escapeHtml(data.message || 'Inbox scan complete')}</p>
                <p class="text-xs text-slate-500 mt-1">Emails scanned: ${escapeHtml(data.emails_scanned ?? 0)}</p>
            </div>
            ${source.subject ? `<p class="text-xs text-slate-600"><strong>Matched email:</strong> ${escapeHtml(source.subject)}</p>` : ''}
            ${claim.flight_number ? `<p class="text-xs text-slate-600"><strong>Flight:</strong> ${escapeHtml(claim.flight_number)} on ${escapeHtml(claim.flight_date || 'unknown date')}</p>` : ''}
            ${analysisCard}
        </div>
    `;
}

// ── Message rendering ─────────────────────────────────────────────────────────

function appendMessage(role, content, analysis = null, uiAction = null) {
    const isUser = role === 'user';
    const el = document.createElement('div');

    if (isUser) {
        el.className = 'flex justify-end';
        el.innerHTML = `
            <div class="max-w-[80%] bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-3 shadow-sm">
                <p class="text-sm leading-relaxed">${formatText(content)}</p>
            </div>`;
    } else {
        el.className = 'flex items-end gap-2.5';
        const cardHtml = renderAnalysisCard(analysis);
        const actionHtml = renderFlightConfirmationCard(uiAction);
        el.innerHTML = `
            <div class="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0 mb-0.5">
                <svg class="w-4 h-4 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
            </div>
            <div class="max-w-[80%]">
                <div class="bg-slate-100 text-slate-800 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
                    <p class="text-sm leading-relaxed">${formatText(content)}</p>
                    ${cardHtml}
                    ${actionHtml}
                </div>
            </div>`;
    }

    messagesArea.appendChild(el);
    if (role === 'assistant') {
        refreshResponseHelpersForAssistantMessage(content);
    }
    scrollToBottom();
    return el;
}

function startChatExperience() {
    if (hasStartedChat) {
        chatInput.focus();
        return;
    }

    hasStartedChat = true;
    welcomeScreen.classList.add('hidden');
    messagesArea.classList.remove('hidden');
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatInput.placeholder = 'Enter a flight number like BA117, plus the scheduled date...';

    const welcome = "Welcome to FlightClaim AI.\n\nStart by sending your **flight number** and the **scheduled flight date** in `YYYY-MM-DD` format.\n\nYou can also tell me what happened if you already know it, for example: delay, cancellation, denied boarding, or missed connection.";
    appendMessage('assistant', welcome);
    chatHistory.push({ role: 'assistant', content: welcome });
    chatInput.focus();
}

// ── Loading state ─────────────────────────────────────────────────────────────

function setLoading(loading) {
    isLoading = loading;
    sendBtn.disabled = loading;
    chatInput.disabled = loading;

    if (loading) {
        typingIndicator.classList.remove('hidden');
        scrollToBottom();
    } else {
        typingIndicator.classList.add('hidden');
    }
}

// ── Send message ──────────────────────────────────────────────────────────────

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isLoading) return;

    await sendMessagePayload(text, text);
}

async function sendMessagePayload(displayText, payloadText) {
    if (!payloadText || isLoading) return;

    chatInput.value = '';
    chatInput.style.height = 'auto';
    hideResponseHelpers();

    appendMessage('user', displayText);
    chatHistory.push({ role: 'user', content: displayText });

    setLoading(true);

    try {
        const response = await fetch(`${API_BASE_URL}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: payloadText,
                // send all history except the message we just added
                history: chatHistory.slice(0, -1),
            }),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || err.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        const replyText = data.response || "I'm sorry, I couldn't process that. Could you try again?";
        const analysis = data.analysis || null;
        const uiAction = data.ui_action || null;

        setLoading(false);
        appendMessage('assistant', replyText, analysis, uiAction);
        chatHistory.push({ role: 'assistant', content: replyText });

    } catch (error) {
        setLoading(false);
        const errMsg = `I'm sorry, I couldn't reach the backend. Make sure the server is running on ${API_BASE_URL}.\n\nError: ${error.message}`;
        appendMessage('assistant', errMsg);
        chatHistory.push({ role: 'assistant', content: errMsg });
    }
}

async function refreshGmailStatus(options = {}) {
    const { silent = false } = options;
    try {
        const response = await fetch(`${API_BASE_URL}/api/gmail/status`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        setGmailStatus(data.connected, data.configured, data.connected ? 'Gmail is connected.' : '');
        if (data.connected && !silent) {
            hideGmailConnectPanel();
        }
    } catch (error) {
        setGmailStatus(false, false, 'Unable to reach Gmail status endpoint.');
    }
}

async function scanGmail() {
    gmailScanBtn.disabled = true;
    startScanAnimation();

    try {
        const response = await fetch(`${API_BASE_URL}/api/gmail/scan`, { method: 'POST' });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data.detail || data.error || `HTTP ${response.status}`);
        }

        if (data.status === 'analyzed') {
            showGmailResult(renderGmailScanResult(data));
            return;
        }

        showGmailResult(`
            <div>
                <p class="text-sm font-semibold text-slate-800">${escapeHtml(data.message || 'No matching flight email found.')}</p>
                <p class="text-xs text-slate-500 mt-1">Emails scanned: ${escapeHtml(data.emails_scanned ?? 0)}</p>
            </div>
        `);
    } catch (error) {
        showGmailResult(`<p class="text-sm font-semibold text-red-600">Gmail scan failed</p><p class="text-xs text-red-500 mt-1">${escapeHtml(error.message)}</p>`);
    } finally {
        stopScanAnimation();
        gmailScanBtn.disabled = !gmailConnected;
    }
}

async function disconnectGmail() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/gmail/disconnect`, { method: 'POST' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        stopConnectPolling();
        hideGmailConnectPanel();
        clearGmailResult();
        await refreshGmailStatus();
    } catch (error) {
        showGmailResult(`<p class="text-sm font-semibold text-red-600">Disconnect failed</p><p class="text-xs text-red-500 mt-1">${escapeHtml(error.message)}</p>`);
    }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

function init() {
    gmailConnectBtn.addEventListener('click', beginGmailConnect);
    gmailScanBtn.addEventListener('click', scanGmail);
    gmailDisconnectBtn.addEventListener('click', disconnectGmail);
    gmailConnectDismissBtn.addEventListener('click', hideGmailConnectPanel);
    startChatBtn.addEventListener('click', startChatExperience);
    useDateBtn.addEventListener('click', async () => {
        if (!datePickerInput.value) return;
        await sendMessagePayload(datePickerInput.value, datePickerInput.value);
    });
    refreshGmailStatus();

    messagesArea.addEventListener('click', async (event) => {
        const target = event.target.closest('.flight-action-btn');
        if (target) {
            const payload = decodeActionPayload(target.dataset.payload);
            const isConfirm = target.dataset.action === 'confirm-flight';
            const displayText = isConfirm ? "Yes, that's my flight." : "No, that's not my flight.";
            const payloadText = `${isConfirm ? 'CONFIRM_FLIGHT' : 'REJECT_FLIGHT'}::${JSON.stringify(payload)}`;
            await sendMessagePayload(displayText, payloadText);
            return;
        }

    });

    responseHelperBar.addEventListener('click', async (event) => {
        const quickReply = event.target.closest('.quick-reply-btn');
        if (!quickReply) return;
        const value = quickReply.dataset.quickReply;
        await sendMessagePayload(value, value);
    });
}

init();
