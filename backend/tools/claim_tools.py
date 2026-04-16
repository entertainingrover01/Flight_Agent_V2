"""
Domain-specific tools for the claim analysis agent
"""
from langchain.tools import tool
from typing import Dict, Any
import json
from datetime import datetime

class FlightToolkit:
    """Collection of tools for flight data queries"""
    
    @staticmethod
    @tool
    def check_flight_status(flight_number: str, date: str) -> str:
        """
        Query flight data from aviation API.
        Returns actual vs scheduled times to verify delay.
        
        Args:
            flight_number: e.g., "BA123"
            date: e.g., "2024-01-15"
        """
        # Mock response - replace with real API: FlightRadar24, AviationStack, etc.
        mock_data = {
            "flight": flight_number,
            "date": date,
            "scheduled_arrival": "14:30 UTC",
            "actual_arrival": "18:45 UTC",
            "delay_minutes": 255,
            "airport_code": "LHR",
            "airline": "British Airways",
            "status": "landed"
        }
        return json.dumps(mock_data)
    
    @staticmethod
    @tool
    def check_weather_history(airport_code: str, date: str, time: str) -> str:
        """
        Check historical weather for the flight date.
        Used to verify if airline's "weather" claim is legitimate.
        
        Args:
            airport_code: e.g., "LHR" 
            date: e.g., "2024-01-15"
            time: e.g., "14:30"
        """
        # Mock response - replace with NOAA, OpenWeatherMap historical API
        mock_weather = {
            "airport": airport_code,
            "date": date,
            "time": time,
            "weather_summary": "Clear skies, light winds",
            "severe_weather": False,
            "wind_speed_knots": 8,
            "visibility_km": 15,
            "temperature_c": 12,
            "precipitation_mm": 0
        }
        return json.dumps(mock_weather)
    
    @staticmethod
    @tool
    def verify_extraordinary_circumstances(delay_reason: str) -> str:
        """
        Check if the delay reason qualifies as 'extraordinary circumstances'
        (which would exempt the airline from compensation).
        
        Common exemptions:
        - Bad weather
        - Security threats
        - Air traffic control strikes
        - Runway issues
        
        Common NON-exemptions:
        - Technical issues (airline's responsibility)
        - Crew scheduling (airline's responsibility)
        - Maintenance (airline's responsibility)
        """
        exemption_keywords = [
            "weather", "snow", "ice", "lightning", "wind", "fog",
            "security", "bomb threat", "strike", "air traffic control",
            "airport closure", "military", "civil unrest"
        ]
        
        reason_lower = delay_reason.lower()
        is_exempt = any(keyword in reason_lower for keyword in exemption_keywords)
        
        analysis = {
            "reason": delay_reason,
            "is_extraordinary_circumstance": is_exempt,
            "exemption_applies": is_exempt,
            "reasoning": "Weather-related delays are typically exempt" if is_exempt 
                        else "Airline-related issues typically qualify for compensation"
        }
        return json.dumps(analysis)


