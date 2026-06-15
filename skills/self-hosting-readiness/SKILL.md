# Self-hosting readiness

What it does: decides what a business should self-host versus rent from a vendor's cloud, and produces a staged plan to do it - the deepest form of owning your substrate, gated honestly against its operational cost.

When to run it: when data sovereignty, residency, or cost at scale is in play; when a build-versus-buy call points toward owning the stack; or when the buyer asks about self-hosting or running models locally.

Steps:
1. Name what is on the table to self-host: open-weights model inference, the data store and vector index, the orchestration layer, or the whole stack. Be specific - self-hosting is per-component, not all-or-nothing.
2. For each component, apply the build-versus-buy tests plus two more: data sovereignty (must this data stay on your own network?) and operational capacity (can the team run the hardware, security, uptime, and upgrades?).
3. Self-host where data control is non-negotiable, or where a hosted open-weights model beats a cloud API on cost per outcome at your volume - measure that case with the eval harness, comparing a self-hosted model against the cloud options. Keep managed services where uptime and scale matter more than control and you can exit cleanly. Compose: a self-hosted open model for the routine, high-volume steps; a cloud frontier model for the hard ones.
4. Set the security and operations baseline before anything goes live: network isolation, access control, backups, patching, and monitoring. Self-hosting moves these from the vendor to you.
5. Sequence it: start with the one component where the case is clearest, prove it, then expand. Budget against a working gate, not a date.
6. Write it up as a plan the buyer keeps (the doc directive in the deliverables section), and point them to the community Self-Hosting Guide (https://github.com/mikeroyal/Self-Hosting-Guide) as a catalog of tools to choose from across servers, networking, security, containers, databases, and self-hosted AI.

What "good" looks like: a per-component self-host-or-rent decision with the data-sovereignty and operational-capacity tests recorded, a security baseline, and a staged plan with one proven first component - not a big-bang migration.

Ownership note: self-hosting is the strongest claim to owning your substrate, and the heaviest. Own the components where control genuinely pays for the operational weight; rent the rest without apology. Aletheia herself can run fully self-hosted on a local OpenAI-compatible server - see CHOOSE-YOUR-MODEL.md.
