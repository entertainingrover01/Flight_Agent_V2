"""
FastAPI Backend for Bureaucracy Hacker
Exposes Gemini-backed endpoints for flight compensation analysis.
"""
from collections import deque
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from typing import Optional
import logging
import re

# Load environment variables from .env file
load_dotenv()

# Import our agent and models
from agents.claim_agent import get_agent
from agents.chat_agent import get_chat_agent
from gmail_service import (
    GmailConfigurationError,
    build_formal_claim_letter,
    callback_redirect,
    disconnect_gmail,
    exchange_code_for_token,
    get_authorization_url,
    gmail_status,
    scan_inbox_for_claims,
)
from models.schemas import ClaimRequest, ClaimResponse, ChatRequest, ChatResponse

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
log_buffer = deque(maxlen=200)
latest_analysis_snapshot = {
    "source": None,
    "claim_data": None,
    "analysis": None,
}


class InMemoryLogHandler(logging.Handler):
    """Keep a rolling in-memory copy of logs for the demo dashboard."""

    def emit(self, record):
        try:
            log_buffer.append(self.format(record))
        except Exception:
            pass


memory_handler = InMemoryLogHandler()
memory_handler.setLevel(logging.INFO)
memory_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
logging.getLogger().addHandler(memory_handler)


def update_latest_analysis(source: str, claim_data: dict, analysis_payload: dict) -> None:
    latest_analysis_snapshot["source"] = source
    latest_analysis_snapshot["claim_data"] = claim_data
    latest_analysis_snapshot["analysis"] = analysis_payload


def _extract_flight_number(text: str) -> Optional[str]:
    match = re.search(r"\b([A-Z]{2,3}\s?\d{2,4})\b", (text or "").upper())
    if not match:
        return None
    return match.group(1).replace(" ", "")


def _extract_date(text: str) -> Optional[str]:
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text or "")
    return match.group(1) if match else None


