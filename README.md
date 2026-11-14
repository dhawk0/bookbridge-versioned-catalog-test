# BookBridge — Versioned GitHub Catalog Publisher v0.4

A **separate, synthetic-data-only** GitHub Pages publisher and rollback test. This is **not** a BookBridge Studio/Engine Gallery upgrade. It leaves the installed v0.1.6 engine, 3,157,026-record local catalog, JDownloader, and existing GitHub test sites unchanged.

## What is implemented

- `v0001` and `v0002` deterministic demonstration releases (15,000 synthetic/demo records each)
- Deep validation of manifest, shard SHA-256, row counts, gzip contents, and expected fields *before* promoting a release
- Immutable `versions/v0001/manifest.json` and `versions/v0002/manifest.json`
- Content-addressed `objects/<2-digit-prefix>/<sha256>.jsonl.gz` blobs shared between releases
- `current.json` pointer with a manifest digest, changed only after local validation
- Tested pointer rollback to a previous preserved version
- GitHub Actions workflow that keeps published site contents on a durable `catalog-state` branch and deploys the checked site through the GitHub Pages Actions mechanism
- Simple browser UI showing the active version and fetching/checking only one query shard
- Explicit block on production SQLite imports and non-demo source manifests in this experiment

**Limits:** This tool reuses identical blobs in the catalog-state branch and avoids duplicate published file paths. GitHub Pages Actions still uploads a complete site artifact on every deployment, so this is NOT network-level incremental deployment. The source manifest's SHA is a local integrity check, not independent publisher authenticity. Real-world publication requires separately verified redistribution rights and source provenance, a non-demo release process, and a compatible BookBridge remote client (the existing v0.1.6 client expects the older unversioned shard layout).

## Publish with GitHub Actions (Windows PowerShell)

1. Extract ZIP so this README is at:
   `C:\Users\<your-user>\Desktop\BookBridge_Versioned_GitHub_Catalog_v0.4\README.md`.
2. Use a **new public test repository**, not the existing PoC or load-test repositories:

```powershell
cd "$env:USERPROFILE\Desktop\BookBridge_Versioned_GitHub_Catalog_v0.4"
git init -b main
git config user.name "dhawk0"
git config user.email "$(gh api user --jq .id)+dhawk0@users.noreply.github.com"
git add .
git commit -m "Create synthetic versioned BookBridge catalog publisher"
gh repo create dhawk0/bookbridge-versioned-catalog-test --public --source=. --remote=origin --push
```

3. In `https://github.com/dhawk0/bookbridge-versioned-catalog-test/settings/pages`, choose **GitHub Actions** as publishing source.
4. Run these **in order**, checking each run before the next. If a run fails, do not proceed:

```powershell
gh workflow run versioned-catalog.yml --repo dhawk0/bookbridge-versioned-catalog-test -f operation=publish -f version=v0001
gh run list --repo dhawk0/bookbridge-versioned-catalog-test --workflow versioned-catalog.yml --limit 3
```

Open `https://dhawk0.github.io/bookbridge-versioned-catalog-test/`. Search `BookBridge Synthetic Release Marker`; release v0001 should show synthetic year **2026**.

5. Publish v0002:

```powershell
gh workflow run versioned-catalog.yml --repo dhawk0/bookbridge-versioned-catalog-test -f operation=publish -f version=v0002
```

After the run succeeds, reload the site. The active version should be `v0002` and the synthetic marker year **2027**.

6. Roll back:

```powershell
gh workflow run versioned-catalog.yml --repo dhawk0/bookbridge-versioned-catalog-test -f operation=rollback -f version=v0001
```

After that run succeeds, refresh the site. It should again display `v0001` and year **2026**, while both versions remain preserved on the `catalog-state` branch.

To inspect run detail: `gh run list --repo dhawk0/bookbridge-versioned-catalog-test --workflow versioned-catalog.yml --limit 5` and `gh run view <run-number-or-id> --repo dhawk0/bookbridge-versioned-catalog-test --log-failed`.

## Run tests locally (Python 3.10+)

```bash
python3 -m unittest discover -s tests -v
```

## Publisher CLI (local-only; source must be synthetic)

```bash
python3 publisher/make_synthetic_candidate.py --version v0001 --count 15000 --output /tmp/bb-candidate-1
python3 publisher/versioned_catalog.py publish --site /tmp/bb-site --candidate /tmp/bb-candidate-1 --version v0001
python3 publisher/versioned_catalog.py verify --site /tmp/bb-site --all-versions
python3 publisher/versioned_catalog.py rollback --site /tmp/bb-site --version v0001
```

## Development milestones not yet complete

1. Real-source redistribution/right-to-publish review and independently authenticated metadata feed.
2. Compatible BookBridge engine update for `current.json` and content-addressed shard paths, with full local fallback.
3. Production-scale index-change builder, smoke search quality across varied title/author searches, and immutable authorized release signing.
4. Scheduled update triggering only after source validation and live version+rollback tests.
5. Site size, GitHub file/storage growth and bandwidth monitoring; plan cleanup of unreferenced blobs with retention safeguards.

**Failure behavior:** A bad candidate stops before promotion; a missing older blob stops rollback; a failed Pages deployment can leave the `catalog-state` branch one release ahead of the live Pages deployment. Re-running the same workflow (idempotent for unchanged versions) redeploys its state. No action in this test interacts with your seedbox or BookBridge acquisition pipeline.
