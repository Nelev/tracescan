# Eval notes

A log of eval experiments on TraceScan: what was run, what came out, and what it changes. Newest first. The commands and the meaning of each score are in the README ("The evaluation"); the code is in `backend/eval/`.

## Silent failures get a signature of their own (2026-11-14)

### Question

After the judge learned to see a request going round in circles, the small-context requests were judged failed but merged with the truncated prompt's: both blame a `chat` span with no error, so clustering read the same `chat openai/gpt-4.1-mini: no error message` for both. Can code, with no model, tell silent failures apart?

### What changed

- **`agent.judge.symptom`**: for a blamed step that recorded neither an error type nor a message, the fixed words of what the trace shows, read from structure only: a search under the blamed step that found nothing, a tool asked for in `REPEATED_ROUNDS` (4) rounds or more (`rounds_per_tool`: a round is what follows one `chat` span, so calls made together count once), a reply whose `medas.reply.format` is off, else a search anywhere that found nothing. `failure_fields` puts it in the message, which clustering embeds and groups by. A step that recorded its own error keeps it.
- Nothing else: the judge, the thresholds and the embedding are as in the entry below.

### Results

| Score | Medas, judge change only | **Medas, with symptoms** | Seeded day | Control day |
| --- | --- | --- | --- | --- |
| Detection | 4/6 | **4/6** (context in, timeouts out) | 8/8 | n/a |
| Purity | 13/16 | **15/15** | 34/34 | n/a |
| Separation | 1/6 | **3/6** | 7/8 | n/a |
| Category accuracy | 5/6 | 2/4 | 9/9 | n/a |
| Cause accuracy | 1/6 | 0/4 (all graded 1) | 9/9 | n/a |
| Judge recall, false positives | 16/24, 0/32 | 15/24, 0/32 | 34/34, 0/18 | 0/52 |
| False alarms | 0 | 0 | 0 | 0 |

Files: Medas `out/eval/20261114T072846Z.json` (retriaged from `20261114T070539Z.json`), seeded `20261114T072917Z.json`, control `20261114T072933Z.json`.

Medas clusters: tool schema (5), truncated prompt (4, "the reply is not in the shape the app asks for"), small context (3, "the same tool asked for round after round"), empty retrieval (3, "a search returned nothing", step and error). Each holds one fault.

### Findings

1. **Each silent fault is its own cluster.** The small context has a diagnosis of its own for the first time, and no cluster mixes faults.
2. **Detection is still 4/6, for another reason.** The two timeout requests were not judged failed this time. Their scores sit between 0.3 and 0.6 under the old prompt and the new one (four calls each): one source timed out while the record search worked, and the judge is split on whether that failed the user. Detection of the timeouts is a coin flip until the judge is told.
3. **The diagnoses name the place, not the cause.** Every diagnosis was graded 1. The small context is `system_design` ("the agent keeps searching"), not `context_overflow`: nothing on the trace says the model is sent too little. The same as before for the others.
4. **The seeded day did not move.** Its one silent fault (`silent_no_hits`) now reads "a search returned nothing" and still gets its own cluster; scores as in experiment 8.

### Next steps

- Tell the judge whether one failed lookup, while the others worked, failed the user, so the timeouts stop being a coin flip.
- The weak model (still invisible).
- Causes: the diagnoses need something on the trace that says why (an exception message from the tool, the context size the model was sent); that is Medas's to add, as safe signals.

## The judge and a request that goes round in circles (2026-11-14)

### Question

On Medas, the trace judge passed every request of the small-context fault: the model asks for the same record search round after round (6 to 12 model calls, 11 to 21 searches), every call succeeds, and an answer comes at the end. Can the judge be taught to see that without flagging healthy requests?

### What changed

- **Judge prompt** (`agent/judge_prompt.md`): a request whose rounds (`chat` spans) ask for the same tool or search again, four rounds or more, failed its user even with no error; several calls in one round, or a few rounds that each ask for something different, are normal; blame the first `chat` span that asked again. "A request with no error and no empty result went fine" now also needs no step asked for round after round.
- **First wording dropped.** It also said "one more try after a failed or empty call is normal", and the judge then let a timed-out lookup pass (one timeout trace from 0.4 to 0.68 on average over four calls each). Without the clause the timeouts score as before.
- **`eval.medas_run --retriage FILE`**: triage a results file's window again with its traces and answer key unchanged, so a judge change is measured on the same requests.

### Results

The judge alone, four calls per trace on the first run's traces, old prompt / new prompt: small context 0.8-1.0 / **0.1-0.2** (12 of 12 failed); upstream timeout 0.3-0.6 / 0.3-0.6; truncated prompt unchanged. Every healthy trace twice per prompt: 0.9-1.0 under both, none failed.

| Score | Medas, first run | Medas, retriaged | Seeded day | Control day |
| --- | --- | --- | --- | --- |
| Judge recall | 15/24 | **16/24** (context 3/3) | 34/34 | n/a |
| Judge false positives | 0/32 | 0/32 | 0/18 | 0/52 |
| Detection | 4/6 | 4/6 | 8/8 | n/a |
| Purity | 15/15 | 13/16 | 34/34 | n/a |
| Separation | 3/6 | 1/6 | 7/8 | n/a |
| Cause accuracy | 2/5 | 1/6 | 9/9 | n/a |
| False alarms | 0 | 0 | 0 | 0 |

Files: Medas retriaged `out/eval/20261114T071737Z.json` (from `20261114T070539Z.json`), seeded day `20261114T071811Z.json`, control day `20261114T071826Z.json`.

### Findings

