"""
Domain-specific tools for the claim analysis agent
"""
from langchain.tools import tool
from typing import Dict, Any
import json
import os
from datetime import datetime
from json import JSONDecodeError

import httpx

class FlightToolkit:
    """Collection of tools for flight data queries"""

    AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1/flights"
    AERODATABOX_APIMARKET_BASE_URL = "https://prod.api.market/api/v1/aedbx/aerodatabox"
    AERODATABOX_RAPIDAPI_BASE_URL = "https://aerodatabox.p.rapidapi.com"

    @staticmethod
    def _extract_code_parts(flight_number: str) -> tuple[str, str]:
        normalized = flight_number.upper().replace(" ", "")
        prefix = ""
        digits = ""
        for char in normalized:
            if char.isalpha() and not digits:
                prefix += char
            elif char.isdigit():
                digits += char
        return prefix, digits

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _provider_error_payload(flight_number: str, date: str, provider: str, message: str) -> Dict[str, Any]:
        return {
            "flight": flight_number.upper().replace(" ", ""),
            "date": date,
            "lookup_status": "error",
            "error": message,
            "data_source": provider,
        }

    @staticmethod
    def _compute_delay_minutes(departure: Dict[str, Any], arrival: Dict[str, Any]) -> int:
        arrival_delay = FlightToolkit._safe_int(arrival.get("delay"), -1)
        if arrival_delay >= 0:
            return arrival_delay

        departure_delay = FlightToolkit._safe_int(departure.get("delay"), -1)
        if departure_delay >= 0:
            return departure_delay

        return 0

    @staticmethod
    def _normalize_aviationstack_flight(record: Dict[str, Any], requested_flight_number: str, requested_date: str) -> Dict[str, Any]:
        departure = record.get("departure") or {}
        arrival = record.get("arrival") or {}
        airline = record.get("airline") or {}
        flight = record.get("flight") or {}

        return {
            "flight": flight.get("iata") or flight.get("icao") or requested_flight_number.upper().replace(" ", ""),
            "date": record.get("flight_date") or requested_date,
            "scheduled_departure": departure.get("scheduled"),
            "actual_departure": departure.get("actual"),
            "scheduled_arrival": arrival.get("scheduled"),
            "actual_arrival": arrival.get("actual"),
            "delay_minutes": FlightToolkit._compute_delay_minutes(departure, arrival),
            "departure_airport": departure.get("iata") or departure.get("icao") or departure.get("airport") or "Unknown",
            "arrival_airport": arrival.get("iata") or arrival.get("icao") or arrival.get("airport") or "Unknown",
            "airport_code": arrival.get("iata") or arrival.get("icao") or "Unknown",
            "airline": airline.get("name") or "Unknown airline",
            "status": record.get("flight_status") or "unknown",
            "data_source": "aviationstack",
        }

    @staticmethod
    def _score_match(record: Dict[str, Any], requested_flight_number: str, requested_date: str) -> int:
        flight = record.get("flight") or {}
        departure = record.get("departure") or {}
        arrival = record.get("arrival") or {}
        normalized = requested_flight_number.upper().replace(" ", "")
        prefix, digits = FlightToolkit._extract_code_parts(normalized)

        score = 0
        if (flight.get("iata") or "").upper() == normalized:
            score += 100
        if (flight.get("icao") or "").upper() == normalized:
            score += 100
        if digits and str(flight.get("number") or "") == digits:
            score += 35

        airline = record.get("airline") or {}
        if len(prefix) == 2 and (airline.get("iata") or "").upper() == prefix:
            score += 25
        if len(prefix) == 3 and (airline.get("icao") or "").upper() == prefix:
            score += 25

        if record.get("flight_date") == requested_date:
            score += 20

        if departure.get("actual") or arrival.get("actual"):
            score += 5

        return score

    @staticmethod
    def _fetch_aviationstack_flight(flight_number: str, date: str) -> Dict[str, Any]:
        access_key = os.getenv("AVIATIONSTACK_API_KEY")
        if not access_key:
            raise RuntimeError("AVIATIONSTACK_API_KEY is not configured.")

        normalized = flight_number.upper().replace(" ", "")
        prefix, digits = FlightToolkit._extract_code_parts(normalized)
        params: Dict[str, Any] = {
            "access_key": access_key,
            "flight_date": date,
            "limit": 10,
        }

        if len(prefix) == 2 and digits:
            params["flight_iata"] = f"{prefix}{digits}"
        elif len(prefix) == 3 and digits:
            params["flight_icao"] = f"{prefix}{digits}"
        elif digits:
            params["flight_number"] = digits
        else:
            params["flight_iata"] = normalized

        with httpx.Client(timeout=15.0) as client:
            response = client.get(FlightToolkit.AVIATIONSTACK_BASE_URL, params=params)
            response.raise_for_status()
            payload = response.json()

        if payload.get("error"):
            error_info = payload["error"]
            raise RuntimeError(error_info.get("message") or "aviationstack request failed")

        results = payload.get("results") or payload.get("data") or []
        if not results:
            raise RuntimeError(f"No live flight data found for {flight_number} on {date}.")

        best = max(results, key=lambda record: FlightToolkit._score_match(record, normalized, date))
        return FlightToolkit._normalize_aviationstack_flight(best, normalized, date)

    @staticmethod
    def _extract_nested_code(value: Any) -> Any:
        if isinstance(value, dict):
            return (
                value.get("iata")
                or value.get("icao")
                or value.get("code")
                or value.get("shortName")
                or value.get("name")
            )
        return value

    @staticmethod
    def _normalize_aerodatabox_flight(record: Dict[str, Any], requested_flight_number: str, requested_date: str) -> Dict[str, Any]:
        departure = record.get("departure") or {}
        arrival = record.get("arrival") or {}
        airline = record.get("airline") or {}
        local_flight = record.get("number") or requested_flight_number.upper().replace(" ", "")

        scheduled_departure_local = (departure.get("scheduledTime") or {}).get("local") if isinstance(departure.get("scheduledTime"), dict) else departure.get("scheduledTime")
        revised_departure_local = (departure.get("revisedTime") or {}).get("local") if isinstance(departure.get("revisedTime"), dict) else departure.get("revisedTime")
        runway_departure_local = (departure.get("runwayTime") or {}).get("local") if isinstance(departure.get("runwayTime"), dict) else departure.get("runwayTime")
        scheduled_arrival_local = (arrival.get("scheduledTime") or {}).get("local") if isinstance(arrival.get("scheduledTime"), dict) else arrival.get("scheduledTime")
        revised_arrival_local = (arrival.get("revisedTime") or {}).get("local") if isinstance(arrival.get("revisedTime"), dict) else arrival.get("revisedTime")
        runway_arrival_local = (arrival.get("runwayTime") or {}).get("local") if isinstance(arrival.get("runwayTime"), dict) else arrival.get("runwayTime")

        delay_minutes = 0
        if scheduled_arrival_local and revised_arrival_local:
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_arrival_local.replace("Z", "+00:00"))
                revised_dt = datetime.fromisoformat(revised_arrival_local.replace("Z", "+00:00"))
                delay_minutes = max(int((revised_dt - scheduled_dt).total_seconds() / 60), 0)
            except ValueError:
                delay_minutes = 0

        return {
            "flight": local_flight,
            "date": requested_date,
            "scheduled_departure": scheduled_departure_local,
            "actual_departure": revised_departure_local or runway_departure_local,
            "scheduled_arrival": scheduled_arrival_local,
            "actual_arrival": revised_arrival_local or runway_arrival_local,
            "delay_minutes": delay_minutes,
            "departure_airport": FlightToolkit._extract_nested_code(departure.get("airport")) or "Unknown",
            "arrival_airport": FlightToolkit._extract_nested_code(arrival.get("airport")) or "Unknown",
            "airport_code": FlightToolkit._extract_nested_code(arrival.get("airport")) or "Unknown",
            "airline": airline.get("name") or "Unknown airline",
            "status": record.get("status") or "unknown",
            "data_source": "aerodatabox",
        }

    @staticmethod
    def _fetch_aerodatabox_flight(flight_number: str, date: str) -> Dict[str, Any]:
        api_market_key = os.getenv("AERODATABOX_APIMARKET_KEY")
        rapidapi_key = os.getenv("AERODATABOX_RAPIDAPI_KEY")
        if not api_market_key and not rapidapi_key:
            raise RuntimeError("AERODATABOX_APIMARKET_KEY or AERODATABOX_RAPIDAPI_KEY is not configured.")

        normalized = flight_number.upper().replace(" ", "")
        if api_market_key:
            url = f"{FlightToolkit.AERODATABOX_APIMARKET_BASE_URL}/flights/Number/{normalized}/{date}"
            headers = {
                "x-magicapi-key": api_market_key,
            }
        else:
            url = f"{FlightToolkit.AERODATABOX_RAPIDAPI_BASE_URL}/flights/Number/{normalized}/{date}"
            headers = {
                "X-RapidAPI-Key": rapidapi_key,
                "X-RapidAPI-Host": os.getenv("AERODATABOX_RAPIDAPI_HOST", "aerodatabox.p.rapidapi.com"),
            }
        params = {
            "dateLocalRole": "Departure",
        }

        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            try:
                payload = response.json()
            except JSONDecodeError as exc:
                raise RuntimeError(
                    "The live flight verification service returned an unreadable response. Please try again in a moment."
                ) from exc

        results = payload if isinstance(payload, list) else payload.get("data") or payload.get("items") or []
        if not results:
            raise RuntimeError(f"No AeroDataBox flight data found for {flight_number} on {date}.")

        record = results[0]
        return FlightToolkit._normalize_aerodatabox_flight(record, normalized, date)

    @staticmethod
    def _mock_flight_record(flight_number: str, date: str) -> Dict[str, Any]:
        normalized = flight_number.upper().replace(" ", "")

        if normalized in {"WS714", "WJA714"}:
            return {
                "flight": normalized,
                "date": date,
                "scheduled_departure": "08:00 PST",
                "actual_departure": "08:55 PST",
                "scheduled_arrival": "15:35 EST",
                "actual_arrival": "16:20 EST",
                "delay_minutes": 45,
                "departure_airport": "YVR",
                "arrival_airport": "YYZ",
                "airport_code": "YYZ",
                "airline": "WestJet",
                "status": "landed",
            }

        if normalized.startswith("BA"):
            return {
                "flight": normalized,
                "date": date,
                "scheduled_departure": "12:10 UTC",
                "actual_departure": "12:42 UTC",
                "scheduled_arrival": "14:30 UTC",
                "actual_arrival": "18:45 UTC",
                "delay_minutes": 255,
                "departure_airport": "BCN",
                "arrival_airport": "LHR",
                "airport_code": "LHR",
                "airline": "British Airways",
                "status": "landed",
            }

        return {
            "flight": normalized,
            "date": date,
            "scheduled_departure": "10:00 UTC",
            "actual_departure": "10:20 UTC",
            "scheduled_arrival": "14:30 UTC",
            "actual_arrival": "18:45 UTC",
            "delay_minutes": 255,
            "departure_airport": "Unknown",
            "arrival_airport": "LHR",
            "airport_code": "LHR",
            "airline": "Unknown airline",
            "status": "landed",
        }
    
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
        if os.getenv("AERODATABOX_APIMARKET_KEY") or os.getenv("AERODATABOX_RAPIDAPI_KEY"):
            try:
                live_data = FlightToolkit._fetch_aerodatabox_flight(flight_number, date)
                return json.dumps(live_data)
            except Exception as exc:
                return json.dumps(
                    FlightToolkit._provider_error_payload(
                        flight_number,
                        date,
                        "aerodatabox",
                        str(exc),
                    )
                )

        if os.getenv("AVIATIONSTACK_API_KEY"):
            try:
                live_data = FlightToolkit._fetch_aviationstack_flight(flight_number, date)
                return json.dumps(live_data)
            except Exception as exc:
                return json.dumps(
                    FlightToolkit._provider_error_payload(
                        flight_number,
                        date,
                        "aviationstack",
                        str(exc),
                    )
                )

        mock_data = FlightToolkit._mock_flight_record(flight_number, date)
        mock_data["data_source"] = "mock"
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
