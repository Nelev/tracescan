# TraceScan

## Problem
Engineers running an LLM application can see every run in observability tools, but finding the pattern behind hundreds of failed traces is still manual work. Left unsolved, recurring failures are diagnosed slowly, inconsistently, or not at all, and fixes are never captured as regression tests. The first application to be triaged is Medas, a clinician-facing RAG assistant built by the author.

## Evidence
- Assumption — needs validation via prototype (fault-injection eval on Medas) and user research (interviews with other LLM-app engineers).
- No measurements yet of current manual triage time, Medas failure volume, or failed attempts with existing tools (e.g. Langfuse). TBD — needs validation via analytics on Medas traces and a timed manual-triage baseline.
- Source: author's architecture overview (2026-11-04); it asserts the problem but cites no data.

## Users
- **Primary**: Engineer on call for an LLM application (first user: the Medas builder). Need is triggered by a batch of failed or low-scored traces that must be turned into actionable, deduplicated issues.
- **Not for**: End users of the LLM app (e.g. clinicians); teams who want fully autonomous fixes with no human approval.
- **Open**: whether the product targets anyone beyond the Medas builder — TBD — needs validation via user research.

## Hypothesis
We believe **an agent that groups failed traces, diagnoses each group, confirms the cause by replaying the failing inputs, and drafts GitHub issues with regression tests for human approval** will **replace the manual work of finding patterns in failed LLM traces** for **engineers running LLM applications, starting with the Medas builder**.
We'll know we're right when **TBD — thresholds to be set after a baseline run (see Success Metrics)**.

## Success Metrics
Metrics are taken from the source document's evaluation plan; targets are not yet defined.

| Metric | Target | How measured |
|---|---|---|
| Detection rate | TBD — needs baseline run | 6 injected Medas faults (empty retrieval, broken tool schema, truncated system prompt, small context window, weaker model, upstream timeouts), enabled one at a time with generated traffic; fraction detected |
| Root-cause accuracy | TBD — needs baseline run | Diagnosis compared with the known injected fault |
| False positives | TBD — needs baseline run | Reported issues that match no injected fault |
| Duplicate issues on a second run | TBD (expected 0 once known-issues memory exists) | Re-run on the same traffic; count repeat issues |
| Cost per run | TBD — needs baseline run | Measured spend per triage run |
| Time per run | TBD — needs baseline run | Wall-clock time per triage run |
| Time saved vs. manual triage (stretch, validates the problem) | TBD | Timed manual-triage baseline vs. TraceScan report |
| Agreement with human labels (stretch) | TBD | Comparison on the published MAST-Data benchmark |

## Scope
**MVP** (due day 10 of 16) — Tracing for Medas with a trace viewer; a full triage loop on Medas (collect failed traces, group, diagnose, draft proposals); human review before anything is written; dry-run actions (local files instead of real writes); and the fault-injection evaluation.
*Flag:* the source's pipeline includes failure replay and known-issues matching, but its schedule lists both as stretch. Whether the MVP loop ships without them (unconfirmed causes, possible duplicates) is an open question.

**Stretch** (days 11–14) — Replay-based reproduction of failures; known-issues memory to avoid duplicates; real GitHub issue creation; MAST-Data comparison; review dashboard UI.

**Out of scope** (deferred vs. deliberate not yet confirmed by the author — TBD)
- Any change made without human approval — ruled out by the source document.
- Reliance on an existing observability platform — the source chooses to build the tracing path; whether that holds is an open question.
- Applications other than Medas — not mentioned in the source; TBD.
- Automatically fixing the bugs found (as opposed to filing issues) — not mentioned in the source; TBD.

## Delivery Milestones
<!-- Business outcomes, not engineering tasks. /plan turns each into a plan. -->
<!-- Status: pending | in-progress | complete -->

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | Medas traces visible | The author can view Medas runs, failures and scores in a trace viewer built on the project's own trace store | pending | — |
| 2 | Triage report on Medas | A run over a time window produces grouped, diagnosed failures drafted as issue proposals | pending | — |
| 3 | Human-gated actions | Nothing is written until a person approves each proposal; approved items produce dry-run output | pending | — |
| 4 | Fault-injection evaluation | Detection, accuracy, false-positive, duplicate, cost and time results for the 6 injected faults (MVP gate, day 10) | pending | — |
| 5 | Confirmed, deduplicated issues (stretch) | Causes confirmed by replay; repeat failures update existing issues; real GitHub issues with regression tests | pending | — |
| 6 | Benchmark and review UI (stretch) | MAST-Data comparison and a review dashboard | pending | — |
| 7 | Shippable capstone | Deployed or recorded demo, README and three-minute demo (days 15–16) | pending | — |

## Open Questions
- [ ] Is the 16-day scope realistic, or should some stretch goals be cut now?
- [ ] Does the course require a deployed demo, or is a recorded one enough?
- [ ] Is fault injection a strong enough evaluation on its own, or should MAST-Data move into the MVP?
- [ ] Is building a custom tracing stack, instead of using a platform such as Langfuse, a good use of capstone time?
- [ ] What are the success thresholds for each metric? (needs a baseline run)
- [ ] Should the MVP include replay and known-issues matching, given the source lists them as stretch?
- [ ] Who is the user beyond the Medas builder, and why now? (not stated in source)
- [ ] Medas is clinician-facing: may its traces contain sensitive clinical content, and how should that affect what TraceScan stores and writes to GitHub? (raised from document review, not from the author)

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Problem is not real or not painful enough (no evidence yet) | Unknown | High | Timed manual-triage baseline on Medas before claiming value |
| 16-day schedule too tight, MVP slips | Medium (author asks this themselves) | High | Cut stretch goals early; treat day 10 as a hard gate |
| Fault injection alone is a weak validation (author-injected bugs, author-built agent) | Medium | Medium | Add MAST-Data comparison; decide whether it joins the MVP |
| Building own tracing stack consumes time otherwise spent on the agent | Medium | High | Decide explicitly (open question above) before starting |
| Diagnosis not confirmed by replay in the MVP, so false positives reach reviewers | Medium | Medium | Measure false-positive rate; keep the human approval gate |
| Sensitive clinical data in traces | Unknown | High | TBD — needs validation (see open question) |

---
*Status: DRAFT — requirements only. Implementation planning pending via /plan.*