def build_chat_activity_snapshot(message: str, history: list, result: dict) -> tuple[Optional[dict], Optional[dict]]:
    """Translate chat progress into a dashboard-friendly latest-analysis snapshot."""
    response = result.get("response") or ""
    analysis = result.get("analysis")
    ui_action = result.get("ui_action") or {}
    combined_user_text = "\n".join(
        [msg.content for msg in history if getattr(msg, "role", "") == "user"] + [message]
    )

    if analysis:
        claim_data = (
            (ui_action.get("claim_data") if isinstance(ui_action, dict) else None)
            or {
                "flight_number": _extract_flight_number(combined_user_text) or "Unknown",
                "flight_date": _extract_date(combined_user_text) or "Unknown",
                "delay_reason": "Flight disruption reported by passenger",
                "delay_minutes": analysis.get("verified_flight", {}).get("delay_minutes", 0),
                "jurisdiction": "EU",
            }
        )
        return claim_data, analysis

    if isinstance(ui_action, dict) and ui_action.get("type") == "flight_confirmation":
        claim_data = ui_action.get("claim_data", {})
        verified_flight = ui_action.get("verified_flight", {})
        snapshot = {
            "eligible": False,
            "compensation_eur": 0,
            "regulation_reference": "Pending confirmation",
            "regulation_text": "",
            "claim_letter": "",
            "reasoning": "Verified flight found. Waiting for passenger confirmation before final analysis.",
            "next_steps": [
                "Confirm whether this is the passenger's flight.",
                "Collect any passenger details already available.",
                "Run EU coverage, weather, and Gemini analysis after confirmation.",
            ],
            "confidence": 0.0,
            "verified_flight": verified_flight,
            "weather_evidence": None,
            "verification_summary": (
                f"Verified flight match found for {claim_data.get('flight_number', 'the flight')}. "
                "Waiting for the passenger to confirm the match."
            ),
            "eu_coverage": {
                "covered": None,
                "country_or_region": "Pending",
                "reason": "EU coverage will be checked after the passenger confirms the verified flight.",
            },
            "workflow_steps": [
                {
                    "step": "flight_lookup",
                    "status": "completed",
                    "message": "Flight provider returned a likely flight match.",
                },
                {
                    "step": "passenger_confirmation",
                    "status": "in_progress",
                    "message": "Waiting for the passenger to confirm whether this is the correct flight.",
                },
                {
                    "step": "eu_coverage_check",
                    "status": "pending",
                    "message": "Will run after passenger confirmation.",
                },
                {
                    "step": "weather_check",
                    "status": "pending",
                    "message": "Will run after passenger confirmation.",
                },
                {
                    "step": "gemini_analysis",
                    "status": "pending",
                    "message": "Will run after passenger confirmation.",
                },
            ],
        }
        return claim_data, snapshot

    flight_number = _extract_flight_number(combined_user_text) or _extract_flight_number(response)
    flight_date = _extract_date(combined_user_text) or _extract_date(response)

    if "still need the flight date" in response:
        claim_data = {
            "flight_number": flight_number or "Unknown",
            "flight_date": "Pending user input",
            "delay_reason": "Awaiting additional details from passenger",
            "delay_minutes": "Unknown",
            "jurisdiction": "Pending",
        }
        snapshot = {
            "eligible": False,
            "compensation_eur": 0,
            "regulation_reference": "Pending flight date",
            "regulation_text": "",
            "claim_letter": "",
            "reasoning": "The assistant found a flight number but cannot verify anything until the scheduled date is provided.",
            "next_steps": ["Collect the scheduled flight date in YYYY-MM-DD format."],
            "confidence": 0.0,
            "verified_flight": None,
            "weather_evidence": None,
            "verification_summary": f"Flight number {flight_number or 'Unknown'} detected. Waiting for the passenger to provide the scheduled date.",
            "eu_coverage": {
                "covered": None,
                "country_or_region": "Pending",
                "reason": "Coverage cannot be checked before flight verification.",
            },
            "workflow_steps": [
                {
                    "step": "collect_flight_number",
                    "status": "completed",
                    "message": f"Detected flight number {flight_number or 'Unknown'}.",
                },
                {
                    "step": "collect_flight_date",
                    "status": "in_progress",
                    "message": "Waiting for the scheduled date in YYYY-MM-DD format.",
                },
                {
                    "step": "flight_lookup",
                    "status": "pending",
                    "message": "Will run after the flight date is provided.",
                },
            ],
        }
        return claim_data, snapshot

    if "live flight provider is unavailable" in response:
        claim_data = {
            "flight_number": flight_number or "Unknown",
            "flight_date": flight_date or "Unknown",
            "delay_reason": "Flight lookup blocked by provider issue",
            "delay_minutes": "Unknown",
            "jurisdiction": "Pending",
        }
        provider_message = "Provider unavailable."
        if "Provider message:" in response:
            provider_message = response.split("Provider message:", 1)[1].strip().splitlines()[0]
        snapshot = {
            "eligible": False,
            "compensation_eur": 0,
            "regulation_reference": "Live flight provider unavailable",
            "regulation_text": "",
            "claim_letter": "",
            "reasoning": provider_message,
            "next_steps": [
                "Activate the live flight provider subscription or try again later.",
                "Use the manual claim flow if the passenger already knows the flight details.",
            ],
            "confidence": 0.0,
            "verified_flight": {
                "data_source": "aerodatabox",
                "status": "lookup_error",
            },
            "weather_evidence": None,
            "verification_summary": (
                f"Live lookup for {flight_number or 'the flight'} on {flight_date or 'the provided date'} failed "
                f"because the provider is unavailable."
            ),
            "eu_coverage": {
                "covered": None,
                "country_or_region": "Pending",
                "reason": "Coverage check was skipped because live flight verification failed.",
            },
            "workflow_steps": [
                {
                    "step": "flight_lookup",
                    "status": "failed",
                    "message": provider_message,
                },
                {
                    "step": "eu_coverage_check",
                    "status": "skipped",
                    "message": "Skipped because flight verification failed.",
                },
                {
                    "step": "weather_check",
                    "status": "skipped",
                    "message": "Skipped because flight verification failed.",
                },
                {
                    "step": "gemini_analysis",
                    "status": "skipped",
                    "message": "Skipped because flight verification failed.",
                },
            ],
        }
        return claim_data, snapshot

    if response:
        claim_data = {
            "flight_number": flight_number or "Pending",
            "flight_date": flight_date or "Pending",
            "delay_reason": "Conversation in progress",
            "delay_minutes": "Unknown",
            "jurisdiction": "Pending",
        }
        snapshot = {
            "eligible": False,
            "compensation_eur": 0,
            "regulation_reference": "Conversation in progress",
            "regulation_text": "",
            "claim_letter": "",
            "reasoning": response,
            "next_steps": ["Continue gathering the passenger's flight details."],
            "confidence": 0.0,
            "verified_flight": None,
            "weather_evidence": None,
            "verification_summary": "Chat is active. Waiting for enough details to run verification.",
            "eu_coverage": {
                "covered": None,
                "country_or_region": "Pending",
                "reason": "Coverage check has not started yet.",
            },
            "workflow_steps": [
                {
                    "step": "conversation",
                    "status": "in_progress",
                    "message": "Collecting the passenger's flight details.",
                },
            ],
        }
        return claim_data, snapshot

    return None, None


