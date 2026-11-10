# Eval notes

A log of eval experiments on TraceScan: what was run, what came out, and what it changes. Newest first. The commands and the meaning of each score are in the README ("Other entry points"); the code is in `backend/eval/`.

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
