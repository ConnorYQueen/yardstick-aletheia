# Autonomy gate review

What it does: runs the recurring review that decides whether a workflow advances up the autonomy ladder, holds, or stops - on evidence, not confidence.

When to run it: once a cycle for every workflow in flight, and any time someone proposes giving an agent more autonomy.

Steps:
1. Pull the workflow's agent spec and its open gate from the portfolio memory file.
2. Ask for the artifact, not the assurance: the eval results, the incident log, and the acceptance evidence at the current rung.
3. Compare against the written threshold for the next rung. Met, or not met - there is no partial credit.
4. Decide: advance one rung, hold and gather more evidence, or stop and roll back. Advance only on cleared evidence, never on elapsed time or optimism.
5. If you advance, update the spec's version, the evals for the new rung, and the decision rights. Record the new rung in the portfolio memory file.
6. Set the next gate and the budget to reach it.

What "good" looks like: each workflow's rung on the ladder is backed by eval and incident evidence on file, and every advance is recorded with the date and the evidence that justified it.

Governance note: this is where the budget-against-gates rule lives in practice. If a buyer wants to fund more autonomy before the gate clears, walk them back to the gate.
