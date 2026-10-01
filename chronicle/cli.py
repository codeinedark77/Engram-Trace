from __future__ import annotations

import argparse
import json
import os
import secrets
import sys

from . import __version__
from .models import DecisionOutcome
from .recorder import Recorder
from .replay import replay_chain


def _cmd_verify(args) -> int:
    recorder = Recorder(db_path=args.db)
    if args.archive_path:
        report = recorder.verify_continuity(args.archive_path)
    else:
        report = recorder.verify_integrity()
    if args.json:
        print(json.dumps(report.__dict__))
    else:
        status = "VALID" if report.is_valid else "BROKEN"
        print(f"{status} — {report.total_records} record(s)")
        if report.is_valid and report.anchored_at_genesis is False:
            print(
                "  note: not verified back to genesis — history may have been pruned; pass --archive to check continuity"
            )
        if not report.is_valid:
            print(f"  first break at seq={report.first_break_seq}: {report.detail}")
    return 0 if report.is_valid else 1


def _cmd_replay(args) -> int:
    recorder = Recorder(db_path=args.db)
    chain = recorder.get_chain(args.correlation_id)
    if not chain:
        print(f"no records for correlation_id={args.correlation_id}", file=sys.stderr)
        return 1
    print(replay_chain(chain))
    return 0


def _cmd_log(args) -> int:
    recorder = Recorder(db_path=args.db)
    rec = recorder.record(
        agent_id=args.agent_id,
        decision=args.decision,
        outcome=DecisionOutcome(args.outcome),
        correlation_id=args.correlation_id,
        reasoning=args.reasoning,
    )
    print(rec.trace_id)
    return 0


def _cmd_archive(args) -> int:
    recorder = Recorder(db_path=args.db)
    try:
        deleted = recorder.archive_and_prune(args.path, args.up_to_seq)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"archived and pruned {deleted} record(s) to {args.path}")
    return 0


def _cmd_serve(args) -> int:
    import uvicorn

    from .api import create_app

    token = args.token or os.environ.get("CHRONICLE_API_TOKEN") or None
    if not token:
        print(
            "warning: no API token set (--token or CHRONICLE_API_TOKEN) — serving without authentication",
            file=sys.stderr,
        )
    app = create_app(db_path=args.db, api_token=token)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _cmd_token(args) -> int:
    print(secrets.token_urlsafe(32))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chronicle", description="Tamper-evident decision-trace recorder")
    parser.add_argument("--version", action="version", version=f"chronicle {__version__}")
    parser.add_argument("--db", default="chronicle.db", help="path to the SQLite store (default: chronicle.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_verify = sub.add_parser("verify", help="check the chain's integrity")
    p_verify.add_argument("--json", action="store_true", help="print the report as JSON")
    p_verify.add_argument(
        "--archive",
        dest="archive_path",
        default=None,
        help="also verify continuity against a JSONL archive produced by 'archive'",
    )
    p_verify.set_defaults(func=_cmd_verify)

    p_replay = sub.add_parser("replay", help="print a correlation id's decision chain as markdown")
    p_replay.add_argument("correlation_id")
    p_replay.set_defaults(func=_cmd_replay)

    p_log = sub.add_parser("log", help="record a single decision from the shell")
    p_log.add_argument("agent_id")
    p_log.add_argument("decision")
    p_log.add_argument("outcome", choices=[o.value for o in DecisionOutcome])
    p_log.add_argument("--correlation-id", dest="correlation_id")
    p_log.add_argument("--reasoning")
    p_log.set_defaults(func=_cmd_log)

    p_serve = sub.add_parser("serve", help="run the Chronicle API service")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8420)
    p_serve.add_argument("--token", default=None, help="require this bearer token (or set CHRONICLE_API_TOKEN)")
    p_serve.set_defaults(func=_cmd_serve)

    p_token = sub.add_parser("token", help="generate a random API token for use with 'serve'")
    p_token.set_defaults(func=_cmd_token)

    p_archive = sub.add_parser(
        "archive", help="export records up to a seq to JSONL, verify them, then prune them from the live store"
    )
    p_archive.add_argument("path", help="output path for the JSONL archive")
    p_archive.add_argument("--up-to-seq", type=int, required=True, dest="up_to_seq")
    p_archive.set_defaults(func=_cmd_archive)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
