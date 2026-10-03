import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.db import SessionLocal
from app.enforcement.sync import apply_sync, plan_sync
from app.importer import import_csv
from app.netconfig import load_netconfig
from app.providers import registry
from app.providers.base import ProviderError
from app.providers.runtime import reservation_provider
from app.syncmode import MODES, set_sync_mode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="janus")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-csv", help="import devices from a CSV export")
    imp.add_argument("path", type=Path)
    imp.add_argument("--dry-run", action="store_true", help="show the report without saving")
    syn = sub.add_parser("sync", help="compare (or apply) the reservations of the DHCP provider")
    syn.add_argument("--apply", action="store_true")
    mode = sub.add_parser("sync-mode", help="switch enforcement: apply writes to the DHCP provider, dry-run only plans")
    mode.add_argument("mode", choices=MODES)
    for spec in registry.all_specs():
        if spec.cli is not None:
            spec.cli(sub)   # provider-specific commands; each sets `run`
    args = parser.parse_args(argv)
    if hasattr(args, "run"):
        return args.run(args)

    with SessionLocal() as db:
        if args.command == "import-csv":
            report = import_csv(db, args.path.read_text(encoding="utf-8-sig"), load_netconfig(db).plan())
            print(json.dumps(asdict(report), indent=2))
            if args.dry_run:
                db.rollback()
            else:
                db.commit()
            return 0
        dhcp = reservation_provider(db)
        if args.command == "sync-mode":
            if args.mode == "apply" and dhcp is None:
                print("error: no DHCP provider with reservations is configured", file=sys.stderr)
                return 2
            set_sync_mode(db, args.mode, actor="cli")
            db.commit()
            print(f"sync mode: {args.mode}")
            return 0
        if dhcp is None:
            print("error: no DHCP provider with reservations is configured", file=sys.stderr)
            return 2
        kind, policies, factory = dhcp
        try:
            with factory() as store:
                diff = apply_sync(db, store, kind, policies) if args.apply else plan_sync(db, store, kind, policies)
        except ProviderError as exc:
            db.commit()
            print(f"error: {exc}", file=sys.stderr)
            return 1
        db.commit()
        print(json.dumps(diff.as_dict(store.describe), indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
