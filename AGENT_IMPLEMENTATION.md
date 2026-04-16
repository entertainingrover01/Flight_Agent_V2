# Agent Implementation Deep Dive

## Understanding the Agent Architecture

Your system needs **THREE types of agents**, not just one:

### 1. **Claim Analyzer Agent** (Main Intelligence)
- Input: Flight delay details
- Process: Verify legitimacy, check regulations, determine eligibility
- Output: Eligibility decision + compensation amount
 
### 2. **Email Parser Agent** (Triggered by n8n)
- Input: Raw email from airline
- Process: Extract flight info, delay reason, dates
- Output: Structured claim data

### 3. **Claim Generator Agent** (Content Creation)
- Input: Verified claim facts + applicable regulations
- Process: Generate persuasive, legally-sound claim letter
- Output: Claim letter ready to send

---

## Option 1: Using Claude Agent SDK (Simplest)

Your current `AGENT.py` uses Claude Agent SDK. Here's the enhanced version:

```python
# backend/agents/enhanced_agent.py
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions
from typing import Optional
import json

class BureaucracyHacker:
    def __init__(self):
        self.claim_analyzer_prompt = """
        You are an expert aviation compensation specialist. You have access to tools to:
        1. Query flight data from aviation APIs
        2. Check weather conditions
        3. Search aviation compensation regulations
        4. Generate claim documents
        
        Your task is to analyze flight delay claims and:
        - Verify if the delay actually occurred
        - Confirm the airline's stated reason is legitimate
        - Find applicable regulations for the passenger's jurisdiction
        - Determine compensation eligibility
        - Generate a formal claim letter
        
        Be thorough, accurate, and always cite regulations.
        """
    
    async def analyze_claim(self, flight_info: dict) -> dict:
        """
        Main agent entry point
        
        Args:
            flight_info: {
                "flight_number": "BA123",
                "date": "2024-01-15",
                "delay_minutes": 300,
                "delay_reason": "Technical issues",
                "passenger_location": "EU"
            }
        """
        
        options = ClaudeAgentOptions(
            system_prompt=self.claim_analyzer_prompt,
            allowed_tools=["str_replace_editor"],  # For generating documents
            permission_mode="acceptEdits"
        )
        
        prompt = f"""
        Analyze this flight compensation claim:
        
        Flight Number: {flight_info['flight_number']}
        Date: {flight_info['date']}
        Delay Duration: {flight_info['delay_minutes']} minutes
        Stated Reason: {flight_info['delay_reason']}
        Passenger Location: {flight_info['passenger_location']}
        
        Please:
        1. Verify if this delay typically qualifies for compensation
        2. Check if the airline's reason (technical issues) is a valid exemption
        3. Find the applicable regulation (likely EU261)
        4. Determine the compensation amount (€250/400/600)
        5. Generate a professional claim letter requesting compensation
        6. Save the claim letter as claim.txt
        
        Return a JSON with:
        {{
            "eligible": true/false,
            "compensation_eur": 400,
            "regulation": "EU261 Article 7",
            "reasoning": "explanation",
            "next_steps": ["step1", "step2"]
        }}
        """
        
        result_text = ""
        async for message in query(prompt=prompt, options=options):
            result_text += message
            print(message)  # Stream to console
        
        # Parse JSON from agent response
        try:
            import re
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
        except:
            pass
        
        return {"error": "Could not parse agent response"}
```

**Pros:**
- Simple async interface
- Integrated memory management
- Stateful conversations

**Cons:**
- Limited tool variety
- Less flexible control
- Only `str_replace_editor` tool available

---

## Option 2: Using LangChain Agents (Most Flexible)

Recommended for production. More powerful but more code:

