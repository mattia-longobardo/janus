"""FastAPI dependencies for the providers holding each role; tests override them with fakes."""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.providers.runtime import DhcpRef, DnsLogRef, dns_query_log, reservation_provider


def get_dhcp(db: Session = Depends(get_db)) -> DhcpRef | None:
    return reservation_provider(db)


def get_dns(db: Session = Depends(get_db)) -> DnsLogRef | None:
    return dns_query_log(db)