1. **The judge sees the loop now, and nothing else moved.** The context requests fail for the right reason ("asked for search_patient_record in 11 of 12 rounds"), and no healthy request on either eval is flagged. The seeded day scores as in experiment 8.
2. **Detection did not rise: the clustering merges silent failures.** The context requests and the truncated prompt's both blame a `chat` span with no error, so their signatures are the same (`chat openai/gpt-4.1-mini`) and they form one cluster, diagnosed `system_design`. The cluster's majority is the truncated prompt, so the context fault still has no diagnosis of its own.
3. **The rest is the models' variance.** Separation and cause accuracy fell because this triage split the empty retrievals into two single-trace findings and graded them 0; the timeouts are on the judge's border (0.3-0.6) under either prompt. One run is not enough to compare these.
4. **The weak model is still invisible**, and no prompt can change that: one chat call and no tool is also what a healthy answer to a blank question looks like. Only the model's name differs, and the judge does not know which model the app should run on.

### Next steps

- Give silent failures a signature of their own: what the judge saw (a repeated step, a malformed reply, an empty search) rather than only the blamed step.
- Decide how the weak model can be seen: the model the app is meant to run on as app configuration, or a signal from Medas.
- Repeated runs, to average out the variance.

## Medas's own faults: the first run (2026-11-14)

### Question

The seeded eval scores full marks on synthetic traces. What does TraceScan find when the faults are real bugs in Medas, sent through its real agent among healthy requests?

### What changed

- **Medas** (Nelev/medas PR 11): six fault switches, and two safe signals on its spans, `medas.reply.format` and a failed lookup's own reason.
- **Answer key** (`eval/medas_ground_truth.py`): each fault's category, cause, symptom, failing span, switch and input sets. `FIRED` decides from the stored tree whether the switch fired on a request; a spared request is `healthy`.
- **Runner** (`eval/medas_run.py`): one Medas traffic process per input set, every fault and then the controls in one window, each trace matched to its process by time, then one triage run. `eval.metrics` and `eval.judge` read the answer key the file names.
- **Run.** `out/eval/20261114T070539Z.json`: 17 sends, 56 requests.

### Results

| Fault | Fired | Judge caught | Cluster | Category | Cause (0-2) |
| --- | --- | --- | --- | --- | --- |
| tool_schema | 5 of 5 | 5 | c1, alone | tool_schema_error | 1 |
| truncated_prompt | 5 of 5 | 5 | c0, alone | unknown (expected prompt_regression) | 0 |
| empty_retrieval | 3 of 4 | 3 | c2, alone (step and error) | retrieval_miss | 1 |
| upstream_timeout | 2 of 8 | 2 | c3, c4: one trace each | infra_error | 2, 2 |
| context_tokens | 3 of 3 | 0 | none | | |
| weak_model | 6 of 6 | 0 | none | | |
| healthy (32) | | 0 flagged | | | |

Scores: detection 4/6, purity 15/15, separation 3/6, category 4/5, cause 2/5, false alarms 0, judge recall 15/24, judge false positives 0/32, judge blame 10/15. Cost $0.12 ($0.03 judge, $0.09 diagnoser); the triage took 25 s.

### Findings

1. **The two silent faults are invisible to the judge.** The small context (the same search seven or more times, then an answer) and the weak model (one chat call, no tool) leave no error and a well-formed reply, and every one of their traces scored as healthy. The same as on 2026-11-13: the judge reads a trace as failed only on an error, an empty search or a malformed reply.
2. **Caught faults are diagnosed by place, not by cause.** The broken schema is "the arguments do not match the schema" (the rename is not visible: the span keeps no exception message), the empty retrieval is "the retriever returned nothing" (the medication filter is not visible: no query text), the truncated prompt is `unknown` (the reply was malformed; no span says why). Only the timeout, whose status message says what happened, gets full marks.
3. **Two identical timeouts became two issues.** Each was diagnosed alone (`isolated`): the clustering does not group two traces with the same step and error when HDBSCAN finds nothing. A reviewer gets two proposals for one cause.
4. **The low-volume fault clustered.** The empty retrieval fired on three requests, enough for a step-and-error cluster, so `rare_recall` is 0/0: no fault was sent only once.
5. **The healthy traffic is left alone.** No healthy trace was judged failed, so no false alarm, including the edge cases (blank, Italian, emoji). PubMed did not fail on its own this time.
6. **The answer key needed one fix.** The truncated prompt's fifth reply was `no_severity`, not `malformed`, and was first labelled healthy, which cost purity and made a false alarm. `FIRED` now counts both as the fault, and `--relabel` labelled the run again from the stored trees.

### Next steps

- Make the judge see the two silent faults: a request that repeats one search many times, and an answer to a record question with no lookup at all. Measure with this runner, with the controls in the same window.
- Group identical isolated failures (same step, same error) into one cluster.
- Run it again to see the variance; the timeout share fired on only 2 of 8 requests.

## Healthy twins: compatibility filters and fewer than three (2026-11-13)

### Question

Which healthy calls may the diagnoser compare a failed step with, and when should it see fewer than three?

### What changed

The collector keeps `service.version` and the telemetry `schema_url` on every span (migration 0007). A healthy pick is stored with its `StepKey` (step, operation, app version, schema), and `similar` hard-filters on all of it plus the app and the chunk template version, in the same query as the vector search. `pick_twins` then drops candidates past `MAX_TWIN_DISTANCE` and merges identical texts into one twin with a count.

### Results

No model calls: `step_text` of every error span of the seeded day (end 2026-01-15) against the healthy calls of the same step, embedded with bge-small.

| Pair | Cosine distance |
| --- | --- |
| Failed step vs healthy calls of the same step | 0.044 to 0.097 |
| Failed step vs the nearest healthy calls of other steps | 0.053 to 0.11 (one 0.25) |
| Healthy vs healthy, same step | 0.001 to 0.067 |

### Findings