class RegulationToolkit:
    """Tools for searching and applying regulations"""
    
    @staticmethod
    @tool
    def search_regulations(query: str, jurisdiction: str = "EU") -> str:
        """
        Search regulation database using RAG (Retrieval-Augmented Generation).
        Currently returns mock regulations. Would query vector DB in production.
        
        Args:
            query: Search terms, e.g., "flight delay compensation"
            jurisdiction: "EU" (EU261), "US" (DOT), "UK" (CAA), etc.
        """
        regulations_db = {
            "EU": {
                "title": "EU Regulation 261/2004",
                "article_7": """
ARTICLE 7 - COMPENSATION
Member States shall ensure that passengers affected by the cancellation of a flight 
receive from the operating air carrier:

(a) reimbursement of the full cost of the ticket or re-routing to final destination
(b) care and assistance
(c) COMPENSATION:
    - €250 for flights ≤ 1,500 km
    - €400 for flights > 1,500 km (within EU) or 1,500-3,500 km
    - €600 for flights > 3,500 km

EXCEPTIONS (Force Majeure):
- Extraordinary circumstances beyond airline control
- Weather extremes, security threats, air traffic control issues
- NOT: technical failures, crew issues, maintenance (airline responsibility)
""",
                "article_9": """
ARTICLE 9 - EXEMPTIONS
No compensation if delay caused by:
1. Extreme weather conditions incompatible with safe flight
2. Security risks
3. Unforeseeable circumstances not inherent to normal operation
4. Air traffic control decisions
""",
                "article_5": """
ARTICLE 5 - RIGHT TO CARE
Passengers have right to:
- Accommodation (if necessary)
- Meals and refreshments
- Communication
- Re-routing on next available flight
""",
            },
            "US": {
                "title": "Department of Transportation (DOT) Regulations",
                "rules": """
U.S. aviation differs from EU261:
- NO mandatory compensation for delays
- Airlines only required to disclose issues
- AA can offer voluntary compensation
- No set compensation amounts
- Focus on disclosure, not compensation
""",
            }
        }
        
        result = regulations_db.get(jurisdiction, {}).get("article_7", 
                                                           regulations_db.get(jurisdiction, {}))
        return json.dumps({
            "jurisdiction": jurisdiction,
            "status": "found",
            "regulations": result
        })
    
    @staticmethod
    @tool
    def calculate_compensation(flight_distance_km: int, delay_minutes: int, 
                              jurisdiction: str = "EU") -> str:
        """
        Calculate compensation amount based on flight distance and jurisdiction.
        
        Args:
            flight_distance_km: Distance between airports
            delay_minutes: Total delay in minutes
            jurisdiction: "EU", "US", "UK", etc.
        """
        compensation = 0
        
        # EU261 rules
        if jurisdiction == "EU":
            if delay_minutes >= 180:  # 3+ hours
                if flight_distance_km <= 1500:
                    compensation = 250
                elif flight_distance_km <= 3500:
                    compensation = 400
                else:
                    compensation = 600
        
        elif jurisdiction == "US":
            compensation = 0  # No mandatory compensation
        
        return json.dumps({
            "jurisdiction": jurisdiction,
            "flight_distance_km": flight_distance_km,
            "delay_minutes": delay_minutes,
            "eligible_delay": delay_minutes >= 180,
            "compensation_eur": compensation,
            "status": "eligible" if compensation > 0 else "not_eligible"
        })


class DocumentToolkit:
    """Tools for generating claim documents"""
    
    @staticmethod
    @tool
    def generate_claim_letter(flight_number: str, flight_date: str, 
                             delay_reason: str, delay_minutes: int,
                             compensation_amount: int, regulation: str) -> str:
        """
        Generate a professional, legally-sound compensation claim letter.
        
        Args:
            flight_number: e.g., "BA123"
            flight_date: e.g., "2024-01-15"
            delay_reason: Stated reason for delay
            delay_minutes: Total delay
            compensation_amount: EUR amount to claim
            regulation: e.g., "EU261 Article 7"
        """
        letter = f"""
Dear Airline Customer Service,

I am writing to formally claim compensation for my delayed flight as per {regulation}.

FLIGHT DETAILS:
- Flight Number: {flight_number}
- Flight Date: {flight_date}
- Delay Duration: {delay_minutes} minutes (over 3 hours)
- Stated Reason: {delay_reason}

COMPENSATION CLAIM:
Under {regulation}, I am entitled to compensation of €{compensation_amount} for this delay.

The delay significantly disrupted my travel and caused me material inconvenience. 
The reason provided does not constitute an extraordinary circumstance and is therefore 
the airline's responsibility.

I request that compensation of €{compensation_amount} be transferred to my account 
within 30 days of receiving this claim.

I have attached supporting documentation:
- Booking confirmation
- Boarding pass
- Proof of payment

I look forward to your prompt response.

Respectfully,
The Passenger
""".strip()
        
        return json.dumps({
            "success": True,
            "letter": letter,
            "status": "ready_to_send"
        })


def get_all_tools():
    """Register all tools for the agent"""
    return [
        FlightToolkit.check_flight_status,
        FlightToolkit.check_weather_history,
        FlightToolkit.verify_extraordinary_circumstances,
        RegulationToolkit.search_regulations,
        RegulationToolkit.calculate_compensation,
        DocumentToolkit.generate_claim_letter,
    ]
