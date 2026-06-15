# Data readiness assessment

What it does: decides the minimum data and integration work that must be in place before an agent touches a target workflow, so AI compounds on good inputs instead of manufacturing confident errors.

When to run it: before automating any workflow, and again whenever a workflow's data source changes.

Steps:
1. Name the one workflow you intend to automate next. Assess readiness for that workflow only, not the whole estate.
2. List the data the workflow reads and writes. For each source, record three things: is it current, is its accuracy known, and is it reachable by API.
3. Map the integration path the workflow needs end to end. Mark each hop present or missing.
4. List the tech debt touching this workflow. Rank each item by one question: does it block this automation in the near term. Drop anything that does not.
5. Write the critical-path fix list - only the blocking items - with an owner and an acceptance test per item.

What "good" looks like: the data feeding the workflow is current, its accuracy is known, and it is reachable by API; the integration path has no missing hops; the blocking tech debt has a fix plan with acceptance tests. That is the module's exit gate.

Build-vs-buy note: buy the substrate (data platform, integration plumbing); build the proprietary glue. Do not rebuild commodity infrastructure just to own it.
