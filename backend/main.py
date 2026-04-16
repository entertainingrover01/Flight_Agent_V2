"""
FastAPI Backend for Bureaucracy Hacker
Exposes agent endpoints for flight compensation analysis
"""
import os
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import logging

# Import our agent and models
from agents.claim_agent import get_agent
from models.schemas import ClaimRequest, ClaimResponse

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    Analyze a flight compensation claim
    
    This endpoint:
    1. Receives flight delay details from user
    2. Passes to Claude Agent via LangChain
    3. Agent verifies flight, checks weather, searches regulations
    4. Returns eligibility decision + claim letter
    
    Example request:
    {
        "flight_number": "BA123",
        "flight_date": "2024-01-15",
        "delay_reason": "Technical issues",
        "delay_minutes": 300,
        "passenger_email": "user@example.com",
        "jurisdiction": "EU"
    }
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

# ============================================================================
# ALTERNATIVE ENDPOINTS (for different input types)
# ============================================================================

@app.post("/api/analyze-from-email")
async def analyze_from_email(request: dict):
    """
    Analyze a claim from a raw email
    (Useful for n8n integration)
    
    Example:
    {
        "email_subject": "Your flight BA123 has been delayed",
        "email_body": "Dear passenger, your flight BA123 from LHR to JFK on 2024-01-15 has been delayed by 4 hours due to technical issues...",
        "passenger_email": "user@example.com"
    }
    """
    
    try:
        # In production, use NLP to extract from email
        # For now, return error
        return {
            "status": "not_implemented",
            "message": "Email parsing coming soon. Please use /api/analyze-claim endpoint instead."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/api/claim-status/{claim_id}")
async def claim_status(claim_id: str):
    """
    Get status of a submitted claim
    (Would query database in production)
    """
    
    return {
        "claim_id": claim_id,
        "status": "In development",
        "message": "Claim tracking coming soon"
    }

# ============================================================================
# UTILITIES
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Bureaucracy Hacker API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "analyze_claim": "POST /api/analyze-claim",
            "regulations": "GET /api/regulations/{jurisdiction}",
            "docs": "/docs"
        }
    }

@app.get("/docs")
async def docs():
    """API documentation"""
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
    
    # Run: python backend/main.py
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        log_level="info"
    )
