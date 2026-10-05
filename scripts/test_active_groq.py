import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_groq():
    groq_key = os.getenv("GROQ_API_KEY")
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
    for m in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]:
        payload = {
            "model": m,
            "messages": [{"role": "user", "content": "Respond with JSON: {\"status\": \"ok\"}"}],
            "response_format": {"type": "json_object"}
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(groq_url, headers=headers, json=payload)
            print(f"Model {m}: {resp.status_code}")
            if resp.status_code == 200:
                print("  Response:", resp.json()["choices"][0]["message"]["content"])

if __name__ == "__main__":
    asyncio.run(test_groq())
