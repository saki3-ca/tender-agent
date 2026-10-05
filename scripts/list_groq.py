import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def list_groq_models():
    groq_key = os.getenv("GROQ_API_KEY")
    headers = {"Authorization": f"Bearer {groq_key}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.groq.com/openai/v1/models", headers=headers)
        if resp.status_code == 200:
            models = [m["id"] for m in resp.json()["data"]]
            print("Active Groq models:", models)
        else:
            print("Failed to list Groq models:", resp.status_code, resp.text)

if __name__ == "__main__":
    asyncio.run(list_groq_models())