def build_gmail_activity_snapshot(scan_result: dict) -> tuple[dict, dict]:
    """Translate Gmail scan results into the dashboard snapshot format."""
    emails_scanned = scan_result.get("emails_scanned", 0)

    if scan_result.get("status") != "match_found":
        claim_data = {
            "flight_number": "Pending",
            "flight_date": "Pending",
            "delay_reason": "No claim-ready airline email extracted yet",
            "delay_minutes": "Unknown",
            "jurisdiction": "Pending",
        }
        analysis = {
            "eligible": False,
            "compensation_eur": 0,
            "regulation_reference": "Gmail scan incomplete",
            "regulation_text": "",
            "claim_letter": "",
            "reasoning": scan_result.get("message", "No suitable airline disruption email was found."),
            "next_steps": [
                "Scan a mailbox with airline disruption emails.",
                "Or continue with manual flight entry if the passenger knows the details.",
            ],
            "confidence": 0.0,
            "verified_flight": None,
            "weather_evidence": None,
            "verification_summary": (
                f"Gmail scan completed. Scanned {emails_scanned} message(s) but did not extract a claim-ready flight."
            ),
            "eu_coverage": {
                "covered": None,
                "country_or_region": "Pending",
                "reason": "Coverage could not be checked because no verified flight was extracted from Gmail.",
            },
            "workflow_steps": [
                {
                    "step": "gmail_scan",
                    "status": "completed",
                    "message": f"Scanned {emails_scanned} email(s) from Gmail.",
                },
                {
                    "step": "email_match",
                    "status": "failed",
                    "message": scan_result.get("message", "No disruption email with enough detail was found."),
                },
                {
                    "step": "flight_lookup",
                    "status": "skipped",
                    "message": "Skipped because Gmail did not yield a usable flight/date pair.",
                },
            ],
            "gmail_scan": {
                "status": scan_result.get("status"),
                "emails_scanned": emails_scanned,
                "message": scan_result.get("message"),
            },
        }
        return claim_data, analysis

    claim_data = scan_result["claim_data"]
    extracted = scan_result.get("extracted_email_data", {})
    source_email = scan_result.get("source_email", {})
    analysis = {
        "eligible": False,
        "compensation_eur": 0,
        "regulation_reference": "Gmail match extracted",
        "regulation_text": "",
        "claim_letter": "",
        "reasoning": "Gmail scan found a likely disruption email and extracted flight details. Verification is continuing.",
        "next_steps": [
            "Verify the extracted flight against the live provider.",
            "Check EU coverage.",
            "Check weather if the route is EU-covered.",
            "Run Gemini analysis and produce the claim summary.",
        ],
        "confidence": 0.0,
        "verified_flight": {
            "airline": extracted.get("airline"),
            "departure_airport": extracted.get("departure_airport"),
            "arrival_airport": extracted.get("arrival_airport"),
            "scheduled_arrival": extracted.get("scheduled_departure"),
            "actual_arrival": extracted.get("actual_departure"),
            "delay_minutes": claim_data.get("delay_minutes"),
            "airport_code": extracted.get("arrival_airport") or extracted.get("departure_airport"),
            "status": "pending_verification",
            "data_source": "gmail_extraction",
        },
        "weather_evidence": None,
        "verification_summary": (
            f"Gmail scan found a likely disruption email for {claim_data.get('flight_number', 'the flight')} "
            f"and extracted a route from {extracted.get('departure_airport', 'Unknown')} to "
            f"{extracted.get('arrival_airport', 'Unknown')}."
        ),
        "eu_coverage": {
            "covered": None,
            "country_or_region": "Pending",
            "reason": "Coverage will be checked after live flight verification.",
        },
        "workflow_steps": [
            {
                "step": "gmail_scan",
                "status": "completed",
                "message": f"Scanned {emails_scanned} email(s) from Gmail.",
            },
            {
                "step": "email_match",
                "status": "completed",
                "message": scan_result.get("message", "Found a likely airline disruption email."),
            },
            {
                "step": "email_extraction",
                "status": "completed",
                "message": (
                    f"Extracted flight {claim_data.get('flight_number', 'Unknown')} on "
                    f"{claim_data.get('flight_date', 'Unknown')} from email subject "
                    f"'{source_email.get('subject', 'Unknown')}'."
                ),
            },
            {
                "step": "flight_lookup",
                "status": "in_progress",
                "message": "Starting live flight verification and compensation workflow.",
            },
        ],
        "gmail_scan": {
            "status": scan_result.get("status"),
            "emails_scanned": emails_scanned,
            "message": scan_result.get("message"),
            "source_email": source_email,
            "extracted_email_data": extracted,
        },
    }
    return claim_data, analysis