```python
# backend/agents/langchain_agent.py
from langchain.agents import AgentExecutor, create_tool_calling_agent, Tool
from langchain_anthropic import ChatAnthropic
from langchain.memory import ConversationBufferMemory
from typing import Optional, List
import httpx
import json
from datetime import datetime

class LangChainClaimAgent:
    def __init__(self):
        self.llm = ChatAnthropic(
            model="claude-3-5-sonnet-20241022",
            temperature=0,
            max_tokens=4096
        )
        
        # Memory for multi-turn conversations
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        self.tools = self._initialize_tools()
        
    def _initialize_tools(self) -> List[Tool]:
        """Create domain-specific tools"""
        
        # Tool 1: Query Flight Data
        async def check_flight_data(flight_number: str, date: str) -> str:
            """Query aviationstack API for real flight data"""
            try:
                # Mock response - replace with real API in production
                return json.dumps({
                    "flight": flight_number,
                    "date": date,
                    "scheduled_arrival": "14:30 UTC",
                    "actual_arrival": "18:45 UTC",
                    "delay_minutes": 255,
                    "status": "landed"
                })
            except Exception as e:
                return f"Error: {str(e)}"
        
        # Tool 2: Check Weather
        async def check_weather(airport: str, date: str, time: str) -> str:
            """Check if weather caused delays"""
            try:
                # Mock response - replace with NOAA/OpenWeatherMap
                return json.dumps({
                    "airport": airport,
                    "date": date,
                    "weather": "Clear skies, 20°C",
                    "severe_weather": False,
                    "wind_speed": "5 knots",
                    "visibility": ">10km"
                })
            except Exception as e:
                return f"Error: {str(e)}"
        
        # Tool 3: Search Regulations
        def search_regulations(query: str, jurisdiction: str = "EU") -> str:
            """Search regulation database (RAG backend)"""
            regulations = {
                "EU261": """
EU Regulation 261/2004 Compensation:
- €250 for flights up to 1500 km
- €400 for flights 1500-3500 km  
- €600 for flights over 3500 km

Exemptions:
- Extraordinary circumstances (weather, security)
- Force majeure

Articles:
- Article 5: Right to compensation
- Article 7: Compensation standards
- Article 9: Exemptions
                """,
                "FAA": """
U.S. Flight Compensation (Limited):
- No mandatory compensation
- But many airlines offer voluntary compensation
- Department of Transportation rules focus on disclosure
                """
            }
            return regulations.get(jurisdiction, "Regulations not found")
        
        # Tool 4: Generate Claim Letter
        def generate_claim_letter(
            flight_info: dict, 
            regulation: str, 
            compensation: int
        ) -> str:
            """Generate professional claim letter"""
            letter = f"""
Dear Airline Customer Service,

I am writing to formally claim compensation under {regulation} for a disrupted flight.

Flight Details:
- Flight Number: {flight_info['flight_number']}
- Date: {flight_info['date']}
- Delay Duration: {flight_info['delay_minutes']} minutes
- Stated Reason: {flight_info['reason']}

According to {regulation}, I am entitled to compensation of €{compensation} for this delay.
The delay exceeded 3 hours, and the reason provided does not constitute an extraordinary circumstance.

I request compensation in the amount of €{compensation} to be transferred to my account.

Respectfully,
The Claim Holder
            """
            return letter
        
        # Register tools
        tools = [
            Tool(
                name="check_flight",
                func=check_flight_data,
                description="Check real flight data - scheduled vs actual times"
            ),
            Tool(
                name="check_weather",
                func=check_weather,
                description="Check weather conditions on delay date/time"
            ),
            Tool(
                name="search_regulations",
                func=search_regulations,
                description="Search aviation compensation regulations by jurisdiction"
            ),
            Tool(
                name="generate_letter",
                func=generate_claim_letter,
                description="Generate professional compensation claim letter"
            ),
        ]
        
        return tools
    
    def create_claim_analyzer(self):
        """Create the agent executor"""
        
        system_prompt = """
You are an expert aviation compensation analyst. Your role is to:

1. When given a flight delay claim, use the check_flight tool to verify the delay
2. Use check_weather to verify if weather actually caused it
3. Use search_regulations to find applicable compensation laws
4. Determine if the claim is eligible (usually yes if >3 hours and not extraordinary)
5. Use generate_letter to create a claim

Always:
- Be thorough in verification
- Cite specific regulations
- Calculate correct compensation amounts
- Provide clear next steps

Return your analysis in JSON format:
{
    "eligible": boolean,
    "compensation_eur": number,
    "regulation_cited": "string",
    "reasoning": "string",
    "claim_letter": "string"
}
        """
        
        agent = create_tool_calling_agent(
            self.llm,
            self.tools,
            system_prompt=system_prompt
        )
        
        executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,
            max_iterations=10
        )
        
        return executor
    
    async def analyze(self, claim_data: dict) -> dict:
        """Main analysis endpoint"""
        
        executor = self.create_claim_analyzer()
        
        prompt = f"""
Please analyze this flight compensation claim:

Flight: {claim_data['flight_number']}
Date: {claim_data['date']}
Reported Delay: {claim_data['delay_minutes']} minutes
Airline Reason: {claim_data['reason']}
Jurisdiction: {claim_data.get('jurisdiction', 'EU')}
        """
        
        result = executor.invoke({"input": prompt})
        
        # Extract final JSON from agent output
        try:
            import re
            json_match = re.search(r'\{.*?\}', result['output'], re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return {"output": result['output']}
```

