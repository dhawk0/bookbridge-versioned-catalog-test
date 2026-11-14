#!/usr/bin/env python3
"""Hosted synthetic catalog update coordinator (never ingests/publishes LibGen).

Each run builds a deterministic *synthetic-only* candidate on the hosted runner.
A candidate is published as a new immutable version only when its indexed
content differs from EVERY preserved version. This avoids scheduled runs
undoing a deliberate rollback. BookBridge clients download no database.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

import static_catalog as builder
import versioned_catalog as publisher

FEED_SCHEMA = "bookbridge-synthetic-feed-1"
MARKER_TITLE = "BookBridge Synthetic Release Marker"
MARKER_AUTHOR = "Example Catalog Robot"
VERSION = re.compile(r"v[0-9]{4,8}\Z")


def load_feed(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("FEED_MISSING_SYMLINK_OR_OVERSIZED")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or set(doc) != {"schema", "marker_year", "record_count"}:
        raise ValueError("FEED_FIELDS_INVALID")
    if doc["schema"] != FEED_SCHEMA:
        raise ValueError("SYNTHETIC_FEED_ONLY_REAL_SOURCE_REFUSED")
    year, count = doc["marker_year"], doc["record_count"]
    if not isinstance(year, str) or not re.fullmatch(r"20[0-9]{2}", year):
        raise ValueError("DEMO_MARKER_YEAR_INVALID")
    if type(count) is not int or not 6 <= count <= 1_000_000:
        raise ValueError("DEMO_RECORD_COUNT_INVALID")
    return doc


def content_fingerprint(doc: dict) -> str:
    """Hash the indexed content, excluding the release version and volatile stats."""
    if doc.get("source") != "synthetic-demo" or doc.get("completeness") != "demo":
        raise ValueError("NON_SYNTHETIC_CATALOG_REFUSED")
    if doc.get("schema") != publisher.TARGET_SCHEMA:
        raise ValueError("INDEX_SCHEMA_INVALID")
    groups = doc.get("shards")
    if not isinstance(groups, dict) or set(groups) != {"title", "author"}:
        raise ValueError("INDEX_GROUPS_INVALID")
    reduced = {}
    for kind in ("title", "author"):
        if not isinstance(groups[kind], dict):
            raise ValueError("INDEX_GROUP_INVALID")
        reduced[kind] = {}
        for key, item in sorted(groups[kind].items()):
            publisher.src_shard_path(kind, key)
            reduced[kind][key] = {
                "sha256": item["sha256"], "bytes": item["bytes"], "n": item["n"]
            }
    payload = {
        "source": doc["source"], "completeness": doc["completeness"],
        "record_count": doc["record_count"], "shards": reduced,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def next_version(versions: list[str]) -> str:
    if any(not VERSION.fullmatch(v) for v in versions):
        raise ValueError("UNEXPECTED_VERSION")
    n = max((int(v[1:]) for v in versions), default=0) + 1
    if n > 99999999:
        raise ValueError("VERSION_LIMIT_REACHED")
    return "v" + str(n).zfill(4)


def build_demo_candidate(feed: dict, candidate: Path) -> None:
    # The marker is deliberately imaginary and is never presented as a book.
    builder.DEMO_BOOKS[0] = (
        MARKER_TITLE, MARKER_AUTHOR, "EPUB", feed["marker_year"],
        "demo-synthetic", "bookbridge-release-marker"
    )
    # Suppress builder's own JSON report; output just one machine-readable result.
    with contextlib.redirect_stdout(io.StringIO()):
        builder.build(None, candidate, None, feed["record_count"])


def run(feed_file: Path, site: Path, apply: bool = False) -> dict:
    feed = load_feed(feed_file)
    existing = site / "current.json"
    if existing.is_file():
        initial = publisher.verify(site, all_versions=True)
        versions = initial["versions"]
        active = initial["active_version"]
    else:
        # Refuse to overwrite an incomplete or corrupt existing publication.
        if (site / "versions").exists() or existing.is_symlink():
            raise ValueError("EXISTING_SITE_REQUIRES_RECOVERY")
        versions = []
        active = None

    with tempfile.TemporaryDirectory(prefix="bookbridge-hosted-sync-") as temp:
        candidate = Path(temp) / "candidate"
        build_demo_candidate(feed, candidate)
        target_version = next_version(versions)
        manifest, _ = publisher.candidate_manifest(candidate, target_version)
        fingerprint = content_fingerprint(manifest)
        for version in versions:
            old = publisher.load_json(site / "versions" / version / "manifest.json")
            if content_fingerprint(old) == fingerprint:
                return {
                    "state": "NO_CHANGE", "active_version": active,
                    "matching_existing_version": version,
                    "record_count": manifest["record_count"],
                    "source_fingerprint": fingerprint,
                    "public_libgen_records": 0,
                }

        if not apply:
            return {
                "state": "CHANGE_AVAILABLE", "active_version": active,
                "next_version": target_version,
                "record_count": manifest["record_count"],
                "source_fingerprint": fingerprint, "public_libgen_records": 0,
            }

        result = publisher.publish(site, candidate, target_version)
        checked = publisher.verify(site, all_versions=True)
        if checked["active_version"] != target_version:
            raise ValueError("PROMOTION_VERIFICATION_FAILED")
        return {
            "state": "UPDATED", "active_version": target_version,
            "previous_version": active, "record_count": manifest["record_count"],
            "new_blobs": result["new_blobs"], "reused_blobs": result["reused_blobs"],
            "verified_versions": checked["verified_versions"],
            "source_fingerprint": fingerprint, "public_libgen_records": 0,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", required=True, type=Path)
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="Publish validated synthetic changes (default: check only)")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.feed, args.site, args.apply), indent=2))
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"state": "REFUSED", "error": str(exc)}, indent=2))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
