"""AI ki jaanch: uv run python -m app.ai_check
Active provider admin panel ki DB se aata hai (warna .env fallback). Key kabhi print nahi hoti."""
import httpx

from .services import llm

cfg = llm.get_runtime_config()
if cfg is None:
    raise SystemExit("Koi AI provider set nahi: admin panel se key save karein ya .env fallback dijiye.")

print("Provider:", cfg.provider_name, "| model:", cfg.model_name, "| key set:", bool(cfg.api_key),
      "| key length:", len(cfg.api_key), "| source:", cfg.source)

if cfg.source == "environment" and cfg.provider_name == "gemini":
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.model_name}:generateContent"
    headers = {"x-goog-api-key": cfg.api_key}
    body = {"contents": [{"parts": [{"text": "Say hello in one word"}]}]}
else:
    url = f"{llm.PROVIDER_BASE_URLS[cfg.provider_name].rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    body = {"model": cfg.model_name, "messages": [{"role": "user", "content": "Say hello in one word"}],
            "max_tokens": 20}

try:
    r = httpx.post(url, headers=headers, timeout=90, json=body)
except httpx.HTTPError as e:
    raise SystemExit(f"Provider tak pahunch nahi saka (internet?): {type(e).__name__}")

print("HTTP status:", r.status_code)
try:
    j = r.json()
    if r.status_code != 200:
        print("Provider ka error:", j.get("error", {}).get("message", j.get("error", j)))
    elif "choices" in j:
        print("Jawab:", j["choices"][0]["message"]["content"])
    else:
        print("Jawab:", j["candidates"][0]["content"]["parts"][0]["text"])
except (ValueError, KeyError, IndexError, TypeError) as e:
    print("Jawab parh nahi saka:", type(e).__name__)
