"""Offline tests of the bulk generator: contract, determinism, prefixes, manifest."""
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/generation"))
import bulk_events as bulk  # noqa: E402

TYPES = {"authentication": {"login", "suspicious_access"}, "network": {"connection", "traffic_anomaly"},
         "alert": {"potential_threat"}}
DEVICE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SAMPLE = json.loads((ROOT / "data/samples/events.json").read_text(encoding="utf-8"))


def valid_metadata(value, depth=0):
    if depth > 8:
        return False
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return not isinstance(value, str) or "\0" not in value
    if isinstance(value, int):
        return -2**63 <= value < 2**63
    if isinstance(value, list):
        return all(valid_metadata(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return all(len(k.encode()) <= 64 and valid_metadata(v, depth + 1) for k, v in value.items())
    return False  # floats are rejected by the API contract


class GeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen = bulk.BulkGenerator()
        cls.events = list(cls.gen.events(0, 5000))

    def test_contract(self):
        for e in self.events:
            self.assertEqual(list(e), ["event_id", "occurred_at", "event_date", "device_id", "source_ip", "category",
                                       "event_type", "severity", "outcome", "message", "metadata"])
            parsed = uuid.UUID(e["event_id"])
            self.assertEqual((parsed.version, parsed.variant, str(parsed)), (4, uuid.RFC_4122, e["event_id"]))
            self.assertRegex(e["occurred_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
            when = datetime.strptime(e["occurred_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            self.assertTrue(bulk.WINDOW_START <= when < bulk.WINDOW_END)
            self.assertEqual(e["event_date"], when.date().isoformat())
            self.assertRegex(e["device_id"], DEVICE)
            self.assertEqual(str(ipaddress.ip_address(e["source_ip"])), e["source_ip"])
            self.assertIn(e["event_type"], TYPES[e["category"]])
            self.assertIn(e["severity"], range(1, 6))
            self.assertIn(e["outcome"], {"success", "failure", "blocked", "unknown"})
            self.assertTrue(e["message"].strip() and len(e["message"].encode()) <= 2048 and e["message"].isascii())
            self.assertTrue(valid_metadata(e["metadata"]))
            self.assertLessEqual(len(json.dumps(e["metadata"], separators=(",", ":"))), 4096)
            self.assertEqual(e["metadata"]["dataset"], bulk.DATASET)
            self.assertNotIn("\\", json.dumps(e))  # keeps cqlsh CSV exports unambiguous

    def test_deterministic_and_prefix_stable(self):
        other = bulk.BulkGenerator(bulk.DEFAULT_SEED)
        for index in (0, 1, 999, 4999):
            self.assertEqual(other.event(index), self.events[index])
        self.assertNotEqual(bulk.BulkGenerator(bulk.DEFAULT_SEED + 1).event(0), self.events[0])
        self.assertEqual(len({e["event_id"] for e in self.events}), len(self.events))

    def test_disjoint_from_sample(self):
        sample_ids = {e["event_id"] for e in SAMPLE}
        sample_keys = {(e["device_id"], e["event_date"]) for e in SAMPLE} | {(e["source_ip"], e["event_date"]) for e in SAMPLE}
        self.assertFalse(sample_ids & {e["event_id"] for e in self.events})
        self.assertFalse(sample_keys & ({(e["device_id"], e["event_date"]) for e in self.events}
                                        | {(e["source_ip"], e["event_date"]) for e in self.events}))
        self.assertFalse({e["event_date"] for e in SAMPLE} & set(bulk.DATES))

    def test_mix_is_realistic(self):
        categories = {c: sum(e["category"] == c for e in self.events) for c in TYPES}
        self.assertTrue(all(count > 0 for count in categories.values()))
        self.assertTrue(0.06 < categories["alert"] / len(self.events) < 0.11)
        self.assertTrue(any(":" in e["source_ip"] for e in self.events))
        self.assertEqual({e["severity"] for e in self.events if e["category"] == "alert"}, {1, 2, 3, 4, 5})
        self.assertTrue({"failure", "blocked"} <= {e["outcome"] for e in self.events})

    def test_manifest_matches_generator(self):
        manifest = json.loads((ROOT / "data/bulk" / f"{bulk.DATASET}.manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["dataset"], manifest["seed"], manifest["generator_version"]),
                         (bulk.DATASET, bulk.DEFAULT_SEED, bulk.GENERATOR_VERSION))
        for chunk in (0, 4):
            self.assertEqual(self.gen.chunk_digest(chunk)[0], manifest["chunk_sha256"][chunk])


if __name__ == "__main__":
    unittest.main(verbosity=1)
