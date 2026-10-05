import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_ai():
    # Test Groq
    groq_key = os.getenv("GROQ_API_KEY")
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 10
    }
    print(f"Testing Groq with key {groq_key[:8]}...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(groq_url, headers=headers, json=payload)
            print("Groq status:", resp.status_code, resp.text[:200])
    except Exception as e:
        print("Groq exception:", e)

    # Test Gemini with 2.0-flash, 1.5-flash
    gemini_key = os.getenv("GEMINI_API_KEY")
    for model in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash"]:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        payload = {"contents": [{"parts": [{"text": "ping"}]}]}
        print(f"Testing Gemini model {model}...")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(gemini_url, json=payload)
                print(f"Gemini ({model}) status:", resp.status_code, resp.text[:200])
        except Exception as e:
            print(f"Gemini ({model}) exception:", e)

    # Test Cloudflare
    cf_account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    cf_token = os.getenv("CLOUDFLARE_API_TOKEN")
    cf_model = "@cf/baai/bge-m3"
    cf_url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/run/{cf_model}"
    print(f"Testing Cloudflare embeddings...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(cf_url, headers={"Authorization": f"Bearer {cf_token}"}, json={"text": ["test"]})
            print("Cloudflare status:", resp.status_code, resp.text[:200])
    except Exception as e:
        print("Cloudflare exception:", e)

if __name__ == "__main__":
    asyncio.run(test_ai())