1. **Distance does not separate relevant from irrelevant here.** The two ranges overlap, so a threshold cannot stand in for the step filter. The hard filters decide relevance; `MAX_TWIN_DISTANCE` is set at 0.12, just above every same-step pair, as a safety net only.
2. **Fewer than three comes from merging.** Bucketed texts repeat: `search_patient_record` has 3 healthy calls with one text, `search_pubmed` 3 calls with 2 texts. After merging they give 1 and 2 twins, each saying how many calls share it.
3. **A deploy leaves a step without twins until its new version has healthy calls.** This is the intended cost of the hard app-version filter.

### Next steps

1. Measure the threshold again once Medas sends real `service.version` values and its traces vary more than the seeded day.
2. Check in the eval whether the diagnoses change with the merged twins.

## Experiment 8: the clustering fix and one fault per cause (2026-11-12)

### Question

Experiment 6 found why the clustering merges faults: the look-alike timeouts have identical failure texts, and two misfits join a cluster with HDBSCAN membership 0.0. Experiment 7 found that the answer key counts a correct merge (the two-failure requests with the provider outage) as a loss. Do the simplest fixes for the three raise separation?

### What changed

- **Answer key.** `Fault.same_cause_as`: `double_failure` names `model_unavailable`. `eval.metrics` maps every trace's kind through `cause_of` before the clustering scores, so the fault day has 8 faults, not 9. The trace judge's scores still use the seeded kinds.
- **Seconds as a word.** `failure_text` and `normalise_error` turn seconds in the error (`timed out after 1.0s`) into the latency word of `LATENCY_BUCKETS_S` before digits are masked. This only helps when the message states the seconds, as the seeded ones do.
- **Membership threshold.** A trace HDBSCAN puts in a group with membership under `MIN_MEMBERSHIP` (0.1) is noise: it goes to the step-and-error stage, and stands alone if nothing there matches.

- **Run K.** The fault day of runs G and I. Results file: `out/eval/20261112T201117Z.json`.
- **Run L.** The control day. Results file: `out/eval/20261112T201130Z.json`.

### Results

Run I is rescored with the new answer key, so both columns count 8 faults.

| Score | Run I (exp 7, new key) | Run K | Run L (control) |
| --- | --- | --- | --- |
| Detection | 6/8 | **8/8** | n/a |
| Purity | 29/34 | **34/34** | 0/0 |
| Separation | 2/8 | **7/8** | n/a |
| Rare-failure recall | 0/1 | **1/1** | n/a |
| False alarms (clusters) | 0 | 0 | 0 |
| Category / cause accuracy | 6/6, 6/6 | 9/9, 9/9 | n/a |
| Judge recall, false positives, blame | 34/34, 0/18, 34/34 | 34/34, 0/18, 34/34 | 0/52 flagged |
| Total cost | $0.13 | $0.17 | $0.02 |

Run K's clusters: `source_timeout` (6), `context_overflow` (5), `tool_arguments` (5), `model_unavailable`'s 5xx face (4), `silent_no_hits` (4), the two `double_failure` traces with `model_unavailable`'s timeout face (3), `tight_timeout` (3, step and error), `unexplained` (3, step and error), `store_down` (1, isolated).

### Findings

1. **Every cluster holds one fault.** Purity is 34/34. The look-alike timeout has its own cluster, found by the second stage once its text differs, and the store outage stands alone and is diagnosed correctly.
2. **The one miss is a split, not a merge.** The provider outage is two clusters: its four 5xx traces, and its timeout face with the two `double_failure` traces (whose blamed span is a 503 too). Both name the same cause, so a reviewer gets two issues for one bug.
3. **More clusters cost more.** Nine diagnoses instead of six: $0.17 instead of $0.13.

### Limits

- One run, on the day the fixes were written for. The 0.1 threshold was chosen from experiment 6's values (misfits at 0.0, members at 1.0).
- The seconds word needs the seconds in the error message. Real httpx timeouts often do not say them; the failing span's own duration on `TraceSummary` would be the sturdier source.

### What to do next

1. A third, unseen day and a second control run, to see how far these results hold.
2. If the provider split persists, look at why the 503 of `double_failure` sits nearer the timeout face than the 5xx traces.

## Experiment 7: the judge's unsure, not-found and blame rules (2026-11-12)

### Question

Experiments 4 and 5 found two weak spots in the trace judge. An unsure judge scores 0.5, which counts as failed. And in a request with two errors it blames the first, not the one that ended the request. Do three prompt rules fix both without losing recall?

### What changed

`agent/judge_prompt.md`, three rules; the same two days as experiment 5 (runs G and H):

- **Unsure:** score 0.6, not "in the middle". The prompt now says that 0.5 or less means failed.
- **Not-found:** a lookup that says the thing does not exist, followed by a model call that completed, is by design. The trace never holds the answer, so its absence is no reason to doubt it. (The old rule required "the model tells the user so", which a trace cannot show.)
- **Blame:** when more than one step failed, blame the one that ended the request (the failure after which nothing went on to serve the user, usually the last). An earlier failure still counts towards the score. This matches the answer key, which already names the provider's `chat` span for `double_failure`. `TraceVerdict.blamed_span_id`'s description says the same.

`eval.metrics` also gained `judge_blame`: of the faulty traces the judge caught, how many blame the answer key's `failing_span` step. It was worked out by hand before.

- **Run I.** The fault day of run G. Results file: `out/eval/20261112T154735Z.json`.
- **Run J.** The control day of run H. Results file: `out/eval/20261112T154749Z.json`.

### Results

