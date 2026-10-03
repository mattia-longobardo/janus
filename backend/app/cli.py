import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.importer import import_csv
from app.netconfig import load_netconfig
from app.pihole.sync import apply_sync, plan_sync
from app.providers.pihole.client import PiholeClient, PiholeError
from app.providers.pihole.cutover import PiholeAdmin, cutover, preflight, rollback, take_backup
from app.providers.pihole.provider import PiholeConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="janus")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-csv", help="import devices from a CSV export")
    imp.add_argument("path", type=Path)
    imp.add_argument("--dry-run", action="store_true", help="show the report without saving")
    syn = sub.add_parser("sync", help="compare (or apply) Pi-hole reservations")
    syn.add_argument("--apply", action="store_true")
    sub.add_parser("preflight", help="check that the DHCP cutover can start")
    sub.add_parser("backup", help="save a Pi-hole Teleporter export and a Janus data dump")
    for name, text in (("cutover", "turn on Pi-hole DHCP and switch Janus to apply"),
                       ("rollback", "turn Pi-hole DHCP off and switch Janus back to dry-run")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--pihole-password-env", required=True, metavar="VAR",
                         help="name of the environment variable holding the Pi-hole admin password")
    args = parser.parse_args(argv)
    if args.command in ("preflight", "backup", "cutover", "rollback"):
        return _cutover_command(args)

    with SessionLocal() as db:
        if args.command == "import-csv":
            report = import_csv(db, args.path.read_text(encoding="utf-8-sig"), load_netconfig(db).plan())
            print(json.dumps(asdict(report), indent=2))
            if args.dry_run:
                db.rollback()
            else:
                db.commit()
            return 0
        try:
            with PiholeClient(load_netconfig(db).pihole_url, settings.pihole_password) as client:
                diff = apply_sync(db, client, settings.reservation_lease) if args.apply else plan_sync(
                    db, client, settings.reservation_lease)
        except PiholeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        db.commit()
        print(json.dumps(diff.as_dict(), indent=2))
        return 0


def _cutover_command(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        url = load_netconfig(db).pihole_url
        password = settings.pihole_password
        if args.command in ("cutover", "rollback"):
            password = os.environ.get(args.pihole_password_env, "")
            if not password:
                print(f"error: environment variable {args.pihole_password_env} is empty", file=sys.stderr)
                return 2
        try:
            cfg = PiholeConfig(url=url, password=password, lease=settings.reservation_lease)
            with PiholeAdmin(url, password) as client:
                if args.command == "preflight":
                    report = preflight(db, client, cfg, dhcp_kind="pihole")
                    print(json.dumps(report.as_dict(), indent=2))
                    return 0 if report.ready else 1
                if args.command == "backup":
                    print(f"backup written to {take_backup(db, client)}")
                    return 0
                result = (cutover(db, client, cfg, dhcp_kind="pihole") if args.command == "cutover"
                          else rollback(db, client))
        except (PiholeError, RuntimeError) as exc:
            db.rollback()
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(json.dumps(result, indent=2))
    if args.command == "cutover":
        print("\nNext: switch DHCP OFF on the QHora-301W, then reconnect devices and check the map.", file=sys.stderr)
    else:
        print("\nNext: switch DHCP back ON on the QHora-301W.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
