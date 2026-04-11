"""File upload service – process a document and store it in Supabase.

Flow:
  1. Check if filename already exists in the vector store → raise FileExistsError
  2. Extract text chunks from the file bytes (process_document)
  3. Embed with Jina AI and upsert to Supabase (upsert_chunks)

Usage:
    from services.upload_service import upload_file, FileAlreadyIndexedError

    try:
        count = upload_file(file_bytes, filename)
    except FileAlreadyIndexedError as e:
        # filename already in DB
        print(e.message, e.chunk_count)
"""

from __future__ import annotations

import logging

from services.document_processor import is_supported_file, process_document
from services.vector_store import list_indexed_files, upsert_chunks

logger = logging.getLogger(__name__)


class FileAlreadyIndexedError(Exception):
    """Raised when the filename is already present in the vector store."""

    def __init__(self, filename: str, chunk_count: int) -> None:
        self.filename = filename
        self.chunk_count = chunk_count
        self.message = (
            f"File '{filename}' đã được index rồi ({chunk_count} chunks). "
            "Dùng /delete để xóa trước nếu muốn index lại."
        )
        super().__init__(self.message)


class UnsupportedFileError(Exception):
    """Raised when the file extension is not supported."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__(f"File '{filename}' không được hỗ trợ.")


def file_already_indexed(filename: str) -> int:
    """Return chunk count if filename is already in the DB, else 0."""
    indexed = list_indexed_files()
    if filename in indexed:
        # Count chunks for this file by checking via delete_file dry-run equivalent
        # We reuse list_indexed_files which gets filenames; for chunk count we do a separate query
        from sqlalchemy import create_engine, text
        from config import settings

        engine = create_engine(settings.SUPABASE_DB_URL)
        table = f'vecs."{settings.COLLECTION_NAME}"'
        try:
            with engine.connect() as conn:
                count = conn.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE metadata->>'filename' = :fn"),
                    {"fn": filename},
                ).scalar() or 0
            return int(count)
        finally:
            engine.dispose()
    return 0


def upload_file(file_bytes: bytes, filename: str) -> int:
    """Process and upload a file to Supabase.

    Args:
        file_bytes: Raw file content.
        filename:   Original filename (used as the key in metadata).

    Returns:
        Number of chunks stored.

    Raises:
        UnsupportedFileError:     File extension not in SUPPORTED_EXTENSIONS.
        FileAlreadyIndexedError:  Filename already exists in the vector store.
        ValueError:               File has no extractable text content.
    """
    # 1. Check file type
    if not is_supported_file(filename):
        raise UnsupportedFileError(filename)

    # 2. Check if already indexed
    existing_chunks = file_already_indexed(filename)
    if existing_chunks > 0:
        raise FileAlreadyIndexedError(filename, existing_chunks)

    # 3. Extract text chunks
    logger.info("upload_file: processing '%s' (%d bytes)", filename, len(file_bytes))
    chunks = process_document(file_bytes, filename)
    if not chunks:
        raise ValueError(
            f"Không extract được text từ '{filename}'. "
            "Đảm bảo file có nội dung văn bản (không phải ảnh scan)."
        )
    logger.info("upload_file: extracted %d chunks from '%s'", len(chunks), filename)

    # 4. Embed (Jina AI) + upsert to Supabase
    count = upsert_chunks(chunks)
    logger.info("upload_file: stored %d chunks for '%s'", count, filename)
    return count
