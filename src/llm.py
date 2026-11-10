"""
llm.py — one provider-agnostic wrapper.

Swap providers by changing `provider=` or the DEFAULT_PROVIDER below.
Free options: 'gemini' (aistudio.google.com/app/apikey), 'groq' (console.groq.com).
Keys are read from environment (.env locally, or Streamlit secrets when deployed).
"""
import os

from dotenv import load_dotenv

load_dotenv()  # read keys from .env when running locally

DEFAULT_PROVIDER = "gemini"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")


def _get_key(name: str) -> str:
    key = os.environ.get(name)
    if not key:
        raise RuntimeError(
            f"Missing {name}. Add it to your .env (local) or Streamlit secrets (deployed)."
        )
    return key


def call_llm(prompt: str, system: str | None = None, provider: str | None = None) -> str:
    """Return the model's text response as a plain string."""
    provider = provider or DEFAULT_PROVIDER

    if provider == "gemini":
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=_get_key("GEMINI_API_KEY"))
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system or "You are a precise data assistant.",
            ),
        )
        return resp.text.strip()

    if provider == "groq":
        from groq import Groq
        client = Groq(api_key=_get_key("GROQ_API_KEY"))
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile", messages=messages
        )
        return resp.choices[0].message.content.strip()

    raise ValueError(f"Unknown provider: {provider}")


if __name__ == "__main__":
    # smoke test:  python src/llm.py
    print(call_llm("Reply with exactly: wrapper OK"))
