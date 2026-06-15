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

Nothing is sent anywhere except to the model provider you choose.
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
#   @aletheia:eval   <name>        ... JSON cases ...         -> eval/<name>.cases.json
# Each block ends with a line: @aletheia:end
DIRECTIVE_RE = re.compile(
    r"@aletheia:(memory|skill|brand|deck|doc|sheet|eval)[ \t]*([^\n]*?)[ \t]*\n(.*?)\n@aletheia:end",
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


def cmd_setup(pack_dir: Path) -> int:
    stack = _declared_stack(pack_dir)
    provider, model, why = recommend_model(stack)
    print("Aletheia setup -- choosing the best model for your stack\n")
    if stack:
        print(f"Detected from your audit: {', '.join(stack)}\n")
    else:
        print("No declared stack found in audit-data.json (run `unlock` first, or "
              "this is the generic template).\n")
    print(f"Recommended provider: {provider}")
    print(f"Recommended model:    {model}")
    print(f"Why: {why}\n")
    print("See CHOOSE-YOUR-MODEL.md for the full guidance and how to run on any "
          "other provider.\n")
    ans = input(f"Write these to .env (provider={provider}, model={model})? [y/N] ").strip().lower()
    if ans in ("y", "yes"):
        env = pack_dir / ".env"
        set_env_var(env, "ALETHEIA_PROVIDER", provider)
        set_env_var(env, "ALETHEIA_MODEL", model)
        key_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        print(f"\nWrote .env. Now add your {key_var} to .env, then run `python aletheia.py`.")
    else:
        print("\nNothing written. Set ALETHEIA_PROVIDER / ALETHEIA_MODEL in .env yourself, "
              "or pass --provider / --model when you run.")
    return 0


# ---------------------------------------------------------------------------
# unlock: the integration code from the paid PDF / PowerPoint
# ---------------------------------------------------------------------------
# Soft, local proof-of-purchase check (no network call). MAINTAINER RULE: never
# surface the code's exact shape to a user in any prompt, error, or doc -- a
# format-only gate is worthless if we tell people the format. Point users to
# their PDF / PowerPoint and nothing more.

def code_is_valid(code: str) -> bool:
    code = (code or "").strip()
    return len(code) == 8 and code[:2].upper() == "AI"


def is_unlocked(pack_dir: Path) -> bool:
    return (pack_dir / UNLOCK_MARKER).exists()


def mark_unlocked(pack_dir: Path, code: str) -> None:
    (pack_dir / UNLOCK_MARKER).write_text(code.strip().upper() + "\n", encoding="utf-8")


def cmd_unlock(pack_dir: Path, code: str) -> int:
    if not code_is_valid(code):
        raise SystemExit("That code wasn't accepted. Find your integration code in "
                         "your Full AI Deployment PDF or PowerPoint.")
    mark_unlocked(pack_dir, code)
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


def cmd_run(args, pack_dir: Path) -> int:
    if not prompt_for_code(pack_dir):
        return 1
    system = build_system_prompt(pack_dir)
    provider, backend, model = resolve_backend(args)
    client = backend.make_client()
    messages: list[dict] = []

    print("=" * 64)
    print("  Aletheia - your Yardstick strategy agent")
    print(f"  {provider} / {model}")
    print("=" * 64)
    print("She coaches from your audit and saves memory + builds skills as you go.")
    print("Type 'exit' or press Ctrl-D to quit. A good first prompt:\n")
    print(f"  {FIRST_PROMPT}\n")

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
        parts: list[str] = []
        try:
            for chunk in backend.stream_reply(client, system, messages, model, args.max_tokens):
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


def cmd_check(args, pack_dir: Path) -> int:
    system = build_system_prompt(pack_dir)
    provider, backend, model = resolve_backend(args)
    print(f"OK  provider : {provider}")
    print(f"OK  model    : {model}")
    print(f"OK  api key  : {backend.API_KEY_VAR} is set")
    print(f"OK  files    : ALETHEIA.md loaded ({len(system):,} chars incl. audit + memory)")
    print("\nReady. Run `python aletheia.py` to start.")
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

    print(f"Running {len(cases)} case(s) across {len(models)} model(s) "
          "(this calls each provider on your key)...\n")
    results = _eval.run_eval(cases, models, complete_fn, args.max_tokens)
    report = _eval.render_report(results, target)
    print(report)
    out = pack_dir / "eval" / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[saved: {out.relative_to(pack_dir).as_posix()}]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Aletheia - your Yardstick strategy agent.")
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "setup", "unlock", "check", "eval"],
                    help="run (default), setup (pick a model), unlock <CODE>, check, "
                         "eval (measure cost per outcome across models).")
    ap.add_argument("code", nargs="?", help="integration code (for `unlock`).")
    ap.add_argument("--provider", choices=sorted(BACKENDS))
    ap.add_argument("--model")
    ap.add_argument("--max-tokens", type=int, default=8000)
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
        return cmd_unlock(pack_dir, args.code or "")
    if args.command == "eval":
        return cmd_eval(args, pack_dir)
    return cmd_run(args, pack_dir)


if __name__ == "__main__":
    raise SystemExit(main())
