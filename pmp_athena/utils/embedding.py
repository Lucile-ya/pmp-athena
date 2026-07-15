"""
Embedding 函数封装 —— sentence-transformers 单例
"""

import threading
from chromadb.api.types import Documents, Embeddings
import numpy as np


_embedding_model = None
_model_lock = threading.Lock()


def get_embedding_function(model_name: str | None = None):
    """
    返回一个 ChromaDB 兼容的 embedding function。
    使用 sentence-transformers 开源模型，无需 API Key。
    """
    from chromadb import Documents, EmbeddingFunction
    from chromadb.api.types import Embeddings

    if model_name is None:
        from ..config import EMBEDDING_MODEL

        model_name = EMBEDDING_MODEL

    class SentenceTransformerEF(EmbeddingFunction):
        def __init__(self):
            self._model = None

        @property
        def model(self):
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(model_name)
            return self._model

        def __call__(self, input: Documents) -> Embeddings:
            vectors = self.model.encode(list(input), convert_to_numpy=True)
            return vectors.tolist()

    return SentenceTransformerEF()
