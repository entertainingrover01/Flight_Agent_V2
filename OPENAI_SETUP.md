# Using OpenAI Instead of Claude

## Why OpenAI?

✅ **Cheaper**: GPT-3.5-turbo is ~$0.001 per 1K tokens (~50% cheaper than Claude)  
✅ **Free Trial**: $5 free credits for new accounts  
✅ **Already Have It**: You mentioned you have OpenAI access  
✅ **Works Great**: LangChain supports it perfectly  

## Cost Comparison

| Model | Cost per 1K tokens | Cost per claim (~1000 tokens) |
|-------|-------------------|------|
| GPT-3.5-turbo | $0.001 input / $0.002 output | ~$0.001-0.002 |
| GPT-4 | $0.03 input / $0.06 output | ~$0.03-0.06 |
| Claude 3 Sonnet | $0.003 input / $0.015 output | ~$0.003-0.015 |

**GPT-3.5-turbo is the cheapest option!**

---

## Setup (2 Steps)

### Step 1: Get OpenAI API Key

1. Go to: https://platform.openai.com/
2. Sign up or login
3. Click "API keys" (left sidebar)
4. Create new API key
5. Copy it

### Step 2: Configure

**Option A: Export in Terminal**
```bash
export OPENAI_API_KEY="sk-proj-YOUR_KEY"
```

**Option B: Add to .env file**
```bash
cd backend
echo 'OPENAI_API_KEY=sk-proj-YOUR_KEY' > .env
```

---

## That's It! 

The code is already updated to use OpenAI. Just:

```bash
# Terminal 1
cd backend
export OPENAI_API_KEY="sk-proj-YOUR_KEY"
python main.py

# Terminal 2
cd ..
python -m http.server 8000
```

Visit http://localhost:8000 and test!

---

## What Changed?

**Before (Claude):**
```python
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
```

**After (OpenAI):**
```python
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-3.5-turbo")  # Cheapest!
```

That's the only change needed! LangChain handles the rest.

---

## Switching Between Models

All in one line in `backend/agents/claim_agent.py`:

```python
# Cheapest (recommended)
self.llm = ChatOpenAI(model="gpt-3.5-turbo")

# Better quality, more expensive
self.llm = ChatOpenAI(model="gpt-4")

# Or go back to Claude
from langchain_anthropic import ChatAnthropic
self.llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
```

---

## Testing

```bash
# Run a single claim test
python -c "
import asyncio
from agents.claim_agent import get_agent

async def test():
    agent = get_agent()
    result = await agent.analyze_claim({
        'flight_number': 'BA123',
        'flight_date': '2024-01-15',
        'delay_reason': 'Technical issues',
        'delay_minutes': 300,
        'jurisdiction': 'EU'
    })
    print(result)

asyncio.run(test())
"
```

---

## FAQ

**Q: Is GPT-3.5-turbo accurate enough?**  
A: Yes! For rule-based tasks like EU261 compliance, it's more than accurate. We use temperature=0 for deterministic results.

**Q: Can I use GPT-4 instead?**  
A: Yes! Just change `model="gpt-3.5-turbo"` to `model="gpt-4"` in claim_agent.py. It's more accurate but costs ~30x more.

**Q: What if I want to use Claude again?**  
A: Install `pip install anthropic langchain-anthropic` and change the import back.

**Q: How much will this cost?**  
A: ~$0.001-0.002 per claim analyzed. ~$1 for 500 claims. Very cheap!

**Q: Do I need to pay upfront?**  
A: No. You only pay for what you use. New accounts get $5 free credits.

---

## Next: Using Different Models

You can easily mix and match models:

```python
# backend/agents/claim_agent.py

# Option 1: Cheapest (default)
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-3.5-turbo")

# Option 2: Better accuracy (costs more)
# llm = ChatOpenAI(model="gpt-4")

# Option 3: Use Claude
# from langchain_anthropic import ChatAnthropic
# llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")

# Option 4: Use multiple (expert routing)
# cheap_llm = ChatOpenAI(model="gpt-3.5-turbo")
# expensive_llm = ChatOpenAI(model="gpt-4")
# Use cheap for simple cases, expensive for complex ones
```

---

## Ready!

You're all set. Just get your OpenAI key and run:

```bash
export OPENAI_API_KEY="sk-proj-YOUR_KEY"
cd backend && python main.py
```

💰 Save 50% compared to Claude!
