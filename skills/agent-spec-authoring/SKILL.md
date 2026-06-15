# Agent specification authoring

What it does: writes the contract a system must have before it runs autonomously, so capability never outruns control.

When to run it: before any agent takes an action without a human in the loop, and again each time it climbs an autonomy rung.

Steps:
1. Write the spec with these parts:
   - Purpose: the one job this agent does.
   - Inputs: the data and systems it may read.
   - Actions: exactly what it is allowed to do.
   - Decision rights: what it may decide versus what it must escalate.
   - Human in the loop: who reviews what, and the escalation path.
   - Guardrails: the refusals and limits, including the decisions that never leave humans (pricing, contracts, legal exposure, named-account relationships).
   - Evaluations: the tests and acceptance thresholds that gate each autonomy rung.
   - Owner: the named human accountable for it.
   - Version: this revision, dated.
2. Pair the spec with an assurance loop: monitor in production, evaluate against the spec, and roll back on breach.
3. Store the spec beside the workflow; it is the thing a gate review reads.

What "good" looks like: every live autonomous step has a current spec with a named owner and an eval set. No spec, no autonomy.

Governance note: the spec is the buyer's, not a vendor's. Even when you buy the system, you write the spec that governs how far it runs in your business.
