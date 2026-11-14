# Hosted catalog synchronization (development)

This branch adds **GitHub-hosted synthetic catalog synchronization**. It does not process, fetch, upload or publish LibGen data.

- `publisher/hosted_catalog_sync.py`: builds deterministic synthetic metadata on the hosted runner and compares content-addressed index fingerprints against **all** retained releases.
- `publisher/synthetic_feed.json`: explicitly synthetic test input. The sample year 2028 differs from the earlier demo versions so a manual publication can exercise version creation.
- `.github/workflows/hosted-catalog-sync.yml`: weekly **check-only** job. Manual `publish` is required for any changed synthetic version.
- `tests/test_hosted_catalog_sync.py`: tests change detection, immutability, rollback preservation, invalid provenance, and tamper refusal.

## Safety and rollout

Existing production/client configurations and the working `versioned-catalog.yml` are unchanged. No seedbox commands, client databases, or local SQLite operations are needed.

**Do not merge until CI tests succeed.** GitHub Pages receives a complete site artifact on each successful synthetic publication (not an incremental network upload). The workflow does not alter `current.json` on scheduled checks. A rollback remains effective even when a later content fingerprint already exists.

This is *not* the final LibGen production ingestion connector. A verified, redistributable feed and appropriate hosting must be approved separately.