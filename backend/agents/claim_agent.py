"""
LangChain-based Claim Analysis Agent
Core AI reasoning engine for the Bureaucracy Hacker system
Now using OpenAI GPT instead of Claude
"""
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Optional, Dict, Any
import json
import re
from tools.claim_tools import get_all_tools
from models.schemas import ClaimResponse

class ClaimAnalysisAgent:
    """
    Autonomous agent that analyzes flight compensation claims
    using OpenAI GPT + LangChain + domain-specific tools
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the agent with OpenAI and tools"""
        
        self.llm = ChatOpenAI(
            model="gpt-3.5-turbo",  # Cheapest! (~$0.001 per 1K tokens)
            # OR use: model="gpt-4" for better accuracy (more expensive)
            temperature=0,  # Deterministic for legal decisions
            max_tokens=4096,
            api_key=api_key
        )
        
        self.tools = get_all_tools()

        
        self.system_prompt = """
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

PROCESS:
1. Acknowledge the claim details
2. Use check_flight_status to verify delay
3. Use check_weather_history to validate reason
4. Use verify_extraordinary_circumstances to check exemptions
5. Use search_regulations to find applicable law
6. Use calculate_compensation to determine amount
7. If eligible, use generate_claim_letter to create document
8. Provide clear decision with reasoning

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
    
    def create_executor(self) -> AgentExecutor:
        """Create the agent executor with tools"""
        
        agent = create_tool_calling_agent(
            self.llm,
            self.tools,
            system_prompt=self.system_prompt
        )
        
        executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,
            max_iterations=10,
            handle_parsing_errors=True,
            return_intermediate_steps=False
        )
        
        return executor
    
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
        
        executor = self.create_executor()
        
        # Build the analysis prompt
        analysis_prompt = f"""
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
            # Run the agent
            result = executor.invoke({
                "input": analysis_prompt
            })
            
            # Parse the agent's response
            response_text = result.get('output', '')
            
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                # Fallback if JSON not found
                analysis = {
                    "eligible": False,
                    "compensation_eur": 0,
                    "regulation_reference": "Unable to parse response",
                    "regulation_text": "",
                    "claim_letter": "",
                    "reasoning": response_text,
                    "next_steps": ["Contact support for manual review"],
                    "confidence": 0.0
                }
            
            # Create response object
            return ClaimResponse(
                eligible=analysis.get('eligible', False),
                compensation_eur=analysis.get('compensation_eur', 0),
                regulation_reference=analysis.get('regulation_reference', 'N/A'),
                regulation_text=analysis.get('regulation_text', ''),
                claim_letter=analysis.get('claim_letter', ''),
                reasoning=analysis.get('reasoning', ''),
                next_steps=analysis.get('next_steps', []),
                confidence=analysis.get('confidence', 0.5)
            )
        
        except Exception as e:
            # Error handling
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


# Global agent instance (can be reused)
_agent_instance = None

def get_agent() -> ClaimAnalysisAgent:
    """Get or create singleton agent instance"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ClaimAnalysisAgent()
    return _agent_instance
