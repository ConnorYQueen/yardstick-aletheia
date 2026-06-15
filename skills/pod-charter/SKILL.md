# Pod charter

What it does: stands up a small, cross-functional team that owns one workflow and its agents end to end, with a written acceptance criterion, so automation does not pool into a central queue.

When to run it: when a workflow is committed for automation.

Steps:
1. Name the workflow and the single outcome the pod owns.
2. Staff the pod small and cross-functional: the people who know the workflow, someone who can build, and a named owner accountable for the outcome.
3. Write the acceptance criterion - the evidence that the automation works - before any building starts. It must be something you can inspect, not a feeling.
4. Set the decision boundary for the pod: which steps the agent may run, and which decisions escalate to a human.
5. Set the budget to the next gate only, and the date you review evidence.
6. Name what the pod hands back to central enablement: the reusable skill, the agent spec, and the eval set.

What "good" looks like: a one-page charter with the outcome, the owner, the acceptance criterion, the decision boundary, and the gate budget. The pod can start, and you will know when it is done.

Build-vs-buy note: the pod builds the workflow's own glue and agent; it draws shared platform and skills from central enablement rather than each pod buying its own.
