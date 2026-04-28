"""
LangChain-based Claim Analysis Agent
Core AI reasoning engine for the Bureaucracy Hacker system.
"""
import os
import logging
import time
from dotenv import load_dotenv
from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from typing import Optional, Dict, Any
import json
import re
from tools.claim_tools import get_all_tools, FlightToolkit
from models.schemas import ClaimResponse

# Load environment variables
load_dotenv()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an expert aviation compensation specialist and legal analyst. Your role is to 
autonomously analyze flight delay and cancellation claims to determine compensation eligibility.

Your responsibility:
1. Verify the flight delay details using available flight data APIs
2. Check historical weather to validate airline's stated reason
3. Determine if circumstances are "extraordinary" (exemptions)
4. Cross-reference applicable aviation regulations (EU261, DOT, etc.)
5. Calculate the correct compensation amount
6. Generate a professional, legally-sound compensation claim letter

YOU MUST:
- Be thorough and verify all information
- Always cite specific regulations with article numbers
- Consider the jurisdiction (EU uses EU261, US has no mandatory compensation)
- Provide clear reasoning for your decision
- Generate actionable next steps

RESPOND IN JSON FORMAT:
{
    "eligible": true/false,
    "compensation_eur": number,
    "regulation_reference": "EU261 Article 7",
    "regulation_text": "relevant excerpt",
    "claim_letter": "generated letter or empty if not eligible",
    "reasoning": "detailed explanation",
    "next_steps": ["list", "of", "actions"],
    "confidence": 0.95
}
"""


class ClaimAnalysisAgent:
    """
    Autonomous agent that analyzes flight compensation claims
    using Gemini + LangChain + domain-specific tools.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the agent with Google Gemini and tools"""
        
        if api_key is None:
            api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found. Please set it in .env file or as environment variable.")

        model_name = os.getenv("GEMINI_MODEL", os.getenv("GOOGLE_MODEL", "gemini-2.5-pro"))

        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            max_output_tokens=2048,
            google_api_key=api_key,
        )
        
        self.tools = get_all_tools()
        self.agent = None
    
    def _create_agent(self):
        """Create the agent executor with tools"""
        if self.agent is None:
            logger.info("[Agent] Building LangGraph ReAct agent with %d tools", len(self.tools))
            self.agent = create_react_agent(
                self.llm,
                self.tools
            )
        return self.agent

    @staticmethod
    def _stringify_content(content: Any) -> str:
        """Normalize provider-specific message content into plain text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text"):
                        parts.append(str(item["text"]))
                    elif item.get("content"):
                        parts.append(str(item["content"]))
            return "\n".join(part for part in parts if part).strip()
        return str(content or "")

    def _verify_flight(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch and normalize flight verification data."""
        flight_data = {}
        try:
            flight_raw = FlightToolkit.check_flight_status.invoke({
                "flight_number": claim_data["flight_number"],
                "date": claim_data["flight_date"],
            })
            flight_data = json.loads(flight_raw) if isinstance(flight_raw, str) else flight_raw
            if flight_data.get("lookup_status") == "error":
                logger.warning(
                    "[Claim %s on %s] Flight provider unavailable: %s",
                    claim_data["flight_number"],
                    claim_data["flight_date"],
                    flight_data.get("error"),
                )
                return flight_data
            logger.info(
                "[Claim %s on %s] Verified flight status: delay=%s minutes, airport=%s",
                claim_data["flight_number"],
                claim_data["flight_date"],
                flight_data.get("delay_minutes"),
                flight_data.get("airport_code"),
            )
        except Exception:
            logger.exception(
                "[Claim %s on %s] Flight verification failed",
                claim_data["flight_number"],
                claim_data["flight_date"],
            )

        return flight_data or {}

    def _check_weather(self, claim_data: Dict[str, Any], verified_flight: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch weather evidence only after flight is confirmed EU-covered."""
        weather_data = {}
        if not verified_flight.get("airport_code"):
            return weather_data

        try:
            weather_raw = FlightToolkit.check_weather_history.invoke({
                "airport_code": verified_flight["airport_code"],
                "date": claim_data["flight_date"],
                "time": verified_flight.get("scheduled_arrival", "00:00 UTC"),
            })
            weather_data = json.loads(weather_raw) if isinstance(weather_raw, str) else weather_raw
            logger.info(
                "[Claim %s on %s] Weather check: %s | severe=%s",
                claim_data["flight_number"],
                claim_data["flight_date"],
                weather_data.get("weather_summary"),
                weather_data.get("severe_weather"),
            )
        except Exception:
            logger.exception(
                "[Claim %s on %s] Weather verification failed",
                claim_data["flight_number"],
                claim_data["flight_date"],
            )

        return weather_data or {}

    @staticmethod
    def _build_verification_summary(verified_flight: Dict[str, Any], weather_evidence: Dict[str, Any], eu_coverage: Dict[str, Any]) -> str:
        verification_summary = "No external verification data available."
        if verified_flight:
            verified_delay = verified_flight.get("delay_minutes", 0)
            airport = verified_flight.get("airport_code", "unknown airport")
            departure_airport = verified_flight.get("departure_airport", "unknown departure")
            arrival_airport = verified_flight.get("arrival_airport", airport)
            coverage_label = "covered by EU261" if eu_coverage.get("covered") else f"not covered by EU261 ({eu_coverage.get('country_or_region', 'Unknown region')})"
            weather_summary = weather_evidence.get("weather_summary", "weather not checked")
            verification_summary = (
                f"Verified route: {departure_airport} to {arrival_airport}. "
                f"Coverage check: {coverage_label}. "
                f"Verified delay from flight data: {verified_delay} minutes at {airport}. "
                f"Weather evidence: {weather_summary}."
            )

        return verification_summary

    @staticmethod
    def _airport_country_or_region(airport_code: str) -> str:
        mapping = {
            "YVR": "Canada",
            "YYZ": "Canada",
            "JFK": "United States",
            "LAX": "United States",
            "ORD": "United States",
            "LHR": "United Kingdom",
            "LGW": "United Kingdom",
            "BCN": "Spain",
            "MAD": "Spain",
            "CDG": "France",
            "ORY": "France",
            "AMS": "Netherlands",
            "FCO": "Italy",
            "DUB": "Ireland",
            "FRA": "Germany",
            "MUC": "Germany",
            "BRU": "Belgium",
            "VIE": "Austria",
            "LIS": "Portugal",
            "CPH": "Denmark",
            "ARN": "Sweden",
            "OSL": "Norway",
            "HEL": "Finland",
            "ZRH": "Switzerland",
            "GVA": "Switzerland",
        }
        return mapping.get((airport_code or "").upper(), "another country/region")

    @staticmethod
    def _is_eu261_covered(claim_data: Dict[str, Any], verified_flight: Dict[str, Any]) -> bool:
        eu_airports = {
            "LHR", "LGW", "BCN", "MAD", "CDG", "ORY", "AMS", "FCO", "DUB", "FRA", "MUC",
            "BRU", "VIE", "LIS", "CPH", "ARN", "OSL", "HEL", "ZRH", "GVA",
        }
        eu_carriers = {
            "British Airways", "Lufthansa", "Air France", "KLM", "Iberia", "Ryanair",
            "easyJet", "Swiss", "Austrian Airlines", "TAP Air Portugal",
        }

        departure = verified_flight.get("departure_airport")
        arrival = verified_flight.get("arrival_airport")
        airline = verified_flight.get("airline")

        if departure in eu_airports:
            return True
        if arrival in eu_airports and airline in eu_carriers:
            return True

        return claim_data.get("jurisdiction") in {"EU", "UK"}

    def _assess_eu_coverage(self, claim_data: Dict[str, Any], verified_flight: Dict[str, Any]) -> Dict[str, Any]:
        departure = verified_flight.get("departure_airport")
        arrival = verified_flight.get("arrival_airport")
        airline = verified_flight.get("airline")
        covered = self._is_eu261_covered(claim_data, verified_flight)
        non_eu_country = self._airport_country_or_region(departure or arrival or "")

        if covered:
            reason = (
                f"The flight is EU/UK-covered because it either departs an EU/UK airport or arrives there on an EU/UK carrier."
            )
            country_or_region = "EU/UK"
        else:
            reason = (
                f"The flight appears to be operated by {airline or 'a non-EU carrier'} on a route from "
                f"{departure or 'Unknown'} to {arrival or 'Unknown'}, which is treated as outside EU261 coverage."
            )
            country_or_region = non_eu_country

        return {
            "covered": covered,
            "country_or_region": country_or_region,
            "reason": reason,
        }

    @staticmethod
    def _normalize_analysis_output(
        analysis: Dict[str, Any],
        claim_data: Dict[str, Any],
        verified_flight: Dict[str, Any],
        eu_coverage: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Polish model output so user-facing results stay clear and product-appropriate."""
        if analysis.get("eligible"):
            return analysis

        verified_delay = verified_flight.get("delay_minutes")
        flight_number = claim_data.get("flight_number", "the flight")
        flight_date = claim_data.get("flight_date", "the scheduled date")

        if eu_coverage and eu_coverage.get("covered") is False:
            analysis["regulation_reference"] = "Not covered by EU261"
            analysis["reasoning"] = (
                f"I checked {flight_number} on {flight_date}. Based on the verified route and airline, "
                "this trip does not appear to fall within EU261 coverage."
            )
            analysis["next_steps"] = [
                f"This looks like a {eu_coverage.get('country_or_region', 'non-EU')} route, so EU261 is not the right claim path here.",
                "Keep any airline emails, receipts, or disruption notices in case another jurisdiction applies.",
            ]
            return analysis

        if isinstance(verified_delay, int) and verified_delay < 180:
            analysis["regulation_reference"] = "EU261 delay threshold"
            analysis["reasoning"] = (
                f"I checked the available flight data for {flight_number} on {flight_date}. "
                "Based on the records currently available, I could not confirm an arrival delay of 3 hours or more at the final destination."
            )
            analysis["next_steps"] = [
                "If you have stronger evidence of the final arrival delay, share it and I can review the claim again.",
                "Useful evidence includes airline messages, rebooking notices, or a photo of the arrivals board.",
            ]
            return analysis

        analysis["reasoning"] = (
            f"I checked the available flight data for {flight_number} on {flight_date}. "
            "Based on the information I could verify, I cannot currently support an EU261 compensation claim."
        )
        analysis["next_steps"] = [
            "Review the flight details and route once more to make sure they are correct.",
            "If you have airline communications or other evidence, share them and I can reassess the claim.",
        ]
        return analysis

    @staticmethod
    def _build_claim_letter(
        analysis: Dict[str, Any],
        claim_data: Dict[str, Any],
        verified_flight: Dict[str, Any],
    ) -> str:
        """Generate a deterministic draft letter from structured claim data."""
        passenger_name = claim_data.get("passenger_name") or "[Passenger Name]"
        passenger_email = claim_data.get("passenger_email") or "[Passenger Email]"
        passenger_age = claim_data.get("passenger_age") or "[Passenger Age]"
        passenger_sex = claim_data.get("passenger_sex") or "[Passenger Sex]"
        flight_number = claim_data.get("flight_number", "Unknown")
        flight_date = claim_data.get("flight_date", "Unknown")
        airline = verified_flight.get("airline", "the operating airline")
        departure_airport = verified_flight.get("departure_airport", "Unknown")
        arrival_airport = verified_flight.get("arrival_airport", "Unknown")
        compensation = analysis.get("compensation_eur", 0)
        delay_reason = claim_data.get("delay_reason", "Flight disruption")
        delay_minutes = claim_data.get("delay_minutes", 0)

        delay_summary = f"Arrival delay of approximately {delay_minutes} minutes"
        if "cancel" in delay_reason.lower() and "no replacement" in delay_reason.lower():
            delay_summary = "Flight cancellation with no replacement flight provided"
        elif "cancel" in delay_reason.lower():
            delay_summary = f"Flight cancellation resulting in an arrival disruption of approximately {delay_minutes} minutes"

        return f"""Dear {airline} Customer Relations,

I am writing to request compensation under EU261 for the disruption to flight {flight_number} on {flight_date}.

Passenger details:
- Full name: {passenger_name}
- Age: {passenger_age}
- Sex: {passenger_sex}
- Contact email: {passenger_email}

Flight details:
- Flight number: {flight_number}
- Date: {flight_date}
- Route: {departure_airport} -> {arrival_airport}
- Disruption: {delay_reason}
- Verified outcome: {delay_summary}

Based on the current analysis, this claim appears eligible for compensation of EUR {compensation} under {analysis.get("regulation_reference", "EU261")}.

Please review this claim and arrange compensation at your earliest convenience. I can provide booking confirmation, tickets, and disruption notices on request.

Sincerely,
{passenger_name}""".strip()
    
    async def analyze_claim(self, claim_data: Dict[str, Any]) -> ClaimResponse:
        """
        Main entry point: analyze a flight compensation claim
        
        Args:
            claim_data: {
                "flight_number": "BA123",
                "flight_date": "2024-01-15",
                "delay_reason": "Technical issues",
                "delay_minutes": 300,
                "jurisdiction": "EU"
            }
        
        Returns:
            ClaimResponse with analysis results
        """
        
        request_label = f"{claim_data['flight_number']} on {claim_data['flight_date']}"
        started_at = time.perf_counter()

        logger.info("[Claim %s] Step 1/5: Preparing agent", request_label)
        agent = self._create_agent()
        workflow_steps = []

        logger.info("[Claim %s] Step 2/5: Checking flight using provider", request_label)
        verified_flight = self._verify_flight(claim_data)
        workflow_steps.append({
            "step": "flight_lookup",
            "status": "failed" if verified_flight.get("lookup_status") == "error" else ("completed" if verified_flight else "failed"),
            "message": verified_flight.get("error") if verified_flight.get("lookup_status") == "error" else ("Fetched flight details from configured provider." if verified_flight else "Unable to fetch flight details from provider."),
        })

        if verified_flight.get("lookup_status") == "error":
            workflow_steps.append({
                "step": "eu_coverage_check",
                "status": "skipped",
                "message": "Skipped EU coverage check because live flight lookup failed.",
            })
            workflow_steps.append({
                "step": "weather_check",
                "status": "skipped",
                "message": "Skipped weather check because live flight lookup failed.",
            })
            workflow_steps.append({
                "step": "gemini_analysis",
                "status": "skipped",
                "message": "Skipped Gemini because live flight verification failed.",
            })
            workflow_steps.append({
                "step": "final_decision",
                "status": "failed",
                "message": verified_flight.get("error", "Live flight lookup failed."),
            })
            return ClaimResponse(
                eligible=False,
                compensation_eur=0,
                regulation_reference="Live flight provider unavailable",
                regulation_text="The app could not verify the flight because the configured live flight provider is currently unavailable.",
                claim_letter="",
                reasoning=f"Live flight verification failed: {verified_flight.get('error', 'Unknown provider error')}",
                next_steps=[
                    "Activate or fix the live flight provider subscription and try again.",
                    "If you already know the route and delay details, use the manual claim flow temporarily.",
                ],
                confidence=0.0,
                verified_flight=verified_flight,
                weather_evidence=None,
                verification_summary="Live flight verification failed before EU coverage and weather checks could run.",
                eu_coverage=None,
                workflow_steps=workflow_steps,
            )

        logger.info("[Claim %s] Step 3/5: Validating EU coverage", request_label)
        eu_coverage = self._assess_eu_coverage(claim_data, verified_flight) if verified_flight else {
            "covered": False,
            "country_or_region": "Unknown",
            "reason": "EU coverage could not be validated because flight details were unavailable.",
        }
        workflow_steps.append({
            "step": "eu_coverage_check",
            "status": "completed" if verified_flight else "failed",
            "message": eu_coverage["reason"],
        })

        weather_evidence = {}
        if eu_coverage.get("covered"):
            logger.info("[Claim %s] Step 4/5: Checking weather", request_label)
            weather_evidence = self._check_weather(claim_data, verified_flight)
            workflow_steps.append({
                "step": "weather_check",
                "status": "completed" if weather_evidence else "skipped",
                "message": "Fetched weather evidence for the arrival airport." if weather_evidence else "No weather evidence available.",
            })
        else:
            workflow_steps.append({
                "step": "weather_check",
                "status": "skipped",
                "message": "Skipped weather check because the flight is not EU-covered.",
            })

        verification_summary = self._build_verification_summary(verified_flight, weather_evidence, eu_coverage)
        verified_delay = verified_flight.get("delay_minutes", claim_data["delay_minutes"])

        if verified_flight and not eu_coverage.get("covered"):
            reasoning = (
                f"{claim_data['flight_number']} appears to be a flight from {eu_coverage.get('country_or_region', 'another country/region')}. "
                "It is not covered by EU261 yet."
            )
            workflow_steps.append({
                "step": "gemini_analysis",
                "status": "skipped",
                "message": "Skipped Gemini because the flight is not EU-covered.",
            })
            workflow_steps.append({
                "step": "final_decision",
                "status": "completed",
                "message": reasoning,
            })
            return ClaimResponse(
                eligible=False,
                compensation_eur=0,
                regulation_reference="Not covered by EU261",
                regulation_text="EU261 generally applies to flights departing the EU/UK or arriving there on EU/UK carriers. This flight appears to belong to another country/region.",
                claim_letter="",
                reasoning=reasoning,
                next_steps=[
                    f"This appears to be a {eu_coverage.get('country_or_region', 'non-EU')} flight and we are working on support for those rules.",
                    "If you have receipts or disruption notices, keep them for any airline complaint.",
                ],
                confidence=0.95,
                verified_flight=verified_flight or None,
                weather_evidence=weather_evidence or None,
                verification_summary=verification_summary,
                eu_coverage=eu_coverage,
                workflow_steps=workflow_steps,
            )
        
        # made changes to Reported delay in Flight Information
        user_message = f"""
Please analyze this flight compensation claim:

FLIGHT INFORMATION:
- Flight Number: {claim_data['flight_number']}
- Flight Date: {claim_data['flight_date']}
- Reported Delay: {claim_data['delay_minutes']} minutes ({round(claim_data['delay_minutes']/60, 1)} hours)
- Verified Delay From Flight Data: {verified_delay} minutes
- Airline's Stated Reason: {claim_data['delay_reason']}
- Passenger Location: {claim_data.get('jurisdiction', 'EU')}

VERIFICATION EVIDENCE:
- Flight status data: {json.dumps(verified_flight) if verified_flight else "Unavailable"}
- Weather data: {json.dumps(weather_evidence) if weather_evidence else "Unavailable"}
- Verification summary: {verification_summary}

Please:
1. Verify the flight and delay using available data
2. Check if weather actually occurred (to verify airline's claim)
3. Determine if this qualifies as "extraordinary circumstances"
4. Find the applicable regulation for {claim_data.get('jurisdiction', 'EU')}
5. Calculate the compensation amount
6. If eligible, generate a professional claim letter
7. Provide your decision in the specified JSON format

Return ONLY valid JSON with no additional text.
"""
        
        try:
            logger.info("[Claim %s] Step 5/5: Sending analysis request to Gemini", request_label)
            result = agent.invoke({
                "messages": [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=user_message)
                ]
            })
            logger.info("[Claim %s] Gemini response received", request_label)
            
            response_text = ""
            if result.get('messages'):
                last_message = result['messages'][-1]
                content = last_message.get('content', '') if hasattr(last_message, 'get') else getattr(last_message, "content", last_message)
                response_text = self._stringify_content(content)
            
            logger.info("[Claim %s] Parsing model output", request_label)
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            
            if json_match:
                try:
                    analysis = json.loads(json_match.group())
                except json.JSONDecodeError:
                    logger.warning("[Claim %s] Model returned invalid JSON, using fallback analysis", request_label)
                    analysis = self._fallback_analysis(claim_data)
            else:
                logger.warning("[Claim %s] No JSON found in model output, using fallback analysis", request_label)
                analysis = self._fallback_analysis(claim_data)

            analysis = self._normalize_analysis_output(
                analysis=analysis,
                claim_data=claim_data,
                verified_flight=verified_flight,
                eu_coverage=eu_coverage,
            )
            if analysis.get("eligible"):
                analysis["claim_letter"] = self._build_claim_letter(
                    analysis=analysis,
                    claim_data=claim_data,
                    verified_flight=verified_flight,
                )
            
            workflow_steps.append({
                "step": "gemini_analysis",
                "status": "completed",
                "message": "Gemini returned an analysis result.",
            })
            response = ClaimResponse(
                eligible=analysis.get('eligible', False),
                compensation_eur=analysis.get('compensation_eur', 0),
                regulation_reference=analysis.get('regulation_reference', 'EU261'),
                regulation_text=analysis.get('regulation_text', ''),
                claim_letter=analysis.get('claim_letter', ''),
                reasoning=analysis.get('reasoning', ''),
                next_steps=analysis.get('next_steps', []),
                confidence=analysis.get('confidence', 0.5),
                verified_flight=verified_flight or analysis.get('verified_flight'),
                weather_evidence=weather_evidence or analysis.get('weather_evidence'),
                verification_summary=analysis.get('verification_summary', verification_summary),
                eu_coverage=eu_coverage,
                workflow_steps=workflow_steps + [{
                    "step": "final_decision",
                    "status": "completed",
                    "message": analysis.get('reasoning', 'Decision completed.'),
                }],
            )
            elapsed = time.perf_counter() - started_at
            logger.info(
                "[Claim %s] Completed in %.2fs | eligible=%s | amount=EUR %s",
                request_label,
                elapsed,
                response.eligible,
                response.compensation_eur
            )
            return response
        
        except Exception as e:
            elapsed = time.perf_counter() - started_at
            logger.exception("[Claim %s] Analysis failed after %.2fs", request_label, elapsed)
            return ClaimResponse(
                eligible=False,
                compensation_eur=0,
                regulation_reference="Error",
                regulation_text="",
                claim_letter="",
                reasoning=f"Agent encountered an error: {str(e)}",
                next_steps=["Please try again or contact support"],
                confidence=0.0,
                verified_flight=verified_flight or None,
                weather_evidence=weather_evidence or None,
                verification_summary=verification_summary,
                eu_coverage=eu_coverage,
                workflow_steps=workflow_steps + [{
                    "step": "final_decision",
                    "status": "failed",
                    "message": f"Analysis failed: {str(e)}",
                }],
            )
    
    def _fallback_analysis(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback analysis when agent doesn't return valid JSON"""
        delay_minutes = claim_data.get('delay_minutes', 0)
        delay_reason = claim_data.get('delay_reason', '').lower()
        
        is_weather = 'weather' in delay_reason or 'storm' in delay_reason or 'snow' in delay_reason
        is_security = 'security' in delay_reason or 'threat' in delay_reason
        is_eligible = delay_minutes >= 180 and not (is_weather or is_security)
        
        flight_date = claim_data.get('flight_date', '')
        compensation = 0
        if is_eligible:
            compensation = 250
        
        return {
            "eligible": is_eligible,
            "compensation_eur": compensation,
            "regulation_reference": "EU261 Article 7",
            "regulation_text": "Passengers of flights with a delay of three hours or more are entitled to compensation",
            "claim_letter": f"Dear Airline,\n\nI am writing to claim compensation for flight {claim_data['flight_number']} delayed {delay_minutes} minutes on {flight_date}.\n\nRespectfully,\nPassenger" if is_eligible else "",
            "reasoning": f"Delay of {delay_minutes} minutes {'is' if is_eligible else 'is not'} eligible for compensation under EU261",
            "next_steps": ["Send claim letter to airline", "Wait for response"] if is_eligible else ["Contact airline for appeal"],
            "confidence": 0.75,
            "verified_flight": None,
            "weather_evidence": None,
            "verification_summary": "Fallback analysis used reported claim details because verification data was unavailable.",
            "eu_coverage": None,
            "workflow_steps": None,
        }


# Global agent instance (can be reused)
_agent_instance = None

def get_agent() -> ClaimAnalysisAgent:
    """Get or create singleton agent instance"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ClaimAnalysisAgent()
    return _agent_instance
