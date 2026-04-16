# QUICK START - Run the Project Now! 🚀

## You're Ready! Everything is Set Up.

### Step 1: Get Your API Key (2 minutes)

You need an **Anthropic API Key** to run Claude.

1. Go to: https://console.anthropic.com/
2. Sign up (or login)
3. Click "API Keys" on the left
4. Create a new API key
5. Copy it (you won't see it again!)

### Step 2: Configure Environment Variable

**Option A: Export in Terminal** (easiest)
```bash
export ANTHROPIC_API_KEY="sk-ant-YOUR_KEY_HERE"
```

**Option B: Create .env file**
```bash
cd backend
echo 'ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE' > .env
```

### Step 3: Start Backend (Terminal 1)

```bash
cd /Users/krishnaprasadchapagain/Desktop/IDS517_project/Flight_Agent_V2/backend
python main.py
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8001 
INFO:     🚀 Bureaucracy Hacker API starting up...
INFO:     ✅ Agent ready for claim analysis
```

✅ Backend is running!

### Step 4: Start Frontend (Terminal 2)

```bash
cd /Users/krishnaprasadchapagain/Desktop/IDS517_project/Flight_Agent_V2
python -m http.server 8000
```

You should see:
```
Serving HTTP on :: port 8000
```

✅ Frontend is running!

### Step 5: Open in Browser

Visit: **http://localhost:8000**

You should see the Flight Claim Checker UI.

### Step 6: Test It! 

Fill out the form:
- **Flight Number**: BA123
- **Flight Date**: 2024-01-15
- **What happened?**: "Flight delayed 5 hours due to technical issues"

Click **"Check Eligibility"**

The agent will:
1. ✅ Verify the flight delay
2. ✅ Check weather history
3. ✅ Search EU261 regulations
4. ✅ Calculate compensation
5. ✅ Generate a claim letter

**Expected Result:**
```
🎉 You may be eligible for €400!

[Claim letter will appear here]

Confidence: 95%

Next Steps:
• Download the claim letter
• Send to airline customer service
• Track your claim status
```

---

## What Just Happened?

```
Your Browser (localhost:8000)
    ↓
    You fill form and click "Check Eligibility"
    ↓
API Call to Backend (localhost:8001)
    ↓
FastAPI receives: {flight_number, date, delay_reason, ...}
    ↓
Claude Agent (AI Intelligence)
    ├─ Tool: check_flight_status("BA123", "2024-01-15")
    │  → Returns: Flight was indeed delayed 5 hours
    ├─ Tool: check_weather_history(airport, date)
    │  → Returns: Weather was clear
    ├─ Tool: verify_extraordinary_circumstances("technical issues")
    │  → Returns: Technical issues ≠ extraordinary circumstance
    ├─ Tool: search_regulations("EU")
    │  → Returns: EU261 Article 7 applies
    ├─ Tool: calculate_compensation(distance, delay)
    │  → Returns: €400 eligible
    └─ Tool: generate_claim_letter(...)
       → Returns: Professional letter
    ↓
Response with eligibility + claim letter
    ↓
Your Browser displays results
```

---

## Troubleshooting

### "Connection Error" - Backend not connecting

**Check 1:** Is backend running?
```bash
curl http://localhost:8001/health
```
Should return `{"status": "ok"}`

**Check 2:** Did you add the API key?
```bash
echo $ANTHROPIC_API_KEY
```
Should show your key (not empty)

**Check 3:** Are you on the right port?
- Frontend: http://localhost:**8000**
- Backend: http://localhost:**8001**

### "ModuleNotFoundError: No module named 'langchain'"

Packages didn't install properly. Try:
```bash
pip install --upgrade pip
pip install fastapi uvicorn langchain langchain-anthropic anthropic pydantic
```

### Agent returns "Error analyzing claim"

Check backend terminal for error logs. Common issues:
- Missing ANTHROPIC_API_KEY
- Invalid API key
- Network issues
- Package compatibility

---

## Next Steps

### Now That It's Running:

1. **Try different scenarios:**
   - Weather delay → Not eligible
   - Mechanical issue → Eligible
   - Strike → Not eligible (extraordinary)

2. **Explore the API:**
   - Backend docs: http://localhost:8001/docs

3. **Examine the code:**
   - Agent logic: `backend/agents/claim_agent.py`
   - Tools: `backend/tools/claim_tools.py`
   - Frontend: `scripts.js`

4. **Make improvements:**
   - Add real API integrations (FlightRadar24)
   - Add database for tracking claims
   - Setup Gmail monitoring (n8n)

---

## Architecture Overview

### Files You Just Deployed:

```
Flight_Agent_V2/
├── frontend/
│   ├── index.html       (UI form)
│   ├── scripts.js       (Calls backend API)
│   └── style.css        (Styling)
│
├── backend/
│   ├── main.py          (FastAPI server)
│   ├── agents/
│   │   └── claim_agent.py    (Claude agent logic)
│   ├── tools/
│   │   └── claim_tools.py    (Domain tools)
│   └── models/
│       └── schemas.py        (Data models)
│
├── README.md            (Full documentation)
└── ARCHITECTURE.md      (System design)
```

### How They Talk:

1. **Frontend** sends JSON → **Backend** (HTTP POST)
2. **Backend** uses **Agent** to analyze
3. **Agent** calls **Tools** for verification
4. **Agent** returns decision → **Backend** → **Frontend**
5. **Frontend** displays results

---

## Key Insights

✅ **The agent is already working!** You have a fully functional autonomous system that:
- Takes user input
- Verifies flight details
- Cross-references regulations
- Calculates compensation
- Generates professional claims

✅ **It uses Claude + LangChain** for maximum reliability and flexibility

✅ **All tools are mock data** - ready to connect to real APIs:
- FlightRadar24 for flight data
- NOAA for weather history
- Pinecone for regulation database

✅ **Frontend is fully integrated** - no more mock delays, it's calling real agent!

---

## Support

**Questions?** Check:
- [README.md](README.md) - Full documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) - Code examples
- [AGENT_IMPLEMENTATION.md](AGENT_IMPLEMENTATION.md) - Agent details

**Something broken?**
- Check terminal logs
- Try: `curl http://localhost:8001/health`
- Verify API key is set
- Try restarting backend

**Want to contribute?**
- All code is modular
- Easy to add new tools
- Easy to swap out implementations
- Fully documented

---

## Congratulations! 🎉

You now have a working **Bureaucracy Hacker** system!

This is the foundation for a multi-billion dollar market opportunity. 

Next: Add real APIs, Gmail integration, payment processing, and scale to production.

🚀 Happy analyzing!
