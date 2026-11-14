#!/usr/bin/env python3
"""Produce two deterministic DEMO-only versions using original BookBridge indexer."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import static_catalog as builder

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--version', required=True, choices=['v0001','v0002'])
p.add_argument('--output', type=Path, required=True)
p.add_argument('--count', type=int, default=15000)
a = p.parse_args()
if a.count < 6 or a.count > 1_000_000:
    p.error('--count outside 6..1000000')
# This is not a real book. Only synthetic marker content varies between releases.
builder.DEMO_BOOKS[0] = (
    'BookBridge Synthetic Release Marker', 'Example Catalog Robot',
    'EPUB', '2026' if a.version == 'v0001' else '2027',
    'demo-synthetic', 'bookbridge-release-marker'
)
builder.build(None, a.output, None, a.count)
