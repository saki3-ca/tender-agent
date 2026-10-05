import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_models():
    groq_key = os.getenv("GROQ_API_KEY")
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
    for model in ["llama-3.1-8b-instant", "llama-3.1-70b-versatile", "llama3-70b-8192", "mixtral-8x7b-32768", "gemma2-9b-it"]:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 10
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(groq_url, headers=headers, json=payload)
                print(f"Groq ({model}) status:", resp.status_code)
                if resp.status_code == 200:
                    print(f"  -> SUCCESS: {resp.json()['choices'][0]['message']['content']}")
        except Exception as e:
            print(f"Groq ({model}) exception:", e)

    gemini_key = os.getenv("GEMINI_API_KEY")
    for model in ["gemini-3.8-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        payload = {"contents": [{"parts": [{"text": "ping"}]}]}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(gemini_url, json=payload)
                print(f"Gemini ({model}) status:", resp.status_code)
                if resp.status_code == 200:
                    print(f"  -> SUCCESS: {resp.json()['candidates'][0]['content']['parts'][0]['text']}")
        except Exception as e:
            print(f"Gemini ({model}) exception:", e)

if __name__ == "__main__":
    asyncio.run(test_models())