# Initialize FastAPI app
app = FastAPI(
    title="Bureaucracy Hacker API",
    description="Autonomous flight compensation claim analyzer",
    version="1.0.0"
)

# CORS configuration - allow frontend to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# HEALTH CHECKS
# ============================================================================

@app.get("/health")
async def health_check():
    """Check if API is running"""
    return {
        "status": "ok",
        "service": "Bureaucracy Hacker API",
        "version": "1.0.0"
    }

@app.get("/api/health")
async def api_health():
    """Detailed health check"""
    return {
        "status": "healthy",
        "agent_ready": True,
        "timestamp": "2024-01-15T10:30:00Z"
    }

# ============================================================================
# MAIN CLAIM ANALYSIS ENDPOINT
# ============================================================================

@app.post("/api/analyze-claim", response_model=ClaimResponse)
async def analyze_claim(request: ClaimRequest) -> ClaimResponse:
    """
    Analyze a manually entered flight compensation claim.
    """
    
    logger.info(f"Analyzing claim for flight {request.flight_number}")
    
    try:
        # Get the agent
        agent = get_agent()
        
        # Prepare claim data
        claim_data = {
            "flight_number": request.flight_number,
            "flight_date": request.flight_date,
            "delay_reason": request.delay_reason,
            "delay_minutes": request.delay_minutes,
            "jurisdiction": request.jurisdiction
        }
        
        # Run agent analysis
        result = await agent.analyze_claim(claim_data)
        update_latest_analysis("manual", claim_data, result.model_dump())
        
        logger.info(f"Analysis complete - Eligible: {result.eligible}, Amount: €{result.compensation_eur}")
        
        return result
    
    except Exception as e:
        logger.error(f"Error analyzing claim: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing claim: {str(e)}"
        )

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    Conversational endpoint — accepts a user message plus prior turn history,
    returns the assistant's reply and an optional structured analysis object.
    """
    logger.info("Chat message received (history length: %d)", len(request.history))
    try:
        chat_agent = get_chat_agent()
        history = [{"role": msg.role, "content": msg.content} for msg in request.history]
        result = chat_agent.chat(request.message, history)
        snapshot_claim_data, snapshot_analysis = build_chat_activity_snapshot(
            request.message,
            request.history,
            result,
        )
        if snapshot_analysis:
            update_latest_analysis("chat", snapshot_claim_data or {}, snapshot_analysis)
        return ChatResponse(
            response=result["response"],
            analysis=result.get("analysis"),
            ui_action=result.get("ui_action"),
        )
    except Exception as e:
        logger.exception("Chat endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gmail/status")
async def gmail_connection_status():
    """Return Gmail OAuth configuration and connection status."""
    return gmail_status()


@app.get("/api/gmail/connect")
async def gmail_connect():
    """Start Google OAuth for Gmail access."""
    try:
        authorization_url = get_authorization_url()
        return RedirectResponse(url=authorization_url, status_code=302)
    except GmailConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/gmail/callback")
async def gmail_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Handle Google OAuth callback and return user to the frontend."""
    if error:
        return RedirectResponse(url=callback_redirect(False, error), status_code=302)
    if not code or not state:
        return RedirectResponse(url=callback_redirect(False, "Missing OAuth code"), status_code=302)

    try:
        exchange_code_for_token(code=code, state=state)
        return RedirectResponse(url=callback_redirect(True, "Gmail connected"), status_code=302)
    except Exception as exc:
        return RedirectResponse(url=callback_redirect(False, str(exc)), status_code=302)


