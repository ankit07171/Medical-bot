"""
session_store.py
-----------------
Manages a private, per-browser-session Chroma vector store for
user-uploaded documents so different visitors never see each other's files.

Layout on disk:
    chroma_store/
        <session_id>/
            manifest.json         -> list of uploaded files + chunk ids
            (chroma sqlite files) -> vector data
"""

import json
import os
import shutil
import uuid
from typing import Dict, List

from langchain.schema import Document

# Silences a harmless "Failed to send telemetry event" warning some
# chromadb/posthog version combinations print to stderr.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

STORE_ROOT = os.environ.get("SESSION_STORE_DIR", "chroma_store")


def _session_dir(session_id: str) -> str:
    d = os.path.join(STORE_ROOT, session_id)
    os.makedirs(d, exist_ok=True)
    return d


def _manifest_path(session_id: str) -> str:
    return os.path.join(_session_dir(session_id), "manifest.json")


def load_manifest(session_id: str) -> List[Dict]:
    path = _manifest_path(session_id)
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)


def save_manifest(session_id: str, manifest: List[Dict]) -> None:
    with open(_manifest_path(session_id), "w") as f:
        json.dump(manifest, f, indent=2)


def get_vectorstore(session_id: str, embeddings):
    from chromadb.config import Settings
    from langchain_chroma import Chroma

    return Chroma(
        collection_name="uploads",
        persist_directory=_session_dir(session_id),
        embedding_function=embeddings,
        client_settings=Settings(anonymized_telemetry=False),
    )


def add_documents(session_id: str, embeddings, filename: str, chunks: List[Document], used_ocr: bool) -> int:
    """Embeds and stores chunks for one uploaded file. Returns chunk count."""
    if not chunks:
        return 0

    vectorstore = get_vectorstore(session_id, embeddings)
    ids = [str(uuid.uuid4()) for _ in chunks]
    vectorstore.add_documents(chunks, ids=ids)

    manifest = load_manifest(session_id)
    manifest.append(
        {
            "filename": filename,
            "chunk_ids": ids,
            "chunk_count": len(chunks),
            "used_ocr": used_ocr,
        }
    )
    save_manifest(session_id, manifest)
    return len(chunks)


def remove_file(session_id: str, embeddings, filename: str) -> bool:
    manifest = load_manifest(session_id)
    entry = next((m for m in manifest if m["filename"] == filename), None)
    if not entry:
        return False

    vectorstore = get_vectorstore(session_id, embeddings)
    vectorstore.delete(ids=entry["chunk_ids"])

    manifest = [m for m in manifest if m["filename"] != filename]
    save_manifest(session_id, manifest)
    return True


def has_documents(session_id: str) -> bool:
    return len(load_manifest(session_id)) > 0


def clear_session(session_id: str) -> None:
    shutil.rmtree(_session_dir(session_id), ignore_errors=True)


def retrieve(session_id: str, embeddings, query: str, k: int = 4) -> List[Document]:
    if not has_documents(session_id):
        return []
    vectorstore = get_vectorstore(session_id, embeddings)
    return vectorstore.similarity_search(query, k=k)
