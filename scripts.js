// DOM Elements
const form = document.getElementById('claimForm');
const loading = document.getElementById('loading');
const result = document.getElementById('result');
const resultTitle = document.getElementById('resultTitle');
const resultMessage = document.getElementById('resultMessage');
const resultIcon = document.getElementById('resultIcon');
const resetBtn = document.getElementById('resetBtn');

// Tab Elements
const tabManual = document.getElementById('tabManual');
const tabGmail = document.getElementById('tabGmail');
const manualSection = document.getElementById('manualSection');
const gmailSection = document.getElementById('gmailSection');
const gmailSuccess = document.getElementById('gmailSuccess');

// Google Auth Elements
const googleAuthBtn = document.getElementById('googleAuthBtn');
const googleAuthText = document.getElementById('googleAuthText');
const googleSpinner = document.getElementById('googleSpinner');
const disconnectGmailBtn = document.getElementById('disconnectGmailBtn');
const scanGmailBtn = document.getElementById('scanGmailBtn');
const gmailStatusText = document.getElementById('gmailStatusText');
const gmailScanResult = document.getElementById('gmailScanResult');
const gmailScanMessage = document.getElementById('gmailScanMessage');
const gmailFoundScreen = document.getElementById('gmailFoundScreen');
const gmailFoundSubtitle = document.getElementById('gmailFoundSubtitle');
const gmailFoundSource = document.getElementById('gmailFoundSource');
const gmailExtractedDetails = document.getElementById('gmailExtractedDetails');
const gmailDraftTitle = document.getElementById('gmailDraftTitle');
const gmailFoundOutcome = document.getElementById('gmailFoundOutcome');
const gmailDraftLetter = document.getElementById('gmailDraftLetter');
const gmailBackBtn = document.getElementById('gmailBackBtn');
const appCard = document.querySelector('body > div');
let activeTab = 'manual';
let gmailState = {
    loading: true,
    configured: false,
    connected: false,
    message: '',
};

function showElement(element, displayValue = 'block') {
    element.classList.remove('hidden');
    element.style.display = displayValue;
}

function hideElement(element) {
    element.classList.add('hidden');
    element.style.display = 'none';
}

// SVG Icons
const successIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;
const warningIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;
const errorIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;

function setActiveTab(tabName) {
    activeTab = tabName;
    gmailFoundScreen.classList.add('hidden');

    if (tabName === 'manual') {
        tabManual.classList.replace('text-slate-500', 'text-blue-600');
        tabManual.classList.replace('border-transparent', 'border-blue-600');
        tabGmail.classList.replace('text-blue-600', 'text-slate-500');
        tabGmail.classList.replace('border-blue-600', 'border-transparent');

        showElement(manualSection, 'block');
        hideElement(gmailSection);
        hideElement(gmailSuccess);
        hideElement(result);
        return;
    }

    tabGmail.classList.replace('text-slate-500', 'text-blue-600');
    tabGmail.classList.replace('border-transparent', 'border-blue-600');
    tabManual.classList.replace('text-blue-600', 'text-slate-500');
    tabManual.classList.replace('border-blue-600', 'border-transparent');

    hideElement(manualSection);
    hideElement(loading);
    hideElement(result);
    renderGmailTab();
}

tabManual.addEventListener('click', () => setActiveTab('manual'));
tabGmail.addEventListener('click', () => {
    setActiveTab('gmail');
    refreshGmailState();
});

function showGmailConnectView(message = '') {
    hideElement(gmailSuccess);
    showElement(gmailSection, 'block');
    hideElement(gmailScanResult);
    gmailStatusText.innerText = message || 'Connect Gmail to scan recent flight disruption emails directly from this app.';
}

function showGmailConnectedView() {
    hideElement(gmailSection);
    showElement(gmailSuccess, 'block');
}

function renderGmailTab() {
    if (activeTab !== 'gmail') {
        hideElement(gmailSection);
        hideElement(gmailSuccess);
        return;
    }

    if (gmailState.loading) {
        showGmailConnectView('Checking Gmail connection...');
        return;
    }

    if (!gmailState.configured) {
        showGmailConnectView('Google OAuth is not configured yet. Add Google OAuth credentials in the backend before connecting Gmail.');
        return;
    }

    if (gmailState.connected) {
        showGmailConnectedView();
        if (gmailState.message) {
            showElement(gmailScanResult, 'block');
            gmailScanMessage.innerText = gmailState.message;
        } else {
            hideElement(gmailScanResult);
        }
        return;
    }

    showGmailConnectView(gmailState.message || 'Connect Gmail to scan recent flight disruption emails directly from this app.');
}

function showMainCard() {
    showElement(appCard, 'block');
    hideElement(gmailFoundScreen);
}

