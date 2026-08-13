"""
gemini_client.py
-----------------
Thin wrapper around the Gemini REST API (generateContent), used for both:
  - plain chat answers (RAG-grounded medical Q&A)
  - multimodal OCR (transcribing scanned/handwritten pages)

No langchain_google_genai / google-generativeai SDK involved — just requests,
so it's easy to keep pointed at whatever model ID Google currently supports.
"""

import os
from typing import Optional

import requests

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
DEFAULT_TIMEOUT = 60


class GeminiError(Exception):
    pass


def _endpoint(model: str, api_key: str) -> str:
    return f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"


def _extract_text(response_json: dict) -> str:
    candidates = response_json.get("candidates") or []
    if not candidates:
        feedback = response_json.get("promptFeedback", {})
        reason = feedback.get("blockReason", "no candidates returned")
        raise GeminiError(f"Gemini returned no candidates ({reason})")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if "text" in p)
    return text.strip()


def _post(payload: dict, api_key: str, model: str, timeout: int) -> dict:
    if not api_key:
        raise GeminiError("Missing GEMINI_API_KEY")
    resp = requests.post(_endpoint(model, api_key), json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise GeminiError(f"Gemini API error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def generate_text(
    api_key: str,
    user_message: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.4,
    max_output_tokens: int = 1024,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Plain text -> text generation, with an optional system instruction."""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

    data = _post(payload, api_key, model or DEFAULT_MODEL, timeout)
    return _extract_text(data)


def generate_from_image(
    api_key: str,
    prompt: str,
    image_b64: str,
    mime_type: str = "image/png",
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_output_tokens: int = 2048,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Multimodal generation: an image + a text instruction (used for OCR)."""
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                ],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    data = _post(payload, api_key, model or DEFAULT_MODEL, timeout)
    return _extract_text(data)
