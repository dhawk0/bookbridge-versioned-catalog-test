"""Regression tests for hosted synthetic-only catalog sync."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "publisher"))
import hosted_catalog_sync as sync
import versioned_catalog as publisher


class HostedSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bb-hosted-test-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.site = self.home / "site"
        self.feed = self.home / "feed.json"
        self.write_feed("2026")

    def write_feed(self, year, **extra):
        doc = {"schema": sync.FEED_SCHEMA, "marker_year": year, "record_count": 60}
        doc.update(extra)
        self.feed.write_text(json.dumps(doc), encoding="utf-8")

    def test_first_publication_and_no_change(self):
        first = sync.run(self.feed, self.site, apply=True)
        self.assertEqual(first["state"], "UPDATED")
        self.assertEqual(first["active_version"], "v0001")
        self.assertEqual(first["public_libgen_records"], 0)
        before = (self.site / "current.json").read_bytes()
        repeat = sync.run(self.feed, self.site, apply=True)
        self.assertEqual(repeat["state"], "NO_CHANGE")
        self.assertEqual(repeat["matching_existing_version"], "v0001")
        self.assertEqual(before, (self.site / "current.json").read_bytes())

    def test_changed_feed_new_version_and_reuse(self):
        sync.run(self.feed, self.site, apply=True)
        self.write_feed("2027")
        plan = sync.run(self.feed, self.site, apply=False)
        self.assertEqual(plan["state"], "CHANGE_AVAILABLE")
        self.assertEqual(plan["next_version"], "v0002")
        self.assertFalse((self.site / "versions/v0002").exists())
        update = sync.run(self.feed, self.site, apply=True)
        self.assertEqual(update["active_version"], "v0002")
        self.assertEqual(update["verified_versions"], 2)
        self.assertGreater(update["reused_blobs"], 0)
        self.assertEqual(publisher.verify(self.site, all_versions=True)["verified_versions"], 2)

    def test_scheduled_run_does_not_undo_rollback(self):
        sync.run(self.feed, self.site, apply=True)
        self.write_feed("2027")
        sync.run(self.feed, self.site, apply=True)
        publisher.rollback(self.site, "v0001")
        report = sync.run(self.feed, self.site, apply=True)
        self.assertEqual(report["state"], "NO_CHANGE")
        self.assertEqual(report["active_version"], "v0001")
        self.assertEqual(report["matching_existing_version"], "v0002")
        self.assertEqual(publisher.verify(self.site)["active_version"], "v0001")

    def test_invalid_source_and_invalid_record_count_rejected(self):
        self.write_feed("2026", schema="legacy-libgen-ipfs")
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_FEED_ONLY"):
            sync.run(self.feed, self.site, apply=True)
        self.write_feed("2026", record_count=0)
        with self.assertRaisesRegex(ValueError, "COUNT_INVALID"):
            sync.run(self.feed, self.site, apply=True)
        self.assertFalse((self.site / "current.json").exists())

    def test_fingerprint_ignores_version_not_content(self):
        sync.run(self.feed, self.site, apply=True)
        manifest = publisher.load_json(self.site / "versions/v0001/manifest.json")
        clone = dict(manifest, version="v9999")
        self.assertEqual(sync.content_fingerprint(manifest), sync.content_fingerprint(clone))
        self.write_feed("2027")
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate"
            sync.build_demo_candidate(sync.load_feed(self.feed), candidate)
            changed, _ = publisher.candidate_manifest(candidate, "v0002")
            self.assertNotEqual(sync.content_fingerprint(manifest), sync.content_fingerprint(changed))

    def test_corrupted_existing_site_refused(self):
        sync.run(self.feed, self.site, apply=True)
        m = publisher.load_json(self.site / "versions/v0001/manifest.json")
        ref = next(iter(m["shards"]["title"].values()))
        (self.site / ref["path"]).write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            sync.run(self.feed, self.site, apply=True)

    def test_next_version_scans_all_preserved_versions(self):
        self.assertEqual(sync.next_version(["v0001", "v0004", "v0002"]), "v0005")
        self.assertEqual(sync.next_version([]), "v0001")
        with self.assertRaises(ValueError):
            sync.next_version(["not-a-version"])


if __name__ == "__main__":
    unittest.main()
