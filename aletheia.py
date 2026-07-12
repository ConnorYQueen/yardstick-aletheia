#!/usr/bin/env python3
"""Aletheia - your Yardstick strategy agent, run in your own environment.

Aletheia is model-agnostic: she runs on whatever frontier model fits your
stack (Claude by default, OpenAI with one flag, any provider via a small
backend file). She coaches you from your audited state toward a revenue
function that runs agent-first under human governance - and as you go, she
writes persistent MEMORY files (so she remembers across sessions) and creates
SKILLS you can reuse, building your own internal AI capability instead of
renting permanent dependence on vendors.

Commands:

    python aletheia.py unlock CODE      # enter the code from your PDF / PowerPoint
    python aletheia.py setup            # pick the best model for your stack
    python aletheia.py                  # start (or resume) a coaching session
    python aletheia.py update           # refresh the runner from the public repo
    python aletheia.py status           # portfolio view of your automation projects
    python aletheia.py --check          # verify setup without an API call

The first time you run her she asks for your integration code; it's printed in
your Full AI Deployment PDF and PowerPoint. She then coaches from your audit
results - either the audit-data.json in this folder, or what you read to her
from your report.

Files this folder uses:

    ALETHEIA.md          the agent's instructions (personalized to you)
    audit-data.json      your audit results (if shipped; otherwise you provide them)
    CHOOSE-YOUR-MODEL.md which model to run her on, given your stack
    memory/              persistent notes Aletheia keeps across sessions
    skills/              reusable skills Aletheia builds for you
    sessions/            transcripts of your sessions (JSONL, local only)
    data/                optional: drop CSV/JSON/text exports here and she
                         reads summaries of them as measured inputs

The only network calls are to the model provider you choose, plus the explicit
`unlock` and `update` fetches from Yardstick.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNLOCK_MARKER = ".aletheia-unlocked"

BACKENDS = {
    "anthropic": "_backends.anthropic_backend",
    "openai": "_backends.openai_backend",
}

# Model-agnostic directives. Aletheia emits these in her replies; the runner
# parses them out, writes/builds the files, and shows a one-line confirmation
# instead of the raw block. Works on ANY instruction-following model -- no
# provider-specific tool-call API required.
#   @aletheia:memory <path>        ... markdown ...          -> memory/<path>.md
#   @aletheia:skill  <name>        ... SKILL.md ...           -> skills/<name>/SKILL.md
#   @aletheia:brand                ... JSON ...               -> brand.json
#   @aletheia:deck   title="..."   ... JSON spec ...          -> artifacts/<slug>.pptx
#   @aletheia:doc    title="..."   ... JSON spec ...          -> artifacts/<slug>.pdf
#   @aletheia:sheet  title="..."   ... JSON spec ...          -> artifacts/<slug>.xlsx
#   @aletheia:dashboard title="..." ... JSON spec ...         -> artifacts/<slug>.html
#   @aletheia:eval   <name>        ... JSON cases ...         -> eval/<name>.cases.json
# Each block ends with a line: @aletheia:end
DIRECTIVE_RE = re.compile(
    r"@aletheia:(memory|skill|brand|deck|doc|sheet|dashboard|eval)[ \t]*([^\n]*?)[ \t]*\n(.*?)\n@aletheia:end",
    re.DOTALL,
)


def _parse_title(arg: str) -> str:
    m = re.search(r'''title\s*=\s*["']([^"']+)["']''', arg)
    return (m.group(1) if m else arg).strip().strip('"').strip("'")

FIRST_PROMPT = ("Start our first session. Read my state back to me, tell me the "
                "one gap you would close first, and save a memory file with where "
                "we're starting.")

# --- stack -> model guidance (advisory; see CHOOSE-YOUR-MODEL.md) -----------
# Maps a buyer's cloud / platform lock-in to the provider whose procurement and
# data-residency path is shortest for them. Default is Claude for reasoning-heavy
# strategy work when there's no strong lock-in.
MODEL_GUIDE = [
    ("aws",        "anthropic", "claude-opus-4-8",
     "Claude is first-party on AWS (Bedrock / Claude on AWS), so it inherits your existing AWS data-residency and security review."),
    ("azure",      "openai", "gpt-5",
     "GPT runs through Azure OpenAI inside your existing Microsoft tenant and procurement boundary."),
    ("microsoft",  "openai", "gpt-5",
     "A Microsoft 365 / Azure-heavy stack keeps the shortest procurement + data path on GPT via Azure OpenAI (or Copilot)."),
    ("gcp",        "openai", "gpt-5",
     "On Google Cloud, run via Vertex AI; set --model to your preferred Vertex model. (Add a Gemini backend if you want it native.)"),
    ("google",     "openai", "gpt-5",
     "On Google Cloud, run via Vertex AI; set --model to your preferred Vertex model."),
]


# ---------------------------------------------------------------------------
# .env handling
# ---------------------------------------------------------------------------

def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        if key and key not in os.environ:
            os.environ[key] = value


def set_env_var(path: Path, key: str, value: str) -> None:
    """Idempotently set KEY=value in a .env file (create if absent)."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, found = [], False
    for line in lines:
        if line.strip().startswith(f"{key}=") and not line.strip().startswith("#"):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# memory + skills (model-agnostic persistence)
