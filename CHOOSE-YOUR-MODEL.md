# Choose your model

Aletheia is model-agnostic. She runs the same coaching on whatever frontier
model you point her at, so pick the one whose procurement and data-residency
path is shortest for your environment. You do not need a Claude account.

## Our recommendation for you

Based on your declared stack (no declared stack in your audit yet (run `unlock` first)):

- **Provider: Anthropic (Claude)**
- **Model: claude-opus-4-8**
- Why: No strong cloud lock-in shows up in your stack, so the default is Claude Opus, the strongest model for the reasoning-heavy strategy work Aletheia does.

`python aletheia.py setup` will detect this and offer to write it to your
`.env` for you.

## The general guidance

| If your stack is anchored on... | Run Aletheia on | Why |
|---|---|---|
| AWS | Claude (`claude-opus-4-8`), first-party on AWS | Inherits your AWS data-residency + security review |
| Microsoft 365 / Azure | GPT via Azure OpenAI (or Copilot) | Stays in your Microsoft tenant + procurement |
| Google Cloud | A Vertex AI model | Stays in your GCP data boundary |
| No strong cloud lock-in | Claude Opus (the default) | Strongest model for reasoning-heavy strategy work |

This is about procurement and data residency, not capability: the frontier
models are all strong enough for this work. Run her where your security review
is already done.

## How to set it

- Easiest: `python aletheia.py setup` (recommends + writes `.env`).
- By hand: set `ALETHEIA_PROVIDER` and `ALETHEIA_MODEL` in `.env`, plus the
  matching API key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`).
- Per run: `python aletheia.py --provider openai --model gpt-5`.

## Run her fully self-hosted (maximum data control)

If you want nothing to leave your network, run Aletheia on a local,
OpenAI-compatible server - Ollama, vLLM, and LM Studio all expose one:

- `--provider openai` (the OpenAI backend speaks the compatible API),
- set `OPENAI_BASE_URL` to your local server and `OPENAI_API_KEY` to any
  non-empty value it accepts,
- set `ALETHEIA_MODEL` to the model your server serves.

Her reasoning then runs on hardware you control, on data that never leaves it.
This is the deepest form of owning your substrate; she can also build you a plan
for self-hosting the rest of your AI stack (ask her, or see the
self-hosting-readiness skill and https://github.com/mikeroyal/Self-Hosting-Guide).

Anthropic and OpenAI are built in. Any other provider is one small file in
`_backends/` exposing the same functions the existing backends do.
