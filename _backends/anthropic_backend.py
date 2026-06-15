"""Anthropic backend for the Aletheia runner (the default provider).

Pure Anthropic SDK. Uses the Messages API with adaptive thinking and
streaming, and caches the large system prompt across turns so a long
coaching session stays cheap.
"""
from __future__ import annotations

API_KEY_VAR = "ANTHROPIC_API_KEY"


def default_model() -> str:
    # The current frontier Claude model. Override with --model or
    # ALETHEIA_MODEL (e.g. claude-sonnet-4-6 for a cheaper, faster run).
    return "claude-opus-4-8"


def make_client():
    import anthropic
    # Reads ANTHROPIC_API_KEY from the environment (the runner also loads .env).
    return anthropic.Anthropic()


def _is_param_error(exc: Exception) -> bool:
    """True when the failure is the SDK/model rejecting the advanced params
    (old SDK that doesn't accept the kwarg, or a model that doesn't support
    adaptive thinking / effort) -- as opposed to a real error like a bad key,
    which should surface. Param errors raise at call time, before any text
    streams, so falling back never double-prints output."""
    if isinstance(exc, TypeError):
        return True
    if getattr(exc, "status_code", None) == 400:
        return True
    needle = str(exc).lower()
    return any(w in needle for w in
               ("output_config", "thinking", "effort", "unexpected keyword"))


def _stream(client, system, messages, model, max_tokens, advanced):
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=messages,
    )
    if advanced:
        # Adaptive thinking lets the model decide how much to reason per
        # question; effort tunes depth. Both are current frontier-model
        # features; the caller falls back without them on older SDKs or
        # models that don't support them.
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "high"}
    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            yield text


def stream_reply(client, system, messages, model, max_tokens):
    """Yield text deltas for one assistant turn.

    The system prompt (your ALETHEIA.md + audit data) is sent as a cached
    block, so every turn after the first reuses it at a fraction of the cost.
    """
    try:
        yield from _stream(client, system, messages, model, max_tokens, advanced=True)
    except Exception as exc:
        if _is_param_error(exc):
            yield from _stream(client, system, messages, model, max_tokens, advanced=False)
        else:
            raise


def complete_once(client, system, messages, model, max_tokens):
    """One non-streaming completion -> {text, input_tokens, output_tokens}.

    Used by the cost-per-outcome eval harness. Plain settings (no adaptive
    thinking / effort) so the eval measures the model the way a deployed
    workflow would run it, and reads real token usage off the response."""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system}],
        messages=messages,
    )
    text = "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", "") == "text")
    u = getattr(resp, "usage", None)
    return {
        "text": text,
        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
    }
