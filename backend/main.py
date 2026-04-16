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

# Load environment variables from .env file
load_dotenv()

# Import our agent and models
from agents.claim_agent import get_agent
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
from models.schemas import ClaimRequest, ClaimResponse

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
log_buffer = deque(maxlen=200)


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
        
        logger.info(f"Analysis complete - Eligible: {result.eligible}, Amount: €{result.compensation_eur}")
        
        return result
    
    except Exception as e:
        logger.error(f"Error analyzing claim: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing claim: {str(e)}"
        )

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
        if scan_result["status"] != "match_found":
            return scan_result

        claim_data = scan_result["claim_data"]
        logger.info(
            "Running claim analysis from Gmail email for flight %s",
            claim_data["flight_number"]
        )
        result = await get_agent().analyze_claim(claim_data)
        analysis_payload = result.model_dump()
        analysis_payload["claim_letter"] = build_formal_claim_letter(
            analysis=analysis_payload,
            claim_data=claim_data,
            extracted_email_data=scan_result["extracted_email_data"],
            contact_email="krishnachapai500@gmail.com",
        )
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
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.5;
      min-height: 420px;
      max-height: 70vh;
      overflow: auto;
    }
    a { color: var(--accent); }
  </style>
</head>
<body>
  <h1>Bureaucracy Hacker API</h1>
  <p>Recent backend activity. Submit a claim from the frontend and the steps will appear here.</p>
  <div class="panel">
    <div class="row">
      <span class="badge">Live Logs</span>
      <span>Frontend: <a href="http://localhost:8000">localhost:8000</a></span>
      <span>API endpoint: <code>POST /api/analyze-claim</code></span>
    </div>
    <pre id="logs">Loading logs...</pre>
  </div>
  <script>
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
    refreshLogs();
    setInterval(refreshLogs, 1000);
  </script>
</body>
</html>
"""


@app.get("/api/logs")
async def get_logs():
    """Expose recent log lines for the demo dashboard."""
    return {"logs": list(log_buffer)}

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
