#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.ingest.pipeline import run_pipeline

DEFAULT_DATA_DIR = str(Path(__file__).parent.parent / "data" / "deliveries")
DEFAULT_DB_URL   = os.getenv("DB_URL", "sqlite:///./campaign_hub.db")
STATUS_SYMBOLS   = {"pass": "✓", "warn": "⚠", "fail": "✗"}


def main():
    arg_parser = argparse.ArgumentParser(description="Campaign Data Hub - ingestion CLI")
    arg_parser.add_argument("--dry-run",  action="store_true", help="Run all checks without writing to the DB")
    arg_parser.add_argument("--data-dir", default=os.getenv("DATA_DIR", DEFAULT_DATA_DIR))
    arg_parser.add_argument("--db-url",   default=DEFAULT_DB_URL)
    args = arg_parser.parse_args()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Ingesting from: {args.data_dir}")
    summary = run_pipeline(args.data_dir, args.db_url, dry_run=args.dry_run)

    print("\nSummary:")
    print(f"  Files processed : {summary['files_processed']}")
    print(f"  Rows written    : {summary['rows_written']}")
    print(f"  Rows excluded   : {summary['rows_excluded']}  (see Data Health for reasons)")
    if summary["ignored_files"]:
        print(f"  Ignored files   : {', '.join(summary['ignored_files'])}")

    print("\nDeliveries:")
    for delivery in summary["deliveries"]:
        status_symbol = STATUS_SYMBOLS.get(delivery["status"], "?")
        print(f"  {status_symbol} {delivery['platform']:<14} {delivery['week']}  {delivery['filename'] or '[MISSING]'}")

    for error in summary["errors"]:
        print(f"  ERROR {error}")
    if args.dry_run:
        print("\n[Dry run complete - no data written]")
    sys.exit(1 if summary["errors"] else 0)


if __name__ == "__main__":
    main()
