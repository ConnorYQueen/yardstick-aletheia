"""OpenAI backend for the Aletheia runner (alternative provider).

Pure OpenAI SDK. Run the agent on GPT instead of Claude with:

    python aletheia.py --provider openai

The neutral {role, content} history the runner keeps works as-is; the
system prompt is prepended as a system message.
"""
from __future__ import annotations

API_KEY_VAR = "OPENAI_API_KEY"


def default_model() -> str:
    # A current frontier OpenAI model. Override with --model or ALETHEIA_MODEL
    # (e.g. gpt-4o) if your key does not have access to this one.
    return "gpt-5"


def make_client():
    from openai import OpenAI
    # Reads OPENAI_API_KEY from the environment (the runner also loads .env).
    return OpenAI()


def _open_stream(client, model, chat, max_tokens):
    """Start a streaming completion, honoring --max-tokens across model
    families: newer models take max_completion_tokens, older ones max_tokens.
    Try the newer name, fall back to the older, then to no cap -- all before
    any text streams, so no output is duplicated."""
    base = dict(model=model, messages=chat, stream=True)
    for attempt in ({"max_completion_tokens": max_tokens},
                    {"max_tokens": max_tokens},
                    {}):
        try:
            return client.chat.completions.create(**base, **attempt)
        except Exception:
            continue
    # Last resort: surface the real error from the plain call.
    return client.chat.completions.create(**base)


def stream_reply(client, system, messages, model, max_tokens):
    """Yield text deltas for one assistant turn via Chat Completions."""
    chat = [{"role": "system", "content": system}] + messages
    stream = _open_stream(client, model, chat, max_tokens)
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
