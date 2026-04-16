# Bureaucracy Hacker - Getting Started

## System Overview

```
Frontend (HTML/CSS/JS on localhost:8000)
        ↓ (Calls API)
Backend FastAPI (localhost:8001)
        ↓ (Uses tools)
Claude Agent (via LangChain)
        ↓ (Calls tools)
Flight Data Tools, Weather Tools, Regulation Tools
```

## Quick Start

### 1. Install Backend Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Set Environment Variables

```bash
# Create .env from template
cp .env.example .env

# Edit .env and add your Anthropic API key
nano .env
```

You need:
- `ANTHROPIC_API_KEY` - Get from https://console.anthropic.com/

### 3. Run Backend API

```bash
# From project root
cd backend
python main.py

# OR with uvicorn directly
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8001
INFO:     🚀 Bureaucracy Hacker API starting up...
INFO:     ✅ Agent ready for claim analysis
```

### 4. Run Frontend (Separate Terminal)

```bash
# From project root
python -m http.server 8000
```

Visit: http://localhost:8000

### 5. Test the System

1. Open http://localhost:8000
2. Enter a flight claim:
   - Flight: **BA123**
   - Date: **2024-01-15**
   - Delay reason: **Technical issues**
   - Delay minutes: Extract from reason or enter 300

3. Click "Check Eligibility"

The backend should analyze and return:
- ✅ Eligible for €400-600 (if delay > 3 hours and not weather)
- ⚠️ Not eligible (if weather or other exemptions)
- Generated claim letter ready to send

---

## API Endpoints

### Main Endpoint

```
POST /api/analyze-claim
```

**Request:**
```json
{
    "flight_number": "BA123",
    "flight_date": "2024-01-15",
    "delay_reason": "Technical issues",
    "delay_minutes": 300,
    "passenger_email": "user@example.com",
    "jurisdiction": "EU"
}
```

**Response:**
```json
{
    "eligible": true,
    "compensation_eur": 400,
    "regulation_reference": "EU261 Article 7",
    "regulation_text": "...",
    "claim_letter": "Dear Airline...",
    "reasoning": "Delay exceeded 3 hours...",
    "next_steps": ["Send claim letter to airline", "Track claim status"],
    "confidence": 0.95
}
```

### Other Endpoints

- `GET /health` - Health check
- `GET /api/regulations/{jurisdiction}` - Get regulations for jurisdiction
- `GET /docs` - API documentation
- `POST /api/analyze-from-email` - Parse email (coming soon)

---

## Architecture

### Frontend
- **index.html** - User interface
- **scripts.js** - Handles form submission, calls backend API
- **style.css** - Styling

### Backend
- **main.py** - FastAPI app with endpoints
- **agents/claim_agent.py** - LangChain agent implementation
- **tools/claim_tools.py** - Domain-specific tools (flight data, weather, regulations)
- **models/schemas.py** - Pydantic models (request/response schemas)

### Agent Flow

1. User submits flight claim form
2. Frontend sends POST to `/api/analyze-claim`
3. Backend receives request
4. **Claude Agent** kicks off:
   - Uses `check_flight_status` tool → Query flight data
   - Uses `check_weather_history` tool → Verify weather claim
   - Uses `verify_extraordinary_circumstances` tool → Check exemptions
   - Uses `search_regulations` tool → Find applicable law (EU261, etc.)
   - Uses `calculate_compensation` tool → Determine amount
   - Uses `generate_claim_letter` tool → Create professional letter
5. Agent returns JSON with decision + letter
6. Backend formats and returns to frontend
7. Frontend displays results

---

## Troubleshooting

### "Connection Error" on Frontend

**Problem:** Frontend says "Unable to connect to the AI agent"

**Solution:**
- Check backend is running: `http://localhost:8001/health`
- Check backend is on port 8001 (not 8000)
- Backend logs should show errors

### Backend fails to start

**Problem:** ImportError, ModuleNotFoundError

**Solution:**
```bash
cd backend
pip install -r requirements.txt
```

### "API key not found"

**Problem:** Backend says ANTHROPIC_API_KEY not set

**Solution:**
```bash
# Set environment variable
export ANTHROPIC_API_KEY=sk-ant-xxx

# OR add to .env file
echo "ANTHROPIC_API_KEY=sk-ant-xxx" >> backend/.env
```

Get key from: https://console.anthropic.com/

### Agent taking too long

**Problem:** Analysis takes 30+ seconds

**Reason:** Claude is verifying multiple tools (flight data, weather, regulations)

**Solution:**
- First run will be slower (model initialization)
- Subsequent requests are faster
- In production, cache results

---

## Next Steps

### Phase 1 ✅ (Current)
- ✅ Basic agent working
- ✅ Mock tools returning sample data
- ✅ Frontend calling backend
- ✅ Claim eligibility analysis

### Phase 2 (Next)
- [ ] Integrate real APIs (FlightRadar24, OpenWeatherMap)
- [ ] Add vector database for RAG (Pinecone)
- [ ] Setup Gmail monitoring (n8n)
- [ ] Add database for claim tracking
- [ ] Build admin dashboard

### Phase 3 (Later)
- [ ] Automated form submission to airlines
- [ ] Multi-airline support (Lufthansa, KLM, etc.)
- [ ] Email notifications
- [ ] Payment processing
- [ ] Analytics dashboard

---

## Development

### Adding a New Tool

1. Create tool in `backend/tools/claim_tools.py`:
```python
@staticmethod
@tool
def my_new_tool(param1: str) -> str:
    """Description of what tool does"""
    result = do_something(param1)
    return json.dumps(result)
```

2. Register in `get_all_tools()`:
```python
def get_all_tools():
    return [
        FlightToolkit.my_new_tool,
        # ... other tools
    ]
```

3. Agent will automatically use it

### Testing the Agent Locally

```python
# In backend/ directory
from agents.claim_agent import get_agent
import asyncio

async def test():
    agent = get_agent()
    result = await agent.analyze_claim({
        "flight_number": "BA123",
        "flight_date": "2024-01-15",
        "delay_reason": "Technical issues",
        "delay_minutes": 300,
        "jurisdiction": "EU"
    })
    print(result)

asyncio.run(test())
```

---

## Support

- API Docs: http://localhost:8001/docs
- Backend Logs: Terminal running `python main.py`
- Issues: Check console for error messages
