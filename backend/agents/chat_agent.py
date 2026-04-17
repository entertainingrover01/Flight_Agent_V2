"""
Conversational claim analysis agent for multi-turn chat interactions.
"""
import os
import json
import logging
import asyncio
import concurrent.futures
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

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
def analyze_flight_claim(flight_number: str, flight_date: str, delay_reason: str, delay_minutes: int) -> str:
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

    def __init__(self, api_key: Optional[str] = None):
        if api_key is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found.")

        model_name = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        self.llm = ChatAnthropic(
            model=model_name,
            temperature=0.4,
            max_tokens=2048,
            anthropic_api_key=api_key,
        )
        self.llm_with_tools = self.llm.bind_tools([analyze_flight_claim])

    def chat(self, message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Process a chat message with conversation history.

        Args:
            message: The user's current message.
            history: List of prior turns as {role: "user"|"assistant", content: str}.

        Returns:
            {response: str, analysis: dict | None}
        """
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
                        raw_result = analyze_flight_claim.invoke(tc["args"])
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
                return {"response": final_response.content, "analysis": analysis}

            return {"response": response.content, "analysis": None}

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
