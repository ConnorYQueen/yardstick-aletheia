# Model and task routing

What it does: assigns the cheapest model or agent that clears each step of a workflow, so the deployed system stays affordable as it scales without losing the quality the task needs.

When to run it: when you scope a workflow for automation, when you write an agent spec, and on a cadence as cheaper models appear.

Steps:
1. Decompose the workflow into steps. For each, note its judgment level (routine or reasoning), its stakes (reversible or not), and its volume (how often it runs).
2. Assign a model tier by demand: small, fast, inexpensive models for routine, high-volume, low-stakes steps (extraction, classification, formatting, retrieval, first drafts); a frontier model for the steps that need reasoning, resolve ambiguity, or carry high stakes. A narrow, specialized agent often beats a general frontier model on a repetitive task, for far less.
3. Set the escalation rule: the system runs the cheap model by default and bumps to the frontier model on low confidence or high stakes. Often the frontier model also reviews the cheap model's output on the steps that matter.
4. Write a small evaluation per step - the bar the output must clear - and measure it, do not guess: the pack's eval harness (`python aletheia.py eval`) runs each candidate model over your cases on your own key and reports pass rate and cost per outcome. Run the cheapest model that passes; do not pick by reputation.
5. Record the model, the reason, and the escalation rule in the agent spec. A step that routes to a human gets no cheap-model autonomy.
6. Measure cost per outcome, not cost per token. Re-test cheaper models on a cadence and move down a tier whenever one passes the eval.

What "good" looks like: every step runs on the cheapest model that passes its eval, with escalation on low confidence, and a recorded cost per outcome you can defend to the CFO.

Ownership note: this is how an agent-first business stays affordable. Owning the routing - rather than letting one vendor's most expensive model run everything - is part of owning your substrate.