| Score | Run G (exp 5) | Run I | Run H (exp 5, control) | Run J (control) |
| --- | --- | --- | --- | --- |
| Judge recall | 34/34 | **34/34** | n/a | n/a |
| Judge false positives | 0/18 | 0/18 | 1/52 | **0/52** |
| Judge blame (right step) | 32/34 | **34/34** | n/a | n/a |
| Scores between 0.3 and 0.85 | 1 | 0 | 1 (0.5) | 0 |
| Detection | 6/9 | 6/9 | n/a | n/a |
| Purity | 27/34 | 27/34 | 1/1 | 0/0 |
| Separation | 2/9 | 2/9 | n/a | n/a |
| False alarms (clusters) | 0 | 0 | 1 | **0** |
| Category / cause accuracy | 5/6, 5/6 | **6/6, 6/6** | n/a | n/a |
| Total cost (judge part) | $0.13 ($0.03) | $0.13 ($0.03) | $0.04 ($0.03) | $0.02 ($0.02) |

Run I's clusters: the PubMed timeouts (normal and look-alike); the provider's 5xx failures together with both `double_failure` traces; `context_overflow` with the one model timeout; `tool_arguments` alone; `silent_no_hits` with `store_down`; `unexplained` alone (step and error).

### Findings

1. **All three rules did what they were for.** On the control day every trace scored 0.9 or more and nothing was proposed. On the fault day every trace scored 0.2 or less or 0.9 or more, so nothing sits near the threshold, and the judge now blames the step the answer key names in all 34 faulty traces.
2. **The double failures now cluster with the provider outage, which is their cause.** Both blame the provider's 503, so their failure text is the same as `model_unavailable`'s 5xx face, and the timeout cluster now holds only timeouts. Detection and separation do not move: `double_failure` is the minority kind of the provider cluster, and separation wants each seeded kind alone.
3. **The eval now penalises a right answer.** `double_failure` and `model_unavailable` have the same injected cause, the model provider answering with a server error, and the same category. Grouping them is what a reviewer would want: one issue for the provider. The answer key counts them as two faults because they were seeded as two kinds. Scoring should treat kinds that share a cause as one fault, for example a `same_cause_as` field on `Fault`.
4. **Cause accuracy is 6/6.** The silent-miss diagnosis that lost a point in run G got full marks this time. One run each, so that may be run-to-run variation rather than the prompt change.

### Limits

- One run per day, and on the same two days the rules were written from. The not-found rule was written after seeing run H's false alarm.
- The judge's attribution (`app`, `external`, `unclear`) is still not scored: the answer key has no expected value for it.

### What to do next

1. Let the answer key say which kinds share a cause, so that `detection` and `separation` stop counting the provider merge as a loss.
2. The clustering, as in experiment 6: a membership threshold, and a duration size word in the failure text.
3. A third, unseen day and a second control run, to see how far these results hold.

## Experiment 6: why the clustering merges faults (2026-11-12)

### Question

Experiment 5's fault day (run G) left three faults without a cluster of their own: `tight_timeout`, `double_failure` and `store_down`. Is HDBSCAN the cause, or what it is given?

### What changed

Nothing in the code, and no model call. Run G's 34 failure texts (`failure_text`, rebuilt from its `trace_verdicts`) were embedded again with the real model and passed to HDBSCAN with the app's settings (`MIN_CLUSTER_SIZE` 3, `MIN_SAMPLES` 4, cosine). For each fault, the labels, HDBSCAN's membership (`probabilities_`) and the cosine distance to the nearest other fault were read.

### Results

| Fault | Cluster | Membership | Nearest other fault (cosine distance) |
| --- | --- | --- | --- |
| source_timeout, tight_timeout, double_failure | one cluster | 1.0 | 0.000 to each other: identical texts |
| silent_no_hits | its own | 1.0 | store_down, 0.137 |
| store_down | silent_no_hits' | **0.0** | silent_no_hits 0.137; every other fault 0.35 or more |
| context_overflow | its own | 1.0 | model_unavailable, 0.112 |
| model_unavailable, timeout face (1 trace) | context_overflow's | **0.0** | context_overflow 0.112; its own 5xx siblings 0.114 |
| model_unavailable, 5xx face (4 traces) | its own | 1.0 | |
| tool_arguments | its own | 1.0 | model_unavailable, 0.298 |
| unexplained | noise (then `step_error`) | 0.0 | 0.35 or more from everything |

### Findings

1. **The timeouts merge before HDBSCAN.** Their texts are identical: the look-alike differs only in its timeout length, which digit masking erases, and the double failure's text describes the PubMed timeout the judge blamed, not the provider's 503 the answer key calls the cause. No algorithm can separate identical inputs. The fixes are in the text (a coarse size word for durations instead of `#`) and in the judge (which error to blame when a request has two; experiment 4, next step 2).
2. **HDBSCAN absorbs a lone outlier into the nearest cluster and says so.** A point that joins a cluster after the cluster has formed counts as a member, with low membership; only a point that joins nothing before the root merge is noise. The store outage (one trace, below `MIN_CLUSTER_SIZE`) sits 0.137 from the silent misses, which share its step `retrieval record_chunks`, and is attached to them with membership 0.0. The same happens to the one model timeout, absorbed into the context overflows. `group_failures` reads only the labels, so a 0.0 member counts the same as a 1.0 member.
3. **The embedding weights the step more than the error.** "Connection refused" and "no error" at the same step are 0.137 apart; two different failures of a `chat` step are 0.11 apart, about as far as one cause's two faces. The error type does not separate failures of one step well.
4. **`MIN_SAMPLES` works as intended for small identical groups.** The three `unexplained` traces are identical but have no fourth neighbour, so HDBSCAN calls them noise and the second stage makes them a `step_error` cluster.

### Limits

- One day, one embedding of each text. The distances are from this model (`bge-small-en-v1.5`) and these seeded texts; real Medas errors will be more varied.

### What to do next

