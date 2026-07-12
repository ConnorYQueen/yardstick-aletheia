# Aletheia as a harness: orchestrating the whole portfolio

Aletheia started as a coach you talk to one session at a time. A deployment,
though, is not one conversation - it is a portfolio of automation projects
(pods), each moving through gates at its own pace. This document describes the
harness that makes her act on the portfolio, what already ships, and what comes
next. The design rule throughout: everything is plain files the buyer owns, on
the buyer's machine - no server, no scheduler dependency, no new trust
boundary.

## The spine that ships today

**The project ledger - `memory/projects/<slug>.md`.** One Markdown file per
automation pod, written and updated by Aletheia through her ordinary memory
directive, so it loads into every session with the rest of her memory. The
first heading names the project; these bullet lines feed the tooling:

    # Invoice intake automation

    - Status: active            (active | paused | done)
    - Rung: L2 -> L3
    - Owner: Ops lead
    - Next gate: 2 weeks at <1% correction rate
    - Gate due: 2026-08-01
    - Gate status: on_track     (passed | on_track | at_risk | blocked | pending)

    Free prose below: decisions, history, links to artifacts.

**`python aletheia.py status`.** The buyer-side portfolio view: a table of
every project, its rung, next gate, due date, and owner, straight from the
ledger with no API call. The empty state tells the buyer how to start.

**The autonomy dashboard (`@aletheia:dashboard`).** The stakeholder-facing
render of the same state - stage, savings, per-workflow rungs and gates - as a
single self-contained HTML file she regenerates whenever the numbers move.

**Session summaries.** On exit she offers to write where-we-are, decisions,
and next actions with owners to memory - so every session ends by advancing
the ledger, not just the conversation.

**Measured inputs (`data/`).** Buyer-dropped exports are summarized into her
context as measured numbers, which is what gate checks should run on.

**The eval harness (`python aletheia.py eval`).** Routing decisions per task
become evidence (pass rate and cost per outcome per model) instead of guesses.

Together these already close a loop: ledger in -> she proposes the
highest-leverage next moves across projects -> work happens -> gates update ->
ledger and dashboard out.

## Roadmap - in build order

1. **Standing agenda.** Open every session with a one-screen portfolio review:
   which gates are due or at risk, and the two or three moves that most
   advance the portfolio. This is prompt-side (ALETHEIA.md) plus a small
   runner nudge; no new machinery.

2. **Project-scoped sessions.** `python aletheia.py --project <slug>` loads
   only that project's ledger, its linked memory, and its skills - a focused
   working session that cannot drift across pods, and the unit a future
   multi-agent setup would parallelize.

3. **Gate checks.** Let a ledger file declare a mechanical check for its next
   gate - an eval cases file that must clear the target, or a threshold on a
   column in a `data/` export ("correction rate below 1% across the last 500
   rows"). `status` runs the checks and flips `Gate status` from evidence,
   with Aletheia handling the judgment gates that stay human.

4. **Scheduled refresh.** A non-interactive `python aletheia.py refresh` that
   re-summarizes `data/`, runs gate checks, regenerates the dashboard, and
   writes a short brief to memory - suitable for the buyer's own cron or Task
   Scheduler. Nothing sends anywhere; the buyer reads the brief next session.

5. **Delegation drafts.** A task ledger alongside the project ledger: actions
   with human owners, where Aletheia prepares the artifact (the email, the
   one-pager, the checklist) into `artifacts/` and the owner sends it. She
   never sends anything herself; that boundary is part of the product.

6. **One session per pod, one ledger for all.** With scoped sessions and gate
   checks in place, several Aletheia instances can each run a pod against the
   shared ledger. The ledger's file-per-project layout already avoids write
   collisions; `status` is already the merge view.

## What stays true at every step

 - Plain Markdown and JSON, readable and portable; the buyer can leave with
   everything.
 - Local first: the only network calls are to the model provider the buyer
   chose, plus the explicit `unlock` and `update` fetches.
 - She recommends and prepares; humans own sends, spend, and go-live. Gates
   that encode judgment stay human even after mechanical checks exist.
