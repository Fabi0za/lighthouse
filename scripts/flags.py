"""Flags a person handles: list them and resolve them.

Usage:
    python scripts/flags.py list
    python scripts/flags.py approve VERSION_ID        # a held candidate becomes current
    python scripts/flags.py reject VERSION_ID         # a held candidate is retired
    python scripts/flags.py confirm SOURCE_KEY        # the source is still what is watched
    python scripts/flags.py set-address SOURCE_KEY ADDRESS   # watch another address (confirms)
    python scripts/flags.py discard VERSION_ID        # give up a failed (or stuck loading) version
    python scripts/flags.py resolve FLAG_NUMBER       # a failed check is settled (e.g. address back)
    python scripts/flags.py raise-overdue [--max-age-days N]
    python scripts/flags.py report-unreachable SOURCE_KEY ADDRESS [--message TEXT]

raise-overdue flags every source not confirmed within CONFIRMATION_MAX_AGE_DAYS
(default 180), unless --max-age-days is given. This is a command line, not a
review screen; when to run raise-overdue is up to whoever schedules it.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from app.config import get_settings
from app.models.database import DatabaseClient


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="open flags, by number")
    for name, help_ in (("approve", "a held candidate becomes current"),
                        ("reject", "a held candidate is retired")):
        sub.add_parser(name, help=help_).add_argument("version_id")
    sub.add_parser("confirm", help="a person confirms the source").add_argument("source_key")
    watch = sub.add_parser("set-address", help="watch another address for a source (confirms it)")
    watch.add_argument("source_key")
    watch.add_argument("address")
    sub.add_parser("discard", help="give up a failed or stuck loading version").add_argument("version_id")
    sub.add_parser("resolve", help="settle an open check_failed flag").add_argument("flag_number", type=int)
    overdue = sub.add_parser("raise-overdue", help="flag sources not confirmed for too long")
    overdue.add_argument("--max-age-days", type=int, default=None)
    unreachable = sub.add_parser("report-unreachable", help="a watched address cannot be reached")
    unreachable.add_argument("source_key")
    unreachable.add_argument("address")
    unreachable.add_argument("--message", default=None)
    return ap


def _line(flag: dict) -> str:
    detail = flag["detail"]
    where = detail.get("file") or detail.get("address") or "-"
    line = f"#{flag['id']} {flag['source_key']} {flag['kind']}/{flag['reason']} {where}"
    if detail.get("message"):
        line += f": {detail['message']}"
    held = [v["id"] for v in flag.get("versions") or []]
    if held:
        line += f" (version {', '.join(held)})"
    return line


def _age(created_at: str) -> str:
    started = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    minutes = int((datetime.now(timezone.utc) - started).total_seconds() // 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    return f"{days} d {hours} h" if days else f"{hours} h {minutes} min"


def main(argv: list[str] | None = None, db=None, settings=None) -> int:
    args = _parser().parse_args(argv)
    db = db or DatabaseClient()
    if args.command == "list":
        open_flags = db.list_open_flags()
        for flag in open_flags:
            print(_line(flag))
        if not open_flags:
            print("no open flags")
        for v in db.list_loading_versions():  # a load in progress, or one that crashed
            print(f"loading {v['source_key']} ({v.get('version_label') or '-'}) {v['id']} since {_age(v['created_at'])}")
    elif args.command == "approve":
        seen = db.approve_candidate(args.version_id)
        print(f"approved {args.version_id}; the version it retired was seen by {seen} earlier answers"
              + (" (scripts/answers.py saw lists them)" if seen else ""))
    elif args.command == "reject":
        db.reject_version(args.version_id)
        print(f"rejected {args.version_id}")
    elif args.command == "set-address":
        db.set_watch_address(args.source_key, args.address)
        print(f"watching {args.address} for {args.source_key} (confirmed)")
    elif args.command == "discard":
        db.discard_version(args.version_id, resolved_by="person")
        print(f"discarded {args.version_id}")
    elif args.command == "resolve":
        db.resolve_check(args.flag_number)
        print(f"flag #{args.flag_number} resolved")
    elif args.command == "confirm":
        db.confirm_source(args.source_key)
        print(f"confirmed {args.source_key}")
    elif args.command == "raise-overdue":
        days = args.max_age_days or (settings or get_settings()).confirmation_max_age_days
        n = db.raise_overdue_flags(days)
        print(f"{n} overdue flags raised (older than {days} days)")
    elif args.command == "report-unreachable":
        n = db.raise_check_failed(args.source_key, args.address, args.message)
        print(f"flag #{n} raised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