function showGmailFoundScreen(payload) {
    const { source_email, extracted_email_data, analysis, emails_scanned, claim_data } = payload;
    hideElement(appCard);
    showElement(gmailFoundScreen, 'block');

    gmailFoundSubtitle.innerText = `Scanned ${emails_scanned} email(s) and matched a flight disruption notice that looks ready for compensation review.`;
    gmailFoundSource.innerText = `From: ${source_email.from}\nSubject: ${source_email.subject}\n\nSnippet:\n${source_email.snippet || 'No preview available.'}`;

    const detailItems = [
        ['Airline', extracted_email_data.airline || 'Unknown'],
        ['Flight Number', claim_data?.flight_number || 'Unknown'],
        ['Flight Date', claim_data?.flight_date || 'Unknown'],
        ['Departure Airport', extracted_email_data.departure_airport || 'Unknown'],
        ['Arrival Airport', extracted_email_data.arrival_airport || 'Unknown'],
        ['Scheduled Departure', extracted_email_data.scheduled_departure || 'Unknown'],
        ['Actual Departure', extracted_email_data.actual_departure || 'Unknown'],
        ['Booking Reference', extracted_email_data.booking_reference || 'Not provided'],
        ['Ticket Number', extracted_email_data.ticket_number || 'Not provided'],
    ];

    gmailExtractedDetails.innerHTML = detailItems.map(([label, value]) => `
        <div class="grid grid-cols-[140px,1fr] gap-3">
            <dt class="font-semibold text-slate-500">${label}</dt>
            <dd class="text-slate-900">${value}</dd>
        </div>
    `).join('');

    gmailDraftTitle.innerText = analysis.eligible
        ? `EUR ${analysis.compensation_eur} compensation draft ready`
        : 'Formal claim review generated';

    gmailFoundOutcome.innerText = analysis.eligible
        ? `Eligibility: likely eligible\nCompensation: EUR ${analysis.compensation_eur}\nRegulation: ${analysis.regulation_reference}\n\nReasoning:\n${analysis.reasoning}`
        : `Eligibility: likely not eligible\nRegulation: ${analysis.regulation_reference}\n\nReasoning:\n${analysis.reasoning}`;

    gmailDraftLetter.innerText = analysis.claim_letter || 'No formal draft was generated.';
}

function renderAnalysisResult(data) {
    result.className = "mt-2 p-5 rounded-xl border transition-all duration-300";
    resultTitle.className = "font-bold text-lg mt-0.5";

    const isAgentError = data.regulation_reference === "Error";
    const errorText = `${data.reasoning || ""} ${data.next_steps?.join(" ") || ""}`.toLowerCase();
    const isQuotaError =
        errorText.includes("insufficient_quota") ||
        errorText.includes("exceeded your current quota") ||
        errorText.includes("resource_exhausted") ||
        errorText.includes("rate limit") ||
        errorText.includes("quota");

    if (isAgentError) {
        result.classList.add('bg-red-50', 'border-red-200');
        resultTitle.classList.add('text-red-800');
        resultIcon.innerHTML = errorIcon;
        resultTitle.innerText = isQuotaError ? "❌ Gemini Quota Issue" : "❌ Analysis Failed";

        const extraHelp = isQuotaError
            ? "\n\nYour Gemini setup is being reached correctly, but the Google AI project/key appears to be out of free-tier quota or temporarily rate-limited. Check your Gemini API quota and retry after the cooldown window."
            : "";

        resultMessage.innerText = `${data.reasoning}${extraHelp}\n\nNext Steps:\n${data.next_steps.map(step => `• ${step}`).join('\n')}`;
    } else if (data.eligible) {
        result.classList.add('bg-green-50', 'border-green-200');
        resultTitle.classList.add('text-green-800');
        resultIcon.innerHTML = successIcon;
        resultTitle.innerText = `🎉 You may be eligible for €${data.compensation_eur}!`;
        resultMessage.innerText = `Great news! Based on ${data.regulation_reference}, you are eligible for compensation.\n\n📋 CLAIM LETTER:\n\n${data.claim_letter}\n\n✅ Confidence: ${(data.confidence * 100).toFixed(0)}%\n\nNext Steps:\n${data.next_steps.map(step => `• ${step}`).join('\n')}`;
    } else {
        result.classList.add('bg-amber-50', 'border-amber-200');
        resultTitle.classList.add('text-amber-800');
        resultIcon.innerHTML = warningIcon;
        resultTitle.innerText = "⚠️ Likely Not Eligible";
        resultMessage.innerText = `Based on ${data.regulation_reference}:\n\n${data.reasoning}\n\nNext Steps:\n${data.next_steps.map(step => `• ${step}`).join('\n')}`;
    }

    showElement(result, 'block');
}

