# Automation portfolio prioritization

What it does: turns a function into a ranked list of automation candidates, so you commit pods to the right one or two workflows and let the rest wait.

When to run it: at the start of a cycle, and whenever a workflow finishes or a new one appears.

Steps:
1. Decompose the function into discrete workflows. Keep each one small enough that a single pod could own it.
2. Score each workflow on four axes: business value, reversibility (how easily a wrong output is undone), data-readiness (from the data readiness assessment), and ambiguity (how much judgment a step needs).
3. Rank by value first, then prefer high reversibility, high data-readiness, and low ambiguity. Those are the safe first automations.
4. Pick the top one or two. Mark the rest as waiting, with the reason, so the choice is on the record.
5. Record each pick in the portfolio memory file with its module and a blank gate to fill when the pod charters.

What "good" looks like: a portfolio board that ranks every workflow on the four axes, with one or two committed and the reason each other waits. Capital follows this board, per gate.

Governance note: a high-value but high-ambiguity, hard-to-reverse workflow is not an early automation. Keep it supervised and route its decisions to humans until its readiness improves.
