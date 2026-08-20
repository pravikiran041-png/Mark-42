import requests
import json
from pathlib import Path
import sys

def _get_keys() -> dict:
    base_dir = Path(__file__).resolve().parent.parent if not getattr(sys, "frozen", False) else Path(sys.executable).parent
    config_path = base_dir / "config" / "api_keys.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def call_ai(prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    keys = _get_keys()
    
    # 1. Try Groq first (fastest)
    result = try_groq(prompt, system, max_tokens, keys.get("groq_api_key", ""))
    if result:
        return result
        
    # 2. Try Gemini Free (Google AI Studio)
    result = try_gemini_free(prompt, system, max_tokens, keys.get("gemini_api_key", ""))
    if result:
        return result
        
    # 3. Try OpenRouter free models
    result = try_openrouter(prompt, system, max_tokens, keys.get("openrouter_api_key", ""))
    if result:
        return result
        
    return "Research unavailable Sir, all AI services are at capacity or API keys are missing."

def try_groq(prompt: str, system: str, max_tokens: int, key: str) -> str | None:
    if not key: return None
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return None
    except:
        return None

def try_gemini_free(prompt: str, system: str, max_tokens: int, key: str) -> str | None:
    if not key: return None
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={key}",
            json={
                "contents": [{
                    "parts": [{"text": f"{system}\n\n{prompt}"}]
                }],
                "generationConfig": {"maxOutputTokens": max_tokens}
            },
            timeout=60
        )
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return None
    except:
        return None

def try_openrouter(prompt: str, system: str, max_tokens: int, key: str) -> str | None:
    if not key: return None
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://holojarvis.app"
            },
            json={
                "model": "meta-llama/llama-3.3-70b-instruct:free",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens
            },
            timeout=60
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return None
    except:
        return None
