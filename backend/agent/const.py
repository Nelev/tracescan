"""Tuning constants for failure clustering and the diagnoser. Revisit once Medas produces real traffic."""

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # fastembed ONNX model, runs locally
EMBEDDING_DIMENSIONS = 384  # its vector size: the healthy-span store's column is this wide

# The span texts agent.chunks builds for retrieval. Bump the version on any change to the text
# or a bucket: a stored embedding is only comparable to one built from the same version.
CHUNK_TEMPLATE_VERSION = 1
# (exclusive upper bound, word): numbers read as words.
LATENCY_BUCKETS_S = (
    (0.5, "fast (<0.5 s)"),
    (2.0, "normal (0.5-2 s)"),
    (5.0, "slow (2-5 s)"),
    (float("inf"), "very slow (>5 s)"),
)
HITS_BUCKETS = ((1, "none"), (11, "some (1-10)"), (float("inf"), "many (>10)"))
# Healthy spans the trace judge may pick in one trace that went fine (agent.judge.healthy_picks).
MAX_HEALTHY_PICKS = 3
# The lowest judge score whose healthy picks become references: a borderline "fine" is not an
# example of a step working.
HEALTHY_MIN_SCORE = 0.9
# Healthy calls of a cluster's failing step the diagnoser is shown (runs.healthy similar()).
HEALTHY_TWINS = 3

# An OpenRouter slug ("vendor/model"); the DIAGNOSER_MODEL environment variable overrides it.
DEFAULT_DIAGNOSER_MODEL = "anthropic/claude-sonnet-5-5"
# The small, cheap model for generated UI, which only arranges text it is given. The UI_SPEC_MODEL
# environment variable overrides it.
DEFAULT_UI_SPEC_MODEL = "anthropic/claude-haiku-5.5"
# The trace judge (agent.judge): one call per trace in a run's window, so a small, cheap model.
# The TRACE_JUDGE_MODEL environment variable overrides it (JUDGE_MODEL is the eval's grader).
DEFAULT_TRACE_JUDGE_MODEL = "anthropic/claude-haiku-5.5"

# Parallel branches within one run. The graph's max_concurrency is MAX_PARALLEL_BRANCHES, which is
# what the judge branches (one small call per trace) run at; the diagnose branches are held to
# MAX_PARALLEL_DIAGNOSES by a per-run semaphore (TraceContext.diagnose_slots), since N clusters
# would otherwise mean N large model calls at once. Neither limits several runs at the same time.
MAX_PARALLEL_BRANCHES = 16
MAX_PARALLEL_DIAGNOSES = 4

# The UI spec of each streamed message (api.ui_spec), one model call per message. Starting values.
MAX_UI_CALLS_PER_RUN = 40  # past it, a message gets no call and no spec
UI_CALL_TIMEOUT_S = 15  # one call; a slow one is not waited for, the message goes without a spec

# Below this many failed traces HDBSCAN has too little to work with: group by step and error.
MIN_TRACES_FOR_HDBSCAN = 6
# Tuned on the synthetic fixture with the real model and digit-masked failure texts:
# min_cluster_size 3 to 5 with min_samples 4 or 5 recovers every group and leaves both outliers
# out; min_samples <= 3 absorbs an outlier into a group (and min_cluster_size 2 splits a group).
# min_samples stays above min_cluster_size on purpose.
MIN_CLUSTER_SIZE = 3  # also the size a step-and-error group needs to rescue noise into a cluster
MIN_SAMPLES = 4
# A trace HDBSCAN puts in a group with less membership than this is treated as noise, so it goes
# to the step-and-error stage or stands alone instead of joining a group it barely fits. On the
# eval's fault day the misfits sat at 0.0 and the true members at 1.0 (docs/eval-notes.md, exp 6).
MIN_MEMBERSHIP = 0.1
MAX_EXEMPLARS = 3  # traces per cluster the diagnoser looks at first

# The cluster map (agent.clustering.cluster_map): the embeddings projected to 3D for the run page.
# PCA is always tried; from this many distinct embeddings t-SNE is tried too, and the map keeps the
# more trustworthy of the two. On the 26-trace test fixture t-SNE's trustworthiness swung from 0.61
# to 0.99 with its settings while PCA's was 0.997, so t-SNE waits for more points.
TSNE_MIN_POINTS = 30
TSNE_PERPLEXITY = 30.0  # capped below a third of the points, as t-SNE needs perplexity < n
MAP_SEED = 0  # t-SNE's random state, so the same run draws the same map
TRUST_NEIGHBORS = 5  # neighbours trustworthiness checks per point

# A diagnosis still citing spans it was not shown after one retry is capped at this confidence.
# A starting value; tune it with the fault-injection eval.
UNSUPPORTED_CONFIDENCE_CAP = 0.3

# Model calls for one cluster (agent.model_guard). Starting values; tune them with the eval.
# Every call counts against MAX_MODEL_ATTEMPTS, a retry after an error as much as the evidence
# re-ask. Past it the cluster is not asked again.
MAX_MODEL_ATTEMPTS = 3
RETRY_DELAY_S = 1.0  # before the first retry; doubles after each
# A cluster that has spent this much is not asked again. The check runs before a re-ask, so a
# cluster can overshoot by one call. The cost cap applies only when the provider reports a cost.
MAX_CLUSTER_TOKENS = 100_000
MAX_CLUSTER_COST_USD = 0.5
# The SDK's own retry is off (agent.model); this bounds one call so a hung one is retried by us.
REQUEST_TIMEOUT_MS = 120_000

# Model calls for one trace's judgement: the same attempts as a cluster, smaller spend caps, since
# the judge sees one tree and runs once per trace in the window. Starting values; tune with the eval.
MAX_TRACE_TOKENS = 20_000
MAX_TRACE_COST_USD = 0.05
# Traces one run judges at most, newest first: one judge call and one tree fetch each. The trace
# server's own cap on a search is 200 (trace_store.const.MAX_LIMIT).
MAX_JUDGED_TRACES = 200

# HDBSCAN fails when it gets fewer traces than either of its size settings.
assert max(MIN_CLUSTER_SIZE, MIN_SAMPLES) <= MIN_TRACES_FOR_HDBSCAN
