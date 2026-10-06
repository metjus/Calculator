"""Database tables. Every customer-owned row carries ``workspace_id``.

No contact data is stored anywhere (names of people, phone numbers, e-mails):
companies hold only a business name, website, project and flags. Businesses found
through Google Places keep only their ``place_id`` (Google's terms); names and
addresses are fetched again when needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(UTC)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # "My details for the PDF": name, company id (IČO), phone, e-mail – the user's own, not leads'.
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pdf_language: Mapped[str] = mapped_column(String(2), default="sk")
    # Per-workspace overrides of the core JSON config (weights, thresholds, texts).
    config_overrides: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    workspace: Mapped[Workspace] = relationship(lazy="joined")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("workspace_id", "service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    service: Mapped[str] = mapped_column(String(32))  # pagespeed | claude | google_places
    encrypted: Mapped[str] = mapped_column(Text)
    last4: Mapped[str] = mapped_column(String(4))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    test_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Company(Base):
    """A business the user audits or wants to contact. The CRM (stage 7) builds on this."""

    __tablename__ = "companies"
    __table_args__ = (Index("ix_companies_ws_domain", "workspace_id", "domain"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project: Mapped[str | None] = mapped_column(String(200), nullable=True)
    place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Google Places id (kept permanently)
    osm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. "node/123" (ODbL data)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # The user's decision after checking a website the scanner could not score by hand
    # ("contact" = worth contacting, "skip" = not worth it); stage 7 turns it into a status.
    manual_check: Mapped[str | None] = mapped_column(String(16), nullable=True)
    manual_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def has_website(self) -> bool:
        return bool(self.url)


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    project: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|cancelled|failed
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sites: Mapped[list[AuditSite]] = relationship(back_populates="audit", order_by="AuditSite.position", cascade="all, delete-orphan")

    @property
    def finished(self) -> bool:
        return self.status in ("done", "cancelled", "failed")


class AuditSite(Base):
    __tablename__ = "audit_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    position: Mapped[int] = mapped_column(Integer)  # 1-based order inside the audit
    input_url: Mapped[str] = mapped_column(String(2048))
    competitors: Mapped[list[str]] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|ok|unreachable|protected|...
    state_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    step: Mapped[str | None] = mapped_column(String(200), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # full ScanResult
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    audit: Mapped[Audit] = relationship(back_populates="sites")
    company: Mapped[Company | None] = relationship(lazy="joined")


class AuditEvent(Base):
    """Progress feed of an audit; streamed to the browser over SSE (id = SSE event id)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # audit_started|step|log|site_done|audit_done
    level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SearchTemplate(Base):
    __tablename__ = "search_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ApiUsage(Base):
    """Monthly request counters for paid APIs (cost estimate and free-limit warning)."""

    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("workspace_id", "month", "sku"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7))  # "2026-10"
    sku: Mapped[str] = mapped_column(String(64))
    count: Mapped[int] = mapped_column(Integer, default=0)
