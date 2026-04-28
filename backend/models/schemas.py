from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

class ClaimRequest(BaseModel):
    """User's flight compensation claim request"""
    flight_number: str
    flight_date: str
    delay_reason: str
    delay_minutes: int
    passenger_email: Optional[str] = None
    jurisdiction: str = "EU"  # EU, US, UK, etc.

class ClaimResponse(BaseModel):
    """Agent's analysis response"""
    eligible: bool
    compensation_eur: int
    regulation_reference: str
    regulation_text: str
    claim_letter: str
    reasoning: str
    next_steps: List[str]
    confidence: float  # 0-1, how confident in the decision
    verified_flight: Optional[Any] = None
    weather_evidence: Optional[Any] = None
    verification_summary: Optional[str] = None
    eu_coverage: Optional[Any] = None
    workflow_steps: Optional[Any] = None

class FlightData(BaseModel):
    """Flight information from external APIs"""
    flight_number: str
    date: str
    scheduled_arrival: str
    actual_arrival: str
    delay_minutes: int
    airport_code: str
    airline: str

class WeatherData(BaseModel):
    """Weather information for the flight date"""
    airport: str
    date: str
    weather_conditions: str
    severe_weather: bool
    wind_speed_knots: int
    visibility_km: int

class RegulationMatch(BaseModel):
    """Matched regulation from RAG"""
    jurisdiction: str
    article: str
    text: str
    compensation_en: int
    exemptions: List[str]

class ClaimHistory(BaseModel):
    """Stored claim for user dashboard"""
    id: int
    flight_number: str
    flight_date: str
    status: str  # pending, submitted, approved, rejected
    compensation_amount: int
    created_at: datetime
    updated_at: datetime


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


class ChatResponse(BaseModel):
    response: str
    analysis: Optional[Any] = None
    ui_action: Optional[Any] = None