# ---------------------------------------------------------------------------

def _safe_member(name: str) -> str:
    """Sanitize a model-supplied path/name to a safe slug (no traversal)."""
    name = name.strip().strip("/").replace("\\", "/")
    name = re.sub(r"[^A-Za-z0-9_\-/. ]", "", name).replace(" ", "-")
    parts = [p for p in name.split("/") if p and p not in (".", "..")]
    return "/".join(parts)


def load_memory_and_skills(pack_dir: Path) -> str:
    """Return a context block of everything Aletheia has saved so far, so she
    remembers across sessions. Empty string on a first run."""
    blocks = []
    mem_dir = pack_dir / "memory"
    if mem_dir.is_dir():
        files = sorted(p for p in mem_dir.rglob("*.md") if p.is_file())
        if files:
            blocks.append("## Your saved memory (from earlier sessions)\n")
            for f in files:
                rel = f.relative_to(pack_dir).as_posix()
                blocks.append(f"### {rel}\n\n{f.read_text(encoding='utf-8').strip()}\n")
    skills_dir = pack_dir / "skills"
    if skills_dir.is_dir():
        skills = sorted(p for p in skills_dir.glob("*/SKILL.md") if p.is_file())
        if skills:
            blocks.append("## Skills you have already created\n")
            for s in skills:
                first = s.read_text(encoding="utf-8").strip().splitlines()
                title = next((l.lstrip("# ").strip() for l in first if l.strip()), s.parent.name)
                blocks.append(f"- {s.parent.name}: {title}")
    return "\n".join(blocks).strip()


def apply_directives(reply: str, pack_dir: Path) -> str:
    """Find @aletheia:* blocks in a reply, write/build the files, and replace
    each block with a one-line confirmation for display."""
    import _artifacts  # local module; cheap (heavy libs load lazily per builder)

    def write(match) -> str:
        kind, arg, content = match.group(1), match.group(2), match.group(3)
        try:
            if kind == "memory":
                slug = _safe_member(arg)
                if not slug:
                    return "[skipped a malformed memory directive]"
                if not slug.endswith(".md"):
                    slug += ".md"
                dest = pack_dir / "memory" / slug
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content.strip() + "\n", encoding="utf-8")
                return f"[saved memory: memory/{slug}]"
            if kind == "skill":
                slug = _safe_member(arg)
                if not slug:
                    return "[skipped a malformed skill directive]"
                name = slug.split("/")[0]
                dest = pack_dir / "skills" / name / "SKILL.md"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content.strip() + "\n", encoding="utf-8")
                return f"[created skill: skills/{name}/]"
            if kind == "brand":
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    return "[skipped branding: the block was not valid JSON]"
                (pack_dir / "brand.json").write_text(
                    json.dumps(data, indent=2), encoding="utf-8")
                return "[saved branding + compliance settings: brand.json]"
            if kind == "eval":
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    return "[skipped eval: the cases block was not valid JSON]"
                name = (_safe_member(arg).split("/")[0] or "cases")
                for suffix in (".json", ".cases"):
                    if name.endswith(suffix):
                        name = name[: -len(suffix)]
                dest = pack_dir / "eval" / f"{name}.cases.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return (f"[saved eval cases: eval/{name}.cases.json -- run "
                        f"`python aletheia.py eval --cases eval/{name}.cases.json`]")
            if kind in _artifacts.BUILDERS:
                try:
                    spec = json.loads(content)
                except json.JSONDecodeError:
                    return f"[skipped {kind}: the spec was not valid JSON]"
                title = _parse_title(arg) or spec.get("title") or kind.capitalize()
                out = (pack_dir / "artifacts" /
                       f"{_artifacts._slug(title, kind)}.{_artifacts.EXT[kind]}")
                brand = _artifacts.load_brand(pack_dir)
                return _artifacts.BUILDERS[kind](title, spec, brand, pack_dir, out)
        except Exception as e:
            return f"[could not build {kind}: {e}]"
        return "[skipped an unknown directive]"
    return DIRECTIVE_RE.sub(write, reply)


# ---------------------------------------------------------------------------
# local data ingestion (opt-in: files the buyer drops into data/)
# ---------------------------------------------------------------------------
# Summaries only, never whole files: column shapes + a few sample rows for
# tabular data, a head excerpt for text. The block is labeled [MEASURED]
# because these are the buyer's own exports, read locally -- nothing is
# uploaded anywhere except to the model provider with the rest of the prompt.

