"""Tuning constants for failure clustering and the diagnoser. Revisit once Medas produces real traffic."""

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # fastembed ONNX model, runs locally

# An OpenRouter slug ("vendor/model"); the DIAGNOSER_MODEL environment variable overrides it.
DEFAULT_DIAGNOSER_MODEL = "anthropic/claude-sonnet-5-5"

# Parallel branches within one run (the graph's max_concurrency): N clusters would otherwise
# mean N model calls at once. It does not limit several runs at the same time.
MAX_PARALLEL_BRANCHES = 4

# Below this many failed traces HDBSCAN has too little to work with: group by step and error.
MIN_TRACES_FOR_HDBSCAN = 6
# Tuned on the synthetic fixture with the real model and digit-masked failure texts:
# min_cluster_size 3 to 5 with min_samples 4 or 5 recovers every group and leaves both outliers
# out; min_samples <= 3 absorbs an outlier into a group (and min_cluster_size 2 splits a group).
# min_samples stays above min_cluster_size on purpose.
MIN_CLUSTER_SIZE = 3  # also the size a step-and-error group needs to rescue noise into a cluster
MIN_SAMPLES = 4
MAX_EXEMPLARS = 3  # traces per cluster the diagnoser looks at first

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

# HDBSCAN fails when it gets fewer traces than either of its size settings.
assert max(MIN_CLUSTER_SIZE, MIN_SAMPLES) <= MIN_TRACES_FOR_HDBSCAN
