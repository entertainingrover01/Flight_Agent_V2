"""
Conversational claim analysis agent for multi-turn chat interactions.
"""
import os
import json
import logging
import asyncio
import concurrent.futures
import re
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from tools.claim_tools import FlightToolkit

load_dotenv()
logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = """You are FlightClaim AI, a warm and knowledgeable flight compensation assistant.
You help air passengers understand their rights and check eligibility for compensation under EU Regulation 261/2004.

CONVERSATION FLOW:
1. Warmly greet the user and invite them to describe their flight issue.
2. Through natural conversation, gather these key details:
   - Flight number (e.g., BA123, LH456, FR1234, EZY8765)
   - Flight date (when the flight was scheduled to depart)
   - What happened (delay, cancellation, denied boarding, missed connection)
   - How long the delay was at the final destination (in minutes or hours)
3. Once you have all the information, call the analyze_flight_claim tool.
4. After getting the analysis, explain the result clearly and helpfully.
5. Answer any follow-up questions about regulations, the claims process, or their situation.

IMPORTANT GUIDELINES:
- Be conversational, empathetic, and supportive — disrupted travel is stressful.
- If the user gives you all the info upfront, analyze right away without asking more questions.
- You can estimate delay_minutes from natural language (e.g. "4 hour delay" = 240 minutes).
- Convert natural language dates to YYYY-MM-DD format for the tool (e.g. "last Tuesday" or "March 12th").
- When results show eligibility, be encouraging and explain next steps clearly.
- Keep responses concise and easy to read — avoid long walls of text.

KEY EU261 FACTS (use when answering questions):
- Applies to: ALL flights departing EU airports; AND flights arriving at EU airports on EU-based carriers.
- Compensation threshold: 3+ hour delay at the final destination.
- Compensation amounts by flight distance:
  * Up to 1,500 km → €250
  * 1,500–3,500 km → €400
  * Over 3,500 km → €600
- Exemptions ("extraordinary circumstances"): severe weather, security threats, air traffic control strikes.
- Technical issues with the aircraft are NOT an extraordinary circumstance under EU261.
- Passengers must claim within 6 years (UK) or 2–5 years depending on EU member state."""


