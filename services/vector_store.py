"""Supabase vector store service using vecs (pgvector wrapper)."""

from __future__ import annotations

import logging

import vecs

from config import settings
from schemas import DocumentChunk
from services.ai_client import get_embed_fn

logger = logging.getLogger(__name__)

_vx: vecs.Client | None = None


def _get_vecs_client() -> vecs.Client:
    global _vx
    if _vx is None:
        _vx = vecs.create_client(settings.SUPABASE_DB_URL)
    return _vx


def get_collection() -> vecs.Collection:
    """Get or create the vector collection in Supabase."""
    vx = _get_vecs_client()
    return vx.get_or_create_collection(
        name=settings.COLLECTION_NAME,
        dimension=settings.EMBEDDING_DIMENSION,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using the configured AI provider."""
    return get_embed_fn()(texts)


def upsert_chunks(chunks: list[DocumentChunk]) -> int:
    """Embed and store document chunks in Supabase vector store."""
    if not chunks:
        return 0

    collection = get_collection()
    batch_size = 100
    total = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.text for c in batch]
        embeddings = embed_texts(texts)

        records = [
            (
                chunk.chunk_id,
                embedding,
                {**chunk.metadata, "text": chunk.text},
            )
            for chunk, embedding in zip(batch, embeddings)
        ]

        collection.upsert(records=records)
        total += len(records)
        logger.info("Upserted batch %d-%d", i, i + len(batch))

    # Create index for fast search (idempotent)
    collection.create_index(measure=vecs.IndexMeasure.cosine_distance, replace=True)
    logger.info("Total %d chunks stored in Supabase", total)
    return total


def search_similar(query: str, top_k: int = 5) -> list[dict]:
    """Search for chunks similar to the query."""
    collection = get_collection()
    query_embedding = embed_texts([query])[0]

    results = collection.query(
        data=query_embedding,
        limit=top_k,
        include_value=True,
        include_metadata=True,
    )

    documents = []
    for item in results:
        doc_id, distance, metadata = item
        documents.append(
            {
                "id": doc_id,
                "score": 1 - distance,
                "text": metadata.get("text", ""),
                "filename": metadata.get("filename", ""),
                "page_number": metadata.get("page_number", 0),
            }
        )
    return documents


def list_indexed_files() -> list[str]:
    """List all unique filenames that have been indexed."""
    collection = get_collection()
    zero_vec = [0.0] * settings.EMBEDDING_DIMENSION
    results = collection.query(
        data=zero_vec,
        limit=10000,
        include_metadata=True,
    )
    filenames = set()
    for item in results:
        _, _, metadata = item
        if metadata and "filename" in metadata:
            filenames.add(metadata["filename"])
    return sorted(filenames)


def delete_file(filename: str) -> int:
    """Delete all chunks belonging to a given filename. Returns number of chunks deleted."""
    collection = get_collection()
    zero_vec = [0.0] * settings.EMBEDDING_DIMENSION
    results = collection.query(
        data=zero_vec,
        limit=10000,
        include_metadata=True,
    )

    ids_to_delete = []
    for item in results:
        doc_id, _, metadata = item
        if metadata and metadata.get("filename") == filename:
            ids_to_delete.append(doc_id)

    if ids_to_delete:
        collection.delete(ids=ids_to_delete)
        logger.info("Deleted %d chunks for file '%s'", len(ids_to_delete), filename)

    return len(ids_to_delete)