@app.post("/api/gmail/disconnect")
async def gmail_disconnect():
    """Remove locally stored Gmail credentials."""
    disconnect_gmail()
    return {"status": "disconnected"}


@app.post("/api/gmail/scan")
async def gmail_scan():
    """Scan Gmail for flight disruption emails, then analyze the best match."""
    try:
        scan_result = scan_inbox_for_claims()
        initial_claim_data, initial_analysis = build_gmail_activity_snapshot(scan_result)
        update_latest_analysis("gmail", initial_claim_data, initial_analysis)
        if scan_result["status"] != "match_found":
            return scan_result

        claim_data = scan_result["claim_data"]
        logger.info(
            "Running claim analysis from Gmail email for flight %s",
            claim_data["flight_number"]
        )
        result = await get_agent().analyze_claim(claim_data)
        analysis_payload = result.model_dump()
        analysis_payload["workflow_steps"] = (
            initial_analysis.get("workflow_steps", [])
            + (analysis_payload.get("workflow_steps") or [])
        )
        analysis_payload["gmail_scan"] = initial_analysis.get("gmail_scan")
        if not analysis_payload.get("verified_flight"):
            analysis_payload["verified_flight"] = initial_analysis.get("verified_flight")
        if not analysis_payload.get("verification_summary"):
            analysis_payload["verification_summary"] = initial_analysis.get("verification_summary")
        analysis_payload["claim_letter"] = build_formal_claim_letter(
            analysis=analysis_payload,
            claim_data=claim_data,
            extracted_email_data=scan_result["extracted_email_data"],
            contact_email="krishnachapai500@gmail.com",
        )
        update_latest_analysis("gmail", claim_data, analysis_payload)
        return {
            "status": "analyzed",
            "message": scan_result["message"],
            "emails_scanned": scan_result["emails_scanned"],
            "claim_data": claim_data,
            "source_email": scan_result["source_email"],
            "extracted_email_data": scan_result["extracted_email_data"],
            "analysis": analysis_payload,
        }
    except GmailConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Gmail scan failed")
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/regulations/{jurisdiction}")
async def get_regulations(jurisdiction: str = "EU"):
    """
    Get applicable regulations for a jurisdiction
    
    Supported jurisdictions:
    - EU (EU261)
    - US (DOT)
    - UK (CAA)
    """
    
    regulations_db = {
        "EU": {
            "name": "EU Regulation 261/2004",
            "description": "Compensation and assistance to passengers in event of denied boarding and of cancellation or long delay of flights",
            "compensation_amounts": {
                "short": 250,  # <= 1500 km
                "medium": 400,  # 1500-3500 km
                "long": 600   # > 3500 km
            },
            "minimum_delay_hours": 3
        },
        "US": {
            "name": "DOT Regulations",
            "description": "U.S. Department of Transportation rules",
            "compensation_amounts": 0,  # No mandatory compensation
            "note": "US has no mandatory compensation for delays"
        }
    }
    
    if jurisdiction.upper() not in regulations_db:
        raise HTTPException(
            status_code=404,
            detail=f"Jurisdiction '{jurisdiction}' not found"
        )
    
    return regulations_db[jurisdiction.upper()]

