"""
Text embedder for failure clustering.

FastEmbedEmbedder runs a local ONNX model, so failure text never leaves the machine (Medas traces
may hold clinical content). Tests use the offline HashingEmbedder in tests/fakes.py instead, so CI
never downloads the model.
"""

import threading
from typing import Protocol

import numpy as np

from agent.const import EMBEDDING_MODEL


class Embedder(Protocol):
    """Turns texts into one row vector each. Sync and CPU-bound: call it off the event loop."""

    def embed(self, texts: list[str]) -> np.ndarray: ...


class FastEmbedEmbedder:
    """fastembed model, loaded on first use.

    The model files are cached where fastembed puts them: FASTEMBED_CACHE_PATH, else a
    fastembed_cache folder in the temp dir (which is usually cleared on reboot).
    """

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()  # concurrent runs can reach the first call together

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding  # heavy import, only when first needed

                self._model = TextEmbedding(EMBEDDING_MODEL)
            return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(list(self._load().embed(texts)), dtype=np.float32)
