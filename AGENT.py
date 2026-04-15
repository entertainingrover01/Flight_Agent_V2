import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():

    options = ClaudeAgentOptions(
        system_prompt="You are an EU261 expert, return JSON",
        #allowed_tools=["read","write"],
        allowed_tools=["str_replace_editor"],
        permission_mode="acceptEdits"
    )



    delay = input("please enter the flight delay reason or type exit: ")


    async for message in query(prompt=f"Analyze the {delay} and tell me if I can get compensation based on EU261 guidelines"
                                  f"and also create a file called claim.txt where you will create a claim email I can send to the airlines",options=options):
        print(message)



asyncio.run(main())


