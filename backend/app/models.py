import enum
import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.net.ipplan import IpRange


class Access(enum.StrEnum):
    authorized = "authorized"
    lan_only = "lan_only"
    pending = "pending"
    guest = "guest"
    blocked = "blocked"


ACCESS_TYPE = Enum(Access, name="access")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    color: Mapped[str] = mapped_column(String(9))
    icon: Mapped[str] = mapped_column(String(32))
    range_start: Mapped[str] = mapped_column(String(15))
    range_end: Mapped[str] = mapped_column(String(15))
    default_access: Mapped[Access] = mapped_column(ACCESS_TYPE)
    offline_alert_hours: Mapped[int | None] = mapped_column(Integer)
    scan_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    scan_interval_hours: Mapped[int] = mapped_column(Integer, default=168)

    devices: Mapped[list["Device"]] = relationship(back_populates="group")

    def ip_range(self) -> IpRange:
        return IpRange.parse(self.range_start, self.range_end)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    mac: Mapped[str | None] = mapped_column(String(17), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    hostname: Mapped[str] = mapped_column(String(63), unique=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"))
    static_ip: Mapped[str | None] = mapped_column(String(15), unique=True)
    access: Mapped[Access] = mapped_column(ACCESS_TYPE)
    vendor: Mapped[str | None] = mapped_column(String(128))
    private_mac: Mapped[bool] = mapped_column(Boolean, default=False)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_ip: Mapped[str | None] = mapped_column(String(15))
    dhcp_hostname: Mapped[str | None] = mapped_column(String(255))
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    map_x: Mapped[float | None] = mapped_column(Float)
    map_y: Mapped[float | None] = mapped_column(Float)
    guest_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    guest_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    group: Mapped[Group | None] = relationship(back_populates="devices")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    type: Mapped[str] = mapped_column(String(64), index=True)
    mac: Mapped[str | None] = mapped_column(String(17), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)


class Sighting(Base):
    __tablename__ = "sightings"
    __table_args__ = (Index("ix_sightings_mac_source_ts", "mac", "source", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    mac: Mapped[str] = mapped_column(String(17), index=True)
    ip: Mapped[str | None] = mapped_column(String(15))
    source: Mapped[str] = mapped_column(String(8))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    start_time: Mapped[time] = mapped_column(Time)
    duration_min: Mapped[int] = mapped_column(Integer)
    days: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    mute_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    pause_isolation: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    event_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class DeviceFact(Base):
    __tablename__ = "device_facts"
    __table_args__ = (UniqueConstraint("mac", "field", "source", name="uq_device_facts_mac_field_source"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mac: Mapped[str] = mapped_column(String(17), index=True)
    field: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("mac", "port", "proto", name="uq_services_mac_port_proto"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mac: Mapped[str] = mapped_column(String(17), index=True)
    port: Mapped[int] = mapped_column(Integer)
    proto: Mapped[str] = mapped_column(String(4))
    state: Mapped[str] = mapped_column(String(8))
    service: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[str | None] = mapped_column(String(255))
    risk: Mapped[str] = mapped_column(String(16))
    risk_reason: Mapped[str | None] = mapped_column(String(128))
    muted: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", name="uq_links_source_target"),
        Index("uq_links_pair", func.least(text("source_id"), text("target_id")),
              func.greatest(text("source_id"), text("target_id")), unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(8))
    label: Mapped[str | None] = mapped_column(String(64))
