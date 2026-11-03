#!/usr/bin/env python3
"""Weekly PostgreSQL slow query report for the Artemis production database.

Replaces the MySQL-era slow_queries_notifier, which parsed the MySQL slow query log and therefore
reported "no slow queries" regardless of what PostgreSQL did.

Two sources, because they answer different questions:

* pg_stat_statements: what the database spent its time on during the report window. Finds the
  statements that are fast individually but run constantly, which no per-statement threshold catches.
  The view is cumulative, so the script stores a snapshot and reports the difference to the previous
  one. Statement texts are already normalised by PostgreSQL ($1, $2, ...).
* The server log (log_min_duration_statement): individual slow executions. Literals are stripped
  before anything is reported, because logged statements carry their parameter values.

The report always states its inputs (threshold, window, entries seen and skipped), so an empty report
can be told apart from a report that could not see anything.

Needs root: it switches to the postgres user for psql and reads /var/log/postgresql.
"""

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path("/var/log/postgresql")
LOG_GLOB = "postgresql-*-main.log*"
SNAPSHOT_FILE = Path("/var/lib/postgres-slow-queries/snapshot.json")
MAX_QUERY_CHARS = 600

# %m [%p] %q%u@%d : the log_line_prefix of this cluster. Background processes have no user@db part.
RECORD = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \S+ \[\d+\] (?:(\S+)@(\S+) )?[A-Z]+:  (.*)$")
DURATION = re.compile(r"duration: ([\d.]+) ms  (?:statement|execute [^:]*|bind [^:]*|parse [^:]*): (.*)", re.S)
IDENTIFIER_LIST = re.compile(r"^[A-Za-z0-9_,]*$")


def run_psql(database, sql):
    """Runs one read-only query as the postgres user and returns its single output value."""
    command = ["runuser", "-u", "postgres", "--", "env", "PGOPTIONS=-c default_transaction_read_only=on",
               "psql", "-X", "-q", "-A", "-t", "-d", database, "-c", sql]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()


def fetch_statistics(database, ignored_users):
    if not IDENTIFIER_LIST.match(ignored_users):
        raise ValueError(f"unexpected characters in --ignore-users: {ignored_users!r}")
    sql = f"""
        SELECT json_build_object(
            'stats_reset', (SELECT stats_reset FROM pg_stat_statements_info),
            'threshold', current_setting('log_min_duration_statement'),
            'queries', (SELECT coalesce(json_agg(t), '[]'::json) FROM (
                SELECT s.queryid::text AS queryid,
                       sum(s.calls)::bigint AS calls,
                       sum(s.total_exec_time) AS total_ms,
                       max(s.max_exec_time) AS max_ms,
                       sum(s.rows)::bigint AS rows,
                       (array_agg(s.query))[1] AS query
                FROM pg_stat_statements s
                JOIN pg_roles r ON r.oid = s.userid
                WHERE s.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                  AND s.queryid IS NOT NULL
                  AND r.rolname <> ALL (string_to_array('{ignored_users}', ','))
                GROUP BY s.queryid) t))
    """
    return json.loads(run_psql(database, sql))


def normalise(sql):
    """Strips literals so that executions of one statement group together and no data leaves the host."""
    sql = re.sub(r"'(?:[^']|'')*'", "?", sql)
    sql = re.sub(r"(?<![\w$.])\d+(?:\.\d+)?\b", "?", sql)
    sql = re.sub(r"\(\s*\?(?:\s*,\s*\?)+\s*\)", "(?, ...)", sql)
    return re.sub(r"\s+", " ", sql).strip()


def shorten(sql):
    return sql if len(sql) <= MAX_QUERY_CHARS else sql[:MAX_QUERY_CHARS] + " ..."


def load_snapshot():
    try:
        return json.loads(SNAPSHOT_FILE.read_text())
    except (OSError, ValueError):
        return None


def save_snapshot(stats, now):
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    counters = {q["queryid"]: {"calls": q["calls"], "total_ms": q["total_ms"]} for q in stats["queries"]}
    SNAPSHOT_FILE.write_text(json.dumps({"taken_at": now.isoformat(), "stats_reset": stats["stats_reset"],
                                         "queries": counters}))


def window_delta(stats, snapshot):
    """Returns (queries with this window's calls and time, description of the window)."""
    usable = snapshot is not None and snapshot.get("stats_reset") == stats["stats_reset"]
    previous = snapshot["queries"] if usable else {}
    result = []
    for q in stats["queries"]:
        old = previous.get(q["queryid"])
        calls, total = q["calls"], q["total_ms"]
        # A counter that went backwards means the entry was evicted and re-created: count it from zero.
        if old and calls >= old["calls"] and total >= old["total_ms"]:
            calls, total = calls - old["calls"], total - old["total_ms"]
        if calls > 0:
            result.append({**q, "calls": calls, "total_ms": total, "mean_ms": total / calls})
    if usable:
        description = f"since the previous report ({snapshot['taken_at'][:16]})"
    elif snapshot is None:
        description = f"everything since statistics were last reset ({stats['stats_reset']}), first report"
    else:
        description = f"everything since statistics were last reset ({stats['stats_reset']}), counters were reset"
    return result, description


