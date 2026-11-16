"""Real HTTP integration tests. Only test-created IDs are updated/deleted."""
from concurrent.futures import ThreadPoolExecutor
import copy
import ipaddress
import json
import os
from pathlib import Path
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("CYBERGUARD_API_URL", "http://127.0.0.1:3000")
SOURCES = ("postgresql", "cassandra")


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        response = urllib.request.urlopen(req, timeout=35)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        content = response.read()
        return response.status, json.loads(content) if content else None


class CrudIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.created = []
        cls.run_id = uuid.uuid4().hex
        # Q3 is global within its time range. Refuse to disturb preexisting data.
        for source in SOURCES:
            for severity in (4,5):
                params={"from":"2001-11-06T00:00:00Z","to":"2001-11-09T00:00:00Z","severity":severity,"page_size":1}
                status,body=request("GET",f"/api/{source}/queries/alerts?"+urllib.parse.urlencode(params))
                if status != 200 or body["items"]:
                    raise AssertionError("Integration window 2001-11-06..09 must be available and empty of severity 4/5 alerts; no data was changed")
        cls.sample = copy.deepcopy(json.loads((ROOT / "data/samples/events.json").read_text(encoding="utf-8")))
        for event in cls.sample:
            event["event_id"] = str(uuid.uuid4())
            event["device_id"] = f"it-{cls.run_id[:12]}-{event['device_id'][-2:]}"
            event["source_ip"] = (f"2001:db8:{cls.run_id[:4]}:{cls.run_id[4:8]}::10" if ':' in event["source_ip"]
                                  else f"198.18.{int(cls.run_id[8:10],16)}.{event['source_ip'].split('.')[-1]}")
            event["source_ip"] = str(ipaddress.ip_address(event["source_ip"]))
            # A separate historical window isolates this suite from the shipped sample.
            event["event_date"] = event["event_date"].replace("2026", "2001")
            event["occurred_at"] = event["occurred_at"].replace("2026", "2001")
            event["metadata"]["integration_run"] = cls.run_id
        manifest=ROOT / "tmp" / f"integration-{cls.run_id}.json"
        manifest.parent.mkdir(exist_ok=True)
        manifest.write_text(json.dumps({"run_id":cls.run_id,"event_ids":[e["event_id"] for e in cls.sample]},indent=2),encoding="utf-8")
        try:
            for source in SOURCES:
                for event in cls.sample:
                    cls.created.append((source, event["event_id"]))
                    status, actual = request("POST", f"/api/{source}/events", event)
                    if status != 201 or actual != {"data": event, "revision": 1}:
                        raise AssertionError(f"CREATE failed on {source}: status={status}, response={actual}")
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        failures = []
        for source, event_id in cls.created:
            path = f"/api/{source}/events/{event_id}"
            try:
                status, event = request("GET", path)
                if status == 503:
                    request("POST", path + "/repair")
                    status, event = request("GET", path)
                if status == 200:
                    # Never mutate an ID if its ownership marker differs.
                    if event["data"]["metadata"].get("integration_run") != cls.run_id:
                        failures.append(event_id)
                        continue
                    status, _ = request("DELETE", path + f"?expected_revision={event['revision']}")
                    if status != 204:
                        failures.append(event_id)
                elif status != 404:
                    failures.append(event_id)
            except Exception:
                failures.append(event_id)
        if failures:
            raise AssertionError(f"Could not delete {len(failures)} owned test events; no unrelated data was touched")

    def all_pages(self, source, kind, params):
        params = dict(params)
        items = []
        cursors = set()
        for _ in range(100):
            status, body = request("GET", f"/api/{source}/queries/{kind}?" + urllib.parse.urlencode(params))
            self.assertEqual(status, 200, body)
            items.extend(body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                return items
            self.assertNotIn(cursor, cursors)
            cursors.add(cursor)
            params["cursor"] = cursor
        self.fail("pagination did not terminate")

    def query_case(self, kind, value):
        return {"from": "2001-11-06T00:00:00Z", "to": "2001-11-09T00:00:00Z", "page_size": 2,
                {"device":"device_id", "ip":"source_ip", "alerts":"severity"}[kind]: value}

    def test_01_read_idempotency_and_conflict(self):
        for source in SOURCES:
            for event in self.sample:
                status, body = request("GET", f"/api/{source}/events/{event['event_id']}")
                self.assertEqual((status, body), (200, {"data":event, "revision":1}))
            status, body = request("POST", f"/api/{source}/events", self.sample[0])
            self.assertEqual(status, 200, body)
            conflict = copy.deepcopy(self.sample[0]); conflict["message"] = "conflicting content"
            self.assertEqual(request("POST", f"/api/{source}/events", conflict)[0], 409)

    def test_02_queries_equivalent_ordered_and_paginated(self):
        cases = [("device", self.sample[0]["device_id"]), ("ip", self.sample[0]["source_ip"]),
                 ("ip", self.sample[2]["source_ip"]), ("alerts", 4), ("alerts", 5)]
        for kind, value in cases:
            with self.subTest(kind=kind, value=value):
                params = self.query_case(kind, value)
                expected = [e for e in self.sample if
                            (kind == "device" and e["device_id"] == value) or
                            (kind == "ip" and e["source_ip"] == value) or
                            (kind == "alerts" and e["category"] == "alert" and e["severity"] == value)]
                expected.sort(key=lambda e:(e["occurred_at"], e["event_id"]), reverse=True)
                actual = [self.all_pages(source, kind, params) for source in SOURCES]
                self.assertEqual(actual[0], actual[1])
                self.assertEqual(actual[0], [{"data":e, "revision":1} for e in expected])
                self.assertEqual(len(actual[0]), len({e["data"]["event_id"] for e in actual[0]}))

    def test_03_half_open_bounds_and_missing_rows(self):
        for source in SOURCES:
            params = self.query_case("alerts",4)
            params.update({"from":"2001-11-06T12:00:00Z", "to":"2001-11-06T12:00:00.001Z"})
            self.assertEqual(len(self.all_pages(source,"alerts",params)),2)
            params.update({"from":"2001-11-06T00:00:00Z", "to":"2001-11-06T12:00:00Z"})
            self.assertEqual(self.all_pages(source,"alerts",params),[])
            self.assertEqual(self.all_pages(source,"device",self.query_case("device","no-such-device")),[])
            self.assertEqual(request("GET",f"/api/{source}/events/{uuid.uuid4()}")[0],404)
            self.assertEqual(request("DELETE",f"/api/{source}/events/{uuid.uuid4()}?expected_revision=1")[0],404)

    def test_04_invalid_inputs(self):
        invalid_changes = [
            {"event_id":"not-a-uuid"}, {"event_id":str(uuid.UUID(int=0))},
            {"occurred_at":"2001-02-30T00:00:00Z"}, {"occurred_at":"2001-11-06T00:00:00-03:00"},
            {"occurred_at":"2001-11-06T00:00:00.0001Z"}, {"event_date":"2001-11-05"},
            {"source_ip":"192.0.2.1/24"}, {"source_ip":"999.1.2.3"},
            {"severity":0}, {"severity":6}, {"device_id":"a' OR 1=1"},
            {"category":"invalid"}, {"event_type":"potential_threat"},
            {"outcome":"invented"}, {"message":" "}, {"metadata":[]},
            {"metadata":{"fraction":1.2}}, {"metadata":{"nul":"\u0000"}},
            {"metadata":{"large":"x"*5000}}, {"unexpected":True},
        ]
        for source in SOURCES:
            for changes in invalid_changes:
                event = copy.deepcopy(self.sample[0]); event.update(changes)
                with self.subTest(source=source, changes=list(changes)):
                    self.assertEqual(request("POST",f"/api/{source}/events",event)[0],400)
            for changes in [{"page_size":0},{"page_size":101},{"cursor":"broken"},{"to":"2001-11-14T00:00:00Z"},{"to":"2001-11-06T00:00:00Z"},{"source_ip":"192.0.2.1"}]:
                params=self.query_case("device",self.sample[0]["device_id"]); params.update(changes)
                self.assertEqual(request("GET",f"/api/{source}/queries/device?"+urllib.parse.urlencode(params))[0],400)
            params=self.query_case("device",self.sample[0]["device_id"])
            _, page=request("GET",f"/api/{source}/queries/device?"+urllib.parse.urlencode(params))
            params.update({"cursor":page["next_cursor"],"device_id":"another-device"})
            self.assertEqual(request("GET",f"/api/{source}/queries/device?"+urllib.parse.urlencode(params))[0],400)
            self.assertEqual(request("GET",f"/api/{source}/events/bad-id")[0],400)
        self.assertEqual(request("GET",f"/api/invalid/events/{uuid.uuid4()}")[0],400)

    def test_05_update_visible_in_all_queries_and_retry(self):
        event = self.sample[5]
        update={"expected_revision":1,"outcome":"blocked","message":"Reviewed synthetic alert","metadata":{**event["metadata"],"reviewed":True}}
        expected=copy.deepcopy(event); expected.update({k:v for k,v in update.items() if k!="expected_revision"})
        for source in SOURCES:
            path=f"/api/{source}/events/{event['event_id']}"
            self.assertEqual(request("PUT",path,update),(200,{"data":expected,"revision":2}))
            self.assertEqual(request("PUT",path,update),(200,{"data":expected,"revision":2}))
            stale={**update,"message":"different stale write"}
            self.assertEqual(request("PUT",path,stale)[0],409)
            self.assertEqual(request("PUT",path,{**update,"severity":5})[0],400)
            for kind,value in [("device",event["device_id"]),("ip",event["source_ip"]),("alerts",4)]:
                result=self.all_pages(source,kind,self.query_case(kind,value))
                found=[item for item in result if item["data"]["event_id"]==event["event_id"]]
                self.assertEqual(found,[{"data":expected,"revision":2}])
            self.assertEqual(request("DELETE",path+"?expected_revision=1")[0],409)
            self.assertEqual(request("DELETE",path+"?expected_revision=2")[0],204)
            self.assertEqual(request("DELETE",path+"?expected_revision=2")[0],204)
            self.assertEqual(request("GET",path)[0],404)
            self.assertEqual(request("PUT",path,update)[0],404)
            self.assertEqual(request("POST",f"/api/{source}/events",event)[0],409)
            for kind,value in [("device",event["device_id"]),("ip",event["source_ip"]),("alerts",4)]:
                self.assertNotIn(event["event_id"],[e["data"]["event_id"] for e in self.all_pages(source,kind,self.query_case(kind,value))])

    def test_06_concurrent_updates_have_one_winner(self):
        for source in SOURCES:
            event=copy.deepcopy(self.sample[0]); event["event_id"]=str(uuid.uuid4())
            self.created.append((source,event["event_id"]))
            path=f"/api/{source}/events/{event['event_id']}"
            self.assertEqual(request("POST",f"/api/{source}/events",event)[0],201)
            writes=[{"expected_revision":1,"outcome":"success","message":name,"metadata":event["metadata"]} for name in ("writer-a","writer-b")]
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda body: request("PUT",path,body),writes))
            self.assertEqual(sorted(status for status,_ in results),[200,409])
            self.assertEqual(request("GET",path)[1]["revision"],2)

    def test_07_health_and_repair_contract(self):
        self.assertEqual(request("GET","/api/health")[0],200)
        status,body=request("GET","/api/health/storage")
        self.assertEqual(status,200,body)
        self.assertEqual(body["cassandra"]["status"],"up")
        self.assertEqual(body["postgresql"]["status"],"up")
        for source in SOURCES:
            path=f"/api/{source}/events/{self.sample[0]['event_id']}/repair"
            self.assertEqual(request("POST",path),(200,{"state":"active"}))

    def overview(self, source, **extra):
        params = {"from": "2001-11-06T00:00:00Z", "to": "2001-11-09T00:00:00Z", **extra}
        status, body = request("GET", f"/api/{source}/stats/overview?" + urllib.parse.urlencode(params))
        self.assertEqual(status, 200, body)
        return body

    def test_08_overview_equivalent_and_rollup_follows_crud(self):
        # Same logical state in both sources -> byte-identical aggregate.
        for extra in ({}, {"category": "alert"}, {"severity": 4}, {"category": "alert", "severity": 5}):
            with self.subTest(filters=extra):
                self.assertEqual(self.overview("postgresql", **extra), self.overview("cassandra", **extra))
        event = copy.deepcopy(self.sample[6]); event["event_id"] = str(uuid.uuid4())
        hour = (int(event["occurred_at"][8:10]) - 6) * 24 + int(event["occurred_at"][11:13])
        category = ["authentication", "network", "alert"].index(event["category"])
        for source in SOURCES:
            before = self.overview(source)
            self.created.append((source, event["event_id"]))
            self.assertEqual(request("POST", f"/api/{source}/events", event)[0], 201)
            self.assertEqual(request("POST", f"/api/{source}/events", event)[0], 200)  # retry: no double count
            during = self.overview(source)
            self.assertEqual(during["total"], before["total"] + 1)
            self.assertEqual(during["series"][hour]["by_category"][category],
                             before["series"][hour]["by_category"][category] + 1)
            self.assertEqual(during["by_severity"][event["severity"] - 1],
                             before["by_severity"][event["severity"] - 1] + 1)
            path = f"/api/{source}/events/{event['event_id']}"
            self.assertEqual(request("DELETE", path + "?expected_revision=1")[0], 204)
            self.assertEqual(request("DELETE", path + "?expected_revision=1")[0], 204)  # retry: no double decrement
            self.assertEqual(self.overview(source), before)

    def test_09_overview_rejects_invalid_windows_and_filters(self):
        for source in SOURCES:
            for changes in [{"from": "2001-11-06T00:30:00Z"}, {"to": "2001-11-14T00:00:00Z"},
                            {"to": "2001-11-06T00:00:00Z"}, {"category": "malware"}, {"severity": 9},
                            {"device_id": "x"}]:
                params = {"from": "2001-11-06T00:00:00Z", "to": "2001-11-09T00:00:00Z", **changes}
                with self.subTest(source=source, changes=changes):
                    self.assertEqual(request("GET", f"/api/{source}/stats/overview?" + urllib.parse.urlencode(params))[0], 400)

    def test_10_instrumentation_used_by_dashboard_and_benchmarks(self):
        # Server-Timing is the "tempo no banco" shown in the UI and recorded as db_ms.
        paths = [f"/api/{{s}}/events/{self.sample[1]['event_id']}",
                 "/api/{s}/queries/device?" + urllib.parse.urlencode(self.query_case("device", self.sample[1]["device_id"])),
                 "/api/{s}/stats/overview?from=2001-11-06T00:00:00Z&to=2001-11-07T00:00:00Z"]
        for source in SOURCES:
            for path in paths:
                with urllib.request.urlopen(BASE + path.format(s=source), timeout=35) as response:
                    timing = response.headers.get("Server-Timing", "")
                    self.assertRegex(timing, r"^db;dur=\d+\.\d{3}$", path)
        status, runtime = request("GET", "/api/runtime")
        self.assertEqual(status, 200)
        self.assertIn(runtime["build"], ("debug", "release"))
        self.assertTrue(1 <= runtime["cassandra_read_concurrency"] <= 128)
        self.assertIn(runtime["postgres_synchronous_commit"], ("on", "off"))
        self.assertTrue(1 <= runtime["postgres_pool_size"] <= 64)
        status, summary = request("GET", "/api/benchmarks/summary")
        self.assertIn(status, (200, 404))  # 404 = no measurement yet, never a placeholder
        if status == 200:
            self.assertTrue(summary["main"]["complete"])
            self.assertTrue(all(op["equivalent"] for op in summary["main"]["operations"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