@app.get("/", response_class=HTMLResponse)
async def root():
    """Simple browser dashboard for recent backend activity."""
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bureaucracy Hacker API Logs</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #111827;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --good: #34d399;
      --warn: #fbbf24;
      --border: #1f2937;
    }
    body {
      margin: 0;
      padding: 32px;
      background: radial-gradient(circle at top, #172554, var(--bg) 55%);
      color: var(--text);
      font-family: Menlo, Monaco, Consolas, monospace;
    }
    h1 { margin: 0 0 8px; font-size: 28px; }
    p { margin: 0 0 20px; color: var(--muted); }
    .panel {
      border: 1px solid var(--border);
      background: rgba(17, 24, 39, 0.92);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.35);
    }
    .row {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 14px;
      flex-wrap: wrap;
    }
    .badge {
      border: 1px solid rgba(56, 189, 248, 0.35);
      color: var(--accent);
      border-radius: 999px;
      padding: 4px 10px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }
    .card {
      border: 1px solid var(--border);
      background: rgba(15, 23, 42, 0.7);
      border-radius: 14px;
      padding: 16px;
    }
    .card h3 {
      margin: 0 0 12px;
      font-size: 15px;
      color: var(--text);
    }
    .metric {
      margin: 0 0 10px;
    }
    .label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .value {
      font-size: 18px;
      color: var(--text);
      font-weight: 600;
    }
    .summary {
      border-left: 3px solid var(--accent);
      padding-left: 12px;
      color: var(--text);
      line-height: 1.5;
      margin: 12px 0 0;
    }
    .workflow-step {
      border: 1px solid var(--border);
      background: rgba(15, 23, 42, 0.55);
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 10px;
    }
    .workflow-step:last-child {
      margin-bottom: 0;
    }
    .good { color: var(--good); }
    .warn { color: var(--warn); }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.5;
      min-height: 160px;
      max-height: 70vh;
      overflow: auto;
    }
    a { color: var(--accent); }
  </style>
