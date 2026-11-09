"""Check logical equivalence and bounded physical Cassandra projections of the fixture."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/validation"))
from test_integration import request


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-config")
    args=parser.parse_args()
    sample=json.loads((ROOT / "data/samples/events.json").read_text(encoding="utf-8"))
    for source in ("postgresql","cassandra"):
        for event in sample:
            status,body=request("GET",f"/api/{source}/events/{event['event_id']}")
            assert (status,body)==(200,{"data":event,"revision":1})
        print(f"PASS: {source}: all {len(sample)} canonical IDs and contents match the fixture")
    for kind,key,value in [("device","device_id","soc-sensor-01"),("ip","source_ip","192.0.2.10"),("alerts","severity",4)]:
        params={"from":"2026-11-06T00:00:00Z","to":"2026-11-09T00:00:00Z","page_size":100,key:value}
        left=request("GET","/api/postgresql/queries/"+kind+"?"+urlencode(params))
        right=request("GET","/api/cassandra/queries/"+kind+"?"+urlencode(params))
        assert left==right and left[0]==200 and left[1]["next_cursor"] is None
        print(f"PASS: {kind}: {len(left[1]['items'])} equal logical results")

    # Every statement targets known fixture IDs or complete partition keys, with limits.
    ids=','.join(e['event_id'] for e in sample)
    statements=[f"SELECT JSON event_id,lifecycle FROM cyberguard.events_by_id WHERE event_id IN ({ids});"]
    for table,key,events in [("events_by_device_day","device_id",sample),("events_by_ip_day","source_ip",sample),
                             ("alerts_by_severity_day","severity",[e for e in sample if e['category']=='alert'])]:
        for value,day in sorted({(e[key],e['event_date']) for e in events}):
            literal=str(value) if key=='severity' else quote(value)
            statements.append(f"SELECT JSON {key},event_id FROM cyberguard.{table} WHERE {key}={literal} AND event_date={quote(day)} LIMIT 1000;")
    command=["docker"]+(["--config",args.docker_config] if args.docker_config else [])
    command += ["compose","exec","-T","cassandra","cqlsh","127.0.0.1","9042"]
    result=subprocess.run(command,input=('\n'.join(statements)+'\n').encode(),cwd=ROOT,capture_output=True,check=True)
    assert not any(token in result.stderr for token in (b"Exception",b"InvalidRequest",b"Error"))
    rows=[json.loads(line.strip()) for line in result.stdout.decode().splitlines() if line.strip().startswith('{')]
    counts={key:Counter(row['event_id'] for row in rows if key in row) for key in ('lifecycle','device_id','source_ip','severity')}
    expected=Counter(e['event_id'] for e in sample)
    for key in ('lifecycle','device_id','source_ip'):
        assert counts[key]==expected, key
    assert counts['severity']==Counter(e['event_id'] for e in sample if e['category']=='alert')
    assert all(row['lifecycle']=='active' for row in rows if 'lifecycle' in row)
    print(f"PASS: {len(sample)} logical events = {len(rows)} live Cassandra rows (24 canonical + 24 device + 24 IP + 9 alerts)")


if __name__ == "__main__":
    main()