---

## Option 3: Hybrid Approach (Recommended for Production)

Combine Claude Agent SDK + LangChain for best of both worlds:

```python
# backend/agents/hybrid_agent.py
from claude_agent_sdk import query, ClaudeAgentOptions
from langchain.tools import tool
from typing import Optional
import asyncio

class HybridBureaucracyHacker:
    """
    Uses Claude Agent SDK for conversation management,
    but uses LangChain tools for extensibility
    """
    
    async def multi_step_analysis(self, claim_data: dict) -> dict:
        """
        Step 1: Use Claude Agent SDK for initial analysis
        Step 2: Use LangChain tools for specific tasks
        Step 3: Combine results
        """
        
        # Step 1: Initial analysis with Agent SDK
        options_step1 = ClaudeAgentOptions(
            system_prompt="""
You are analyzing a flight delay claim. 
Determine if this sounds like it qualifies for compensation.
Explain your reasoning.
            """,
            allowed_tools=["str_replace_editor"],
            permission_mode="acceptEdits"
        )
        
        prompt_step1 = f"""
Flight: {claim_data['flight_number']}
Date: {claim_data['date']}
Delay: {claim_data['delay_minutes']} minutes
Reason: {claim_data['reason']}

Is this eligible for EU261 compensation?
        """
        
        analysis_text = ""
        async for message in query(prompt=prompt_step1, options=options_step1):
            analysis_text += message
        
        # Step 2: Use LangChain for specific tool calls
        from agents.langchain_agent import LangChainClaimAgent
        
        langchain_agent = LangChainClaimAgent()
        executor = langchain_agent.create_claim_analyzer()
        
        prompt_step2 = f"""
Based on this analysis: {analysis_text}

Now verify the flight and generate a claim letter.
        """
        
        verification = executor.invoke({"input": prompt_step2})
        
        # Step 3: Combine
        return {
            "initial_analysis": analysis_text,
            "verification": verification,
            "final_decision": "eligible" if "eligible" in analysis_text.lower() else "not eligible"
        }

# Usage
async def main():
    agent = HybridBureaucracyHacker()
    result = await agent.multi_step_analysis({
        "flight_number": "BA123",
        "date": "2024-01-15",
        "delay_minutes": 300,
        "reason": "Technical issues"
    })
    print(result)
```

---

## Comparison: Which Option to Use?

| Feature | Claude SDK | LangChain | Hybrid |
|---------|-----------|-----------|--------|
| **Ease of Setup** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Flexibility** | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Tool Options** | Limited | Unlimited | Both |
| **Memory Management** | Built-in | Manual | Both |
| **Production Ready** | Yes | Yes | Yes |
| **Best For** | MVP | Enterprise | Scaling |

---

## Recommendation: Start with Hybrid

1. **Learn** Claude Agent SDK with your current code ✅
2. **Add** LangChain tools for flexibility
3. **Combine** both when you need advanced features

This gives you quick wins now + scalability later.

---

## Key Distinction: Agent vs Tool

**Don't confuse:**

- **Agent**: Makes decisions, plans steps, calls tools
  ```
  "Should I pursue this claim? Let me verify the flight first..."
  ```

- **Tool**: Performs specific action
  ```
  "check_flight" tool returns: Flight delayed 4 hours
  ```

Your system needs:
1. **One Main Agent** (claims eligibility)
2. **Multiple Tools** (flight data, weather, regulations, letter generation)
3. **Multiple Sub-Agents** (email parser, form filler) - optional

---

## Next Steps

1. Choose Option 2 (LangChain) for full control
2. Implement the `_initialize_tools()` with real API calls
3. Connect to FastAPI backend
4. Test end-to-end and iterate

