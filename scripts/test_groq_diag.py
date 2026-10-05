import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def inspect_groq():
    groq_key = os.getenv("GROQ_API_KEY")
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.1-70b-versatile",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 50
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(groq_url, headers=headers, json=payload)
        print("Groq status:", resp.status_code)
        print("Groq response:", resp.text)

if __name__ == "__main__":
    asyncio.run(inspect_groq())
