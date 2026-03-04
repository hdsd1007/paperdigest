"""
llm_client.py
-------------
Calls Google Gemini for all LLM tasks (PDF parsing, summarization, diagram planning).
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int


def llm_call(
    prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    pdf_bytes: bytes | None = None,
) -> LLMResponse:
    """Single entry point for all LLM calls."""
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(MODEL)

    parts = []
    if pdf_bytes:
        parts.append({"mime_type": "application/pdf", "data": pdf_bytes})
    parts.append(prompt)

    response = model.generate_content(
        parts,
        generation_config=genai.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        ),
    )

    usage = response.usage_metadata
    inp = getattr(usage, "prompt_token_count", 0) or 0
    out = getattr(usage, "candidates_token_count", 0) or 0

    return LLMResponse(text=response.text, input_tokens=inp, output_tokens=out)
