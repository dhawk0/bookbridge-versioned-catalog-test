#!/usr/bin/env python3
"""Versioned synthetic-only BookBridge static catalog publisher.

Never reads a production SQLite database and never publishes source records.
It validates synthetic book index shards before staging content-addressed blobs.
Pages receives the full generated site per deployment: deduplication here is
logical storage/repo-diff deduplication, not incremental Pages artifact upload.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

SOURCE_SCHEMA = 'bookbridge-static-1'
TARGET_SCHEMA = 'bookbridge-versioned-static-1'
POINTER_SCHEMA = 'bookbridge-catalog-pointer-1'
VERSION_RE = re.compile(r'v[0-9]{4,8}\Z')
KEY_RE = re.compile(r'[a-z0-9_]{3}\Z')
HEX_RE = re.compile(r'[0-9a-f]{64}\Z')
MAX_SHARD = 16 * 1024 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
MAX_RAW = 100 * 1024 * 1024
MAX_SITE_BYTES = 900 * 1024 * 1024  # conservative vs. 1 GB Pages limit
MAX_SHARDS = 100000
FIELDS = (200, 160, 16, 20, 64, 160)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path, limit: int = MAX_MANIFEST):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('MISSING_SYMLINK_OR_OVERSIZED_JSON:' + str(path))
    return json.loads(path.read_bytes())


def atomic_json(path: Path, doc: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(doc, separators=(',', ':'), sort_keys=True, ensure_ascii=False).encode('utf-8') + b'\n'
    fd, tmp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def src_shard_path(kind: str, key: str) -> Path:
    if kind not in ('title', 'author') or not KEY_RE.fullmatch(key):
        raise ValueError('INVALID_SHARD_KEY')
    return Path('data') / kind / key[0] / (key + '.jsonl.gz')


def blob_path(sha: str) -> str:
    if not HEX_RE.fullmatch(sha):
        raise ValueError('INVALID_BLOB_DIGEST')
    return f'objects/{sha[:2]}/{sha}.jsonl.gz'


def validate_shard(raw_bytes: bytes, expected_n: int) -> None:
    if not 0 < len(raw_bytes) <= MAX_SHARD:
        raise ValueError('SHARD_SIZE_INVALID')
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes)) as stream:
        decompressed = stream.read(MAX_RAW+1)
    if len(decompressed) > MAX_RAW:
        raise ValueError('SHARD_DECOMPRESSION_LIMIT')
    lines = decompressed.splitlines()
    if len(lines) != expected_n:
        raise ValueError('INDEX_COUNT_MISMATCH')
    for line in lines:
        record = json.loads(line)
        if (not isinstance(record, list) or len(record) != 6 or
            any(not isinstance(v, str) or len(v) > cap for v, cap in zip(record, FIELDS))):
            raise ValueError('INVALID_ROW')


def candidate_manifest(source: Path, version: str) -> tuple[dict, list[tuple[Path,str]]]:
    if not VERSION_RE.fullmatch(version):
        raise ValueError('INVALID_VERSION')
    if source.is_symlink() or not source.is_dir():
        raise ValueError('INVALID_CANDIDATE_DIR')
    old = load_json(source / 'manifest.json')
    # Hard gate: even a complete real catalog is NOT eligible for this workflow.
    if old.get('schema') != SOURCE_SCHEMA or old.get('source') != 'synthetic-demo' or old.get('completeness') != 'demo':
        raise ValueError('SYNTHETIC_ONLY_REAL_CATALOG_REFUSED')
    if not isinstance(old.get('record_count'), int) or not 1 <= old['record_count'] <= 1_000_000:
        raise ValueError('INVALID_RECORD_COUNT')
    if not isinstance(old.get('shards'), dict):
        raise ValueError('INVALID_INDEX')
    shards = {'title': {}, 'author': {}}
    staged = []
    counts = {'title': 0, 'author': 0}
    shard_count = 0
    for kind in ('title', 'author'):
        group = old['shards'].get(kind)
        if not isinstance(group, dict):
            raise ValueError('INVALID_INDEX_GROUP')
        for key, entry in sorted(group.items()):
            path = source / src_shard_path(kind, key)
            if path.is_symlink() or not path.is_file():
                raise ValueError('SHARD_MISSING_OR_SYMLINK')
            if (not isinstance(entry, dict) or type(entry.get('bytes')) is not int or
                type(entry.get('n')) is not int or not isinstance(entry.get('sha256'), str) or
                not HEX_RE.fullmatch(entry['sha256'])):
                raise ValueError('INVALID_INDEX_ENTRY')
            if path.stat().st_size != entry['bytes'] or not 0 < entry['bytes'] <= MAX_SHARD:
                raise ValueError('SHARD_LENGTH_MISMATCH')
            data = path.read_bytes()
            if digest(data) != entry['sha256']:
                raise ValueError('SHARD_SHA256_MISMATCH')
            validate_shard(data, entry['n'])
            target = blob_path(entry['sha256'])
            shards[kind][key] = {'n':entry['n'], 'bytes':entry['bytes'],
                                 'sha256':entry['sha256'], 'path':target}
            staged.append((path, target))
            counts[kind] += entry['n']
            shard_count += 1
            if shard_count > MAX_SHARDS:
                raise ValueError('TOO_MANY_SHARDS')
    if counts['title'] != old['record_count'] or counts['author'] != old['record_count']:
        raise ValueError('FULL_INDEX_COUNTS_MISMATCH')
    doc = {'schema': TARGET_SCHEMA, 'version':version, 'source':'synthetic-demo',
           'completeness':'demo', 'record_count':old['record_count'],
           'shards':shards, 'stats': {'shards':shard_count,
                                     'title_entries':counts['title'],
                                     'author_entries':counts['author']}}
    return doc, staged


def check_all_referenced_blobs(site: Path, manifest: dict) -> int:
    if manifest.get('schema') != TARGET_SCHEMA or manifest.get('source') != 'synthetic-demo':
        raise ValueError('UNAPPROVED_VERSION_MANIFEST')
    verified = set()
    for kind in ('title', 'author'):
        for key, ref in manifest.get('shards', {}).get(kind, {}).items():
            src_shard_path(kind, key)
            sha = ref.get('sha256')
            expected = blob_path(sha)
            if ref.get('path') != expected:
                raise ValueError('VERSION_BLOB_PATH_INVALID')
            if expected in verified:
                continue
            p = site / expected
            if p.is_symlink() or not p.is_file() or p.stat().st_size != ref.get('bytes') or digest(p.read_bytes()) != sha:
                raise ValueError('PUBLISHED_BLOB_INTEGRITY_FAILED:' + expected)
            verified.add(expected)
    return len(verified)


def pointer(version: str, manifest_bytes: bytes) -> dict:
    return {'schema':POINTER_SCHEMA, 'version':version,
            'manifest':f'versions/{version}/manifest.json',
            'manifest_sha256':digest(manifest_bytes), 'synthetic_only':True}


def copy_site_shell(site: Path):
    template = Path(__file__).resolve().parent.parent / 'website' / 'index.html'
    if not template.is_file():
        raise ValueError('SITE_TEMPLATE_MISSING')
    shutil.copyfile(template, site / 'index.html')
    (site / '.nojekyll').write_bytes(b'')


def site_bytes(site: Path):
    total = 0
    for p in site.rglob('*'):
        if p.is_symlink():
            raise ValueError('SITE_SYMLINK_FORBIDDEN')
        if p.is_file():
            total += p.stat().st_size
    return total


def publish(site: Path, source: Path, version: str):
    manifest, staged = candidate_manifest(source, version)  # validate BEFORE mutation
    site.mkdir(parents=True, exist_ok=True)
    target = site / 'versions' / version / 'manifest.json'
    canonical = json.dumps(manifest, separators=(',', ':'), sort_keys=True, ensure_ascii=False).encode('utf-8') + b'\n'
    if target.exists() and target.read_bytes() != canonical:
        raise ValueError('VERSION_IMMUTABILITY_VIOLATION')
    created, reused = 0, 0
    for original, dest in staged:
        output = site / dest
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            if output.is_symlink() or output.stat().st_size != original.stat().st_size or digest(output.read_bytes()) != dest.split('/')[-1].removesuffix('.jsonl.gz'):
                raise ValueError('EXISTING_BLOB_COLLISION')
            reused += 1
        else:
            # content-addressed path is immutable once created
            shutil.copyfile(original, output)
            created += 1
    if not target.exists():
        atomic_json(target, manifest)
    copy_site_shell(site)
    check_all_referenced_blobs(site, manifest)
    if site_bytes(site) > MAX_SITE_BYTES:
        raise ValueError('PAGES_SITE_TOO_LARGE')
    # The pointer is the final logical promotion operation.
    atomic_json(site / 'current.json', pointer(version, target.read_bytes()))
    return {'state':'PUBLISHED_LOCAL_SYNTHETIC', 'version':version,
            'new_blobs':created, 'reused_blobs':reused, 'site_bytes':site_bytes(site),
            'versions':len(list((site/'versions').glob('*/manifest.json'))),
            'synthetic_only':True}


def verify(site: Path, all_versions=False):
    ptr = load_json(site / 'current.json')
    if ptr.get('schema') != POINTER_SCHEMA or ptr.get('synthetic_only') is not True or not VERSION_RE.fullmatch(str(ptr.get('version',''))):
        raise ValueError('POINTER_INVALID')
    versions = sorted(p.parent.name for p in (site / 'versions').glob('*/manifest.json'))
    if ptr['version'] not in versions or ptr.get('manifest') != f'versions/{ptr["version"]}/manifest.json':
        raise ValueError('POINTER_TARGET_INVALID')
    checked = []
    for version in (versions if all_versions else [ptr['version']]):
        mfile = site / 'versions' / version / 'manifest.json'
        doc = load_json(mfile)
        if doc.get('version') != version:
            raise ValueError('VERSION_MISMATCH')
        blob_count = check_all_referenced_blobs(site, doc)
        checked.append((version, blob_count))
    if digest((site / ptr['manifest']).read_bytes()) != ptr.get('manifest_sha256'):
        raise ValueError('CURRENT_MANIFEST_CHECKSUM_MISMATCH')
    if site_bytes(site) > MAX_SITE_BYTES:
        raise ValueError('PAGES_SITE_TOO_LARGE')
    return {'state':'VERIFIED', 'active_version':ptr['version'],
            'versions':versions, 'verified_versions':len(checked),
            'checked_blobs':sum(v for _,v in checked), 'site_bytes':site_bytes(site),
            'synthetic_only':True}


def rollback(site: Path, version: str):
    if not VERSION_RE.fullmatch(version):
        raise ValueError('INVALID_VERSION')
    target = site / 'versions' / version / 'manifest.json'
    doc = load_json(target)
    if doc.get('version') != version:
        raise ValueError('VERSION_MISMATCH')
    check_all_referenced_blobs(site, doc)
    atomic_json(site / 'current.json', pointer(version, target.read_bytes()))
    verify(site)
    return {'state':'ROLLED_BACK_LOCAL_SYNTHETIC', 'active_version':version}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    cmds = p.add_subparsers(dest='action', required=True)
    sub = cmds.add_parser('publish')
    sub.add_argument('--site', type=Path, required=True)
    sub.add_argument('--candidate', type=Path, required=True)
    sub.add_argument('--version', required=True)
    sub = cmds.add_parser('rollback')
    sub.add_argument('--site', type=Path, required=True)
    sub.add_argument('--version', required=True)
    sub = cmds.add_parser('verify')
    sub.add_argument('--site', type=Path, required=True)
    sub.add_argument('--all-versions', action='store_true')
    args = p.parse_args()
    try:
        if args.action == 'publish':
            result = publish(args.site, args.candidate, args.version)
        elif args.action == 'rollback':
            result = rollback(args.site, args.version)
        else:
            result = verify(args.site, args.all_versions)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({'state':'REFUSED', 'error':str(error)}, indent=2))
        raise SystemExit(2)

if __name__ == '__main__':
    main()