</head>
<body>
  <h1>Bureaucracy Hacker API</h1>
  <p>Recent backend activity and the latest verification evidence used by the claim engine.</p>
  <div class="panel" style="margin-bottom: 18px;">
    <div class="row">
      <span class="badge">Latest Evidence</span>
      <span>Flight check + weather check + decision comparison</span>
    </div>
    <div id="evidenceSummary">Loading latest analysis...</div>
    <div class="grid">
      <div class="card">
        <h3>Claim Input</h3>
        <div id="claimCard">Waiting for a claim...</div>
      </div>
      <div class="card">
        <h3>Flight Verification</h3>
        <div id="flightCard">Waiting for flight data...</div>
      </div>
      <div class="card">
        <h3>Gmail Extraction</h3>
        <div id="gmailCard">Waiting for Gmail scan...</div>
      </div>
      <div class="card">
        <h3>Weather Verification</h3>
        <div id="weatherCard">Waiting for weather data...</div>
      </div>
      <div class="card">
        <h3>EU Coverage</h3>
        <div id="coverageCard">Waiting for coverage check...</div>
      </div>
      <div class="card">
        <h3>Decision</h3>
        <div id="decisionCard">Waiting for result...</div>
      </div>
    </div>
    <div class="grid">
      <div class="card">
        <h3>Workflow Steps</h3>
        <div id="workflowCard">Waiting for workflow...</div>
      </div>
      <div class="card" style="grid-column: 1 / -1;">
        <h3>Raw Evidence JSON</h3>
        <pre id="evidence">Loading latest analysis...</pre>
      </div>
    </div>
  </div>
  <div class="panel">
    <div class="row">
      <span class="badge">Live Logs</span>
      <span>Frontend: <a href="http://localhost:8000">localhost:8000</a></span>
      <span>API endpoint: <code>POST /api/analyze-claim</code></span>
    </div>
    <pre id="logs">Loading logs...</pre>
  </div>
  <script>
    function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function metric(label, value, extraClass = '') {
      return `
        <div class="metric">
          <span class="label">${escapeHtml(label)}</span>
          <span class="value ${extraClass}">${escapeHtml(value)}</span>
        </div>
      `;
    }

    async function refreshEvidence() {
      try {
        const response = await fetch('/api/latest-analysis');
        const data = await response.json();
        const el = document.getElementById('evidence');
        const summaryEl = document.getElementById('evidenceSummary');
        const claimCard = document.getElementById('claimCard');
        const flightCard = document.getElementById('flightCard');
        const gmailCard = document.getElementById('gmailCard');
        const weatherCard = document.getElementById('weatherCard');
        const coverageCard = document.getElementById('coverageCard');
        const decisionCard = document.getElementById('decisionCard');
        const workflowCard = document.getElementById('workflowCard');
        if (!data.analysis) {
          summaryEl.textContent = 'No analysis yet. Submit a claim or scan Gmail to populate verified flight and weather evidence.';
          claimCard.textContent = 'Waiting for a claim...';
          flightCard.textContent = 'Waiting for flight data...';
          gmailCard.textContent = 'Waiting for Gmail scan...';
          weatherCard.textContent = 'Waiting for weather data...';
          coverageCard.textContent = 'Waiting for coverage check...';
          decisionCard.textContent = 'Waiting for result...';
          workflowCard.textContent = 'Waiting for workflow...';
          el.textContent = 'No analysis yet. Submit a claim or scan Gmail to populate verified flight and weather evidence.';
          return;
        }

        const claim = data.claim_data || {};
        const analysis = data.analysis || {};
        const flight = analysis.verified_flight || {};
        const gmail = analysis.gmail_scan || {};
        const extractedEmail = gmail.extracted_email_data || {};
        const sourceEmail = gmail.source_email || {};
        const weather = analysis.weather_evidence || {};
        const coverage = analysis.eu_coverage || {};
        const workflowSteps = analysis.workflow_steps || [];
        const reportedDelay = claim.delay_minutes ?? 'Unknown';
        const verifiedDelay = flight.delay_minutes ?? 'Unavailable';
        const delayMatch = typeof reportedDelay === 'number' && typeof verifiedDelay === 'number'
          ? `${verifiedDelay - reportedDelay > 0 ? '+' : ''}${verifiedDelay - reportedDelay} min vs reported`
          : 'No direct delay comparison available';

        summaryEl.innerHTML = `
          <div class="summary">
            ${escapeHtml(analysis.verification_summary || 'Verification summary unavailable.')}
          </div>
        `;

        claimCard.innerHTML = `
          ${metric('Source', data.source || 'manual')}
          ${metric('Flight', claim.flight_number || 'Unknown')}
          ${metric('Date', claim.flight_date || 'Unknown')}
          ${metric('Reported Delay', reportedDelay === 'Unknown' ? reportedDelay : `${reportedDelay} min`)}
          ${metric('Reported Reason', claim.delay_reason || 'Unknown')}
        `;

        flightCard.innerHTML = `
          ${metric('Airline', flight.airline || 'Unavailable')}
          ${metric('Source', flight.data_source || 'Unavailable')}
          ${metric('Route', flight.departure_airport && flight.arrival_airport ? `${flight.departure_airport} -> ${flight.arrival_airport}` : 'Unavailable')}
          ${metric('Airport', flight.airport_code || 'Unavailable')}
          ${metric('Scheduled Arrival', flight.scheduled_arrival || 'Unavailable')}
          ${metric('Actual Arrival', flight.actual_arrival || 'Unavailable')}
          ${metric('Verified Delay', verifiedDelay === 'Unavailable' ? verifiedDelay : `${verifiedDelay} min`, 'good')}
          ${metric('Comparison', delayMatch)}
          ${metric('Status', flight.status || 'Unavailable')}
        `;

        gmailCard.innerHTML = data.source === 'gmail' || gmail.status
          ? `
              ${metric('Scan Status', gmail.status || 'Unavailable')}
              ${metric('Emails Scanned', gmail.emails_scanned == null ? 'Unavailable' : gmail.emails_scanned)}
              ${metric('Matched Subject', sourceEmail.subject || 'Unavailable')}
              ${metric('Email From', sourceEmail.from || 'Unavailable')}
              ${metric('Extracted Airline', extractedEmail.airline || 'Unavailable')}
              ${metric('Extracted Route', extractedEmail.departure_airport && extractedEmail.arrival_airport ? `${extractedEmail.departure_airport} -> ${extractedEmail.arrival_airport}` : 'Unavailable')}
              ${metric('Booking Ref', extractedEmail.booking_reference || 'Unavailable')}
            `
          : 'Waiting for Gmail scan...';

        weatherCard.innerHTML = `
          ${metric('Airport', weather.airport || flight.airport_code || 'Unavailable')}
          ${metric('Date', weather.date || claim.flight_date || 'Unavailable')}
          ${metric('Summary', weather.weather_summary || 'Unavailable')}
          ${metric('Severe Weather', weather.severe_weather == null ? 'Unavailable' : (weather.severe_weather ? 'Yes' : 'No'), weather.severe_weather ? 'warn' : 'good')}
          ${metric('Wind', weather.wind_speed_knots == null ? 'Unavailable' : `${weather.wind_speed_knots} kt`)}
          ${metric('Visibility', weather.visibility_km == null ? 'Unavailable' : `${weather.visibility_km} km`)}
          ${metric('Precipitation', weather.precipitation_mm == null ? 'Unavailable' : `${weather.precipitation_mm} mm`)}
        `;

        coverageCard.innerHTML = `
          ${metric('Covered By EU261', coverage.covered == null ? 'Unavailable' : (coverage.covered ? 'Yes' : 'No'), coverage.covered ? 'good' : 'warn')}
          ${metric('Region/Country', coverage.country_or_region || 'Unavailable')}
          ${metric('Reason', coverage.reason || 'Unavailable')}
        `;

        decisionCard.innerHTML = `
          ${metric('Eligible', analysis.eligible ? 'Yes' : 'No', analysis.eligible ? 'good' : 'warn')}
          ${metric('Compensation', analysis.compensation_eur == null ? 'Unavailable' : `EUR ${analysis.compensation_eur}`)}
          ${metric('Regulation', analysis.regulation_reference || 'Unavailable')}
          ${metric('Confidence', analysis.confidence == null ? 'Unavailable' : `${Math.round(analysis.confidence * 100)}%`)}
          ${metric('Reasoning Snapshot', analysis.reasoning || 'Unavailable')}
        `;

        workflowCard.innerHTML = workflowSteps.length
          ? workflowSteps.map((step, index) => `
              <div class="workflow-step">
                ${metric(`Step ${index + 1}`, step.step || 'Unknown')}
                ${metric('Status', step.status || 'Unknown', step.status === 'completed' ? 'good' : (step.status === 'failed' ? 'warn' : ''))}
                ${metric('Message', step.message || 'Unavailable')}
              </div>
            `).join('')
          : 'Workflow not available.';

        el.textContent = JSON.stringify(data, null, 2);
      } catch (error) {
        document.getElementById('evidence').textContent = 'Unable to load evidence: ' + error.message;
        document.getElementById('evidenceSummary').textContent = 'Unable to load evidence: ' + error.message;
      }
    }
    async function refreshLogs() {
      try {
        const response = await fetch('/api/logs');
        const data = await response.json();
        const text = data.logs.length ? data.logs.join('\\n') : 'No logs yet. Submit a claim from the frontend.';
        const el = document.getElementById('logs');
        el.textContent = text;
        el.scrollTop = el.scrollHeight;
      } catch (error) {
        document.getElementById('logs').textContent = 'Unable to load logs: ' + error.message;
      }
    }
    refreshEvidence();
    refreshLogs();
    setInterval(() => {
      refreshEvidence();
      refreshLogs();
    }, 1000);
  </script>