DATA_TOTAL_BUDGET = 60_000     # chars across all summarized files
DATA_TEXT_EXCERPT = 4_000      # chars of head excerpt per text/JSON file
DATA_CSV_ROW_CAP = 20_000      # rows read per CSV before we stop counting stats
DATA_CELL_CAP = 120            # chars per sample cell


def _summarize_csv(path: Path, delimiter: str) -> str:
    import csv
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            return "(empty file)"
        samples, stats, rows = [], {}, 0
        for row in reader:
            rows += 1
            if len(samples) < 5:
                samples.append([c[:DATA_CELL_CAP] for c in row[:len(header)]])
            for i, cell in enumerate(row[:len(header)]):
                try:
                    v = float(cell.replace(",", ""))
                except ValueError:
                    continue
                lo, hi, tot, n = stats.get(i, (v, v, 0.0, 0))
                stats[i] = (min(lo, v), max(hi, v), tot + v, n + 1)
            if rows >= DATA_CSV_ROW_CAP:
                break
    lines = [f"columns: {', '.join(h[:DATA_CELL_CAP] for h in header)}",
             f"rows: {rows}{'+' if rows >= DATA_CSV_ROW_CAP else ''}"]
    for i, (lo, hi, tot, n) in sorted(stats.items()):
        if n >= max(2, rows // 2) and i < len(header):
            lines.append(f"{header[i][:DATA_CELL_CAP]}: min {lo:g}, max {hi:g}, "
                         f"mean {tot / n:g} (over {n} numeric values)")
    if samples:
        lines.append("sample rows:")
        lines.extend("  " + " | ".join(r) for r in samples)
    return "\n".join(lines)


def load_local_data(pack_dir: Path) -> str:
    """Summaries of files the buyer put in data/. Empty string if none."""
    data_dir = pack_dir / "data"
    if not data_dir.is_dir():
        return ""
    files = sorted(p for p in data_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in
                   (".csv", ".tsv", ".json", ".md", ".txt"))
    if not files:
        return ""
    blocks = ["## The buyer's local data files (data/)\n",
              "These are [MEASURED] values: the buyer's own exports, dropped "
              "into the data/ folder and summarized locally. Ground numeric "
              "claims in them where they apply.\n"]
    used = sum(len(b) for b in blocks)
    skipped = []
    for f in files:
        if used >= DATA_TOTAL_BUDGET:
            skipped.append(f.name)
            continue
        try:
            if f.suffix.lower() in (".csv", ".tsv"):
                body = _summarize_csv(f, "\t" if f.suffix.lower() == ".tsv" else ",")
            else:
                text = f.read_text(encoding="utf-8", errors="replace").strip()
                body = text[:DATA_TEXT_EXCERPT]
                if len(text) > DATA_TEXT_EXCERPT:
                    body += f"\n... (excerpt; file is {len(text):,} chars)"
        except Exception as e:
            body = f"(could not read: {e})"
        block = f"### data/{f.name}\n\n{body}\n"
        blocks.append(block)
        used += len(block)
    if skipped:
        blocks.append(f"(budget reached; not summarized: {', '.join(skipped)} -- "
                      "ask the buyer about these directly)")
    return "\n".join(blocks).strip()


# ---------------------------------------------------------------------------
# system prompt
# ---------------------------------------------------------------------------

def build_system_prompt(pack_dir: Path) -> str:
    prompt_path = pack_dir / "ALETHEIA.md"
    data_path = pack_dir / "audit-data.json"
    if not prompt_path.exists():
        raise SystemExit(f"Missing {prompt_path.name}. Run this from your "
                         "Yardstick pack folder (the one with ALETHEIA.md).")
    prompt = prompt_path.read_text(encoding="utf-8")
    if data_path.exists():
        if data_path.stat().st_size > 1_000_000:
            raise SystemExit(f"{data_path.name} is unexpectedly large; "
                             "use the audit-data.json from your Yardstick bundle.")
        prompt += ("\n\n## Your audit data (audit-data.json)\n\n"
                   "Treat these as the buyer's [MEASURED] values; prefer any "
                   "newer numbers they give you in conversation.\n\n```json\n"
                   + data_path.read_text(encoding="utf-8") + "\n```\n")
    else:
        prompt += ("\n\n## Your audit data\n\nNo audit-data.json is present yet. "
                   "Before coaching from numbers, ask the buyer to read their audit "
                   "results off their Yardstick report and tell you: their score, "
                   "their stage, and their per-dimension scores. Capture what they "
                   "give you to a memory file so you keep it.\n")
    local_data = load_local_data(pack_dir)
    if local_data:
        prompt += "\n\n" + local_data + "\n"
    saved = load_memory_and_skills(pack_dir)
    if saved:
        prompt += "\n\n" + saved + "\n"
    return prompt


# ---------------------------------------------------------------------------
# setup: pick the best model for the buyer's stack
# ---------------------------------------------------------------------------

def _declared_stack(pack_dir: Path) -> list[str]:
    data_path = pack_dir / "audit-data.json"
    if not data_path.exists():
        return []
    try:
        d = json.loads(data_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    stack = []
    buyer = d.get("buyer", {})
    if buyer.get("crm"):
        stack.append(str(buyer["crm"]))
    arch = (d.get("audit", {}) or {}).get("reference_architecture", {}) or {}
    for layer in arch.get("layers", []):
        for node in layer.get("nodes", []):
            if node.get("status") == "EXISTING" and node.get("system"):
                stack.append(str(node["system"]))
    return stack


def recommend_model(stack: list[str]) -> tuple:
    """(provider, model, rationale) from declared stack; Claude default."""
    blob = " ".join(stack).lower()
    for needle, provider, model, why in MODEL_GUIDE:
        if needle in blob:
            return provider, model, why
    return ("anthropic", "claude-opus-4-8",
            "No strong cloud lock-in detected, so the default is Claude Opus -- "
            "the strongest model for the reasoning-heavy strategy work Aletheia does.")


# Services Aletheia can run on. Most are OpenAI-compatible -- the openai backend
# reaches them by pointing OPENAI_BASE_URL at the service -- so one backend
# covers OpenRouter, Azure, the open-weights hosts, and local servers; Anthropic
# is direct. setup asks which one the buyer wants.
SERVICES = [
    {"key": "anthropic", "label": "Anthropic API (Claude direct)",
     "provider": "anthropic", "base_url": "", "key_var": "ANTHROPIC_API_KEY",
     "model": "claude-opus-4-8",
     "note": "Claude direct -- strongest for the reasoning-heavy strategy work."},
    {"key": "openai", "label": "OpenAI API (GPT direct)",
     "provider": "openai", "base_url": "", "key_var": "OPENAI_API_KEY",
     "model": "gpt-5", "note": "GPT direct."},
    {"key": "openrouter",
     "label": "OpenRouter (one key, many models: Claude, GPT, Gemini, Llama)",
     "provider": "openai", "base_url": "https://openrouter.ai/api/v1",
     "key_var": "OPENAI_API_KEY", "model": "anthropic/claude-opus-4-8",
     "note": "OpenAI-compatible aggregator; switch models without switching keys -- handy for comparing models with `eval`."},
    {"key": "local",
     "label": "A local / self-hosted server (Ollama, vLLM, LM Studio)",
     "provider": "openai", "base_url": "http://localhost:11434/v1",
     "key_var": "OPENAI_API_KEY", "model": "",
     "note": "Runs on your hardware; nothing leaves your network."},
    {"key": "compatible",
     "label": "Another OpenAI-compatible service (Azure, Together, Groq, Fireworks)",
     "provider": "openai", "base_url": "", "key_var": "OPENAI_API_KEY", "model": "",
     "note": "Set the service's endpoint as OPENAI_BASE_URL and your key."},
]


def _recommended_service_key(stack: list[str]) -> str:
    provider, _, _ = recommend_model(stack)
    return "anthropic" if provider == "anthropic" else "openai"


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def cmd_setup(pack_dir: Path) -> int:
    stack = _declared_stack(pack_dir)
    rec_key = _recommended_service_key(stack)
    rec_idx = next(i for i, s in enumerate(SERVICES, 1) if s["key"] == rec_key)

    print("Aletheia setup -- choose the service you want to run her on\n")
    if stack:
        print(f"Detected from your audit: {', '.join(stack)}\n")
    print("She is model-agnostic. Pick the service that fits your environment:\n")
    for i, s in enumerate(SERVICES, 1):
        tag = "   [recommended for your stack]" if s["key"] == rec_key else ""
        print(f"  {i}. {s['label']}{tag}")
        print(f"     {s['note']}")
    print("\nSee CHOOSE-YOUR-MODEL.md for the full guidance.\n")

    raw = _ask(f"Which service? [1-{len(SERVICES)}, default {rec_idx}] ")
    if not raw:
        choice = SERVICES[rec_idx - 1]
    else:
        n = None
        try:
            n = int(raw)
        except ValueError:
            n = None
        if n is None or not (1 <= n <= len(SERVICES)):
            print("Not a listed option; nothing written. Re-run `python aletheia.py setup`.")
            return 1
        choice = SERVICES[n - 1]

    # Services we don't preset a URL for (or where the buyer may differ) get asked.
    base_url = choice["base_url"]
    if choice["key"] in ("local", "compatible"):
        shown = f" [{base_url}]" if base_url else ""
        base_url = _ask(f"Server URL (OPENAI_BASE_URL){shown}: ") or base_url

    model = choice["model"]
    shown = f" [{model}]" if model else " (the model id your service serves)"
    model = _ask(f"Model{shown}: ") or model

    env = pack_dir / ".env"
    set_env_var(env, "ALETHEIA_PROVIDER", choice["provider"])
    if model:
        set_env_var(env, "ALETHEIA_MODEL", model)
    if base_url:
        set_env_var(env, "OPENAI_BASE_URL", base_url)

    print(f"\nWrote .env: provider={choice['provider']}"
          + (f", model={model}" if model else "")
          + (f", OPENAI_BASE_URL={base_url}" if base_url else ""))
    note = (" (for OpenRouter or a compatible service, your key goes in OPENAI_API_KEY)"
            if choice["provider"] == "openai" and base_url else "")
    print(f"Now put your key in {choice['key_var']} in .env{note}. "
          "Then run `python aletheia.py`.")
    return 0


# ---------------------------------------------------------------------------
# unlock: the integration code from the paid PDF / PowerPoint
# ---------------------------------------------------------------------------
# Soft, local proof-of-purchase check (no network call). MAINTAINER RULE: never
# surface the code's exact shape to a user in any prompt, error, or doc -- a
# format-only gate is worthless if we tell people the format. Point users to
# their PDF / PowerPoint and nothing more.

def code_is_valid(code: str) -> bool:
    # Soft local pre-check only; the server is the real authority. Accept the
    # legacy short code and the current opaque token alike, so a buyer's code
    # is never rejected here before it can be verified. Kept permissive on
    # purpose -- never narrow this to a single exact shape.
    code = (code or "").strip().upper()
    if len(code) == 8 and code[:2] == "AI":
        return True
    return code.isalnum() and 16 <= len(code) <= 64


def is_unlocked(pack_dir: Path) -> bool:
    return (pack_dir / UNLOCK_MARKER).exists()


def mark_unlocked(pack_dir: Path, code: str) -> None:
    (pack_dir / UNLOCK_MARKER).write_text(code.strip().upper() + "\n", encoding="utf-8")


def _maybe_fetch_personalized(pack_dir: Path, code: str, email: str | None = None) -> None:
    """Offer to fetch the buyer's personalized pack files from Yardstick.

    Only fires when audit-data.json is absent (a repo clone rather than the
    shipped zip). A fetch failure never blocks the local unlock -- Aletheia
    still runs; the buyer can retry or read their numbers to her.
    """
    if (pack_dir / "audit-data.json").exists():
        return
    if not email:
        email = _ask("Email you purchased with (fetches your personalized audit "
                     "files; Enter to skip): ")
    if not email:
        return
    import _sync
    print("Fetching your personalized files from Yardstick...")
    ok, message = _sync.fetch_pack(pack_dir, code, email)
    print(message)


def cmd_unlock(pack_dir: Path, code: str, email: str | None = None) -> int:
    if not code_is_valid(code):
        raise SystemExit("That code wasn't accepted. Find your integration code in "
                         "your Full AI Deployment PDF or PowerPoint.")
    mark_unlocked(pack_dir, code)
    _maybe_fetch_personalized(pack_dir, code, email)
    print("Unlocked. Run `python aletheia.py setup` to pick your model, then "
          "`python aletheia.py`.")
    return 0


def prompt_for_code(pack_dir: Path) -> bool:
    """Ask for the integration code on first run; True once unlocked.
    Never describe the code's shape -- only where to find it."""
    if is_unlocked(pack_dir):
        return True
    print("Enter your integration code to begin. You'll find it in your Full AI "
          "Deployment PDF or PowerPoint.\n")
    for _ in range(3):
        try:
            code = input("code > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if code_is_valid(code):
            mark_unlocked(pack_dir, code)
            _maybe_fetch_personalized(pack_dir, code)
            print("Unlocked.\n")
            return True
        print("That code wasn't accepted. Check your Full AI Deployment PDF or "
              "PowerPoint and try again.\n")
    print("No valid code entered. Your code is in your Full AI Deployment PDF or "
          "PowerPoint; questions: hello@yardstickresearch.app.")
    return False


# ---------------------------------------------------------------------------
# run: the coaching session
# ---------------------------------------------------------------------------

def resolve_backend(args):
    provider = (args.provider or os.environ.get("ALETHEIA_PROVIDER") or "anthropic").lower()
    if provider not in BACKENDS:
        raise SystemExit(f"Unknown provider {provider!r}. Choose: {', '.join(BACKENDS)}.")
    try:
        backend = importlib.import_module(BACKENDS[provider])
    except ImportError:
        raise SystemExit(f"The {provider} SDK is not installed. Run: pip install -r requirements.txt")
    model = args.model or os.environ.get("ALETHEIA_MODEL") or backend.default_model()
    if not os.environ.get(backend.API_KEY_VAR):
        raise SystemExit(f"No API key found. Set {backend.API_KEY_VAR} in your environment "
                         "or in a .env file next to this script (copy .env.example to .env).")
    return provider, backend, model


def _session_log_path(pack_dir: Path) -> Path:
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return pack_dir / "sessions" / f"session-{ts}.jsonl"


def _log_turn(path: Path, role: str, content: str) -> None:
    """Append one turn to the session transcript. Best-effort: a full disk or
    locked file must never kill the live session."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"role": role, "content": content}) + "\n")
    except OSError:
        pass


def _trim_history(messages: list, budget_chars: int) -> int:
    """Drop the oldest user/assistant pairs in place once the transcript grows
    past budget_chars, keeping at least the last 2 completed exchanges plus the
    pending turn. Returns how many pairs were dropped this call. Memory files
    carry the long arc; the live window only needs the recent turns."""
    dropped = 0
    def total() -> int:
        return sum(len(m.get("content") or "") for m in messages)
    # This runs just after the pending user turn is appended, so len is odd;
    # a floor of 5 leaves two full exchanges (4 messages) plus that turn.
    while total() > budget_chars and len(messages) > 5:
        del messages[0:2]
        dropped += 1
    return dropped


def _offer_exit_summary(backend, client, system, messages, model, max_tokens, pack_dir) -> None:
    """On a typed exit after a real session, offer to bank the session into
    memory so the next session starts where this one ended."""
    if sum(1 for m in messages if m["role"] == "assistant") < 2:
        return
    ans = _ask("Save a session summary to memory before you go? [Y/n] ")
    if ans.lower().startswith("n"):
        return
    print("[summarizing...]", flush=True)
    ask = messages + [{"role": "user", "content":
        "We are ending this session. Emit ONE @aletheia:memory directive "
        "updating memory/progress.md with: where we are, decisions made this "
        "session, and the next actions with owners. Emit the directive block "
        "and nothing else."}]
    try:
        result = backend.complete_once(client, system, ask, model, max_tokens)
        reply = result.get("text", "") if isinstance(result, dict) else str(result)
        confirmation = apply_directives(reply, pack_dir)
        for line in confirmation.splitlines():
            if line.strip().startswith("["):
                print(line.strip())
    except Exception as exc:
        print(f"[could not save the summary: {exc}]")


def cmd_run(args, pack_dir: Path) -> int:
    if not prompt_for_code(pack_dir):
        return 1
    system = build_system_prompt(pack_dir)
    provider, backend, model = resolve_backend(args)
    client = backend.make_client()
    messages: list[dict] = []
    log_path = _session_log_path(pack_dir)
    trimmed_pairs = 0

    print("=" * 64)
    print("  Aletheia - your Yardstick strategy agent")
    print(f"  {provider} / {model}")
    print("=" * 64)
    print("She coaches from your audit and saves memory + builds skills as you go.")
    print("Type exit or press Ctrl-D to quit. A good first prompt:\n")
    print(f"  {FIRST_PROMPT}\n")

    while True:
        try:
            user = input("you > ").strip()
        except EOFError:
            # Ctrl-D is an ordinary quit (the banner says so), so give it the
            # same save-memory offer a typed `exit` gets.
            print()
            _offer_exit_summary(backend, client, system, messages, model,
                                args.max_tokens, pack_dir)
            return 0
        except KeyboardInterrupt:
            # Ctrl-C is an interrupt, not a graceful exit: leave immediately.
            print()
            return 0
        if not user:
            continue
        if user.lower() in ("exit", "quit", ":q"):
            _offer_exit_summary(backend, client, system, messages, model,
                                args.max_tokens, pack_dir)
            return 0

        messages.append({"role": "user", "content": user})
        trimmed_pairs += _trim_history(messages, args.history_chars)
        live_system = system
        if trimmed_pairs:
            live_system += (f"\n\n[Context note: the first {trimmed_pairs} "
                            "exchange(s) of this session were trimmed to fit the "
                            "context window; trust your memory files for "
                            "anything from earlier.]")
        print("\naletheia > ", end="", flush=True)
        parts: list[str] = []
        try:
            for chunk in backend.stream_reply(client, live_system, messages, model, args.max_tokens):
                parts.append(chunk)
                print(chunk, end="", flush=True)
        except KeyboardInterrupt:
            print("\n[stopped]\n")
            messages.pop()
            continue
        except Exception as exc:
            print(f"\n[error from {provider}: {exc}]\n")
            messages.pop()
            continue
        reply = "".join(parts)
        # Persist any memory/skill files Aletheia wrote this turn, and show
        # the confirmations in place of the raw directive blocks.
        shown = apply_directives(reply, pack_dir)
        if shown != reply:
            print("\n" + "\n".join(l for l in shown.splitlines()
                                   if l.strip().startswith("[")), end="")
        print("\n")
        messages.append({"role": "assistant", "content": reply})
        _log_turn(log_path, "user", user)
        _log_turn(log_path, "assistant", reply)


def cmd_check(args, pack_dir: Path) -> int:
    system = build_system_prompt(pack_dir)
    provider, backend, model = resolve_backend(args)
    print(f"OK  provider : {provider}")
    print(f"OK  model    : {model}")
    print(f"OK  api key  : {backend.API_KEY_VAR} is set")
    print(f"OK  files    : ALETHEIA.md loaded ({len(system):,} chars incl. audit + memory)")
    data_dir = pack_dir / "data"
    n_data = sum(1 for p in data_dir.iterdir() if p.is_file()) if data_dir.is_dir() else 0
    print(f"OK  data     : {n_data} file(s) in data/ "
          + ("(summarized into her context)" if n_data else "(drop CSV/JSON/text exports there to ground her in your numbers)"))
    print("\nReady. Run `python aletheia.py` to start.")
    return 0


# Field lines cmd_status reads out of a project ledger file. Aletheia maintains
# these files through the ordinary memory directive (memory/projects/<slug>.md),
# so the ledger needs no new machinery and travels with the rest of her memory.
STATUS_FIELDS = ("status", "rung", "owner", "next gate", "gate due", "gate status")
_STATUS_ORDER = {"active": 0, "paused": 1, "done": 2}


def cmd_status(pack_dir: Path) -> int:
    """Print the automation portfolio from memory/projects/*.md. No API call:
    this is the harness view of the ledger Aletheia keeps -- one file per
    automation pod, updated as gates pass. Format + roadmap: ORCHESTRATION.md."""
    proj_dir = pack_dir / "memory" / "projects"
    files = sorted(proj_dir.glob("*.md")) if proj_dir.is_dir() else []
    if not files:
        print("No projects tracked yet.")
        print("In a session, ask Aletheia to set up your project ledger: she keeps")
        print("one memory/projects/<name>.md per automation pod and updates it as")
        print("gates pass. Then this command shows the whole portfolio at a glance.")
        return 0

    rows = []
    for f in files:
        name, info = f.stem, {}
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("# ") and "titled" not in info:
                name = s[2:].strip() or name
                info["titled"] = "1"
                continue
            m = re.match(r"[-*]\s*([A-Za-z ]+):\s*(.+)", s)
            if m and m.group(1).strip().lower() in STATUS_FIELDS:
                info[m.group(1).strip().lower()] = m.group(2).strip()
        rows.append((name, info))
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r[1].get("status", "").lower(), 0), r[0].lower()))

    headers = ("Project", "Status", "Rung", "Next gate", "Due", "Gate status", "Owner")
    keys = (None, "status", "rung", "next gate", "gate due", "gate status", "owner")
    table = [headers]
    for name, info in rows:
        table.append(tuple((name if k is None else info.get(k, "-"))[:40] for k in keys))
    widths = [max(len(r[i]) for r in table) for i in range(len(headers))]
    for i, r in enumerate(table):
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
        if i == 0:
            print("  ".join("-" * w for w in widths))

    n_active = sum(1 for _, i in rows if i.get("status", "").lower() == "active")
    print(f"\n{len(rows)} project(s), {n_active} active. Details: memory/projects/. "
          "Ask Aletheia for the dashboard to share this with stakeholders.")
    return 0


def cmd_eval(args, pack_dir: Path) -> int:
    """Measure cost per outcome across models for one task, so a routing call is
    evidence, not a guess. Calls only the providers in your models file, on your
    key -- the same trust boundary as a normal session."""
    if not prompt_for_code(pack_dir):
        return 1
    import _eval
    cases_path = Path(args.cases) if args.cases else pack_dir / "eval" / "cases.example.json"
    models_path = Path(args.models) if args.models else pack_dir / "eval" / "models.example.json"
    if not cases_path.exists():
        raise SystemExit(f"No cases file at {cases_path}. Copy eval/cases.example.json and "
                         "edit it, or ask Aletheia to write a set for your task.")
    if not models_path.exists():
        raise SystemExit(f"No models file at {models_path}. Copy eval/models.example.json and "
                         "set the models + prices you want to compare.")
    cases = _eval.load_cases(cases_path)
    models = _eval.load_models(models_path)

    target = args.target
    if target is None:
        try:
            raw = json.loads(models_path.read_text(encoding="utf-8"))
            target = float(raw.get("target_pass_rate", 0.9)) if isinstance(raw, dict) else 0.9
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            target = 0.9

    clients: dict = {}

    def complete_fn(provider, model, system, prompt, max_tokens):
        provider = (provider or "anthropic").lower()
        if provider not in BACKENDS:
            raise RuntimeError(f"unknown provider {provider!r}")
        if provider not in clients:
            backend = importlib.import_module(BACKENDS[provider])
            if not os.environ.get(backend.API_KEY_VAR):
                raise RuntimeError(f"{backend.API_KEY_VAR} not set")
            clients[provider] = (backend, backend.make_client())
        backend, client = clients[provider]
        return backend.complete_once(
            client, system, [{"role": "user", "content": prompt}], model, max_tokens)

    # Optional LLM judge for checks a string match can't score (tone, structure,
    # "would a customer accept this"). Configured explicitly in the models file:
    #   "judge": {"provider": "anthropic", "model": "claude-opus-4-8"}
    judge_fn = None
    judge_cfg = None
    try:
        raw = json.loads(models_path.read_text(encoding="utf-8"))
        judge_cfg = raw.get("judge") if isinstance(raw, dict) else None
    except (json.JSONDecodeError, OSError):
        judge_cfg = None
    has_judge_checks = any(
        (chk.get("type") == "judge")
        for case in cases for chk in (case.get("checks") or []))
    if has_judge_checks and not judge_cfg:
        raise SystemExit(
            'Your cases use "judge" checks, but the models file has no judge '
            'configured. Add e.g. "judge": {"provider": "anthropic", '
            '"model": "claude-opus-4-8"} to your models JSON, then re-run.')
    if judge_cfg:
        j_provider = str(judge_cfg.get("provider") or "anthropic")
        j_model = str(judge_cfg.get("model") or "")
        if not j_model:
            raise SystemExit('The "judge" entry in your models file needs a "model".')

        def judge_fn(output, criteria):
            usage = complete_fn(
                j_provider, j_model,
                "You are a strict evaluator. Reply with exactly PASS or FAIL "
                "and nothing else.",
                f"Criteria: {criteria}\n\nOutput to judge:\n{output}\n\n"
                "Does the output meet the criteria? Reply PASS or FAIL.",
                16)
            up = str(usage.get("text") or "").upper()
            p, f = up.find("PASS"), up.find("FAIL")
            return p != -1 and (f == -1 or p < f)

    print(f"Running {len(cases)} case(s) across {len(models)} model(s) "
          "(this calls each provider on your key)...\n")
    results = _eval.run_eval(cases, models, complete_fn, args.max_tokens, judge_fn=judge_fn)
    report = _eval.render_report(results, target)
    if judge_cfg:
        report += (f"\n\nJudge: {j_provider}/{j_model} scored the judge checks. "
                   "Judge calls are not included in the cost columns.\n")
    print(report)
    out = pack_dir / "eval" / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[saved: {out.relative_to(pack_dir).as_posix()}]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Aletheia - your Yardstick strategy agent.")
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "setup", "unlock", "check", "eval", "update", "status"],
                    help="run (default), setup (pick a model), unlock <CODE>, check, "
                         "eval (measure cost per outcome across models), "
                         "update (refresh the runner from the public repo).")
    ap.add_argument("code", nargs="?", help="integration code (for `unlock`).")
    ap.add_argument("--provider", choices=sorted(BACKENDS))
    ap.add_argument("--model")
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--email", help="unlock: the email you purchased with "
                    "(fetches your personalized audit files).")
    ap.add_argument("--history-chars", type=int, default=240_000,
                    help="run: transcript size before the oldest exchanges are "
                         "trimmed (memory files carry the long arc).")
    ap.add_argument("--dir", type=Path, default=HERE)
    ap.add_argument("--cases", help="eval: path to a cases JSON (default eval/cases.example.json).")
    ap.add_argument("--models", help="eval: path to a models JSON (default eval/models.example.json).")
    ap.add_argument("--target", type=float, default=None,
                    help="eval: target pass rate 0-1 (default from the models file, else 0.9).")
    ap.add_argument("--check", action="store_true", help=argparse.SUPPRESS)  # legacy alias
    args = ap.parse_args()

    pack_dir = args.dir.expanduser().resolve()
    load_dotenv(pack_dir / ".env")
    load_dotenv(HERE / ".env")

    if args.check or args.command == "check":
        return cmd_check(args, pack_dir)
    if args.command == "setup":
        return cmd_setup(pack_dir)
    if args.command == "unlock":
        return cmd_unlock(pack_dir, args.code or "", args.email)
    if args.command == "eval":
        return cmd_eval(args, pack_dir)
    if args.command == "update":
        import _sync
        print(_sync.self_update(str(pack_dir)))
        return 0
    if args.command == "status":
        return cmd_status(pack_dir)
    return cmd_run(args, pack_dir)


if __name__ == "__main__":
    raise SystemExit(main())
