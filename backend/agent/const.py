"""Tuning constants for failure clustering. Revisit once Medas produces real traffic."""

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # fastembed ONNX model, runs locally

# Below this many failed traces HDBSCAN has too little to work with: group by step and error.
MIN_TRACES_FOR_HDBSCAN = 6
# Tried on the synthetic fixture with the real model: min_cluster_size=2 / min_samples<=2 split a
# group and absorbed an unrelated outlier into another; 3 / 3 recovered every group.
MIN_CLUSTER_SIZE = 3  # also the size a step-and-error group needs to rescue noise into a cluster
MIN_SAMPLES = 3
MAX_EXEMPLARS = 3  # traces per cluster the diagnoser looks at first

# HDBSCAN fails when it gets fewer traces than either of its size settings.
assert max(MIN_CLUSTER_SIZE, MIN_SAMPLES) <= MIN_TRACES_FOR_HDBSCAN
