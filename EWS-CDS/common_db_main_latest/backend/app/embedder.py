"""
embedder.py — MedCPT clinical embedding pipeline
==================================================

Two separate encoders (MedCPT design):
  ncbi/MedCPT-Article-Encoder  →  for chunks (documents)
  ncbi/MedCPT-Query-Encoder    →  for search queries

Why two encoders?
  MedCPT was trained with asymmetric contrastive loss — query and document
  embeddings live in the same space but are encoded differently. Using the
  wrong encoder for a query will silently return bad results.
  ALWAYS use Article-Encoder for chunks, Query-Encoder for queries.

Output: 768-dimensional L2-normalized float32 vectors.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

logger = logging.getLogger(__name__)

# ── Model identifiers ──────────────────────────────────────────────────────
ARTICLE_ENCODER = "ncbi/MedCPT-Article-Encoder"
QUERY_ENCODER   = "ncbi/MedCPT-Query-Encoder"

# ── Embedding config ───────────────────────────────────────────────────────
VECTOR_DIM  = 768     # MedCPT output dimension
MAX_TOKENS  = 512     # MedCPT max input length
BATCH_SIZE  = 32      # safe for 8GB RAM on CPU


class MedCPTEmbedder:
    """
    Wraps both MedCPT encoders.
    First call downloads models from HuggingFace (~880MB total, once only).
    Subsequent calls load from local cache instantly.
    """

    def __init__(
        self,
        device: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.cache_dir = cache_dir
        self._article_tokenizer = None
        self._article_model     = None
        self._query_tokenizer   = None
        self._query_model       = None
        logger.info(f"MedCPTEmbedder initialised (device={self.device})")

    # ── Lazy loading ───────────────────────────────────────────────────────

    def _load_article_encoder(self) -> None:
        if self._article_model is None:
            logger.info("Loading MedCPT-Article-Encoder …")
            self._article_tokenizer = AutoTokenizer.from_pretrained(
                ARTICLE_ENCODER, cache_dir=self.cache_dir
            )
            self._article_model = AutoModel.from_pretrained(
                ARTICLE_ENCODER, cache_dir=self.cache_dir
            ).to(self.device).eval()
            logger.info("Article-Encoder ready")

    def _load_query_encoder(self) -> None:
        if self._query_model is None:
            logger.info("Loading MedCPT-Query-Encoder …")
            self._query_tokenizer = AutoTokenizer.from_pretrained(
                QUERY_ENCODER, cache_dir=self.cache_dir
            )
            self._query_model = AutoModel.from_pretrained(
                QUERY_ENCODER, cache_dir=self.cache_dir
            ).to(self.device).eval()
            logger.info("Query-Encoder ready")

    # ── Core encode ────────────────────────────────────────────────────────

    def _encode(
        self,
        model: AutoModel,
        tokenizer: AutoTokenizer,
        texts: list[str],
        batch_size: int = BATCH_SIZE,
        show_progress: bool = False,
    ) -> np.ndarray:
        """
        Encodes texts into L2-normalised 768-dim vectors.
        Uses mean-pooling over the last hidden state (MedCPT standard).
        """
        all_vecs: list[np.ndarray] = []
        total = len(texts)

        for start in range(0, total, batch_size):
            batch = texts[start : start + batch_size]

            if show_progress:
                end = min(start + batch_size, total)
                print(f"\r  Embedding {end}/{total} chunks …", end="", flush=True)

            encoded = tokenizer(
                batch,
                truncation=True,
                padding=True,
                max_length=MAX_TOKENS,
                return_tensors="pt",
            )
            encoded = {k: v.to(self.device) for k, v in encoded.items()}

            with torch.no_grad():
                out = model(**encoded)

            # Mean pooling over last hidden state, then L2-normalise
            mask = encoded["attention_mask"].unsqueeze(-1).float()
            pooled = (out.last_hidden_state * mask).sum(1) / mask.sum(1)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            all_vecs.append(pooled.cpu().float().numpy())

        if show_progress:
            print()  # newline after progress

        return np.vstack(all_vecs)

    # ── Public API ─────────────────────────────────────────────────────────

    def embed_chunks(
        self,
        texts: list[str],
        batch_size: int = BATCH_SIZE,
        show_progress: bool = True,
    ) -> np.ndarray:
        """
        Embed document chunks using Article-Encoder.
        Returns float32 array of shape (N, 768).

        Args:
            texts: list of chunk.text strings
            batch_size: how many to encode at once (reduce if OOM)
            show_progress: print a progress counter
        """
        if not texts:
            return np.empty((0, VECTOR_DIM), dtype=np.float32)
        self._load_article_encoder()
        return self._encode(
            self._article_model,
            self._article_tokenizer,
            texts,
            batch_size=batch_size,
            show_progress=show_progress,
        )

    def embed_query(self, query: str) -> np.ndarray:
        """
        Embed a search query using Query-Encoder.
        Returns float32 array of shape (768,).

        CRITICAL: Always use this for queries, never embed_chunks.
        """
        self._load_query_encoder()
        vecs = self._encode(
            self._query_model,
            self._query_tokenizer,
            [query],
            batch_size=1,
            show_progress=False,
        )
        return vecs[0]

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        """Batch-embed multiple queries. Returns (N, 768)."""
        if not queries:
            return np.empty((0, VECTOR_DIM), dtype=np.float32)
        self._load_query_encoder()
        return self._encode(
            self._query_model,
            self._query_tokenizer,
            queries,
            show_progress=False,
        )