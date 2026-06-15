# Aletheia - your Yardstick strategy agent

Aletheia (pronounced ah-LEH-thay-ah; Greek for truth, "un-concealment") is the
strategy agent included with the Yardstick Research Full AI Deployment report.
It coaches you from where your audit found you toward a revenue function that
runs agent-first under human governance: through your stage's exit gates, up
the autonomy ladder, on your own numbers.

This folder is a small, readable program you run on your own machine, against
your own model API key. Aletheia is model-agnostic - run her on Claude, GPT,
or another provider. Your audit data never leaves your computer except as a
request to the model provider you choose. As you work, she keeps persistent
memory across sessions and builds reusable skills you own.

## What's here

| File | What it is |
|---|---|
| `aletheia.py` | The runner: the agent itself. |
| `_backends/` | One file per model provider (Anthropic, OpenAI). |
| `CHOOSE-YOUR-MODEL.md` | Which model to run her on, given your stack. |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Template for your API key. |
| `ALETHEIA.md` | The agent's instructions, personalized to your audit. * |
| `audit-data.json` | Your audit results. * |
| `memory/`, `skills/` | Created as you go: her notes + the skills she builds you. |

\* The two starred files come from your Yardstick bundle. `unlock` fetches
`audit-data.json` for you, or drop your own beside `aletheia.py`.

## Run it

You need Python 3.9+ and a model API key.

```bash
pip install -r requirements.txt
python aletheia.py unlock CODE       # enter the code from your PDF / PowerPoint
python aletheia.py setup             # pick the best model for your stack, write .env
# add your API key to .env, then:
python aletheia.py                   # start (or resume) a session
```

`python aletheia.py --check` verifies setup without an API call. Type your
questions; Aletheia answers from your audit data, saves memory, and builds
skills as you go (you'll see `[saved memory: ...]` / `[created skill: ...]`).
Type `exit` or press Ctrl-D to quit; next time, `python aletheia.py` resumes
from your saved memory.

## Choosing a model

Claude (`claude-opus-4-8`) is the default; `python aletheia.py setup`
recommends the best fit for your stack and writes it to `.env`. See
`CHOOSE-YOUR-MODEL.md`. To run on OpenAI: `pip install openai` then
`python aletheia.py --provider openai`. Override per run with `--model`, or set
`ALETHEIA_PROVIDER` / `ALETHEIA_MODEL` in `.env`. Adding another provider is
one small file in `_backends/` exposing the same four functions.

## Memory and skills

Aletheia writes plain Markdown: `memory/` holds her notes on where you are and
what you decided (reloaded every session); `skills/<name>/SKILL.md` holds
reusable processes she builds so you own the capability internally instead of
renting it from a vendor. Both are yours - portable, readable, and usable on
any agent platform.

## Deliverables (decks, PDFs, financial models)

Ask Aletheia to build a stakeholder deck, a PDF (for example a retraining plan
for affected employees), or a financial projection, and she writes the file to
`artifacts/` in your branding. Install the optional builders first:

```bash
pip install python-pptx fpdf2 openpyxl
```

Set your branding once by copying `brand.json.example` to `brand.json` (company
name, colors, logo file, and a confidentiality footer / classification label),
or just let Aletheia ask you. Before she builds anything she runs a short
compliance check - which regime applies, what must be redacted, what markings
to stamp - and honors it. Everything is generated on your machine with no
network call, so it is safe for regulated and locked-down environments.

## Your data

`audit-data.json` holds your audit responses and the numbers derived from them.
This program sends them only to the model provider you select, and stores
nothing beyond the terminal session. The folder is yours; share it inside your
organization as you see fit.

Questions about your report, a re-audit, or anything in your bundle:
hello@yardstickresearch.app. The published methodology behind every number:
https://yardstickresearch.app/methodology/.