async function refreshGmailState(message = '') {
    gmailState.loading = true;
    if (message) {
        gmailState.message = message;
    }
    renderGmailTab();

    try {
        const response = await fetch(`${API_BASE_URL}/api/gmail/status`);
        const data = await response.json();
        gmailState = {
            loading: false,
            configured: !!data.configured,
            connected: !!data.connected,
            message: message || gmailState.message || '',
        };
        renderGmailTab();
    } catch (error) {
        gmailState = {
            loading: false,
            configured: false,
            connected: false,
            message: `Unable to check Gmail status. ${error.message}`,
        };
        renderGmailTab();
    }
}

// Real Google Auth Flow
googleAuthBtn.addEventListener('click', async () => {
    googleAuthText.innerText = "Redirecting...";
    googleSpinner.classList.remove('hidden');
    googleAuthBtn.disabled = true;
    window.location.href = `${API_BASE_URL}/api/gmail/connect`;
});

// Disconnect Gmail Flow
disconnectGmailBtn.addEventListener('click', async () => {
    await fetch(`${API_BASE_URL}/api/gmail/disconnect`, { method: 'POST' });
    gmailState = {
        loading: false,
        configured: true,
        connected: false,
        message: 'Gmail disconnected.',
    };
    renderGmailTab();
    showMainCard();
});

gmailBackBtn.addEventListener('click', () => {
    showMainCard();
    tabGmail.click();
});

scanGmailBtn.addEventListener('click', async () => {
    scanGmailBtn.disabled = true;
    scanGmailBtn.innerText = 'Scanning Inbox...';
    hideElement(gmailScanResult);
    hideElement(result);

    try {
        const response = await fetch(`${API_BASE_URL}/api/gmail/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || data.detail || 'Gmail scan failed');
        }

        showElement(gmailScanResult, 'block');

        if (data.status === 'analyzed') {
            gmailScanMessage.innerText = `Scanned ${data.emails_scanned} email(s).\n\nMatched Email:\nFrom: ${data.source_email.from}\nSubject: ${data.source_email.subject}\n\n${data.message}`;
            showGmailFoundScreen(data);
        } else {
            gmailScanMessage.innerText = `${data.message}\n\nScanned ${data.emails_scanned || 0} email(s).`;
        }
    } catch (error) {
        showElement(gmailScanResult, 'block');
        gmailScanMessage.innerText = `Unable to scan Gmail.\n\nError: ${error.message}`;
    } finally {
        scanGmailBtn.disabled = false;
        scanGmailBtn.innerText = 'Scan Inbox Now';
    }
});

// Backend API configuration
const API_BASE_URL = "http://localhost:8001";

// Manual Form Submit Logic
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const delayMinutes = parseInt(document.getElementById('delayReason').value.match(/\d+/) || '180');
    
    const payload = {
        flight_number: document.getElementById('flightNumber').value,
        flight_date: document.getElementById('flightDate').value,
        delay_reason: document.getElementById('delayReason').value,
        delay_minutes: delayMinutes,
        passenger_email: "user@example.com",
        jurisdiction: "EU"
    };

    hideElement(form.parentElement);
    hideElement(result);
    showElement(loading, 'block');

    try {
        // Call backend API
        const response = await fetch(`${API_BASE_URL}/api/analyze-claim`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }

        const data = await response.json();

        hideElement(loading);
        renderAnalysisResult(data);
        showElement(manualSection, 'block');
        hideElement(form);

    } catch (error) {
        hideElement(loading);
        result.className = "mt-2 p-5 rounded-xl border transition-all duration-300 bg-red-50 border-red-200";
        resultTitle.className = "font-bold text-lg mt-0.5 text-red-800";
        resultIcon.innerHTML = errorIcon;
        resultTitle.innerText = "❌ Connection Error";
        resultMessage.innerText = `Unable to connect to the AI agent. Make sure the backend is running on ${API_BASE_URL}.\n\nError: ${error.message}`;
        showElement(result, 'block');
        showElement(manualSection, 'block');
        hideElement(form);
    }
});

// Reset the manual form to try another flight
resetBtn.addEventListener('click', () => {
    hideElement(result);
    form.reset();
    showElement(form, 'block');
    showMainCard();
});

const gmailParams = new URLSearchParams(window.location.search);
const gmailStatus = gmailParams.get('gmail_status');
const gmailMessage = gmailParams.get('gmail_message');

if (gmailStatus || gmailMessage) {
    history.replaceState({}, '', window.location.pathname);
    setActiveTab('gmail');
    refreshGmailState(gmailMessage || '');
} else {
    setActiveTab('manual');
    refreshGmailState();
}
