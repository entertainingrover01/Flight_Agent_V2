const API_BASE_URL = "http://localhost:8001";

const messagesArea = document.getElementById('messagesArea');
const typingIndicator = document.getElementById('typingIndicator');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');

let chatHistory = [];
let isLoading = false;

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

// ── Analysis result card ──────────────────────────────────────────────────────

function renderAnalysisCard(analysis) {
    if (!analysis) return '';

    const isError = analysis.regulation_reference === 'Error' || analysis.error;

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

// ── Message rendering ─────────────────────────────────────────────────────────

function appendMessage(role, content, analysis = null) {
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
                </div>
            </div>`;
    }

    messagesArea.appendChild(el);
    scrollToBottom();
    return el;
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

    chatInput.value = '';
    chatInput.style.height = 'auto';

    appendMessage('user', text);
    chatHistory.push({ role: 'user', content: text });

    setLoading(true);

    try {
        const response = await fetch(`${API_BASE_URL}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
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

        setLoading(false);
        appendMessage('assistant', replyText, analysis);
        chatHistory.push({ role: 'assistant', content: replyText });

    } catch (error) {
        setLoading(false);
        const errMsg = `I'm sorry, I couldn't reach the backend. Make sure the server is running on ${API_BASE_URL}.\n\nError: ${error.message}`;
        appendMessage('assistant', errMsg);
        chatHistory.push({ role: 'assistant', content: errMsg });
    }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

function init() {
    const welcome = "Hi there! I'm FlightClaim AI, your EU261 compensation assistant.\n\nIf your flight was delayed, cancelled, or you were denied boarding, you may be entitled to up to **€600** in compensation.\n\nTell me — what happened with your flight?";
    appendMessage('assistant', welcome);
    chatHistory.push({ role: 'assistant', content: welcome });
    chatInput.focus();
}

init();
