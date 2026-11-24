"""One ingestion path for upload, reviewed documents and the command-line importer."""

import json
import os
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout

from backend.config import settings
from backend.core.doc_graph_enricher import build_legal_graph, enrich_graph
from backend.core.graphrag_engine import GraphRAGEngine
from backend.core.rag_engine import RAGEngine


class DocumentIdentityConflict(ValueError):
    """An existing article ID was supplied with different text."""


def validate_filename(filename: str) -> str:
    if not filename or '/' in filename or '\\' in filename or ':' in filename or Path(filename).name != filename:
        raise ValueError('Invalid document filename')
    if Path(filename).suffix.lower() not in ('.docx', '.json'):
        raise ValueError('Only DOCX or parsed JSON documents are supported')
    return filename


def save_chunks(path: Path, chunks: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            json.dump(chunks, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _merge_document_chunks(previous: list[dict], incoming: list[dict]) -> list[dict]:
    merged = {chunk['id']: chunk for chunk in previous}
    for chunk in incoming:
        existing = merged.get(chunk['id'])
        if existing is not None and existing['text'] != chunk['text']:
            raise DocumentIdentityConflict('This document identity already has different content. Reindex in a fresh workspace instead of mixing versions.')
        merged.setdefault(chunk['id'], chunk)
    return list(merged.values())


async def ingest_document(chunks: list[dict], source_filename: str) -> dict:
    validate_filename(source_filename)
    build_legal_graph(chunks, source_filename)  # Validate before any storage writes.
    workdir = Path(settings.LIGHTRAG_WORKING_DIR)
    workdir.mkdir(parents=True, exist_ok=True)
    # The file lock also serializes CLI imports and separate API workers.
    lock = FileLock(str(workdir / '.legal-ingestion.lock'), timeout=0)
    try:
        lock.acquire()
    except Timeout as error:
        raise RuntimeError('Another document is being indexed; retry when it finishes') from error
    try:
        filename = chunks[0]['document_id'] + '.json'
        if Path(filename).name != filename or any(c in filename for c in '/\\:'):
            raise ValueError('Invalid document identity')
        snapshot = workdir / filename
        published = GraphRAGEngine._working_dir() / 'input' / filename
        previous_published = json.loads(published.read_text(encoding='utf-8')) if published.exists() else []
        published_chunks = _merge_document_chunks(previous_published, chunks)
        previous = json.loads(snapshot.read_text(encoding='utf-8')) if snapshot.exists() else []
        retained_chunks = _merge_document_chunks(previous, published_chunks)
        save_chunks(snapshot, retained_chunks)
        rag = RAGEngine.get_instance()
        # LightRAG deduplicates filenames, so each article needs a stable source path.
        await rag.ainsert(
            [c['text'] for c in chunks], ids=[c['id'] for c in chunks],
            file_paths=[f"{source_filename}#{c['id']}" for c in chunks],
            split_by_character='\u241f', split_by_character_only=True,
        )
        statuses = await rag.doc_status.get_by_ids([c['id'] for c in chunks])
        if len(statuses) != len(chunks) or any(not status or status.get('status') != 'processed' for status in statuses):
            raise RuntimeError('LightRAG did not finish indexing every article; source retained for retry')
        summary = await enrich_graph(rag, chunks, source_filename)
        # Publish indexed excerpts without dropping previously published articles.
        save_chunks(published, published_chunks)
        await GraphRAGEngine.build_index()
        return summary
    finally:
        lock.release()
