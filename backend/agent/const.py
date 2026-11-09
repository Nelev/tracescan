"""Tuning constants for failure clustering and the diagnoser. Revisit once Medas produces real traffic."""

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # fastembed ONNX model, runs locally

# An OpenRouter slug ("vendor/model"); the DIAGNOSER_MODEL environment variable overrides it.
DEFAULT_DIAGNOSER_MODEL = "anthropic/claude-sonnet-5-5"
# Parallel branches per run: N clusters would otherwise mean N model calls at once.
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

# HDBSCAN fails when it gets fewer traces than either of its size settings.
assert max(MIN_CLUSTER_SIZE, MIN_SAMPLES) <= MIN_TRACES_FOR_HDBSCAN
