"""`janus preflight|backup|cutover|rollback`: the Pi-hole DHCP cutover, run from the backend container."""
import argparse
import json
import os
import sys
from typing import Any

from app.db import SessionLocal
from app.providers.base import Role
from app.providers.config import load_role
from app.providers.pihole.api import current_config
from app.providers.pihole.client import PiholeError
from app.providers.pihole.cutover import PiholeAdmin, cutover, preflight, rollback, take_backup
from app.providers.pihole.provider import KIND


def register(sub: Any) -> None:
    sub.add_parser("preflight", help="check that the DHCP cutover can start").set_defaults(run=run)
    sub.add_parser("backup", help="save a Pi-hole Teleporter export and a Janus data dump").set_defaults(run=run)
    for name, text in (("cutover", "turn on Pi-hole DHCP and switch Janus to apply"),
                       ("rollback", "turn Pi-hole DHCP off and switch Janus back to dry-run")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--pihole-password-env", required=True, metavar="VAR",
                         help="name of the environment variable holding the Pi-hole admin password")
        cmd.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        cfg, dhcp_kind = current_config(db)
        if args.command == "cutover" and dhcp_kind != KIND:
            # Turning on Pi-hole DHCP next to another DHCP server would put two of them on the LAN.
            dhcp = load_role(db, Role.DHCP)
            owner = f"the DHCP role belongs to {dhcp.spec.label}" if dhcp else "no DHCP provider is configured"
            print(f"error: {owner}; assign the DHCP role to Pi-hole before the cutover", file=sys.stderr)
            return 2
        if args.command in ("cutover", "rollback"):
            password = os.environ.get(args.pihole_password_env, "")
            if not password:
                print(f"error: environment variable {args.pihole_password_env} is empty", file=sys.stderr)
                return 2
            cfg = cfg.model_copy(update={"password": password})
        try:
            with PiholeAdmin(cfg.url, cfg.password) as client:
                if args.command == "preflight":
                    report = preflight(db, client, cfg, dhcp_kind=dhcp_kind)
                    print(json.dumps(report.as_dict(), indent=2))
                    return 0 if report.ready else 1
                if args.command == "backup":
                    print(f"backup written to {take_backup(db, client)}")
                    return 0
                result = (cutover(db, client, cfg, dhcp_kind=dhcp_kind) if args.command == "cutover"
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
