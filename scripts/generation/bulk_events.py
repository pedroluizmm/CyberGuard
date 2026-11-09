"""Deterministic streaming generator for the CyberGuard bulk dataset (Task 03).

`BulkGenerator(seed).event(i)` is a pure function of (DATASET, seed, i). Growing
profiles are therefore prefixes [0, N) of one logical dataset: the first 10 000
events of the 1 000 000 profile are exactly the 10 000 profile.

Only SHA-256 and integer arithmetic are used. Python's `random` module and
floating point weights are avoided on purpose, so output does not depend on the
Python version, platform libm or iteration order. Every event follows the Task 02
contract (UUID v4, UTC milliseconds, immutable routing fields, integer metadata).
All data is synthetic: documentation/private IP ranges, synthetic account names.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import uuid

DATASET = "cyberguard-bulk-v1"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261109
MAX_EVENTS = 5_000_000
CHUNK_SIZE = 1000
PROFILES = (10_000, 100_000, 1_000_000)
WINDOW_START = datetime(2026, 10, 5, tzinfo=timezone.utc)  # Monday, disjoint from the 24-event sample
WINDOW_DAYS = 28
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
WINDOW_START_MS = int(WINDOW_START.timestamp()) * 1000
WINDOW_END = WINDOW_START + timedelta(days=WINDOW_DAYS)
DATES = [(WINDOW_START + timedelta(days=d)).date().isoformat() for d in range(WINDOW_DAYS)]
ID_ALGORITHM = "first 16 bytes of SHA256('cyberguard-bulk-v1|<seed>|id|<index>') with UUID v4 version/variant bits"
RNG_ALGORITHM = ("per event: SHA256('cyberguard-bulk-v1|<seed>|ev|<index>|' + 4-byte counter) split into 64-bit "
                 "unsigned integers; choices use integer modulo/cumulative weights only")


class Draws:
    """Counter-mode SHA-256 stream of unsigned 64-bit integers."""

    __slots__ = ("key", "counter", "block", "pos")

    def __init__(self, key: bytes):
        self.key, self.counter, self.block, self.pos = key, 0, b"", 32

    def u64(self) -> int:
        if self.pos >= 32:
            self.block = hashlib.sha256(self.key + self.counter.to_bytes(4, "big")).digest()
            self.counter += 1
            self.pos = 0
        value = int.from_bytes(self.block[self.pos:self.pos + 8], "big")
        self.pos += 8
        return value

    def below(self, n: int) -> int:
        # Modulo bias is < n / 2**64, negligible for the small n used here.
        return self.u64() % n

    def between(self, low: int, high: int) -> int:
        return low + self.below(high - low + 1)

    def pick(self, items):
        return items[self.below(len(items))]

    def percent(self) -> int:
        return self.below(100)


class Weighted:
    """Integer cumulative weights; deterministic on every platform."""

    __slots__ = ("items", "cumulative", "total")

    def __init__(self, pairs):
        self.items, self.cumulative, total = [], [], 0
        for item, weight in pairs:
            if weight <= 0 or not isinstance(weight, int):
                raise ValueError("weights must be positive integers")
            total += weight
            self.items.append(item)
            self.cumulative.append(total)
        self.total = total

    def choose(self, draws: Draws):
        return self.items[bisect_right(self.cumulative, draws.below(self.total))]


def zipf(items, offset: int) -> Weighted:
    """Integer approximation of a Zipf(s=1) popularity: a few hot keys, a long tail."""
    return Weighted((item, 10**9 // (rank + offset)) for rank, item in enumerate(items))


def fmt_time(ms: int) -> tuple[str, str]:
    """Epoch milliseconds inside the window -> (RFC3339 UTC with 3 decimals, UTC date)."""
    offset = ms - WINDOW_START_MS
    day, rest = divmod(offset, DAY_MS)
    hour, rest = divmod(rest, HOUR_MS)
    minute, rest = divmod(rest, 60_000)
    second, milli = divmod(rest, 1000)
    date = DATES[day]
    return f"{date}T{hour:02d}:{minute:02d}:{second:02d}.{milli:03d}Z", date


def canonical_line(event: dict) -> bytes:
    """Stable serialization used for hashes; independent of dict insertion order."""
    return (json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


# Business-like hourly profile (UTC) and weekday/weekend weights, integers only.
HOUR_WEIGHTS = [25, 20, 18, 18, 20, 30, 50, 90, 140, 160, 160, 150, 130, 150, 160, 150, 130, 100, 70, 55, 45, 40, 35, 30]
DAY_WEIGHTS = [100 if (WINDOW_START + timedelta(days=d)).weekday() < 5 else 45 for d in range(WINDOW_DAYS)]

AUTH_METHODS = ["password", "kerberos", "mfa_push", "certificate", "ssh_key", "saml"]
PROTOCOLS = Weighted([("tcp", 80), ("udp", 17), ("icmp", 3)])
COMMON_PORTS = [22, 25, 53, 80, 123, 389, 443, 445, 636, 993, 1433, 3306, 3389, 5432, 5985, 8080, 8443, 9042]
CAMPAIGN_TYPES = ["brute_force", "port_scan", "credential_stuffing", "exfiltration", "c2_beaconing"]
TECHNIQUES = {  # Public MITRE ATT&CK technique identifiers, used only as labels.
    "brute_force": "T1110.001", "port_scan": "T1046", "credential_stuffing": "T1110.004",
    "exfiltration": "T1041", "c2_beaconing": "T1071.001",
}
ALERT_RULES = [("det-0101", "T1059.001", "Suspicious PowerShell execution"),
               ("det-0102", "T1003.001", "Credential dumping attempt"),
               ("det-0103", "T1078", "Valid account used from unusual location"),
               ("det-0104", "T1486", "Mass file encryption behaviour"),
               ("det-0105", "T1021.001", "Unexpected remote desktop session"),
               ("det-0106", "T1566.001", "Malicious attachment opened"),
               ("det-0107", "T1105", "Tool transfer from untrusted host"),
               ("det-0108", "T1053.005", "Unusual scheduled task created")]
SEVERITY_BACKGROUND_ALERT = Weighted([(1, 12), (2, 28), (3, 34), (4, 19), (5, 7)])
SEVERITY_CAMPAIGN_ALERT = Weighted([(3, 30), (4, 45), (5, 25)])
SEVERITY_SUSPICIOUS = Weighted([(3, 70), (4, 25), (5, 5)])
OUTCOME_SUSPICIOUS = Weighted([("unknown", 60), ("failure", 25), ("success", 15)])

# Scenario mix, parts per 10 000. Alerts end up near 8.2% of all events.
SCENARIOS = Weighted([
    ("login_success", 3400), ("login_failure", 500), ("connection_allowed", 3000),
    ("connection_blocked", 800), ("suspicious_access", 300), ("traffic_anomaly", 300),
    ("campaign", 1000), ("alert", 700),
])


class BulkGenerator:
    def __init__(self, seed: int = DEFAULT_SEED):
        if not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        self.seed = seed
        self.event_prefix = f"{DATASET}|{seed}|ev|".encode()
        self.id_prefix = f"{DATASET}|{seed}|id|".encode()
        self._build_world(Draws(f"{DATASET}|{seed}|world".encode()))

    # ----- static world: devices, address pools, accounts and campaigns -----
    def _build_world(self, w: Draws) -> None:
        groups = {
            "firewall": [f"fw-edge-{n:02d}" for n in range(1, 5)],
            "vpn": [f"vpn-gw-{n:02d}" for n in range(1, 4)],
            "dc": [f"dc-{n:02d}" for n in range(1, 5)],
            "ids": [f"ids-sensor-{n:02d}" for n in range(1, 7)],
            "edr": [f"edr-mgr-{n:02d}" for n in range(1, 3)],
            "server": ([f"srv-web-{n:02d}" for n in range(1, 25)] + [f"srv-db-{n:02d}" for n in range(1, 13)]
                       + [f"srv-app-{n:02d}" for n in range(1, 31)] + [f"srv-file-{n:02d}" for n in range(1, 9)]),
            "workstation": [f"ws-{dept}-{n:04d}" for dept in ("fin", "hr", "eng", "ops", "sales", "it")
                            for n in range(1, 51)],
        }
        self.groups = groups
        self.devices = sorted({d for items in groups.values() for d in items})
        group_pick = {name: zipf(items, 2) for name, items in groups.items()}
        self.group_pick = group_pick
        self.device_mix = {
            "authentication": Weighted([("dc", 40), ("vpn", 25), ("server", 20), ("workstation", 15)]),
            "network": Weighted([("firewall", 45), ("ids", 15), ("server", 25), ("workstation", 15)]),
            "alert": Weighted([("ids", 40), ("edr", 35), ("firewall", 15), ("server", 10)]),
        }
        # Private and documentation-only address ranges (RFC 1918, RFC 4193, RFC 5737, RFC 3849).
        internal_v4 = [str(ipaddress.IPv4Address(f"10.{20 + s}.{v}.{h}"))
                       for s in range(3) for v in range(1, 41) for h in range(10, 60)]
        internal_v6 = [str(ipaddress.IPv6Address(f"fd12:3456:789a:{s:x}::{h:x}"))
                       for s in range(1, 13) for h in range(1, 101)]
        external_v4 = [f"198.51.100.{h}" for h in range(1, 255)]
        external_v6 = [str(ipaddress.IPv6Address(f"2001:db8:100:{s:x}::{h:x}"))
                       for s in range(1, 21) for h in range(1, 101)]
        attacker_v4 = [f"203.0.113.{h}" for h in range(1, 255)]
        attacker_v6 = [str(ipaddress.IPv6Address(f"2001:db8:bad:{s:x}::{h:x}"))
                       for s in range(1, 5) for h in range(1, 51)]
        for pool in (internal_v4, internal_v6, external_v4, external_v6, attacker_v4, attacker_v6):
            for value in pool:  # canonical form equals what Rust/PostgreSQL will return
                assert str(ipaddress.ip_address(value)) == value
        self.internal_ips = internal_v4 + internal_v6
        self.internal_pick = zipf(self._shuffled(w, self.internal_ips), 10)
        self.external_pick = zipf(self._shuffled(w, external_v4 + external_v6), 5)
        self.attacker_pick = zipf(self._shuffled(w, attacker_v4 + attacker_v6), 3)
        accounts = [f"acct-{n:05d}" for n in range(1, 2501)] + [
            "svc-backup", "svc-monitor", "svc-deploy", "svc-sql", "svc-ldap-sync"]
        self.account_pick = zipf(self._shuffled(w, accounts), 20)
        self.day_pick = Weighted(enumerate(DAY_WEIGHTS))
        self.hour_pick = Weighted(enumerate(HOUR_WEIGHTS))
        self.campaigns = []
        target_roles = {"brute_force": ["vpn", "dc", "server"], "port_scan": ["firewall", "ids"],
                        "credential_stuffing": ["vpn"], "exfiltration": ["firewall", "ids"],
                        "c2_beaconing": ["firewall", "ids"]}
        duration_min = {"brute_force": (30, 180), "port_scan": (10, 60), "credential_stuffing": (60, 360),
                        "exfiltration": (20, 120), "c2_beaconing": (360, 1440)}
        window_ms = WINDOW_DAYS * DAY_MS
        for n in range(20):
            kind = CAMPAIGN_TYPES[n % len(CAMPAIGN_TYPES)]
            low, high = duration_min[kind]
            duration = w.between(low, high) * 60_000
            start = WINDOW_START_MS + (w.below(window_ms - HOUR_MS) // 60_000) * 60_000
            duration = min(duration, WINDOW_START_MS + window_ms - start)
            if kind in ("exfiltration", "c2_beaconing"):
                sources = [w.pick(self.internal_ips)]
            else:
                count = {"brute_force": w.between(1, 3), "port_scan": 1, "credential_stuffing": w.between(3, 6)}[kind]
                sources = sorted({w.pick(attacker_v4 + attacker_v6) for _ in range(count)})
            roles = target_roles[kind]
            targets = sorted({w.pick(groups[w.pick(roles)]) for _ in range(w.between(1, 2))})
            self.campaigns.append({"id": f"cmp-{n + 1:02d}", "type": kind, "start_ms": start,
                                   "duration_ms": duration, "sources": sources, "targets": targets,
                                   "intensity": w.between(1, 4)})
        self.campaign_pick = Weighted((c, c["intensity"]) for c in self.campaigns)

    @staticmethod
    def _shuffled(w: Draws, items):
        items = list(items)
        for k in range(len(items) - 1, 0, -1):  # Fisher-Yates with the world stream
            j = w.below(k + 1)
            items[k], items[j] = items[j], items[k]
        return items

    def describe_world(self) -> dict:
        return {
            "devices": len(self.devices), "device_groups": {k: len(v) for k, v in self.groups.items()},
            "internal_addresses": len(self.internal_ips), "external_addresses": len(self.external_pick.items),
            "attacker_addresses": len(self.attacker_pick.items), "accounts": len(self.account_pick.items),
            "campaigns": [{**c, "start": fmt_time(c["start_ms"])[0]} for c in self.campaigns],
        }

    # ----- per event helpers -----
    def event_id(self, index: int) -> str:
        digest = hashlib.sha256(self.id_prefix + str(index).encode()).digest()[:16]
        return str(uuid.UUID(bytes=digest, version=4))

    def _business_ms(self, d: Draws) -> int:
        return WINDOW_START_MS + self.day_pick.choose(d) * DAY_MS + self.hour_pick.choose(d) * HOUR_MS + d.below(HOUR_MS)

    def _flat_ms(self, d: Draws) -> int:
        return WINDOW_START_MS + d.below(WINDOW_DAYS * DAY_MS)

    def _device(self, d: Draws, category: str) -> str:
        return self.group_pick[self.device_mix[category].choose(d)].choose(d)

    def event(self, index: int) -> dict:
        if not 0 <= index < MAX_EVENTS:
            raise ValueError("index outside the supported dataset range")
        d = Draws(self.event_prefix + str(index).encode() + b"|")
        scenario = SCENARIOS.choose(d)
        meta = {"dataset": DATASET, "generator": GENERATOR_VERSION, "seq": index,
                "scenario": scenario, "synthetic": True}
        if scenario == "campaign":
            fields, extra = self._campaign_event(d)
        else:
            fields, extra = getattr(self, "_" + scenario)(d)
        meta.update(extra)
        occurred_at, event_date = fmt_time(fields.pop("ms"))
        return {"event_id": self.event_id(index), "occurred_at": occurred_at, "event_date": event_date,
                "device_id": fields["device_id"], "source_ip": fields["source_ip"],
                "category": fields["category"], "event_type": fields["event_type"],
                "severity": fields["severity"], "outcome": fields["outcome"],
                "message": fields["message"], "metadata": meta}

    def _client_ip(self, d: Draws, external_percent: int) -> str:
        return (self.external_pick if d.percent() < external_percent else self.internal_pick).choose(d)

    def _login(self, d: Draws, success: bool):
        device = self._device(d, "authentication")
        ip = self._client_ip(d, 20 if device.startswith("vpn") else 3)
        account, method = self.account_pick.choose(d), d.pick(AUTH_METHODS)
        if success:
            message = f"Successful {method} logon for {account} from {ip} on {device}"
        else:
            message = f"Failed {method} logon for {account} from {ip} on {device}: invalid credentials"
        return ({"ms": self._business_ms(d), "device_id": device, "source_ip": ip, "category": "authentication",
                 "event_type": "login", "severity": 1 if success else 2,
                 "outcome": "success" if success else "failure", "message": message},
                {"account": account, "auth_method": method, "session_seconds": d.between(30, 28_800) if success else 0})

    def _login_success(self, d):
        return self._login(d, True)

    def _login_failure(self, d):
        return self._login(d, False)

    def _connection(self, d: Draws, blocked: bool):
        device = self._device(d, "network")
        ip = (self.attacker_pick.choose(d) if d.percent() < 30 else self.external_pick.choose(d)) if blocked \
            else self._client_ip(d, 10)
        protocol = PROTOCOLS.choose(d)
        port = 0 if protocol == "icmp" else (d.pick(COMMON_PORTS) if d.percent() < 85 else d.between(1024, 65535))
        destination = self.internal_pick.choose(d)
        bytes_out = 0 if blocked else d.between(64, 2_000_000)
        rule = f"fw-rule-{d.between(1, 240):04d}"
        verb = "Blocked" if blocked else "Allowed"
        return ({"ms": self._flat_ms(d) if blocked else self._business_ms(d), "device_id": device, "source_ip": ip,
                 "category": "network", "event_type": "connection", "severity": 2 if blocked else 1,
                 "outcome": "blocked" if blocked else "success",
                 "message": f"{verb} {protocol} connection from {ip} to {destination} port {port} by {rule}"},
                {"protocol": protocol, "dst_ip": destination, "dst_port": port, "bytes_out": bytes_out,
                 "bytes_in": 0 if blocked else d.between(64, 8_000_000), "rule_id": rule})

    def _connection_allowed(self, d):
        return self._connection(d, False)

    def _connection_blocked(self, d):
        return self._connection(d, True)

    def _suspicious_access(self, d: Draws):
        device = self._device(d, "authentication")
        ip = self.external_pick.choose(d) if d.percent() < 60 else self.internal_pick.choose(d)
        account = self.account_pick.choose(d)
        reason = d.pick(["impossible_travel", "off_hours_admin", "new_device", "privilege_escalation"])
        outcome = OUTCOME_SUSPICIOUS.choose(d)
        return ({"ms": self._flat_ms(d), "device_id": device, "source_ip": ip, "category": "authentication",
                 "event_type": "suspicious_access", "severity": SEVERITY_SUSPICIOUS.choose(d), "outcome": outcome,
                 "message": f"Suspicious access by {account} from {ip} on {device}: {reason}"},
                {"account": account, "reason": reason, "risk_score": d.between(40, 100)})

    def _traffic_anomaly(self, d: Draws):
        device = self._device(d, "network")
        ip = self.internal_pick.choose(d) if d.percent() < 55 else self.external_pick.choose(d)
        kind = d.pick(["volume_spike", "rare_port", "dns_tunneling_pattern", "protocol_mismatch"])
        return ({"ms": self._flat_ms(d), "device_id": device, "source_ip": ip, "category": "network",
                 "event_type": "traffic_anomaly", "severity": SEVERITY_SUSPICIOUS.choose(d),
                 "outcome": "blocked" if d.percent() < 25 else "unknown",
                 "message": f"Traffic anomaly {kind} observed from {ip} on {device}"},
                {"anomaly": kind, "baseline_bytes": d.between(1_000, 5_000_000),
                 "observed_bytes": d.between(5_000_000, 900_000_000)})

    def _alert(self, d: Draws):
        device = self._device(d, "alert")
        ip = self.internal_pick.choose(d) if d.percent() < 70 else self.external_pick.choose(d)
        rule, technique, title = d.pick(ALERT_RULES)
        return ({"ms": self._flat_ms(d), "device_id": device, "source_ip": ip, "category": "alert",
                 "event_type": "potential_threat", "severity": SEVERITY_BACKGROUND_ALERT.choose(d),
                 "outcome": "blocked" if d.percent() < 20 else "unknown",
                 "message": f"{title} involving {ip} reported by {device}"},
                {"rule_id": rule, "technique": technique, "confidence": d.between(30, 99)})

    def _campaign_event(self, d: Draws):
        c = self.campaign_pick.choose(d)
        ms = c["start_ms"] + d.below(c["duration_ms"])
        source, target, kind = d.pick(c["sources"]), d.pick(c["targets"]), c["type"]
        extra = {"campaign": c["id"], "campaign_type": kind, "technique": TECHNIQUES[kind]}
        roll = d.percent()
        if roll < 12:  # The detection layer raised an alert for this campaign activity.
            return ({"ms": ms, "device_id": target, "source_ip": source, "category": "alert",
                     "event_type": "potential_threat", "severity": SEVERITY_CAMPAIGN_ALERT.choose(d),
                     "outcome": "blocked" if d.percent() < 35 else "unknown",
                     "message": f"Detection: {kind} activity from {source} against {target} ({c['id']})"},
                    {**extra, "confidence": d.between(70, 99)})
        if kind in ("brute_force", "credential_stuffing"):
            account = self.account_pick.choose(d)
            if roll < 20:
                return ({"ms": ms, "device_id": target, "source_ip": source, "category": "authentication",
                         "event_type": "suspicious_access", "severity": SEVERITY_SUSPICIOUS.choose(d),
                         "outcome": "success" if d.percent() < 10 else "failure",
                         "message": f"Repeated logon failures followed by access attempt for {account} from {source}"},
                        {**extra, "account": account})
            return ({"ms": ms, "device_id": target, "source_ip": source, "category": "authentication",
                     "event_type": "login", "severity": 3, "outcome": "failure",
                     "message": f"Failed password logon for {account} from {source} on {target}: invalid credentials"},
                    {**extra, "account": account, "auth_method": "password", "attempt": d.between(1, 500)})
        port = d.between(1, 65535) if kind == "port_scan" else d.pick([53, 443, 8443])
        if roll < 30:
            return ({"ms": ms, "device_id": target, "source_ip": source, "category": "network",
                     "event_type": "traffic_anomaly", "severity": SEVERITY_SUSPICIOUS.choose(d),
                     "outcome": "blocked" if kind == "port_scan" else "unknown",
                     "message": f"Traffic anomaly ({kind}) from {source} on {target} port {port}"},
                    {**extra, "dst_port": port, "observed_bytes": d.between(10_000, 900_000_000)})
        blocked = kind == "port_scan" or d.percent() < 20
        return ({"ms": ms, "device_id": target, "source_ip": source, "category": "network",
                 "event_type": "connection", "severity": 2 if blocked else 1,
                 "outcome": "blocked" if blocked else "success",
                 "message": f"{'Blocked' if blocked else 'Allowed'} tcp connection from {source} port {port} on {target}"},
                {**extra, "protocol": "tcp", "dst_port": port, "bytes_out": 0 if blocked else d.between(200, 50_000_000)})

    def events(self, start: int, stop: int):
        for index in range(start, stop):
            yield self.event(index)

    def chunk_digest(self, chunk: int, chunk_size: int = CHUNK_SIZE) -> tuple[str, list[dict]]:
        events = list(self.events(chunk * chunk_size, (chunk + 1) * chunk_size))
        digest = hashlib.sha256(b"".join(canonical_line(e) for e in events)).hexdigest()
        return digest, events
