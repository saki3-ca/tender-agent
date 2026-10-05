import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_gemini_extraction():
    gemini_key = os.getenv("GEMINI_API_KEY")
    for model in ["gemini-2.5-flash", "gemini-3.8-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        payload = {
            "contents": [{"parts": [{"text": "Extract in JSON: {\"is_opportunity\": \"YES\", \"category\": \"AUDIT_ASSURANCE\"}"}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            print(f"Gemini {model} response code: {resp.status_code}")
            if resp.status_code == 200:
                print(f"Success from {model}: {resp.json()['candidates'][0]['content']['parts'][0]['text']}")

if __name__ == "__main__":
    asyncio.run(test_gemini_extraction())