def _run_claim_analysis_in_thread(claim_data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the async claim analysis in a separate thread with its own event loop."""
    from agents.claim_agent import get_agent

    def _in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(get_agent().analyze_claim(claim_data))
            return result.model_dump()
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_in_thread).result()


@tool
def analyze_flight_claim(
    flight_number: str,
    flight_date: str,
    delay_reason: str,
    delay_minutes: int,
    passenger_name: str = "",
    passenger_age: str = "",
    passenger_sex: str = "",
    passenger_email: str = "",
) -> str:
    """
    Analyze whether a flight qualifies for EU261 compensation. Call this once you have gathered
    the flight number, date, reason for disruption, and approximate delay duration.

    Args:
        flight_number: The flight number (e.g., BA123, LH456).
        flight_date: The flight date in YYYY-MM-DD format.
        delay_reason: Description of what happened and the stated reason for the disruption.
        delay_minutes: Estimated delay at the final destination in minutes.

    Returns:
        JSON string with eligibility verdict, compensation amount, regulation reference,
        reasoning, next steps, and a claim letter draft if eligible.
    """
    claim_data = {
        "flight_number": flight_number,
        "flight_date": flight_date,
        "delay_reason": delay_reason,
        "delay_minutes": delay_minutes,
        "jurisdiction": "EU",
        "passenger_name": passenger_name,
        "passenger_age": passenger_age,
        "passenger_sex": passenger_sex,
        "passenger_email": passenger_email,
    }
    try:
        result = _run_claim_analysis_in_thread(claim_data)
        return json.dumps(result)
    except Exception as e:
        logger.exception("analyze_flight_claim tool error")
        return json.dumps({
            "eligible": False,
            "error": str(e),
            "reasoning": f"Analysis failed: {str(e)}",
            "regulation_reference": "Error",
        })


class ConversationalClaimAgent:
    """Multi-turn conversational agent for EU261 claim assistance."""

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
                        continue
                    if "content" in item and item["content"]:
                        parts.append(str(item["content"]))
            return "\n".join(part for part in parts if part).strip()
        return str(content or "")

    def __init__(self, api_key: Optional[str] = None):
        if api_key is None:
            api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found.")

        model_name = os.getenv("GEMINI_MODEL", os.getenv("GOOGLE_MODEL", "gemini-2.5-pro"))
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.4,
            max_output_tokens=2048,
            google_api_key=api_key,
        )
        self.llm_with_tools = self.llm.bind_tools([analyze_flight_claim])

    @staticmethod
    def _extract_flight_number(text: str) -> Optional[str]:
        match = re.search(r"\b([A-Z]{2,3}\s?\d{2,4})\b", text.upper())
        if not match:
            return None
        return match.group(1).replace(" ", "")

    @staticmethod
    def _extract_date(text: str) -> Optional[str]:
        match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        return match.group(1) if match else None

    @staticmethod
    def _looks_like_relative_date(text: str) -> bool:
        lowered = text.lower()
        keywords = {
            "today", "todays", "today's", "yesterday", "tomorrow",
            "last night", "this morning", "this evening", "last week",
            "this week", "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday",
        }
        return any(keyword in lowered for keyword in keywords)

    @staticmethod
    def _extract_delay_minutes(text: str) -> Optional[int]:
        hour_match = re.search(r"(\d+(?:\.\d+)?)\s*(hour|hours|hr|hrs)\b", text.lower())
        if hour_match:
            return int(float(hour_match.group(1)) * 60)
        minute_match = re.search(r"(\d+)\s*(minute|minutes|min|mins)\b", text.lower())
        if minute_match:
            return int(minute_match.group(1))
        return None

    @staticmethod
    def _extract_email(text: str) -> Optional[str]:
        match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.IGNORECASE)
        return match.group(0) if match else None

    @staticmethod
    def _extract_age(text: str) -> Optional[str]:
        match = re.search(r"\bage\s*(?:is|:)?\s*(\d{1,3})\b", text, re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _extract_sex(text: str) -> Optional[str]:
        match = re.search(r"\b(male|female|man|woman|non-binary|nonbinary|other)\b", text, re.IGNORECASE)
        return match.group(1).title() if match else None

    @staticmethod
    def _extract_name(text: str) -> Optional[str]:
        match = re.search(r"\b(?:name|full name)\s*(?:is|:)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})", text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_name_from_single_value(text: str) -> Optional[str]:
        candidate = text.strip()
        lowered = candidate.lower()
        blocked_phrases = {
            "no replacement flight",
            "rebooked next day",
            "denied boarding",
            "missed connection",
            "cancelled",
            "canceled",
            "delayed",
            "delay",
            "male",
            "female",
            "other",
        }
        if lowered in blocked_phrases:
            return None
        if re.fullmatch(r"[A-Za-z]+(?:\s+[A-Za-z]+){0,1}", candidate):
            return " ".join(part.capitalize() for part in candidate.split())
        return None

    def _extract_passenger_profile(self, text: str) -> Dict[str, Any]:
        profile = {
            "passenger_name": self._extract_name(text),
            "passenger_age": self._extract_age(text),
            "passenger_sex": self._extract_sex(text),
            "passenger_email": self._extract_email(text),
        }
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if not profile["passenger_email"]:
                inferred_email = self._extract_email(line)
                if inferred_email:
                    profile["passenger_email"] = inferred_email
                    continue
            if not profile["passenger_age"] and line.isdigit():
                profile["passenger_age"] = line
                continue
            if not profile["passenger_sex"]:
                inferred_sex = self._extract_sex(line)
                if inferred_sex:
                    profile["passenger_sex"] = inferred_sex
                    continue
            if not profile["passenger_name"]:
                inferred_name = self._extract_name_from_single_value(line)
                if inferred_name:
                    profile["passenger_name"] = inferred_name
                    continue
        return profile

    def _apply_single_value_profile_hint(
        self,
        message: str,
        profile: Dict[str, Any],
        missing_fields: List[str],
    ) -> Dict[str, Any]:
        updated = dict(profile)
        stripped = message.strip()

        if "email" in missing_fields:
            email = self._extract_email(stripped)
            if email:
                updated["passenger_email"] = email

        if "age" in missing_fields and stripped.isdigit():
            updated["passenger_age"] = stripped

        if "sex" in missing_fields:
            sex = self._extract_sex(stripped)
            if sex:
                updated["passenger_sex"] = sex

        if "full name" in missing_fields:
            name = self._extract_name_from_single_value(stripped)
            if name:
                updated["passenger_name"] = name

        return updated

    @staticmethod
    def _profile_missing_fields(profile: Dict[str, Any]) -> List[str]:
        missing = []
        if not profile.get("passenger_name"):
            missing.append("full name")
        if not profile.get("passenger_age"):
            missing.append("age")
        if not profile.get("passenger_sex"):
            missing.append("sex")
        if not profile.get("passenger_email"):
            missing.append("email")
        return missing

    @staticmethod
    def _next_profile_prompt(missing_fields: List[str]) -> str:
        if not missing_fields:
            return ""
        field = missing_fields[0]
        prompts = {
            "full name": "Before I prepare the claim letter, what is the passenger's full name?",
            "age": "Thanks. What is the passenger's age?",
            "sex": "Got it. What is the passenger's sex?",
            "email": "Almost done. What email should I use in the draft claim letter?",
        }
        return prompts.get(field, "Please share the next passenger detail.")

    @staticmethod
    def _mentions_cancellation(text: str) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in {"cancelled", "canceled", "cancellation"})

    @staticmethod
    def _has_flight_and_date_context(history: List[Dict[str, str]]) -> bool:
        combined = "\n".join(msg["content"] for msg in history)
        return bool(
            ConversationalClaimAgent._extract_flight_number(combined)
            and ConversationalClaimAgent._extract_date(combined)
        )

    @staticmethod
    def _has_claim_basics(history: List[Dict[str, str]], message: str) -> bool:
        combined = "\n".join(msg["content"] for msg in history if msg["role"] == "user") + "\n" + message
        has_flight = bool(ConversationalClaimAgent._extract_flight_number(combined))
        has_date = bool(ConversationalClaimAgent._extract_date(combined))
        has_outcome = any(term in combined.lower() for term in {
            "delay", "delayed", "cancelled", "canceled", "denied boarding",
            "missed connection", "no replacement flight", "rebooked",
        })
        return has_flight and has_date and has_outcome

    @staticmethod
    def _infer_jurisdiction(text: str) -> str:
        lowered = text.lower()
        if any(term in lowered for term in {"canada", "canadian", "vancouver", "toronto", "westjet"}):
            return "CA"
        if "usa" in lowered or "us flight" in lowered or "united states" in lowered:
            return "US"
        if "uk" in lowered:
            return "UK"
        return "EU"

    def _build_confirmation_candidate(self, message: str, history: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        combined_text = "\n".join([msg["content"] for msg in history if msg["role"] == "user"] + [message])
        # Only start a new flight-match flow when the current message includes a flight number.
        flight_number = self._extract_flight_number(message)
        if not flight_number:
            return None

        flight_date = self._extract_date(message) or self._extract_date(combined_text)
        if not flight_date:
            return {
                "needs_date": True,
                "flight_number": flight_number,
            }

        reported_delay = self._extract_delay_minutes(message) or self._extract_delay_minutes(combined_text)
        jurisdiction = self._infer_jurisdiction(combined_text)

        try:
            verified_raw = FlightToolkit.check_flight_status.invoke({
                "flight_number": flight_number,
                "date": flight_date,
            })
            verified_flight = json.loads(verified_raw) if isinstance(verified_raw, str) else verified_raw
            if verified_flight.get("lookup_status") == "error":
                return {
                    "provider_error": True,
                    "flight_number": flight_number,
                    "flight_date": flight_date,
                    "error": verified_flight.get("error", "Live flight lookup failed."),
                }
        except Exception:
            logger.exception("Flight verification lookup failed for %s", flight_number)
            return None

        claim_data = {
            "flight_number": flight_number,
            "flight_date": flight_date,
            "delay_reason": "Flight disruption reported by passenger",
            "delay_minutes": reported_delay or verified_flight.get("delay_minutes", 0),
            "jurisdiction": jurisdiction,
        }

        if verified_flight.get("airline") == "WestJet":
            claim_data["jurisdiction"] = "CA"

        return {
            "verified_flight": verified_flight,
            "claim_data": claim_data,
        }

    @staticmethod
    def _is_new_flight_start(message: str) -> bool:
        return bool(ConversationalClaimAgent._extract_flight_number(message))

    @staticmethod
    def _extract_pending_confirmation(history: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        for msg in reversed(history):
            if msg["role"] != "assistant":
                continue
            if "Is this your flight?" not in msg["content"]:
                continue

            flight_match = re.search(r"Flight:\s*([A-Z0-9]+)", msg["content"])
            airline_match = re.search(r"Airline:\s*(.+)", msg["content"])
            date_match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", msg["content"])
            delay_match = re.search(r"Verified delay:\s*(\d+)", msg["content"])
            airport_match = re.search(r"Airport:\s*([A-Z0-9]+)", msg["content"])
            route_match = re.search(r"Route:\s*([A-Z]{3})\s*->\s*([A-Z]{3})", msg["content"])

            return {
                "flight_number": flight_match.group(1) if flight_match else "that flight",
                "airline": airline_match.group(1).strip() if airline_match else "the airline",
                "flight_date": date_match.group(1) if date_match else "the scheduled date",
                "delay_minutes": delay_match.group(1) if delay_match else "0",
                "airport_code": airport_match.group(1) if airport_match else "Unknown",
                "departure_airport": route_match.group(1) if route_match else "Unknown",
                "arrival_airport": route_match.group(2) if route_match else "Unknown",
            }

        return None

    @staticmethod
    def _is_affirmative(text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in {"yes", "y", "yeah", "yep", "correct", "confirmed", "that is my flight", "it's my flight", "this is my flight"}

    @staticmethod
    def _is_negative(text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in {"no", "n", "nope", "not my flight", "wrong flight", "incorrect"}

    def chat(self, message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Process a chat message with conversation history.

        Args:
            message: The user's current message.
            history: List of prior turns as {role: "user"|"assistant", content: str}.

        Returns:
            {response: str, analysis: dict | None}
        """
        if message.startswith("CONFIRM_FLIGHT::"):
            claim_data = json.loads(message.split("::", 1)[1])
            analysis = _run_claim_analysis_in_thread(claim_data)
            return {
                "response": (
                    f"I checked {claim_data['flight_number']} and ran the claim analysis. "
                    "Here is the eligibility result based on the verified flight details."
                ),
                "analysis": analysis,
                "ui_action": None,
            }

        if message.startswith("REJECT_FLIGHT::"):
            rejected = json.loads(message.split("::", 1)[1])
            return {
                "response": (
                    f"No problem. I will ignore {rejected.get('flight_number', 'that flight')}. "
                    "Send the correct flight number or add the date, and I will check the next candidate first."
                ),
                "analysis": None,
                "ui_action": None,
            }

        pending_confirmation = self._extract_pending_confirmation(history)
        if pending_confirmation and self._is_affirmative(message):
            claim_data = {
                "flight_number": pending_confirmation["flight_number"],
                "flight_date": pending_confirmation["flight_date"],
                "delay_reason": "Flight disruption reported by passenger",
                "delay_minutes": int(pending_confirmation.get("delay_minutes", "0") or 0),
                "jurisdiction": "CA" if pending_confirmation.get("airline") == "WestJet" else "EU",
            }
            analysis = _run_claim_analysis_in_thread(claim_data)
            return {
                "response": (
                    f"Perfect, I have confirmed {pending_confirmation['flight_number']} as your flight. "
                    "I ran the compensation analysis using the verified flight details."
                ),
                "analysis": analysis,
                "ui_action": None,
            }

        if pending_confirmation and self._is_negative(message):
            return {
                "response": (
                    f"Thanks for confirming that {pending_confirmation['flight_number']} is not your flight. "
                    "Send the correct flight number and I will check the next candidate."
                ),
                "analysis": None,
                "ui_action": None,
            }

        if pending_confirmation and not self._extract_flight_number(message):
            return {
                "response": (
                    f"Thanks, I noted that for {pending_confirmation['flight_number']}.\n\n"
                    f"I am still holding the verified match for {pending_confirmation['flight_number']} on "
                    f"{pending_confirmation['flight_date']} with {pending_confirmation['airline']}.\n\n"
                    "While we confirm the match, you can also share these details so I can prepare the claim faster:\n"
                    "- passenger name\n"
                    "- age\n"
                    "- country\n"
                    "- what happened to the flight for you\n\n"
                    "If this is your flight, just reply `yes` and I will run the compensation analysis."
                ),
                "analysis": None,
                "ui_action": None,
            }

        if self._looks_like_relative_date(message) and any(
            msg["role"] == "assistant" and "Please send the scheduled flight date in `YYYY-MM-DD` format." in msg["content"]
            for msg in history
        ):
            return {
                "response": "Please send the full scheduled flight date in `YYYY-MM-DD` format, for example `2026-04-28`.",
                "analysis": None,
                "ui_action": None,
            }

        if (
            self._mentions_cancellation(message)
            and self._has_flight_and_date_context(history)
            and not self._extract_delay_minutes(message)
        ):
            asked_about_final_arrival = any(
                msg["role"] == "assistant"
                and ("replacement flight" in msg["content"].lower() or "final destination" in msg["content"].lower())
                for msg in history
            )
            response = (
                "Thanks, I’ve noted that this was a cancellation.\n\n"
                "For a cancelled flight, the next thing I need is what happened after the cancellation:\n"
                "- Were you rebooked by the airline?\n"
                "- If yes, about how much later did you arrive at your final destination?\n"
                "- If no replacement flight was provided, tell me that too.\n\n"
                "For example, you can reply with `rebooked, arrived 5 hours later` or `no replacement flight`."
            )
            if asked_about_final_arrival:
                response = (
                    "Thanks. I understand that the flight was cancelled.\n\n"
                    "What I need next is what happened after the cancellation:\n"
                    "- `rebooked, arrived 4 hours later`\n"
                    "- `rebooked next day`\n"
                    "- `no replacement flight`\n\n"
                    "That helps me check the compensation path more accurately."
                )
            return {
                "response": response,
                "analysis": None,
                "ui_action": None,
            }

        candidate = self._build_confirmation_candidate(message, history)
        if candidate and candidate.get("needs_date"):
            return {
                "response": (
                    f"I found the flight number {candidate['flight_number']}, but I still need the flight date before I can verify it.\n\n"
                    "Please send the scheduled flight date in `YYYY-MM-DD` format."
                ),
                "analysis": None,
                "ui_action": None,
            }

        combined_user_text = "\n".join([msg["content"] for msg in history if msg["role"] == "user"] + [message])
        passenger_profile = self._extract_passenger_profile(combined_user_text)
        missing_profile_fields = self._profile_missing_fields(passenger_profile)
        asked_for_profile = any(
            msg["role"] == "assistant" and "Before I prepare the draft claim letter" in msg["content"]
            for msg in history
        )
        if asked_for_profile and missing_profile_fields:
            passenger_profile = self._apply_single_value_profile_hint(message, passenger_profile, missing_profile_fields)
            missing_profile_fields = self._profile_missing_fields(passenger_profile)
        if (
            not self._is_new_flight_start(message)
            and self._has_claim_basics(history, message)
            and missing_profile_fields
            and not asked_for_profile
        ):
            return {
                "response": (
                    "Before I run the final claim analysis and prepare the draft letter, I need a few passenger details.\n\n"
                    f"{self._next_profile_prompt(missing_profile_fields)}"
                ),
                "analysis": None,
                "ui_action": None,
            }
        if (
            asked_for_profile
            and not self._is_new_flight_start(message)
            and self._has_claim_basics(history, message)
            and missing_profile_fields
        ):
            return {
                "response": (
                    "Thanks, I’ve saved that.\n\n"
                    f"{self._next_profile_prompt(missing_profile_fields)}"
                ),
                "analysis": None,
                "ui_action": None,
            }
        if candidate and candidate.get("provider_error"):
            return {
                "response": (
                    f"I tried to verify {candidate['flight_number']} for {candidate['flight_date']}, but the live flight provider is unavailable right now.\n\n"
                    f"Provider message: {candidate['error']}\n\n"
                    "Please try again after the provider subscription is active, or use the manual claim flow with the flight details you already know."
                ),
                "analysis": None,
                "ui_action": None,
            }
        if candidate and "yes" not in message.lower():
            verified = candidate["verified_flight"]
            claim_data = candidate["claim_data"]
            airline = verified.get("airline", "Unknown airline")
            verified_delay = verified.get("delay_minutes", "Unknown")
            airport = verified.get("airport_code", "Unknown airport")
            departure_airport = verified.get("departure_airport", "Unknown")
            arrival_airport = verified.get("arrival_airport", airport)
            return {
                "response": (
                    f"I found a likely match for {claim_data['flight_number']}.\n\n"
                    f"Flight: {claim_data['flight_number']}\n"
                    f"Airline: {airline}\n"
                    f"Date: {claim_data['flight_date']}\n"
                    f"Route: {departure_airport} -> {arrival_airport}\n"
                    f"Verified delay: {verified_delay} minutes\n"
                    f"Airport: {airport}\n\n"
                    "Is this your flight?\n\n"
                    "While I validate the match, please share any details you already know:\n"
                    "- passenger name\n"
                    "- age\n"
                    "- country\n"
                    "- was it a delay, cancellation, denied boarding, or a missed connection?\n\n"
                    "If this is your flight, you can simply reply `yes`."
                ),
                "analysis": None,
                "ui_action": {
                    "type": "flight_confirmation",
                    "claim_data": claim_data,
                    "verified_flight": verified,
                    "prompt": "Is this your flight?",
                },
            }

        messages = [SystemMessage(content=CHAT_SYSTEM_PROMPT)]

        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))

        messages.append(HumanMessage(content=message))

        analysis = None

        try:
            response = self.llm_with_tools.invoke(messages)

            if response.tool_calls:
                tool_results = []
                for tc in response.tool_calls:
                    if tc["name"] == "analyze_flight_claim":
                        tool_args = dict(tc["args"])
                        tool_args.update({k: v for k, v in passenger_profile.items() if v})
                        raw_result = analyze_flight_claim.invoke(tool_args)
                        tool_results.append(
                            ToolMessage(content=raw_result, tool_call_id=tc["id"])
                        )
                        try:
                            analysis = json.loads(raw_result)
                        except Exception:
                            pass

                messages.append(response)
                messages.extend(tool_results)
                final_response = self.llm_with_tools.invoke(messages)
                return {
                    "response": self._stringify_content(final_response.content),
                    "analysis": analysis,
                }

            return {
                "response": self._stringify_content(response.content),
                "analysis": None,
            }

        except Exception as e:
            logger.exception("Chat agent error")
            return {
                "response": "I'm sorry, I ran into a technical issue. Could you try again?",
                "analysis": None,
            }


_chat_agent_instance = None


def get_chat_agent() -> ConversationalClaimAgent:
    global _chat_agent_instance
    if _chat_agent_instance is None:
        _chat_agent_instance = ConversationalClaimAgent()
    return _chat_agent_instance