1. Treat a point whose membership is below a threshold (try 0.5) as noise, so it goes through the second stage and, with nothing sharing its step and error, is diagnosed alone. Expected: `store_down` gets its own cluster (rare recall 1/1, detection +1); the model timeout becomes a one-trace finding instead of joining the overflows. Check on runs G and H, and that the control day gains no cluster.
2. Put durations in the text as a size word (bucketed like `chunks.py`'s latency), so the look-alike timeout differs from the normal one.
3. Settle which error the judge blames in a request with two (experiment 4, next step 2).

## Experiment 5: a fresh day and a control day (2026-11-12)

### Question

Run F's judge prompt was tuned on the day it was scored on. Does it hold on a day it has never seen, and on a day with no fault at all?

### What changed

Code only, no prompt change. `eval.metrics` now scores the trace judge itself (`judge_recall`, `judge_false_positives`, per kind in `judge_by_kind`) and counts its spend in `cost_usd` (`judge_cost_usd` on its own). `eval.run --control` seeds a control day (`CONTROL_COUNTS`: 36 healthy requests, 8 retried rate limits, 8 expected not-founds, no fault) on its own fixed day, `CONTROL_END`.

- **Run G.** A fresh fault day, `--end 2026-02-27T12:00:00Z`, the same twelve kinds as `COUNTS`. Results file: `out/eval/20261112T145040Z.json`.
- **Run H.** The control day (`--control`, ending 2026-02-20). Results file: `out/eval/20261112T145107Z.json`.

### Results

| Score | Run F (exp 4, tuned day) | Run G (fresh day) | Run H (control) |
| --- | --- | --- | --- |
| Judge recall | 34/34 | **34/34** | n/a |
| Judge false positives | 0/14 | **0/18** | 1/52 |
| Detection | 5/9 | 6/9 | n/a |
| Purity | 23/34 | 27/34 | 1/1 |
| Separation | 2/9 | 2/9 | n/a |
| Rare-failure recall | 0/1 | 0/1 | n/a |
| False alarms (clusters) | 0 | 0 | 1 |
| Category / cause accuracy | 5/5, 5/5 | 5/6, 5/6 | n/a |
| Total cost (judge part) | $0.11 ($0.02) | $0.13 ($0.03) | $0.04 ($0.03) |

Run G's clusters: the three timeout kinds (`source_timeout`, `tight_timeout`, `double_failure`) in one cluster; `context_overflow` with one `model_unavailable`; `tool_arguments` alone; `silent_no_hits` with `store_down`; the other four `model_unavailable` alone; `unexplained` alone (step and error).

### Findings

1. **The judge holds on a fresh day.** It catches every faulty trace and flags none of the 18 harmless ones, so run F was not just a fit to its own day.
2. **The control day's one false alarm sits on the threshold again.** One expected not-found scored exactly 0.5 because "the trace does not include the final answer", and the judge blamed no valid span, so the code fell back to the error span. It is experiment 4's finding 2 again, on another kind: an unsure judge lands on 0.5, and 0.5 counts as failed. That one trace became a cluster and a diagnosis (`unknown`, confidence 0.35).
3. **Clustering is the bottleneck, and now the only big one.** Separation is 2/9 on both fault days. The timeouts merge (look-alike and double failure included), and the store outage, the rare fault, joins the silent misses in both runs, so rare recall stays 0/1.
4. **The one cause the grader marked down was `silent_no_hits` (1 of 2).** The diagnosis saw the zero hits but blamed retrieval rather than the model answering without the record, partly because the store outage in the same cluster pulled it towards a connection failure. A clustering fix would likely fix this too.
5. **The judge is now most of a small run's cost.** About $0.026 for 52 calls on each day, against $0.01 to $0.10 for the diagnoser.

### Limits

- One run per day. The 0.5 false alarm shows the judge is not deterministic near the threshold, so a second control run could differ.

### What to do next

1. Clustering (as in experiments 2 and 4): keep look-alike timeouts and the rare store outage apart. It is now the biggest loss in every fault-day score.
2. Make an unsure judge score below or above the threshold, not on it: tell the prompt that 0.5 counts as failed, or make the threshold strictly below 0.5 (`FAILED_MAX_SCORE`). Re-run the control day to check.
3. Average over two or three runs per day before trusting any change of one trace.

## Experiment 4: the judge prompt's recovery rule (2026-11-11)

### Question

Experiment 3's judge missed ten faults because its prompt counted "a model call that went on to answer" as recovery. Does a stricter rule catch them without flagging the harmless traces?

### What changed

`agent/judge_prompt.md`, twice, on the same seeded day as runs C and D:

- **Run E.** Recovery is only a later call of the same tool or step that succeeded; a final answer after a failed or empty step is not a recovery; a lookup error that says the thing does not exist, told to the user, is by design; a search with 0 results is the example of a failure with no error.
- **Run F.** Run E plus one rule: judge only what the trace shows. A step that completed without an error did its work unless the trace shows it came back empty; a request with no error and no empty result went fine.

### Results

| Score | Run D (exp 3) | Run E | Run F |
| --- | --- | --- | --- |
| Trace recall | 24/34 | 34/34 | **34/34** |
| Harmless traces judged failed | 0/14 | 3/14 (healthy, at 0.5) | **0/14** |
| False alarms (clusters) | 0 | 2 | 0 |
| Detection | 7/9 | 5/9 | 5/9 |
| Purity | 22/24 | 23/37 | 23/34 |
| Separation | 3/9 | 1/9 | 2/9 |
| Rare-failure recall | 1/1 | 0/1 | 0/1 |
| Category / cause accuracy | 10/10, 10/10 | 4/5, 4/5 | 5/5, 5/5 |
| Diagnoser cost | $0.14 | $0.09 | $0.09 |
| Trace judge | 49 calls, $0.02 | 51 calls, $0.02 | 48 calls, $0.02 |

In run F every fault scores 0.3 or lower and every harmless trace 0.85 or higher, so the 0.5 threshold sits in a wide gap. Results file of run F: `out/eval/20261111T135251Z.json`.

### Findings

1. **The recovery rule was the whole problem.** With it fixed, the judge collects every faulty trace, including the three `tight_timeout` and the four `silent_no_hits`, and leaves out the retried rate limits and the expected not-founds.
2. **A stricter rule invites doubt about what the trace does not show.** In run E the judge scored three healthy MedlinePlus searches 0.5 because the tool records no result count, and 0.5 counts as failed. The "judge only what the trace shows" rule removed that. Two lessons: "score in the middle when unsure" lands exactly on the threshold, so an unsure judge flags the trace; and the prompt has to say what absence of evidence means.
3. **The double failures now blame the first error.** Both `double_failure` traces blame the PubMed timeout (no retry, so by the new rule a failure of its own) rather than the provider's 503 that ended the request, and so cluster with the PubMed timeouts. The answer key calls the 503 the cause. Arguably both are faults; the prompt does not say which to blame when a request has two.
4. **With full recall, clustering is again the bottleneck**, exactly as in run C (detection 5/9, separation 2/9): the three PubMed timeouts merge, the provider outage merges with context overflow, and the store outage joins the silent misses.

### Limits

- The prompt was tuned on the same seeded day it is scored on, over two rounds. Run F's perfect judge score is a fit to this day, not a measured accuracy; it needs a fresh day, and a healthy-only day, to be believed.
- One run per prompt.

### What to do next

1. Check the judge on a different seeded day (and a healthy-only one) before trusting run F.
2. Decide which span to blame when a request has two failures: the one that ended the request, or the first. Then say so in the prompt and in the answer key.
3. The clustering, as in experiment 2.
4. Score the judge in `eval.metrics` (recall and false positives per kind, `judge_usage` in the cost), so these tables stop being worked out by hand.

## Experiment 3: the trace judge (2026-11-11)

### Question

The heuristic scoring job is replaced by an LLM trace judge (`agent/judge.py`, one call per trace in the window, on `anthropic/claude-haiku-5.5`). Does it decide which traces failed as well as the heuristics did?

### What changed

- Which traces failed is the judge's call: a trace fails when its score is at most 0.5 (`JUDGE_FAILED_MAX_SCORE`), and the clustered step is the span the judge blames.
- Everything else as in experiment 2, and the same seeded day (ending 2026-01-29), so runs C and D are comparable. Results file `out/eval/20261111T134907Z.json`.

### Results

| Score | Run C (heuristic scoring) | Run D (trace judge) |
| --- | --- | --- |
| Trace recall | 34/34 | **24/34** |
| False alarms | 0 | 0 |
| Detection | 5/9 | 7/9 |
| Purity | 23/34 | 22/24 |
| Separation | 2/9 | 3/9 |
| Rare-failure recall | 0/1 | 1/1 |
| Category accuracy | 4/5 | 10/10 |
| Evidence valid, evidence relevant | 5/5, 5/5 | 10/10, 10/10 |
| Cause accuracy (judge scored 2) | 5/5 | 10/10 |
| Diagnoser calls and cost | 5 calls, $0.10 | 10 calls, $0.14 |
| Trace judge | none | 49 calls, 149k tokens, $0.02 (not in `cost_usd`) |
| Time | 16 s | 31 s |

The trace judge per seeded kind (failed of total, and the scores):

| Kind | Failed | Scores |
| --- | --- | --- |
| `context_overflow`, `model_unavailable`, `store_down`, `double_failure`, `unexplained` | all | 0.0 to 0.2 |
| `source_timeout` | 4/6 | 0.3, 0.4, 0.5, 0.5, 0.7, 0.7 |
| `silent_no_hits` | 2/4 | 0.2, 0.4, 0.7, 0.7 |
| `tool_arguments` | 2/5 | 0.3, 0.5, 0.7, 0.7, 0.8 |
| `tight_timeout` | 0/3 | 0.7, 0.8, 0.8 |
| `healthy`, `retried_ok`, `not_found` (no fault) | 0/14 | 0.8 to 1.0 |

The clusters: `c0` context overflow 5, `c1` model 5xx 2 with double failure 2, `c2` PubMed timeout 4, `c3` model timeout 3, `c4` unexplained 3 (`step_error`), and five isolated traces: two `silent_no_hits`, two `tool_arguments`, one `store_down`.

### Findings

1. **The judge never cries wolf, and it misses the failures where the model answered anyway.** No harmless trace failed, and no judge call errored. All ten misses give the same reason: the tool failed or returned nothing, then a second chat call "went on to answer", so the error "looks recovered". The prompt itself names a model call that went on to answer as a sign of recovery; the judge cannot tell an answer built on the result from one made without it, and scores 0.7 to 0.8 instead of the middle the prompt asks for when it cannot decide.
2. **The look-alike is now lost before clustering.** All three `tight_timeout` traces scored fine, so the one fault that is the app's own setting is invisible, where the heuristics collected it (and clustering then merged it).
3. **Fewer traces made the clusters cleaner and more numerous.** With a third of the failures dropped, purity rose to 22/24 and detection to 7/9, and every diagnosis was right. But the surviving pairs are too few for HDBSCAN, so `silent_no_hits` and `tool_arguments` each became two isolated clusters with the same signature: two duplicate proposals.
4. **The two faces of the provider outage split by face again**, and the double failures joined the 5xx face.
5. **Attribution looks plausible**: `app` for the plain app faults, `unclear` or `external` for PubMed timeouts and silent misses. Not graded yet.

### Limits

- One run, as before. Several misses sit at 0.7, so a rerun could move a few traces either way.
- The judge's spend is not in `cost_usd`, and `eval.metrics` does not score the verdicts directly; the table per kind above was worked out by hand from `trace_verdicts`.

### What to do next

1. Fix the judge prompt: a failed or empty step whose result the answer needed is a failure even when a later model call completes; a later call that redoes the same work and succeeds is the recovery. Rerun on this same day and compare recall per kind.
2. Score the judge in `eval.metrics`: recall and false positives per kind against `FAULTS`/`NOT_FAULTS`, and add `judge_usage` to the cost.
3. Merge isolated clusters that share a signature (or group them by step and error like `step_error`), so one fault is one proposal.
4. Still open: the clustering by step (experiment 2), the rubric for a hedged `unknown`, several runs per configuration, a healthy-only day.

## Experiment 2: the scoring job (2026-11-10)

### Question

Experiment 1 showed two things the reader got wrong before any clustering: failures with no error were never collected, and harmless errors were. Does scoring each trace with heuristic checks fix both?

### What changed

- `trace_store/scoring.py` scores each trace with five checks in plain code (`request_failed`, `timeout`, `tool_schema_error`, `tool_error`, `empty_retrieval`) when its root span is stored.
- The Postgres reader calls a trace failed when its lowest score is low. An error span alone no longer counts: a failed tool call that was retried successfully, or that ended in an expected error, scores fine.
- The seed writes the hit count as `retrieval.hits`, the name the trace server lets through, so the diagnoser can see an empty retrieval.
- Same models, clustering and judge as experiment 1. The seeded day is a new one (ending 2026-01-29), because the seeded content changed.

### Results

| Score | Run B (before) | Run C (with scores) |
| --- | --- | --- |
| Trace recall | 30/34 | 34/34 |
| False alarms | 1 | 0 |
| Detection | 6/9 | 5/9 |
| Purity | 24/36 | 23/34 |
| Separation | 3/9 | 2/9 |
| Rare-failure recall | 1/1 | 0/1 |
| Category accuracy | 6/6 | 4/5 |
| Evidence valid, evidence relevant | 6/6, 6/6 | 5/5, 5/5 |
| Cause accuracy (judge scored 2) | 6/6 | 5/5 |
| Cost and time | 6 calls, $0.10, 11 s | 5 calls, $0.10, 16 s |

The clusters of run C:

| Cluster | Size | What it holds | Diagnosis | Judge |
| --- | --- | --- | --- | --- |
| `c0` | 11 | `source_timeout` 6, `tight_timeout` 3, `double_failure` 2 | `infra_error`: PubMed does not answer in time | 2 |
| `c1` | 10 | `context_overflow` 5, `model_unavailable` 5 | `context_overflow` | 2 |
| `c2` | 5 | `tool_arguments` 5 | `tool_schema_error` | 2 |
| `c3` | 5 | `silent_no_hits` 4, `store_down` 1 | `unknown`, confidence 0.4: "the cluster mixes two different failure signatures" | 2 |
| `c4` | 3 | `unexplained` 3 | `unknown`, confidence 0.3 | 2 |

### Findings

1. **The scoring job fixed what it was built to fix.** All 34 faulty traces are collected, the four with no error included, and the six harmless requests (`retried_ok`, `not_found`) are left out. Both numbers moved exactly as predicted before the run.
2. **The clustering groups by failing step, whatever the cause.** With the harmless errors gone, the big cluster is the three kinds of PubMed timeout; every failure of a chat call is one cluster; and the silent retrieval misses share a cluster with the one store outage, because both point at the retrieval span. Each cluster is "one step", none is "one cause".
3. **The rare fault lost its diagnosis.** In run B the single store outage was isolated and diagnosed alone. Now it has neighbours with the same failing span and is absorbed, so rare-failure recall fell from 1/1 to 0/1. Collecting more traces made the rare one easier to lose.
4. **The diagnoser can tell a mixed cluster when its exemplars show it.** For `c3` it saw two empty retrievals and the store outage, said the cluster mixes two failures, and answered `unknown` at 0.4 instead of naming one cause. That is honest, but it cost the category (expected `retrieval_miss`), and for `c0` and `c1` it still wrote one confident cause for a mixed cluster.
5. **The judge is lenient about hedged answers.** It gave `c3` a 2 because the diagnosis mentions the empty retrieval, although the diagnosis declines to name a cause. The rubric says extra detail does not lower a score; it does not say what to do with a diagnosis that describes the cause but refuses to commit to it.

### Limits

- **Runs B and C are different seeded days.** The provider outage has two faces chosen at random: day B had four server errors and one timeout, day C two and three. Two server errors are too few for a cluster of their own, which is part of why all five landed with the context overflows. The drop in detection is not only the scoring job's doing.
- **One run each**, as before.
- **Traces stored before the job** were scored afterwards with the old attribute name for the hit count, so their silent failures still score fine. Only days seeded from now on have them.
- **A trace is scored once.** Spans that arrive after the root do not change its scores.
- **The list of expected errors is one entry**, chosen for the seeded case.

### What to do next

1. The clustering, now the only place faults are lost: stop grouping causes that share a failing step. Candidates are the text that is embedded (it leads with the step name), the thresholds, and keeping a low-volume failure apart when its signature differs from its neighbours'.
2. Tighten the rubric for a diagnosis that describes the cause but answers `unknown`.
3. Keep the seeded day fixed between experiments, or pin the two faces of the provider outage, so runs are comparable.
4. Still open from experiment 1: human grades for the judge, three runs per configuration, a healthy-only control day.

## Experiment 1: seeded traces, plain faults then hard cases (2026-11-10)

### Question

Does the triage group failures by cause, label them correctly and name the real cause, and does it stay quiet when nothing is wrong? This was the first time any of that was measured.

### Setup

| | |
| --- | --- |
| Data | Synthetic Medas traces from `scripts/seed_traces.py`, read from Postgres through the trace server. No real traffic |
| Diagnoser | `anthropic/claude-sonnet-5-5`, one call per cluster, 3 exemplar traces shown per cluster |
| Judge | `openai/gpt-6.1-sol`, rubric in `eval/judge_rubric.md`, score 0 to 2 |
| Clustering | `BAAI/bge-small-en-v1.5` embeddings, HDBSCAN with `MIN_CLUSTER_SIZE` 3 and `MIN_SAMPLES` 4, thresholds tuned earlier on the small fixture |
| Code | Branch `feat/eval-seeded-traces` |

Two runs, one per data set:

- **Run A, plain faults.** 30 traces: 8 healthy and 22 failed, of five faults that each raise their own exception. Seeded day ending 2026-01-15.
- **Run B, hard cases added.** 48 traces of twelve kinds: the same plain faults plus a look-alike, one cause with two faces, a request with two errors, a failure with no visible cause, a failure with no error, and two kinds of error that are not faults. Seeded day ending 2026-01-22.

### Results

| Score | Run A | Run B |
| --- | --- | --- |
| Detection (faults with a diagnosis of their own) | 5/5 | 6/9 |
| Purity (traces in their cluster's majority fault) | 22/22 | 24/36 |
| Separation (faults alone in one cluster) | 5/5 | 3/9 |
| Rare-failure recall | 1/1 | 1/1 |
| Trace recall (faulty traces that reached a cluster) | 22/22 | 30/34 |
| False alarms (clusters holding a trace with no fault) | 0 | 1 |
| Category accuracy | 5/5 | 6/6 |
| Evidence valid, evidence relevant | 5/5, 5/5 | 6/6, 6/6 |
| Cause accuracy (judge scored 2) | 5/5 | 6/6 |
| Cost and time | 5 calls, $0.08, 10 s | 6 calls, $0.10, 11 s |

The clusters of run B:

| Cluster | Size | What it holds | Diagnosis | Judge |
| --- | --- | --- | --- | --- |
| `c0` | 17 | `source_timeout` 6, `tight_timeout` 3, `double_failure` 2, `retried_ok` 3, `not_found` 3 | `infra_error`: PubMed does not answer within 10 s | 2 |
| `c1` | 6 | `context_overflow` 5, `model_unavailable` 1 | `context_overflow` | 2 |
| `c2` | 5 | `tool_arguments` 5 | `tool_schema_error` | 2 |
| `c3` | 4 | `model_unavailable` 4 | `infra_error`: provider 5xx | 2 |
| `c4` | 3 | `unexplained` 3 | `unknown`, confidence 0.3 | 2 |
| `c5` | 1 (isolated) | `store_down` 1 | `infra_error`: record store refused the connection | 2 |

The four `silent_no_hits` traces are in no cluster: they were never collected.

### Findings

1. **On plain faults everything scores full marks, which says little.** Each fault in run A has its own failing step and exception, and the clustering signature is exactly those two things, so separation was close to guaranteed. Run A proved that the eval runs end to end, not that the agent is good.
2. **The diagnoser is right about what it is shown.** In both runs every category and every cause was correct. For the failure with no visible cause it answered `unknown` at 0.3 confidence and said what evidence was missing, where a confident guess was the failure the case was built to catch.
3. **Faults are lost in the clustering, not in the diagnosis.** One cluster of 17 traces took in the plain PubMed timeout, its look-alike (same step and exception, another cause), the request with two errors, and both kinds of harmless error, which are on other tools with other exceptions. Three faults got no diagnosis of their own.
4. **Harmless errors are filed under a real fault.** The six requests that worked as they should (a retried rate limit, a record that does not exist) did not become proposals of their own. They disappeared into the big cluster, which is quieter than a false proposal but inflates a real issue with traces that do not belong to it.
5. **The diagnoser did not notice a mixed cluster.** The three exemplars it saw for `c0` were a double failure, a plain timeout and a retried rate limit. It mentioned the 503 in one trace in passing and still wrote one cause for all 17 traces, at 0.85 confidence.
6. **One cause with two faces did split, and one half joined the wrong neighbour.** Four provider failures with a 5xx formed their own cluster; the one where the provider did not answer landed with the context overflows, which fail in the same step.
7. **A failure with no error is invisible.** The reader collects only traces with an error span, so the four retrievals that returned nothing were never seen. This is the missing scoring job, now with a number on it: trace recall 30/34.
8. **The judge's verdicts matched an informal read-through,** including the two borderline ones (a hedge about a non-string argument in run A, tentative hypotheses after an `unknown` in run B). No human grades are recorded yet, so judge agreement is still unmeasured.

### Limits

- **One run per data set.** The diagnoser and the judge are not deterministic; nothing here is an average.
- **Synthetic data.** The traces are made by a script that follows the planned Medas instrumentation. Real traffic will be messier.
- **Cause accuracy can flatter.** A diagnosis is judged against its cluster's majority fault, so the faults buried in a mixed cluster do not lower it. Read it together with detection, purity and separation.
- **The false-alarm count understates the false positives** when they are absorbed into a cluster with a real fault: run B counts 1 for six harmless traces.
- **Evidence relevance follows the reader's choice of failing span**, which for the request with two errors is the first error, not the one that made the request fail.
- **Two answers in the key are debatable:** `tight_timeout` is `infra_error` (the taxonomy puts timeouts there, though the fault is the app's own setting), and `unexplained` expects `unknown`.
- **Why the tool errors merge was not investigated.** The thresholds were tuned on a fixture of a few traces; whether the cause is the thresholds, the embedded text or the embedding model is open.

### What to do next

1. Find out why HDBSCAN merges errors on different tools into one cluster, and fix it at the cause: the text that is embedded, the thresholds, or both. Re-run and compare with the table above.
2. Decide how a request with an error span that still succeeded should be treated: left out when the trace is collected, or kept and labelled as not a fault.
3. Build the scoring job, so a failure with no error can be collected at all.
4. Have the diagnoser say when its exemplars do not look like one failure, and lower its confidence.
5. Record human grades for the judge's verdicts, and average each configuration over three runs.
6. Add a healthy-only control day, where the right result is no proposal at all.