def log_files(since):
    files = sorted(LOG_DIR.glob(LOG_GLOB))
    return [f for f in files if datetime.fromtimestamp(f.stat().st_mtime) >= since]


def read_records(path):
    opener = gzip.open if path.suffix == ".gz" else open
    current = None
    with opener(path, "rt", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            match = RECORD.match(line)
            if match:
                if current:
                    yield current
                current = {"time": datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"),
                           "user": match.group(2), "message": match.group(4)}
            elif current:
                current["message"] += "\n" + line.lstrip("\t")
    if current:
        yield current


def scan_log(since, ignored_users):
    ignored = set(ignored_users.split(","))
    groups = defaultdict(lambda: {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
    seen = skipped = lock_waits = 0
    files = log_files(since)
    for path in files:
        for record in read_records(path):
            if record["time"] < since:
                continue
            message = record["message"]
            if re.match(r"process \d+ still waiting for ", message):
                lock_waits += 1
                continue
            duration = DURATION.match(message)
            if not duration:
                continue
            seen += 1
            if record["user"] in ignored:
                skipped += 1
                continue
            group = groups[normalise(duration.group(2))]
            ms = float(duration.group(1))
            group["count"] += 1
            group["total_ms"] += ms
            group["max_ms"] = max(group["max_ms"], ms)
    return groups, {"files": len(files), "seen": seen, "skipped": skipped, "lock_waits": lock_waits}


def build_report(args, now):
    since = now - timedelta(days=args.days)
    stats = fetch_statistics(args.database, args.ignore_users)
    snapshot = load_snapshot()
    queries, window = window_delta(stats, snapshot)
    groups, log = scan_log(since, args.ignore_users)

    lines = [
        "PostgreSQL slow query report for the Artemis production database",
        "",
        "What this report looked at:",
        f"  pg_stat_statements: {len(queries)} statements executed {window}",
        f"  server log: {log['files']} file(s) since {since:%Y-%m-%d %H:%M}, "
        f"slow statement threshold log_min_duration_statement = {stats['threshold']} ms",
        f"  {log['seen']} slow log entries, {log['skipped']} skipped because they ran as {args.ignore_users}"
        " (backup, monitoring), "
        f"{log['seen'] - log['skipped']} reported below, {log['lock_waits']} lock wait entries",
        "",
        f"== Top {args.top} statements by total time ==",
    ]
    by_total = sorted(queries, key=lambda q: q["total_ms"], reverse=True)[:args.top]
    lines += format_statements(by_total) or ["  none"]

    lines += ["", f"== Top {args.top} statements by mean time (at least {args.min_calls} calls, "
                  f"mean of at least {args.min_mean_ms} ms) =="]
    slow = [q for q in queries if q["calls"] >= args.min_calls and q["mean_ms"] >= args.min_mean_ms]
    by_mean = sorted(slow, key=lambda q: q["mean_ms"], reverse=True)[:args.top]
    lines += format_statements(by_mean) or ["  none"]

    lines += ["", f"== Slowest statements in the server log (literals removed, top {args.top}) =="]
    worst = sorted(groups.items(), key=lambda item: item[1]["max_ms"], reverse=True)[:args.top]
    for sql, group in worst:
        lines += [f"  {group['count']}x, slowest {group['max_ms'] / 1000:.1f} s, "
                  f"total {group['total_ms'] / 1000:.1f} s", f"    {shorten(sql)}", ""]
    if not worst:
        lines.append("  none")

    return "\n".join(lines) + "\n", stats


def format_statements(queries):
    lines = []
    for q in queries:
        per_call = q["rows"] / q["calls"] if q["calls"] else 0
        lines += [f"  {q['total_ms'] / 1000:.1f} s total, {q['calls']} calls, {q['mean_ms']:.0f} ms mean, "
                  f"{q['max_ms']:.0f} ms max (since reset), {per_call:.1f} rows/call",
                  f"    {shorten(normalise(q['query']))}", ""]
    return lines


def send_mail(report, recipients, now):
    subject = f"[Artemis DB performance scan] PostgreSQL slow query report ({now:%B %d})"
    subprocess.run(["mail", "-s", subject, *recipients], input=report, text=True, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--database", default="Artemis")
    parser.add_argument("--ignore-users", default="postgres,exporter",
                        help="comma separated roles left out of the report (backup, monitoring)")
    parser.add_argument("--days", type=int, default=7, help="how far back the server log is read")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--min-calls", type=int, default=5)
    parser.add_argument("--min-mean-ms", type=int, default=200)
    parser.add_argument("--mail", action="append", default=[], help="recipient, may be repeated")
    parser.add_argument("--stdout", action="store_true", help="print instead of mailing, and keep the snapshot")
    args = parser.parse_args()

    if os.geteuid() != 0:
        sys.exit("must run as root")
    now = datetime.now()
    report, stats = build_report(args, now)
    if args.stdout or not args.mail:
        print(report)
        return
    send_mail(report, args.mail, now)
    save_snapshot(stats, now)  # only after the mail went out, so a failed run is reported next time too


if __name__ == "__main__":
    main()
