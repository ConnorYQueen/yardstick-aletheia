#!/usr/bin/env python3
"""Aletheia - run your Yardstick strategy agent on your own machine.

This is a small command-line chat agent. It loads two files that ship in
your Yardstick bundle:

    ALETHEIA.md      - the agent's instructions, personalized to your audit
    audit-data.json  - your audit results (scores, gaps, ROI, 90-day plan)

and runs them against a frontier model using YOUR OWN API key, so your
audit data never leaves your machine except as a request to the model
provider you choose. Claude (Anthropic) is the default; OpenAI is built in
as an alternative, and any other provider is a short backend file away.

Quick start:

    pip install -r requirements.txt
    cp .env.example .env        # then put your API key in .env
    python aletheia.py

Type your questions; Aletheia answers from your audit data. Type 'exit'
(or Ctrl-D) to quit. Run `python aletheia.py --check` to confirm setup
without making an API call.

No data is sent anywhere except to the model provider you select. Nothing
is stored beyond this terminal session.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Provider -> backend module under _backends/. Each backend is single-
# provider on purpose: one SDK per file, no shims, no mixing.
BACKENDS = {
    "anthropic": "_backends.anthropic_backend",
    "openai": "_backends.openai_backend",
}

FIRST_PROMPTS = [
    "Start our first session. Read my state back to me and tell me the one gap you would close first.",
    "List the exit gates for my stage and mark which ones I can already evidence.",
    "My CFO wants the savings math defended. Rehearse the three hardest questions she will ask.",
]


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency). KEY=VALUE per line; existing
    environment variables win, so an exported key is never overwritten."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip one matched surrounding quote pair (not every quote char).
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            # Unquoted: drop an inline " # comment" tail.
            value = value.split(" #", 1)[0].rstrip()
        if key and key not in os.environ:
            os.environ[key] = value


def build_system_prompt(pack_dir: Path) -> str:
    """System prompt = the personalized ALETHEIA.md, with the buyer's
    audit-data.json appended so the agent has the exact values inline."""
    prompt_path = pack_dir / "ALETHEIA.md"
    data_path = pack_dir / "audit-data.json"
    if not prompt_path.exists():
        raise SystemExit(f"Missing {prompt_path.name}. Run this from your "
                         "Yardstick pack folder (the one with ALETHEIA.md).")
    prompt = prompt_path.read_text(encoding="utf-8")
    if data_path.exists():
        # Guard against a corrupted / oversized data file blowing the model's
        # context window. A real audit-data.json is tens of KB.
        if data_path.stat().st_size > 1_000_000:
            raise SystemExit(f"{data_path.name} is unexpectedly large "
                             f"({data_path.stat().st_size:,} bytes). "
                             "Use the audit-data.json from your Yardstick bundle.")
        data = data_path.read_text(encoding="utf-8")
        prompt += ("\n\n## Your audit data (audit-data.json)\n\n"
                   "The full data file is below. Treat these as the buyer's "
                   "[MEASURED] values; prefer any newer numbers they give you "
                   "in conversation.\n\n```json\n" + data + "\n```\n")
    return prompt


def resolve(args) -> tuple:
    """Resolve provider + backend + model + key from flags and env."""
    provider = (args.provider or os.environ.get("ALETHEIA_PROVIDER")
                or "anthropic").lower()
    if provider not in BACKENDS:
        raise SystemExit(f"Unknown provider {provider!r}. "
                         f"Choose one of: {', '.join(BACKENDS)}.")
    try:
        backend = importlib.import_module(BACKENDS[provider])
    except ImportError:
        raise SystemExit(
            f"The {provider} SDK is not installed. Run:\n"
            f"    pip install -r requirements.txt")
    model = args.model or os.environ.get("ALETHEIA_MODEL") or backend.default_model()
    key_var = backend.API_KEY_VAR
    if not os.environ.get(key_var):
        raise SystemExit(
            f"No API key found. Set {key_var} in your environment or in a "
            f".env file next to this script (copy .env.example to .env).")
    return provider, backend, model


def main() -> int:
    ap = argparse.ArgumentParser(description="Aletheia - your Yardstick strategy agent.")
    ap.add_argument("--provider", choices=sorted(BACKENDS),
                    help="Model provider (default: anthropic, or $ALETHEIA_PROVIDER).")
    ap.add_argument("--model", help="Model id (default: the provider's frontier model, or $ALETHEIA_MODEL).")
    ap.add_argument("--max-tokens", type=int, default=8000, help="Max tokens per reply (default 8000).")
    ap.add_argument("--dir", type=Path, default=HERE,
                    help="Folder holding ALETHEIA.md + audit-data.json (default: this folder).")
    ap.add_argument("--check", action="store_true",
                    help="Verify setup (files, SDK, key, model) without calling the API.")
    args = ap.parse_args()
    args.dir = args.dir.expanduser().resolve()

    # Load .env from the data folder first (where .env.example tells you to put
    # it), then the script folder as a fallback. Already-set env vars win, so
    # an exported key is never overwritten.
    load_dotenv(args.dir / ".env")
    load_dotenv(HERE / ".env")

    system = build_system_prompt(args.dir)
    provider, backend, model = resolve(args)

    if args.check:
        print(f"OK  provider : {provider}")
        print(f"OK  model    : {model}")
        print(f"OK  api key  : {backend.API_KEY_VAR} is set")
        print(f"OK  files    : ALETHEIA.md loaded ({len(system):,} chars incl. audit data)")
        print("\nReady. Run `python aletheia.py` (no --check) to start the session.")
        return 0

    client = backend.make_client()
    messages: list[dict] = []

    print("=" * 64)
    print("  Aletheia - your Yardstick strategy agent")
    print(f"  {provider} / {model}")
    print("=" * 64)
    print("Ask about your gaps, your exit gates, or your next move.")
    print("Type 'exit' or press Ctrl-D to quit. A good first prompt:\n")
    print(f"  {FIRST_PROMPTS[0]}\n")

    while True:
        try:
            user = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        if user.lower() in ("exit", "quit", ":q"):
            return 0

        messages.append({"role": "user", "content": user})
        print("\naletheia > ", end="", flush=True)
        reply_parts: list[str] = []
        try:
            for chunk in backend.stream_reply(client, system, messages, model, args.max_tokens):
                reply_parts.append(chunk)
                print(chunk, end="", flush=True)
        except KeyboardInterrupt:  # Ctrl-C mid-reply stops this turn, not the session
            print("\n[stopped]")
            messages.pop()
            print()
            continue
        except Exception as exc:  # surface provider errors plainly, keep the session alive
            print(f"\n[error from {provider}: {exc}]")
            messages.pop()  # drop the unanswered turn so history stays consistent
            print()
            continue
        print("\n")
        messages.append({"role": "assistant", "content": "".join(reply_parts)})


if __name__ == "__main__":
    raise SystemExit(main())
