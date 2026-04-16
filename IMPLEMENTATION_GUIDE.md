# Implementation Guide: Building the Agent

## Part 1: Backend Setup (FastAPI + Claude Agent)

### Step 1: Create Backend Structure
```bash
mkdir -p backend/{agents,tools,services,models,config}
cd backend
```

### Step 2: Requirements File
```
# backend/requirements.txt
fastapi==0.109.0
uvicorn==0.27.0
python-dotenv==1.0.0
langchain==0.1.0
langchain-anthropic==0.1.0
langchain-community==0.1.0
pydantic==2.5.0
httpx==0.25.0
python-jose==3.3.0
```

### Step 3: Core Agent (LangChain + Claude)
```python
# backend/agents/claim_agent.py
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_anthropic import ChatAnthropic
from langchain.tools import tool
from typing import Optional
import httpx

class ClaimAnalyzer:
    def __init__(self):
        self.llm = ChatAnthropic(
            model="claude-3-5-sonnet-20241022",
            temperature=0
        )
        self.tools = self._create_tools()
        
    def _create_tools(self):
        @tool
        def check_flight_status(flight_number: str, date: str) -> dict:
            """Query FlightRadar24 API to verify actual delay"""
            # Implementation here
            return {
                "flight": flight_number,
                "scheduled_arrival": "14:30",
                "actual_arrival": "18:45",
                "delay_minutes": 255
            }
        
        @tool
        def check_weather_data(airport_code: str, date: str) -> dict:
            """Verify if weather was actually the stated cause"""
            # Implementation: Query NOAA or OpenWeatherMap
            return {
                "airport": airport_code,
                "weather": "Clear skies",
                "severe_weather": False
            }
        
        @tool
        def search_regulations(query: str, jurisdiction: str = "EU261") -> str:
            """RAG search through aviation compensation regulations"""
            # This will query your vector DB
            regulations = """
            EU261 Article 7: Compensation for denied boarding
            - €250 for flights up to 1500 km
            - €400 for flights over 1500 km
            - €600 for flights over 3500 km
            
            Exceptions: Force majeure, weather, safety risks
            """
            return regulations
        
        @tool
        def generate_claim_letter(flight_info: dict, regulation: str) -> str:
            """Generate professional claim letter"""
            prompt = f"""
            Generate a formal EU261 compensation claim letter based on:
            Flight: {flight_info['flight_number']}
            Date: {flight_info['date']}
            Delay: {flight_info['delay_minutes']} minutes
            
            Relevant regulation: {regulation}
            
            Make it professional, legally sound, and compelling.
            """
            # Call Claude to generate
            return "Generated claim letter..."
        
        return [check_flight_status, check_weather_data, search_regulations, generate_claim_letter]
    
    async def analyze_claim(self, claim_input: dict) -> dict:
        """Main entry point for claim analysis"""
        agent = create_tool_calling_agent(
            self.llm,
            self.tools,
            system_prompt="""
            You are an expert aviation compensation specialist. Your role is to:
            1. Verify flight delay details
            2. Check if airline's stated reason is legitimate
            3. Search applicable regulations
            4. Determine compensation eligibility
            5. Generate a claim letter
            
            Be thorough and accurate. Always cross-verify information.
            """
        )
        
        executor = AgentExecutor(agent=agent, tools=self.tools, verbose=True)
        
        result = await executor.ainvoke({
            "input": f"Analyze this flight claim: {claim_input}"
        })
        
        return result
```

### Step 4: FastAPI Endpoints
```python
# backend/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agents.claim_agent import ClaimAnalyzer
import asyncio

app = FastAPI(title="Bureaucracy Hacker API")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

claim_analyzer = ClaimAnalyzer()

class ClaimRequest(BaseModel):
    flight_number: str
    flight_date: str
    delay_reason: str
    delay_minutes: int
    passenger_email: str

class ClaimResponse(BaseModel):
    eligible: bool
    compensation_eur: int
    regulation_reference: str
    claim_letter: str
    next_steps: list

@app.post("/api/analyze-claim", response_model=ClaimResponse)
async def analyze_claim(request: ClaimRequest) -> ClaimResponse:
    """Analyze flight compensation eligibility"""
    try:
        result = await claim_analyzer.analyze_claim({
            "flight_number": request.flight_number,
            "date": request.flight_date,
            "delay_reason": request.delay_reason,
            "delay_minutes": request.delay_minutes
        })
        
        # Parse agent response
        return ClaimResponse(
            eligible=True,  # Parse from agent result
            compensation_eur=400,  # Parse from agent result
            regulation_reference="EU261 Article 7",
            claim_letter="Generated letter here",
            next_steps=[
                "Download the claim letter",
                "Send to airline customer service",
                "Track your claim status"
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.health
async def health():
    return {"status": "ok"}
```

---

## Part 2: n8n Workflow Setup

### Gmail Monitoring Workflow