</body>
</html>
"""


@app.get("/api/logs")
async def get_logs():
    """Expose recent log lines for the demo dashboard."""
    return {"logs": list(log_buffer)}


@app.get("/api/latest-analysis")
async def get_latest_analysis():
    """Expose the latest analysis and verification evidence."""
    return latest_analysis_snapshot

@app.get("/docs")
async def docs():
    """Simple API summary."""
    return {
        "title": "Bureaucracy Hacker API Documentation",
        "version": "1.0.0",
        "endpoints": [
            {
                "method": "POST",
                "path": "/api/analyze-claim",
                "description": "Analyze a flight compensation claim",
                "request_body": {
                    "flight_number": "string (e.g., BA123)",
                    "flight_date": "string (YYYY-MM-DD)",
                    "delay_reason": "string",
                    "delay_minutes": "integer",
                    "jurisdiction": "string (default: EU)"
                },
                "response": "ClaimResponse object"
            },
            {
                "method": "GET",
                "path": "/api/gmail/status",
                "description": "Check Gmail OAuth status"
            },
            {
                "method": "GET",
                "path": "/api/gmail/connect",
                "description": "Start Gmail OAuth"
            },
            {
                "method": "POST",
                "path": "/api/gmail/scan",
                "description": "Scan Gmail and analyze a matched flight disruption email"
            }
        ]
    }

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )

# ============================================================================
# STARTUP/SHUTDOWN EVENTS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Bureaucracy Hacker API starting up...")
    logger.info("✅ Agent ready for claim analysis")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Bureaucracy Hacker API shutting down...")

# ============================================================================
# RUN LOCALLY
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        log_level="info"
    )
