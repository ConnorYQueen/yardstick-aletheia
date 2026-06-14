# Aletheia - your Yardstick strategy agent

Aletheia (pronounced ah-LEH-thay-ah; Greek for truth, "un-concealment") is the
strategy agent included with the Yardstick Research Full AI Deployment report.
It coaches you from where your audit found you toward a revenue function that
runs agent-first under human governance: through your stage's exit gates, up
the autonomy ladder, on your own numbers.

This folder is a small, readable program you run on your own machine, against
your own model API key. Your audit data never leaves your computer except as a
request to the model provider you choose.

## What's here

| File | What it is |
|---|---|
| `aletheia.py` | The runner: a command-line chat agent. |
| `_backends/` | One file per model provider (Anthropic, OpenAI). |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Template for your API key. |
| `ALETHEIA.md` | The agent's instructions, personalized to your audit. * |
| `audit-data.json` | Your audit results. * |

\* The two starred files come from your Yardstick bundle. If you cloned this
from the public repository, drop your own `ALETHEIA.md` and `audit-data.json`
in beside `aletheia.py` before running.

## Run it

You need Python 3.9+ and a model API key (Anthropic by default).

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste your API key into .env
python aletheia.py --check    # confirms setup without calling the API
python aletheia.py            # starts the session
```

Type your questions; Aletheia answers from your audit data. A good first
prompt: *"Start our first session. Read my state back to me and tell me the
one gap you would close first."* Type `exit` or press Ctrl-D to quit.

## Run it on a different model

Claude (`claude-opus-4-8`) is the default. To run on OpenAI instead:

```bash
pip install openai
python aletheia.py --provider openai
```

Override the model per run with `--model`, or set `ALETHEIA_PROVIDER` /
`ALETHEIA_MODEL` in your `.env`. Adding another provider is one small file in
`_backends/` exposing the same four functions the existing backends do.

## Your data

`audit-data.json` holds your audit responses and the numbers derived from them.
This program sends them only to the model provider you select, and stores
nothing beyond the terminal session. The folder is yours; share it inside your
organization as you see fit.

Questions about your report, a re-audit, or anything in your bundle:
hello@yardstickresearch.app. The published methodology behind every number:
https://yardstickresearch.app/methodology/.
