#!/usr/bin/env python3
"""Build or rebuild the vault embedding index using ollama nomic-embed-text.

Usage:
    python3 build_vault_index.py [--vault PATH] [--db PATH] [--incremental]

Stores embeddings in a SQLite DB. Each row: path, mtime, chunk_text, embedding (JSON float list).
"""
import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

VAULT = os.environ.get("OBSIDIAN_VAULT_PATH", "/Users/guido.dilauro/WORKDIR/WORK-WIKI")
DB = os.path.expanduser("~/.claude/vault-index.db")
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "nomic-embed-text"
CHUNK_CHARS = 2000
CHUNK_OVERLAP = 200


def embed(text: str) -> list[float]:
    payload = json.dumps({"model": MODEL, "prompt": text}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["embedding"]


def chunk(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_CHARS
        chunks.append(text[start:end])
        start += CHUNK_CHARS - CHUNK_OVERLAP
    return chunks or [""]


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL,
            mtime REAL NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding TEXT NOT NULL,
            UNIQUE(path, chunk_index)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON embeddings(path)")
    conn.commit()


def index_file(conn: sqlite3.Connection, path: Path, vault: str, force: bool = False) -> int:
    rel = str(path).replace(vault + "/", "")
    mtime = path.stat().st_mtime

    if not force:
        row = conn.execute("SELECT mtime FROM embeddings WHERE path=? LIMIT 1", (rel,)).fetchone()
        if row and abs(row[0] - mtime) < 0.01:
            return 0

    conn.execute("DELETE FROM embeddings WHERE path=?", (rel,))

    text = path.read_text(encoding="utf-8", errors="ignore")
    chunks = chunk(text)
    for i, c in enumerate(chunks):
        emb = embed(c)
        conn.execute(
            "INSERT INTO embeddings(path, mtime, chunk_index, chunk_text, embedding) VALUES (?,?,?,?,?)",
            (rel, mtime, i, c, json.dumps(emb))
        )
    conn.commit()
    return len(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default=VAULT)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--incremental", action="store_true")
    args = parser.parse_args()

    vault = args.vault.rstrip("/")
    conn = sqlite3.connect(args.db)
    init_db(conn)

    files = list(Path(vault).rglob("*.md"))
    total = indexed = 0
    for f in files:
        if any(p.startswith(".") for p in f.parts):
            continue
        total += 1
        n = index_file(conn, f, vault, force=not args.incremental)
        if n:
            indexed += 1
            print(f"  indexed {f.relative_to(vault)} ({n} chunk{'s' if n > 1 else ''})", flush=True)

    conn.close()
    print(f"\nDone: {indexed}/{total} files indexed → {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())