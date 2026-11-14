#!/usr/bin/env python3
"""Live, read-only contract test of the synthetic GitHub Pages remote index.

No real LibGen records, local database, client installation, or acquisition.
This tests the hosted byte-level protocol that BookBridge 0.1.8 consumes.
"""
import gzip
import hashlib
import io
import json
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = "https://dhawk0.github.io/bookbridge-versioned-catalog-test/"
MARKER_TITLE = "BookBridge Synthetic Release Marker"
MARKER_AUTHOR = "Example Catalog Robot"

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        raise ValueError("REDIRECT_REFUSED")

def fetch(path, max_size):
    if not re.fullmatch(r"(current\.json|versions/v[0-9]{4,8}/manifest\.json|objects/[0-9a-f]{2}/[0-9a-f]{64}\.jsonl\.gz)", path):
        raise ValueError("INVALID_STATIC_PATH")
    req = Request(BASE + path, headers={"User-Agent": "BookBridge-Hosted-Contract-Test/1"})
    with build_opener(NoRedirect()).open(req, timeout=25) as response:
        if response.status != 200:
            raise ValueError("REMOTE_STATUS")
        content = response.read(max_size + 1)
    if len(content) > max_size:
        raise ValueError("REMOTE_SIZE_LIMIT")
    return content

def load():
    pointer = json.loads(fetch("current.json", 16384))
    version = pointer.get("version")
    if (pointer.get("schema") != "bookbridge-catalog-pointer-1"
            or not isinstance(version, str) or not re.fullmatch(r"v[0-9]{4,8}", version)
            or pointer.get("synthetic_only") is not True):
        raise ValueError("DEMO_POINTER_INVALID")
    path = f"versions/{version}/manifest.json"
    if pointer.get("manifest") != path:
        raise ValueError("MANIFEST_PATH_INVALID")
    raw = fetch(path, 4 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != pointer.get("manifest_sha256"):
        raise ValueError("MANIFEST_HASH_MISMATCH")
    manifest = json.loads(raw)
    if (manifest.get("schema") != "bookbridge-versioned-static-1"
            or manifest.get("version") != version
            or manifest.get("source") != "synthetic-demo"
            or manifest.get("completeness") != "demo"):
        raise ValueError("UNEXPECTED_SOURCE_OR_SCHEMA")
    count = manifest.get("record_count")
    if type(count) is not int or not 1 <= count <= 1_000_000:
        raise ValueError("BAD_RECORD_COUNT")
    for group in ("title", "author"):
        shards = manifest.get("shards", {}).get(group)
        if not isinstance(shards, dict) or sum(v.get("n", 0) for v in shards.values()) != count:
            raise ValueError("INCOMPLETE_" + group.upper() + "_INDEX")
    return pointer, manifest

def check_group(manifest, group, key):
    item = manifest["shards"][group][key]
    digest = item.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("SHARD_DIGEST_INVALID")
    path = f"objects/{digest[:2]}/{digest}.jsonl.gz"
    if item.get("path") != path:
        raise ValueError("SHARD_PATH_INVALID")
    size = item.get("bytes")
    if type(size) is not int or not 0 < size <= 16 * 1024 * 1024:
        raise ValueError("SHARD_SIZE_INVALID")
    compressed = fetch(path, size)
    if len(compressed) != size or hashlib.sha256(compressed).hexdigest() != digest:
        raise ValueError("SHARD_HASH_MISMATCH")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("SHARD_DECOMPRESSION_LIMIT")
    rows = [json.loads(row) for row in raw.splitlines()]
    if len(rows) != item.get("n"):
        raise ValueError("SHARD_ROW_COUNT_MISMATCH")
    found = [row for row in rows if (isinstance(row, list) and len(row) == 6
             and row[0] == MARKER_TITLE and row[1] == MARKER_AUTHOR
             and row[5] == "bookbridge-release-marker")]
    if len(found) != 1:
        raise ValueError("SYNTHETIC_MARKER_NOT_FOUND")
    return found[0][3]

def main():
    pointer, manifest = load()
    title_year = check_group(manifest, "title", "boo")
    author_year = check_group(manifest, "author", "exa")
    if title_year != author_year:
        raise ValueError("TITLE_AUTHOR_INDEX_DISAGREE")
    print(json.dumps({
        "state": "LIVE_GITHUB_INDEX_CONTRACT_VERIFIED",
        "catalog_version": pointer["version"],
        "synthetic_only": True,
        "record_count": manifest["record_count"],
        "title_shards_fetched": 1,
        "author_shards_fetched": 1,
        "marker_year": title_year,
        "local_databases_accessed": False,
    }, indent=2))

if __name__ == "__main__":
    main()
