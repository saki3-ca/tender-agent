import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def list_gemini():
    gemini_key = os.getenv("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        print("Gemini list models status:", resp.status_code)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            print("Active Gemini models:", models)
        else:
            print("Error response:", resp.text)

if __name__ == "__main__":
    asyncio.run(list_gemini())
