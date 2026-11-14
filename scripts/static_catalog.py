#!/usr/bin/env python3
"""BookBridge GitHub Pages static catalog proof-of-concept.

Standard library only; reads an existing BookBridge SQLite catalog in mode=ro,
never changes it. Generates static compressed lookup shards. No book downloads.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata

SCHEMA = "bookbridge-static-1"
COLUMNS = "title,author,extension,year,source,source_id"
FIELD_LIMITS = (200, 160, 16, 20, 64, 160)
DEMO_BOOKS = [
    ("The Time Machine", "H. G. Wells", "EPUB", "1895", "demo-public-domain", "wells-time-machine"),
    ("Pride and Prejudice", "Jane Austen", "EPUB", "1813", "demo-public-domain", "austen-pride"),
    ("Frankenstein", "Mary Shelley", "EPUB", "1818", "demo-public-domain", "shelley-frankenstein"),
    ("The War of the Worlds", "H. G. Wells", "EPUB", "1898", "demo-public-domain", "wells-war"),
    ("A Study in Scarlet", "Arthur Conan Doyle", "EPUB", "1887", "demo-public-domain", "doyle-study"),
    ("The Adventures of Sherlock Holmes", "Arthur Conan Doyle", "EPUB", "1892", "demo-public-domain", "doyle-holmes"),
]


def norm(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).casefold()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", s).strip()


def title_norm(s: str) -> str:
    s = norm(s)
    return re.sub(r"^(the|an|a)\s+", "", s)


def surname(s: str) -> str:
    s = str(s or "")
    if "," in s:
        s = s.split(",", 1)[0]
    else:
        terms = norm(s).split()
        s = terms[-1] if terms else ""
    return norm(s)


def shard_key(value: str) -> str:
    value = norm(value)
    stem = (value[:3].replace(" ", "_") + "___")[:3]
    # Non-ASCII keys use a deterministic 256-way shard partition.
    # This keeps filenames portable and avoids losing non-English titles.
    if not re.fullmatch(r"[a-z0-9_]{3}", stem):
        return "u" + format(ord(value[0]) & 255, "02x") if value else "___"
    return stem


def shard_path(kind: str, key: str) -> Path:
    if kind not in ("title", "author") or not re.fullmatch(r"[a-z0-9_]{3}", key):
        raise ValueError("INVALID_SHARD_KEY")
    return Path("data") / kind / key[0] / (key + ".jsonl.gz")


class Writer:
    def __init__(self, temp: Path, max_open: int = 64):
        self.temp = temp
        self.handles: OrderedDict[str, object] = OrderedDict()
        self.max_open = max_open

    def write(self, kind: str, key: str, record: list):
        file = self.temp / kind / key[0] / (key + ".jsonl")
        ident = str(file)
        if ident in self.handles:
            f = self.handles.pop(ident)
        else:
            if len(self.handles) >= self.max_open:
                _, handle = self.handles.popitem(last=False)
                handle.close()
            file.parent.mkdir(parents=True, exist_ok=True)
            f = open(file, "a", encoding="utf-8", newline="\n")
        self.handles[ident] = f
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def close(self):
        for h in self.handles.values():
            h.close()
        self.handles.clear()


def demo_rows(count: int):
    for r in DEMO_BOOKS:
        yield r
    starts = ("Amber", "Beyond", "Cedar", "Distant", "Emerald", "Forgotten", "Golden",
              "Hidden", "Ivory", "Jade", "Kindred", "Lunar", "Midnight", "Northern", "Orchard",
              "Paper", "Quiet", "River", "Silver", "Twilight", "Under", "Velvet", "Winding", "Zenith")
    lasts = ("Adams", "Bennett", "Chen", "Diaz", "Evans", "Foster", "Gomez", "Harris",
             "Ibrahim", "Jones", "Keller", "Lewis", "Morgan", "Nolan", "Ortiz", "Parker",
             "Quinn", "Reed", "Singh", "Turner", "Usman", "Vega", "Walker", "Young")
    for i in range(max(0, count-len(DEMO_BOOKS))):
        start = starts[i % len(starts)]
        last = lasts[(i // len(starts)) % len(lasts)]
        yield (f"{start} Example Story {i:06d}", f"Test Author {last}", "EPUB",
               str(1900 + (i % 120)), "demo-synthetic", f"demo-{i:07d}")


def sqlite_rows(file: Path, limit: int | None, sample_every: int | None = None):
    if not file.is_file() or file.is_symlink():
        raise ValueError("CATALOG_NOT_FOUND_OR_SYMLINK")
    with sqlite3.connect(file.resolve().as_uri() + "?mode=ro", uri=True, timeout=20) as db:
        db.execute("PRAGMA query_only=ON")
        cols = {r[1] for r in db.execute("PRAGMA table_info(books)")}
        if not set(COLUMNS.split(",")).issubset(cols):
            raise ValueError("NOT_BOOKBRIDGE_SCHEMA1")
        query = f"SELECT {COLUMNS} FROM books"
        args = []
        if sample_every:
            query += " WHERE id % ? = 0"
            args.append(sample_every)
        query += " ORDER BY id"
        if limit:
            query += " LIMIT ?"
            args.append(limit)
        for row in db.execute(query, args):
            yield row


def build(input_sqlite: Path | None, output: Path, limit: int | None, demo_count: int, sample_every: int | None = None):
    if output.exists() and (output.is_symlink() or any(output.iterdir())):
        raise ValueError("OUTPUT_MUST_BE_NEW_OR_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    temp = output / "_bookbridge_build_tmp"
    if temp.exists():
        raise ValueError("TEMP_ALREADY_EXISTS")
    temp.mkdir()
    writer = Writer(temp)
    count = 0
    source = "sqlite" if input_sqlite else "synthetic-demo"
    rows = sqlite_rows(input_sqlite, limit, sample_every) if input_sqlite else demo_rows(demo_count)
    try:
        for r in rows:
            record = [str(v or "")[:maximum] for v, maximum in zip(r, FIELD_LIMITS)]
            if not record[0].strip():
                continue
            title_key = shard_key(title_norm(record[0]))
            author_key = shard_key(surname(record[1]))
            writer.write("title", title_key, record)
            writer.write("author", author_key, record)
            count += 1
            if count % 100000 == 0:
                print("Indexed", count, "rows", file=sys.stderr)
    finally:
        writer.close()

    manifest = {"schema": SCHEMA, "record_count": count, "source": source,
                "completeness": "sample" if input_sqlite and (limit or sample_every) else ("demo" if not input_sqlite else "full"),
                "shards": {"title": {}, "author": {}}, "stats": {}}
    compressed_total = 0
    raw_total = 0
    max_file = 0
    shard_count = 0
    for path in sorted(temp.rglob("*.jsonl")):
        rel = path.relative_to(temp)
        kind, group, filename = rel.parts
        key = filename.removesuffix(".jsonl")
        destination = output / shard_path(kind, key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256()
        size = 0
        n = 0
        with path.open("rb") as src, destination.open("wb") as raw_out:
            with gzip.GzipFile(fileobj=raw_out, mode="wb", filename="", compresslevel=6, mtime=0) as dst:
                while chunk := src.read(65536):
                    n += chunk.count(b"\n")
                    size += len(chunk)
                    dst.write(chunk)
        gz_bytes = destination.read_bytes()
        sha.update(gz_bytes)
        compressed_total += len(gz_bytes)
        raw_total += size
        max_file = max(max_file, len(gz_bytes))
        shard_count += 1
        manifest["shards"][kind][key] = {
            "n": n, "bytes": len(gz_bytes), "sha256": sha.hexdigest()
        }
    shutil.rmtree(temp)
    manifest["stats"] = {"shards": shard_count, "compressed_bytes": compressed_total,
                         "raw_bytes": raw_total, "largest_shard_bytes": max_file}
    if input_sqlite:
        with sqlite3.connect(input_sqlite.resolve().as_uri()+"?mode=ro", uri=True) as db:
            total_records = db.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        manifest["stats"]["source_total_records"] = total_records
        if count and total_records > count:
            # Deliberately a rough sizing signal, NOT a claim the complete index will fit.
            manifest["stats"]["rough_full_bytes_if_linear"] = round(compressed_total * total_records / count)
    (output / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":"),
                                                     sort_keys=True, ensure_ascii=False), encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    template = Path(__file__).resolve().parent.parent / "site_template" / "index.html"
    shutil.copyfile(template, output / "index.html")
    print(json.dumps({"state": "BUILT", "output": str(output), "manifest": manifest | {"shards": "omitted"}}, indent=2))
    return manifest


def main():
    p = argparse.ArgumentParser(description="Read-only BookBridge static search index builder")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--sqlite", type=Path, help="existing engine-owned catalog.sqlite3 (opened read-only)")
    group.add_argument("--demo", action="store_true", help="use synthetic sample records (safe to publish)")
    p.add_argument("--output", required=True, type=Path, help="new or empty output directory")
    p.add_argument("--limit", type=int, default=None, help="SQLite: first N rows only; never changes catalog")
    p.add_argument("--demo-count", type=int, default=15000)
    p.add_argument("--sample-every", type=int, default=None,
                   help="SQLite size test: select approximately every Nth ID (does not export full catalog)")
    args = p.parse_args()
    if args.limit is not None and not (1 <= args.limit <= 100_000_000):
        p.error("--limit must be positive")
    if args.demo_count < len(DEMO_BOOKS) or args.demo_count > 1_000_000:
        p.error("--demo-count out of range")
    if args.sample_every is not None and not (2 <= args.sample_every <= 100000):
        p.error("--sample-every must be >=2")
    if args.demo and args.sample_every:
        p.error("--sample-every requires --sqlite")
    build(args.sqlite, args.output, args.limit, args.demo_count, args.sample_every)


if __name__ == "__main__":
    main()
