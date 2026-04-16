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

// SVG Icons
const successIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;
const warningIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;
const errorIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;

// Tab Switching Logic
tabManual.addEventListener('click', () => {
    tabManual.classList.replace('text-slate-500', 'text-blue-600');
    tabManual.classList.replace('border-transparent', 'border-blue-600');
    tabGmail.classList.replace('text-blue-600', 'text-slate-500');
    tabGmail.classList.replace('border-blue-600', 'border-transparent');
    
    manualSection.classList.remove('hidden');
    gmailSection.classList.add('hidden');
    gmailSuccess.classList.add('hidden');
    result.classList.add('hidden'); 
});

tabGmail.addEventListener('click', () => {
    tabGmail.classList.replace('text-slate-500', 'text-blue-600');
    tabGmail.classList.replace('border-transparent', 'border-blue-600');
    tabManual.classList.replace('text-blue-600', 'text-slate-500');
    tabManual.classList.replace('border-blue-600', 'border-transparent');
    
    manualSection.classList.add('hidden');
    
    if(localStorage.getItem('gmailConnected') === 'true') {
        gmailSuccess.classList.remove('hidden');
    } else {
        gmailSection.classList.remove('hidden');
    }
    
    loading.classList.add('hidden');
    result.classList.add('hidden');
});

// Simulated Google Auth Flow
googleAuthBtn.addEventListener('click', async () => {
    googleAuthText.innerText = "Connecting...";
    googleSpinner.classList.remove('hidden');
    googleAuthBtn.disabled = true;

    // Simulate redirect to Google and callback
    await new Promise(r => setTimeout(r, 2000)); 

    localStorage.setItem('gmailConnected', 'true');
    gmailSection.classList.add('hidden');
    gmailSuccess.classList.remove('hidden');
    
    googleAuthText.innerText = "Sign in with Google";
    googleSpinner.classList.add('hidden');
    googleAuthBtn.disabled = false;
});

// Disconnect Gmail Flow
disconnectGmailBtn.addEventListener('click', () => {
    localStorage.removeItem('gmailConnected');
    gmailSuccess.classList.add('hidden');
    gmailSection.classList.remove('hidden');
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

    form.parentElement.classList.add('hidden');
    result.classList.add('hidden');
    loading.classList.remove('hidden');

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

        loading.classList.add('hidden');
        
        result.className = "mt-2 p-5 rounded-xl border transition-all duration-300";
        resultTitle.className = "font-bold text-lg mt-0.5";

        if(data.eligible) {
            result.classList.add('bg-green-50', 'border-green-200');
            resultTitle.classList.add('text-green-800');
            resultIcon.innerHTML = successIcon;
            resultTitle.innerText = `🎉 You may be eligible for €${data.compensation_eur}!`;
            
            // Format the message with claim letter
            const fullMessage = `Great news! Based on ${data.regulation_reference}, you are eligible for compensation.\n\n📋 CLAIM LETTER:\n\n${data.claim_letter}\n\n✅ Confidence: ${(data.confidence * 100).toFixed(0)}%\n\nNext Steps:\n${data.next_steps.map(step => `• ${step}`).join('\n')}`;
            resultMessage.innerText = fullMessage;
        } else {
            result.classList.add('bg-amber-50', 'border-amber-200');
            resultTitle.classList.add('text-amber-800');
            resultIcon.innerHTML = warningIcon;
            resultTitle.innerText = "⚠️ Likely Not Eligible";
            
            const fullMessage = `Based on ${data.regulation_reference}:\n\n${data.reasoning}\n\nNext Steps:\n${data.next_steps.map(step => `• ${step}`).join('\n')}`;
            resultMessage.innerText = fullMessage;
        }
        
        result.classList.remove('hidden');
        manualSection.classList.remove('hidden');
        form.classList.add('hidden');

    } catch (error) {
        loading.classList.add('hidden');
        result.className = "mt-2 p-5 rounded-xl border transition-all duration-300 bg-red-50 border-red-200";
        resultTitle.className = "font-bold text-lg mt-0.5 text-red-800";
        resultIcon.innerHTML = errorIcon;
        resultTitle.innerText = "❌ Connection Error";
        resultMessage.innerText = `Unable to connect to the AI agent. Make sure the backend is running on ${API_BASE_URL}.\n\nError: ${error.message}`;
        result.classList.remove('hidden');
        manualSection.classList.remove('hidden');
        form.classList.add('hidden');
    }
});

// Reset the manual form to try another flight
resetBtn.addEventListener('click', () => {
    result.classList.add('hidden');
    form.reset();
    form.classList.remove('hidden');
});