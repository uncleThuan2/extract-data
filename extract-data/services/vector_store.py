"""Supabase vector store service using vecs (pgvector wrapper)."""

from __future__ import annotations

import logging

import vecs
from sqlalchemy import create_engine, text

from config import settings
from schemas import DocumentChunk
from services.ai_client import get_embed_fn

# Supabase free tier database limit
_SUPABASE_FREE_DB_LIMIT_BYTES = 500 * 1024 * 1024  # 500 MB


def _fmt_bytes(n: int) -> str:
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"

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


def get_storage_stats() -> dict:
    """Query current storage usage from the Supabase PostgreSQL database.

    Returns a dict with:
      db_size_bytes       – total database size
      db_limit_bytes      – free-tier limit (500 MB)
      collection_size_bytes – size of the vector collection table
      total_chunks        – total number of stored chunks
      per_file            – list of (filename, chunk_count) sorted by count desc
    """
    table = f'vecs."{settings.COLLECTION_NAME}"'
    engine = create_engine(settings.SUPABASE_DB_URL)
    try:
        with engine.connect() as conn:
            db_size_bytes: int = conn.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar() or 0

            collection_size_bytes: int = conn.execute(
                text(f"SELECT pg_total_relation_size('{table}')")
            ).scalar() or 0

            rows = conn.execute(
                text(
                    f"SELECT metadata->>'filename' AS fn, COUNT(*) AS cnt"
                    f" FROM {table}"
                    f" GROUP BY fn ORDER BY cnt DESC"
                )
            ).fetchall()
    finally:
        engine.dispose()

    per_file = [(row.fn or "unknown", int(row.cnt)) for row in rows]
    return {
        "db_size_bytes": db_size_bytes,
        "db_limit_bytes": _SUPABASE_FREE_DB_LIMIT_BYTES,
        "collection_size_bytes": collection_size_bytes,
        "total_chunks": sum(c for _, c in per_file),
        "per_file": per_file,
    }


def format_storage_stats(stats: dict, bold: str = "**") -> str:
    """Format storage stats into a human-readable string.

    Args:
        stats: dict returned by get_storage_stats()
        bold: markdown bold syntax – '**' for Discord, '*' for Telegram
    """
    db = stats["db_size_bytes"]
    limit = stats["db_limit_bytes"]
    col = stats["collection_size_bytes"]
    pct = db / limit * 100

    bar_width = 20
    filled = int(pct / 100 * bar_width)
    bar = "▓" * filled + "░" * (bar_width - filled)

    b = bold  # shorthand
    lines = [
        f"📊 {b}Supabase Storage{b}",
        "",
        f"🗄️ Database: {b}{_fmt_bytes(db)}{b} / 500 MB  ({pct:.1f}%)",
        f"`[{bar}]`",
        f"📦 Vector collection: {b}{_fmt_bytes(col)}{b}",
        f"📄 Total chunks: {b}{stats['total_chunks']:,}{b}",
    ]

    if stats["per_file"]:
        lines += ["", f"📁 {b}Files ({len(stats['per_file'])}){b}:"]
        for i, (fn, cnt) in enumerate(stats["per_file"], 1):
            lines.append(f"  {i}. {fn} — {cnt:,} chunks")

    return "\n".join(lines)
