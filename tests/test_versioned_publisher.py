import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'publisher'))
sys.path.insert(0, str(ROOT/'scripts'))
import versioned_catalog as v
import static_catalog as b

class VersionedTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix='bb-vpub-'))
        self.site = self.temp/'site'
        self.c1 = self.temp/'v1'
        self.c2 = self.temp/'v2'
        saved = b.DEMO_BOOKS[:]
        try:
            b.DEMO_BOOKS[0] = ('BookBridge Synthetic Release Marker','Example Catalog Robot','EPUB','2026','demo-synthetic','marker')
            b.build(None,self.c1,None,150)
            b.DEMO_BOOKS[0] = ('BookBridge Synthetic Release Marker','Example Catalog Robot','EPUB','2027','demo-synthetic','marker')
            b.build(None,self.c2,None,150)
        finally:
            b.DEMO_BOOKS[:] = saved
    def tearDown(self):
        shutil.rmtree(self.temp)
    def test_publish_and_rollback_preserve_both_versions(self):
        first = v.publish(self.site, self.c1, 'v0001')
        second = v.publish(self.site, self.c2, 'v0002')
        self.assertGreater(first['new_blobs'], 0)
        self.assertGreater(second['reused_blobs'], 0)
        self.assertGreater(second['new_blobs'], 0)
        self.assertEqual(v.verify(self.site,True)['active_version'],'v0002')
        self.assertEqual(v.rollback(self.site,'v0001')['active_version'],'v0001')
        self.assertEqual(v.verify(self.site,True)['versions'],['v0001','v0002'])
        self.assertEqual(v.rollback(self.site,'v0002')['active_version'],'v0002')
    def test_source_guard_rejects_real_catalog(self):
        p=self.c1/'manifest.json'
        m=json.loads(p.read_text());m['source']='sqlite';m['completeness']='full'
        p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'SYNTHETIC_ONLY'):
            v.publish(self.site,self.c1,'v0001')
        self.assertFalse((self.site/'current.json').exists())
    def test_corrupted_shard_prevents_promotion(self):
        p=next((self.c1/'data').rglob('*.jsonl.gz'))
        p.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'SHARD_LENGTH_MISMATCH'):
            v.publish(self.site,self.c1,'v0001')
        self.assertFalse((self.site/'current.json').exists())
    def test_immutable_version_cannot_be_redefined(self):
        v.publish(self.site,self.c1,'v0001')
        with self.assertRaisesRegex(ValueError,'VERSION_IMMUTABILITY_VIOLATION'):
            v.publish(self.site,self.c2,'v0001')
        self.assertEqual(v.verify(self.site)['active_version'],'v0001')
    def test_missing_blob_blocks_rollback(self):
        v.publish(self.site,self.c1,'v0001')
        v.publish(self.site,self.c2,'v0002')
        m=v.load_json(self.site/'versions/v0001/manifest.json')
        ref=next(iter(m['shards']['title'].values()))
        (self.site/ref['path']).unlink()
        with self.assertRaisesRegex(ValueError,'PUBLISHED_BLOB'):
            v.rollback(self.site,'v0001')
        self.assertEqual(v.load_json(self.site/'current.json')['version'],'v0002')
    def test_manifest_tamper_detected(self):
        v.publish(self.site,self.c1,'v0001')
        f=self.site/'versions/v0001/manifest.json'
        f.write_bytes(f.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'CURRENT_MANIFEST_CHECKSUM_MISMATCH'):
            v.verify(self.site)
    def test_republish_is_idempotent(self):
        v.publish(self.site,self.c1,'v0001')
        result=v.publish(self.site,self.c1,'v0001')
        self.assertEqual(result['new_blobs'],0)
        self.assertEqual(v.verify(self.site)['active_version'],'v0001')

if __name__=='__main__':
    unittest.main()
