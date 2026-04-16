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
from tools.claim_tools import get_all_tools
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
        
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,  # Deterministic for legal decisions
            max_output_tokens=2048,
            google_api_key=api_key
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
        
        user_message = f"""
Please analyze this flight compensation claim:

FLIGHT INFORMATION:
- Flight Number: {claim_data['flight_number']}
- Flight Date: {claim_data['flight_date']}
- Reported Delay: {claim_data['delay_minutes']} minutes
- Airline's Stated Reason: {claim_data['delay_reason']}
- Passenger Location: {claim_data.get('jurisdiction', 'EU')}

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
            logger.info("[Claim %s] Step 2/5: Sending analysis request to Gemini", request_label)
            result = agent.invoke({
                "messages": [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=user_message)
                ]
            })
            logger.info("[Claim %s] Step 3/5: Model response received", request_label)
            
            response_text = ""
            if result.get('messages'):
                last_message = result['messages'][-1]
                response_text = last_message.get('content', '') if hasattr(last_message, 'get') else str(last_message)
            
            logger.info("[Claim %s] Step 4/5: Parsing model output", request_label)
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
            
            response = ClaimResponse(
                eligible=analysis.get('eligible', False),
                compensation_eur=analysis.get('compensation_eur', 0),
                regulation_reference=analysis.get('regulation_reference', 'EU261'),
                regulation_text=analysis.get('regulation_text', ''),
                claim_letter=analysis.get('claim_letter', ''),
                reasoning=analysis.get('reasoning', ''),
                next_steps=analysis.get('next_steps', []),
                confidence=analysis.get('confidence', 0.5)
            )
            elapsed = time.perf_counter() - started_at
            logger.info(
                "[Claim %s] Step 5/5: Completed in %.2fs | eligible=%s | amount=EUR %s",
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
                confidence=0.0
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
            "confidence": 0.75
        }


# Global agent instance (can be reused)
_agent_instance = None

def get_agent() -> ClaimAnalysisAgent:
    """Get or create singleton agent instance"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ClaimAnalysisAgent()
    return _agent_instance