```json
{
  "name": "Flight Delay Claim Monitor",
  "nodes": [
    {
      "name": "Gmail Trigger",
      "type": "n8n-nodes-base.gmailTrigger",
      "typeVersion": 1,
      "parameters": {
        "filters": {
          "include": [
            {
              "key": "from",
              "value": "@airlines.com OR @airline OR customer-service"
            },
            {
              "key": "subject",
              "value": "delay OR cancel OR reschedule"
            }
          ]
        }
      }
    },
    {
      "name": "Parse Email",
      "type": "n8n-nodes-base.functionItem",
      "typeVersion": 1,
      "parameters": {
        "functionCode": `
        return {
          flight_number: /([A-Z]{2}\\d{3,4})/gi.exec(item.json.body)?.[0],
          delay_reason: extractDelayReason(item.json.body),
          email_sender: item.json.from,
          received_date: item.json.internalDate
        }
        `
      }
    },
    {
      "name": "Call Backend",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 1,
      "parameters": {
        "method": "POST",
        "url": "http://localhost:8000/api/analyze-claim",
        "headers": {
          "Content-Type": "application/json"
        },
        "body": {
          "flight_number": "{{ $node['Parse Email'].json['flight_number'] }}",
          "flight_date": "{{ $node['Parse Email'].json['received_date'] }}",
          "delay_reason": "{{ $node['Parse Email'].json['delay_reason'] }}",
          "passenger_email": "{{ $node.context.user_email }}"
        }
      }
    },
    {
      "name": "Send User Email",
      "type": "n8n-nodes-base.gmail",
      "typeVersion": 1,
      "parameters": {
        "sendAs": "me",
        "to": "{{ $node['Parse Email'].json['sender'] }}",
        "subject": "✅ Compensation Claim Ready - €{{ $node['Call Backend'].json['compensation_eur'] }}",
        "body": "{{ $node['Call Backend'].json['claim_letter'] }}"
      }
    }
  ]
}
```

---

## Part 3: RAG Setup (Vector Database)

### Setup Pinecone Vector DB
```python
# backend/services/rag.py
from langchain.document_loaders import PDFDirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.vectorstores import Pinecone
import pinecone

class RegulationRAG:
    def __init__(self, pinecone_key: str, pinecone_env: str):
        pinecone.init(api_key=pinecone_key, environment=pinecone_env)
        self.embeddings = OpenAIEmbeddings()
        
    def ingest_regulations(self, pdf_directory: str):
        """Load and chunk regulations into vector DB"""
        loader = PDFDirectoryLoader(pdf_directory)
        documents = loader.load()
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        texts = splitter.split_documents(documents)
        
        # Create Pinecone vector store
        vectorstore = Pinecone.from_documents(
            texts,
            self.embeddings,
            index_name="aviation-regulations"
        )
        return vectorstore
    
    def search_regulations(self, query: str) -> str:
        """Semantic search through regulations"""
        vectorstore = Pinecone.from_existing_index(
            "aviation-regulations",
            self.embeddings
        )
        results = vectorstore.similarity_search(query, k=3)
        return "\n".join([doc.page_content for doc in results])
```

---

## Part 4: Frontend Integration

### Update index.html to Call Backend
```javascript
// scripts.js modifications

const API_BASE = "http://localhost:8000";

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const payload = {
        flight_number: document.getElementById('flightNumber').value,
        flight_date: document.getElementById('flightDate').value,
        delay_reason: document.getElementById('delayReason').value,
        delay_minutes: 300, // Calculate from form
        passenger_email: "user@example.com"
    };

    loading.classList.remove('hidden');

    try {
        const response = await fetch(`${API_BASE}/api/analyze-claim`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (data.eligible) {
            resultTitle.innerText = `Eligible for €${data.compensation_eur}!`;
            resultMessage.innerText = data.claim_letter;
        } else {
            resultTitle.innerText = "Not eligible";
        }

        result.classList.remove('hidden');
    } catch (error) {
        resultTitle.innerText = "Error";
        resultMessage.innerText = error.message;
    } finally {
        loading.classList.add('hidden');
    }
});
```

---

## Deployment

### Docker Setup
```dockerfile
FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Run Locally
```bash
# Terminal 1: Backend
cd backend
python -m uvicorn main:app --reload

# Terminal 2: Frontend
cd ..
python -m http.server 8000

# Terminal 3: n8n (optional)
npx n8n start
```

---

## Testing the Flow

1. **User submits claim** via HTML form
2. **Backend receives request** → Calls Claude Agent
3. **Agent:**
   - Queries FlightRadar24 API
   - Checks weather data
   - Searches regulations (RAG)
   - Generates claim letter
4. **Response sent** to frontend
5. **n8n monitors** Gmail and repeats for email triggers

---

## Next: What to Build First?

1. ✅ FastAPI backend with single agent endpoint
2. ✅ Connect Claude Agent SDK
3. ✅ Add mock tools (before real API calls)
4. ✅ Test end-to-end with frontend
5. ✅ Add Pinecone RAG
6. ✅ Integrate Gmail with n8n
7. ✅ Add real API integrations

