"""Cost-per-outcome eval harness for the Aletheia runner.

Turns a model-routing recommendation into evidence. You give it a small set of
CASES (a task prompt plus deterministic checks on the output) and a set of
MODELS to compare; it runs every model on every case, scores pass/fail, reads
real token usage, and reports each model's pass rate and COST PER OUTCOME -- so
you route each step to the cheapest model that clears the bar, instead of
guessing.

It calls only the providers you configured, on your own key -- the same trust
boundary as a normal Aletheia session. Nothing else leaves your machine.

Run it via:  python aletheia.py eval --cases eval/<your>.cases.json

This module is pure logic; aletheia.py:cmd_eval supplies the model-call
callback, so the providers stay in the backends.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path


def load_cases(path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases", []) if isinstance(data, dict) else data
    out = []
    for c in cases:
        if not isinstance(c, dict) or "prompt" not in c:
            continue
        out.append({
            "name": str(c.get("name") or f"case-{len(out) + 1}"),
            "system": str(c.get("system") or ""),
            "prompt": str(c["prompt"]),
            "checks": c.get("checks") or [],
        })
    if not out:
        raise ValueError(f"No usable cases in {path} (each case needs a 'prompt').")
    return out


def load_models(path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    models = data.get("models", []) if isinstance(data, dict) else data
    out = []
    for m in models:
        if not isinstance(m, dict) or "model" not in m:
            continue
        out.append({
            "name": str(m.get("name") or m["model"]),
            "provider": str(m.get("provider") or "anthropic"),
            "model": str(m["model"]),
            "price_in": float(m.get("price_per_million_input", 0) or 0),
            "price_out": float(m.get("price_per_million_output", 0) or 0),
        })
    if not out:
        raise ValueError(f"No usable models in {path} (each needs a 'model').")
    return out


def check_output(text: str, checks: list) -> tuple:
    """Deterministic scoring. Check types: contains, not_contains, equals,
    iequals, regex. All must pass. Returns (passed, failed_descriptions).

    Deterministic checks fit the routine, high-volume steps where model routing
    saves the most; judgment-heavy steps stay on the frontier model and are not
    what this harness is for."""
    failed = []
    low = text.lower()
    for chk in checks or []:
        t = str(chk.get("type", "contains")).lower()
        v = str(chk.get("value", ""))
        if t == "contains":
            ok = v in text
        elif t == "not_contains":
            ok = v not in text
        elif t == "equals":
            ok = text.strip() == v.strip()
        elif t == "iequals":
            ok = text.strip().lower() == v.strip().lower()
        elif t == "regex":
            ok = re.search(v, text) is not None
        else:
            ok = v.lower() in low  # unknown type -> lenient contains
        if not ok:
            failed.append(f"{t}:{v[:40]}")
    return (len(failed) == 0, failed)


def _cost(usage: dict, price_in: float, price_out: float) -> float:
    return (usage.get("input_tokens", 0) / 1_000_000 * price_in
            + usage.get("output_tokens", 0) / 1_000_000 * price_out)


def run_eval(cases, models, complete_fn, max_tokens) -> list:
    """complete_fn(provider, model, system, prompt, max_tokens) -> usage dict
    {text, input_tokens, output_tokens}. Returns per-model result rows."""
    results = []
    for m in models:
        passed = 0
        total_cost = 0.0
        total_tokens = 0
        total_latency = 0.0
        errors = 0
        per_case = []
        for c in cases:
            t0 = time.monotonic()
            try:
                usage = complete_fn(m["provider"], m["model"],
                                    c["system"], c["prompt"], max_tokens)
                dt = time.monotonic() - t0
                ok, failed = check_output(usage.get("text", ""), c["checks"])
                total_cost += _cost(usage, m["price_in"], m["price_out"])
                total_tokens += (usage.get("input_tokens", 0)
                                 + usage.get("output_tokens", 0))
                total_latency += dt
                if ok:
                    passed += 1
                per_case.append({"name": c["name"], "ok": ok, "failed": failed})
            except Exception as e:  # one bad call must not sink the whole run
                errors += 1
                per_case.append({"name": c["name"], "ok": False,
                                 "failed": [f"error: {str(e)[:60]}"]})
        n = len(cases)
        priced = m["price_in"] > 0 or m["price_out"] > 0
        results.append({
            "name": m["name"], "provider": m["provider"], "model": m["model"],
            "n": n, "passed": passed, "pass_rate": (passed / n if n else 0.0),
            "errors": errors, "total_cost": total_cost, "priced": priced,
            "total_tokens": total_tokens,
            "avg_latency": (total_latency / n if n else 0.0),
            "cost_per_pass": (total_cost / passed if (priced and passed) else None),
            "per_case": per_case,
        })
    return results


def render_report(results, target) -> str:
    lines = [f"# Cost-per-outcome eval (target pass rate: {int(target * 100)}%)\n"]
    any_priced = any(r["priced"] for r in results)
    lines.append("| Model | Provider | Pass rate | Tokens | Cost | Cost / passing outcome |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        cost = f"${r['total_cost']:.4f}" if r["priced"] else "set price"
        cpp = f"${r['cost_per_pass']:.4f}" if r["cost_per_pass"] is not None else "-"
        lines.append("| {} | {} | {}/{} ({:.0f}%) | {:,} | {} | {} |".format(
            r["name"], r["provider"], r["passed"], r["n"], r["pass_rate"] * 100,
            r["total_tokens"], cost, cpp))
    lines.append("")

    qualifying = [r for r in results if r["pass_rate"] >= target]
    if not qualifying:
        best = max(results, key=lambda r: r["pass_rate"]) if results else None
        if best:
            lines.append(
                f"No model cleared the {int(target * 100)}% bar. Highest was "
                f"{best['name']} at {best['pass_rate'] * 100:.0f}%. Tighten the task, "
                f"raise the model, or lower the target with --target.")
    elif any_priced and all(q["cost_per_pass"] is not None for q in qualifying):
        pick = min(qualifying, key=lambda r: r["cost_per_pass"])
        lines.append(
            f"Route this task to {pick['name']} ({pick['provider']} / {pick['model']}): "
            f"it clears {int(target * 100)}% at the lowest cost per outcome "
            f"(${pick['cost_per_pass']:.4f}).")
    else:
        pick = min(qualifying, key=lambda r: r["total_tokens"])
        lines.append(
            f"Of the models that clear {int(target * 100)}%, {pick['name']} uses the "
            f"fewest tokens. Set per-model prices in your models file to rank by cost "
            f"per outcome.")

    fails = [(r["name"], pc["name"], pc["failed"]) for r in results
             for pc in r["per_case"] if not pc["ok"]]
    if fails:
        lines.append("\n## Misses\n")
        for model_name, case_name, failed in fails[:40]:
            lines.append(f"- {model_name} / {case_name}: {', '.join(failed)}")
    return "\n".join(lines) + "\n"
