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
    # The operator's logo for the PDF header (file name inside <data>/branding) and the three
    # offer options last used, so the prices they typed come back prefilled next time.
    logo: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_offer: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # When customers move to the archive, when to offer them again and when to warn that their
    # notes are due to be cleared - the brief's archive rules (stage 8). None = the defaults.
    crm_rules: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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
    # ("contact" = worth contacting, "skip" = not worth it); the CRM status takes it from there.
    manual_check: Mapped[str | None] = mapped_column(String(16), nullable=True)
    manual_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # --- CRM (stage 7). Still no contact person, phone or e-mail: the brief forbids storing them.
    status: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)  # see STATUSES
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_step_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The live demo of a design, and when it went out: after 30 days the program says to take it down.
    proposal_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    proposal_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deal_value: Mapped[int | None] = mapped_column(Integer, nullable=True)  # agreed price, whole currency units
    # --- Archive (stage 8). Nobody is ever deleted automatically; closed customers only move
    # aside, so the user still knows who was already approached.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the owner brought them back by hand. The archive rule then leaves them alone until
    # their status changes again, so "bring back" is not undone by the next pass.
    unarchived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def has_website(self) -> bool:
        return bool(self.url)


class CompanyEvent(Base):
    """The customer's timeline: status changes, contacts, the proposal and the deal.

    Contacts record only the date, how it happened and a short note - never who was spoken to.
    """

    __tablename__ = "company_events"
    __table_args__ = (Index("ix_company_events_company_at", "company_id", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # status | contact | proposal | note
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str | None] = mapped_column(String(24), nullable=True)  # for kind="status"
    way: Mapped[str | None] = mapped_column(String(16), nullable=True)  # in_person | phone | email | message
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


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


class CompetitorScan(Base):
    """A competitor website scanned for comparison, once per audit however many sites list it.

    Competitors come from the CSV column ``konkurencia`` or the competitors field of a new audit;
    they get the normal checks and screenshots but no AI review, and stay out of all statistics.
    """

    __tablename__ = "competitor_scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048))  # as listed with the audited site (normalized)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    state: Mapped[str] = mapped_column(String(16))
    state_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
