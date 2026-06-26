"""
qdrant_store.py — Qdrant vector store for Discharge Summary AI
===============================================================

Stores chunk embeddings + full metadata payload.
Supports per-encounter filtering and section-specific filtering.

Storage modes:
  QdrantStore()                      → in-memory  (lost on restart)
  QdrantStore(path="./qdrant_data")  → local disk  (no Docker, persists)
  QdrantStore(url="http://localhost:6333") → Docker  (production)

For Week 4: use local disk mode — persists without Docker.
For production: switch to Docker URL.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from .chunker import Chunk
from .embedder import VECTOR_DIM

logger = logging.getLogger(__name__)

COLLECTION_NAME = "cardiology_chunks"


class QdrantStore:
    """
    Vector store for cardiology chunk embeddings.

    Each Qdrant point = one Chunk:
      vector  → 768-dim MedCPT embedding (for similarity search)
      payload → full chunk metadata (for filtering + retrieval)
    """

    def __init__(
        self,
        path: Optional[str] = "./qdrant_data",
        url: Optional[str] = None,
    ) -> None:
        """
        Args:
            path: local disk path for persistent storage (default: ./qdrant_data)
            url:  Docker URL e.g. "http://localhost:6333"
                  If url is given, path is ignored.
        """
        if url:
            self.client = QdrantClient(url=url)
            logger.info(f"Qdrant connected to {url}")
        elif path:
            self.client = QdrantClient(path=path)
            logger.info(f"Qdrant local store at {path}")
        else:
            self.client = QdrantClient(":memory:")
            logger.info("Qdrant running in-memory (not persistent)")

        self._ensure_collection()

    # ── Setup ──────────────────────────────────────────────────────────────

    def _ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        existing = [c.name for c in self.client.get_collections().collections]
        if COLLECTION_NAME not in existing:
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=VECTOR_DIM,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Created Qdrant collection '{COLLECTION_NAME}'")

    # ── Indexing ───────────────────────────────────────────────────────────

    def index_encounter(
        self,
        chunks: list[Chunk],
        embeddings: np.ndarray,
        batch_size: int = 256,
    ) -> None:
        """
        Index all chunks for one encounter.

        Args:
            chunks:     list of Chunk objects
            embeddings: float32 array (N, 768) aligned with chunks
            batch_size: Qdrant upload batch size
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) "
                "must have same length"
            )
        if len(chunks) == 0:
            return

        hadm_id = chunks[0].encounter_id

        # Delete existing points for this encounter (idempotent re-indexing)
        self.client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[FieldCondition(
                    key="encounter_id",
                    match=MatchValue(value=hadm_id)
                )]
            ),
        )

        # Build and upload Qdrant points
        for start in range(0, len(chunks), batch_size):
            batch_chunks = chunks[start : start + batch_size]
            batch_vecs   = embeddings[start : start + batch_size]

            points = [
                PointStruct(
                    id=_chunk_id_to_int(c.chunk_id),
                    vector=vec.tolist(),
                    payload=c.to_qdrant_payload(),
                )
                for c, vec in zip(batch_chunks, batch_vecs)
            ]
            self.client.upsert(collection_name=COLLECTION_NAME, points=points)

        logger.info(
            f"Indexed {len(chunks)} chunks for hadm_id={hadm_id} "
            f"in collection '{COLLECTION_NAME}'"
        )

    # ── Search ─────────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: np.ndarray,
        encounter_id: int,
        top_k: int = 30,
        section_filter: Optional[list[str]] = None,
        note_type_filter: Optional[list[str]] = None,
        must_be_cardiology_critical: bool = False,
    ) -> list[dict]:
        """
        Dense search over chunks for one encounter.

        Args:
            query_vector:  768-dim query embedding (from Query-Encoder)
            encounter_id:  hadm_id to restrict search to
            top_k:         how many results to return
            section_filter: restrict to these sections only
                           e.g. ['investigations', 'hospital_course']
            note_type_filter: restrict to these note_types
                              e.g. ['lab', 'troponin_trend']
            must_be_cardiology_critical: only return is_cardiology_critical=True chunks

        Returns:
            list of dicts with keys: chunk_id, score, text, note_type,
                                     section, timestamp, metadata
        """
        must_conditions = [
            FieldCondition(
                key="encounter_id",
                match=MatchValue(value=encounter_id)
            )
        ]

        if section_filter:
            # Qdrant OR across sections
            from qdrant_client.models import MatchAny
            must_conditions.append(
                FieldCondition(key="section", match=MatchAny(any=section_filter))
            )

        if note_type_filter:
            from qdrant_client.models import MatchAny
            must_conditions.append(
                FieldCondition(key="note_type", match=MatchAny(any=note_type_filter))
            )

        if must_be_cardiology_critical:
            must_conditions.append(
                FieldCondition(
                    key="is_cardiology_critical",
                    match=MatchValue(value=True)
                )
            )

        results = self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector.tolist(),
            query_filter=Filter(must=must_conditions),
            limit=top_k,
            with_payload=True,
        ).points

        return [
            {
                "chunk_id":  r.payload.get("chunk_id"),
                "score":     round(r.score, 4),
                "text":      r.payload.get("text", ""),
                "note_type": r.payload.get("note_type"),
                "section":   r.payload.get("section"),
                "timestamp": r.payload.get("timestamp"),
                "is_cardiology_critical": r.payload.get("is_cardiology_critical", False),
                "cardiac_med_category":  r.payload.get("cardiac_med_category"),
            }
            for r in results
        ]

    # ── Stats ──────────────────────────────────────────────────────────────

    def count_encounter(self, encounter_id: int) -> int:
        """How many chunks indexed for this encounter."""
        result = self.client.count(
            collection_name=COLLECTION_NAME,
            count_filter=Filter(must=[
                FieldCondition(
                    key="encounter_id",
                    match=MatchValue(value=encounter_id)
                )
            ]),
            exact=True,
        )
        return result.count

    def total_indexed(self) -> int:
        """Total chunks indexed across all encounters."""
        return self.client.count(
            collection_name=COLLECTION_NAME, exact=True
        ).count

    def get_indexed_encounters(self) -> list[int]:
        """List of all hadm_ids currently indexed."""
        # Scroll through all points to find unique encounter_ids
        encountered: set[int] = set()
        offset = None
        while True:
            records, offset = self.client.scroll(
                collection_name=COLLECTION_NAME,
                limit=1000,
                with_payload=["encounter_id"],
                offset=offset,
            )
            for r in records:
                enc_id = r.payload.get("encounter_id")
                if enc_id:
                    encountered.add(enc_id)
            if offset is None:
                break
        return sorted(encountered)


# ── Helpers ────────────────────────────────────────────────────────────────

def _chunk_id_to_int(chunk_id: str) -> int:
    """
    Convert UUID string to int for Qdrant point ID.
    Qdrant requires integer IDs. We take the first 16 hex chars.
    """
    return int(chunk_id.replace("-", "")[:16], 16)