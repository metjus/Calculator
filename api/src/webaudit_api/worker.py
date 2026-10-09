"""Audit worker: claims queued audits from the database and runs them with the core scanner.

Runs inside the API process (``WEBAUDIT_INPROCESS_WORKER=1``, the default for
development) or as separate processes (``webaudit-worker``). Progress is written
as ``AuditEvent`` rows which the API streams to the browser; a failure on one
website never stops the audit, and "Stop" lets the websites in progress finish.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from webaudit import Config, Scanner
from webaudit.ai_review import ClaudeReviewer, Reviewer
from webaudit.models import ScanResult, SiteState
from webaudit.scanner import ProgressEvent

from .ai_service import apply_review
from .companies import domain_of
from .db import create_schema, make_engine, make_sessionmaker
from .keys import get_key
from .models import Audit, AuditEvent, AuditSite, CompetitorScan, Workspace
from .security import KeyBox
from .settings import Settings

log = logging.getLogger("webaudit.worker")
FINAL_SITE_STATES = {s.value for s in SiteState}
RESTART_DELAY_S = 5.0  # a crashed loop is started again: an audit nobody claims only shows as "queued"
INTERRUPTED = "not checked: the program was closed before this audit finished"


def now() -> datetime:
    return datetime.now(UTC)


class AuditWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        keybox: KeyBox,
        *,
        poll_interval: float = 1.0,
        use_browser: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        config_overrides: dict[str, Any] | None = None,
        ai_reviewer_factory: Callable[[str], Reviewer] | None = None,
        restart_delay: float = RESTART_DELAY_S,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.settings = settings
        self.keybox = keybox
        self.poll_interval = poll_interval
        self.use_browser = use_browser
        self.transport = transport  # tests inject a transport that trusts local fixtures
        self.config_overrides = config_overrides or {}
        self._config = Config.load()  # replaced per audit with the workspace's own overrides
        self.ai_reviewer_factory = ai_reviewer_factory or ClaudeReviewer  # tests inject a fake
        self.restart_delay = restart_delay
        self._dialect = sessionmaker.kw["bind"].dialect.name if sessionmaker.kw.get("bind") is not None else ""
        # What the API tells the UI while an audit waits (``GET /api/audits/{id}`` → ``queue``).
        self.polling = False  # the loop is claiming audits
        self.audit_id: int | None = None  # the audit being scanned right now
        self.last_error: str | None = None

    @property
    def state(self) -> str:
        """One of "running", "starting", "stopped" - shown to the user instead of a silent queue."""
        if self.polling:
            return "running"
        return "stopped" if self.last_error else "starting"

    # ------------------------------------------------------------- loop

    async def run(self, stop: asyncio.Event) -> None:
        """Claim audits until stopped, starting the loop again if it ever fails.

        There is one worker in the desktop app, so a loop that ends leaves every new audit
        sitting in "queued" with nothing to explain it. Any failure is therefore logged,
        kept in ``last_error`` for the UI, and the loop starts again.
        """
        while not stop.is_set():
            try:
                await self._loop(stop)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - never leave the queue without a worker
                self.last_error = f"{exc.__class__.__name__}: {exc}"[:300]
                log.exception("the audit worker failed; starting it again in %.0f s", self.restart_delay)
            finally:
                self.polling = False
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), self.restart_delay)

    async def _loop(self, stop: asyncio.Event) -> None:
        await self.recover()
        self.polling = True
        while not stop.is_set():
            try:
                audit_id = await self.claim()
            except Exception as exc:  # noqa: BLE001 - a transient DB error must not end the loop
                self.last_error = f"{exc.__class__.__name__}: {exc}"[:300]
                log.exception("claiming an audit failed")
                audit_id = None
            if audit_id is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self.poll_interval)
                continue
            self.audit_id = audit_id
            try:
                await self.process(audit_id)
            finally:
                self.audit_id = None

    async def run_once(self) -> bool:
        """Process one queued audit if there is one (used by tests)."""
        audit_id = await self.claim()
        if audit_id is None:
            return False
        await self.process(audit_id)
        return True

    async def recover(self) -> None:
        """An audit interrupted by a restart is closed, not started again behind the user's back.

        The desktop app is stopped by closing its window, often in the middle of an audit.
        Putting that audit back in the queue made it run again on the next start, before
        anything the user begins now - which showed only as "waiting for a free worker" and
        repeated itself every time the window was closed. Websites already checked keep their
        results; the rest are marked cancelled, so the user can simply audit them again.
        (A deployment with several workers needs a lease per worker before this may requeue.)
        """
        async with self.sessionmaker() as db:
            stuck = list(await db.scalars(select(Audit.id).where(Audit.status == "running")))
            # One worker and one user: an audit still queued when the program starts is left
            # over from an earlier launch, and running it now would hold up whatever the user
            # starts next. On a server, queued audits belong to the other workers.
            if self.settings.local_mode:
                stuck += list(await db.scalars(select(Audit.id).where(Audit.status == "queued")))
            if not stuck:
                return
            await db.execute(
                update(AuditSite)
                .where(AuditSite.audit_id.in_(stuck), AuditSite.state.in_(("pending", "running")))
                .values(state="cancelled", state_reason=INTERRUPTED, step=None, finished_at=now())
            )
            for audit_id in stuck:
                done = await db.scalar(
                    select(func.count(AuditSite.id)).where(AuditSite.audit_id == audit_id, AuditSite.finished_at.is_not(None))
                )
                await db.execute(update(Audit).where(Audit.id == audit_id).values(done_count=done or 0))
                db.add(
                    AuditEvent(
                        audit_id=audit_id,
                        kind="log",
                        level="warn",
                        message="The program was closed before this audit finished; the remaining websites were not checked",
                    )
                )
            await db.commit()
        for audit_id in stuck:
            await self._finish(audit_id, "cancelled")
        log.warning("audit(s) %s were interrupted by a restart and are marked stopped", stuck)

    async def claim(self) -> int | None:
        async with self.sessionmaker() as db, db.begin():
            query = select(Audit.id).where(Audit.status == "queued").order_by(Audit.id).limit(1)
            if self._dialect == "postgresql":
                query = query.with_for_update(skip_locked=True)
            audit_id = await db.scalar(query)
            if audit_id is None:
                return None
            claimed = await db.execute(
                update(Audit).where(Audit.id == audit_id, Audit.status == "queued").values(status="running", started_at=now())
            )
            return audit_id if claimed.rowcount == 1 else None

    # ------------------------------------------------------------ audit

    async def process(self, audit_id: int) -> None:
        cancel = asyncio.Event()
        watcher = asyncio.create_task(self._watch_cancel(audit_id, cancel))
        try:
            async with self.sessionmaker() as db:
                audit = await db.get(Audit, audit_id)
                workspace = await db.get(Workspace, audit.workspace_id)
                sites = list(
                    await db.scalars(
                        select(AuditSite).where(AuditSite.audit_id == audit_id, AuditSite.state == "pending").order_by(AuditSite.position)
                    )
                )
                pagespeed_key = await get_key(db, self.keybox, audit.workspace_id, "pagespeed")
                wants_ai = bool((audit.options or {}).get("ai_review"))
                claude_key = await get_key(db, self.keybox, audit.workspace_id, "claude") if wants_ai else None
                language = workspace.pdf_language
                overrides = {**(workspace.config_overrides or {}), **self.config_overrides}
                if audit.cancel_requested:
                    cancel.set()
            log.info("audit %s started: %d website(s) left of %d", audit_id, len(sites), audit.total)
            await self._event(audit_id, "audit_started", data={"total": audit.total, "remaining": len(sites)})
            site_ids = [s.id for s in sites]
            screenshots = self.settings.data_dir / "audits" / str(audit_id)

            async def on_event(event: ProgressEvent) -> None:
                site_id = site_ids[event.index - 1]
                if event.result is not None:
                    await self._site_done(audit_id, site_id, event.index, event.result)
                elif event.step:
                    await self._step(audit_id, site_id, event)
                elif event.level is not None:
                    await self._event(
                        audit_id,
                        "log",
                        level=event.level.value,
                        message=event.message,
                        data={"site_id": site_id, "position": event.index, "url": event.url},
                    )

            self._config = Config.load(overrides=overrides)
            async with Scanner(
                self._config,
                pagespeed_key=pagespeed_key,
                use_browser=self.use_browser,
                allow_private=self.settings.allow_private_targets,
                screenshots_dir=screenshots,
                transport=self.transport,
                on_event=on_event,
                ai_reviewer=self.ai_reviewer_factory(claude_key) if claude_key else None,
                ai_language=language,
            ) as scanner:
                if wants_ai and not claude_key:
                    await self._event(audit_id, "log", level="warn", message="AI design review skipped: add a Claude API key in Settings")
                if scanner.browser_error:
                    await self._event(audit_id, "log", level="warn", message=f"Browser checks disabled: {scanner.browser_error}")
                if not pagespeed_key:
                    await self._event(
                        audit_id, "log", level="info", message="PageSpeed skipped: add a Google PageSpeed API key in Settings"
                    )
                results = await scanner.scan_many([s.input_url for s in sites], concurrency=self.settings.scan_concurrency, cancel=cancel)
                if not cancel.is_set():
                    await self._scan_competitors(audit_id, scanner, sites, results, cancel)
            # Sites skipped by "Stop" never emit a done event; record them from the returned results.
            for index, result in enumerate(results, start=1):
                if result.state is SiteState.CANCELLED:
                    await self._site_done(audit_id, site_ids[index - 1], index, result)
            await self._finish(audit_id, "cancelled" if cancel.is_set() else "done")
        except Exception as exc:  # noqa: BLE001 - mark the audit failed instead of crashing the worker
            log.exception("audit %s failed", audit_id)
            await self._event(audit_id, "log", level="error", message=f"Audit failed: {exc.__class__.__name__}")
            await self._finish(audit_id, "failed")
        finally:
            watcher.cancel()

    async def _scan_competitors(
        self, audit_id: int, scanner: Scanner, sites: list[AuditSite], results: list[ScanResult], cancel: asyncio.Event
    ) -> None:
        """Scan each listed competitor once (no AI review) for the comparison on the website detail."""
        async with self.sessionmaker() as db:
            audited = set(await db.scalars(select(AuditSite.input_url).where(AuditSite.audit_id == audit_id)))
            done = set(await db.scalars(select(CompetitorScan.url).where(CompetitorScan.audit_id == audit_id)))
        wanted: list[str] = []
        for site, result in zip(sites, results, strict=True):
            if result.state is SiteState.OK:
                wanted += [url for url in site.competitors or [] if url not in audited and url not in done and url not in wanted]
        if not wanted:
            return
        noun = "website" if len(wanted) == 1 else "websites"
        await self._event(audit_id, "log", level="info", message=f"Comparing with {len(wanted)} competitor {noun}…")

        async def on_event(event: ProgressEvent) -> None:
            if event.result is not None:
                await self._competitor_done(audit_id, wanted[event.index - 1], event.result)

        scanner.on_event = on_event
        await scanner.scan_many(wanted, concurrency=self.settings.scan_concurrency, cancel=cancel, ai_review=False)

    async def _competitor_done(self, audit_id: int, url: str, result: ScanResult) -> None:
        if result.state is SiteState.CANCELLED:
            return
        payload = result.model_dump(mode="json")
        payload["screenshots"] = {name: self._relative(path) for name, path in result.screenshots.items()}
        payload["snapshots"] = {}
        ok = result.state is SiteState.OK and result.score is not None
        async with self.sessionmaker() as db:
            db.add(
                CompetitorScan(
                    audit_id=audit_id,
                    url=url,
                    final_url=result.final_url,
                    state=result.state.value,
                    state_reason=result.state_reason,
                    score=result.score.total if result.score else None,
                    category=result.score.category.value if result.score else None,
                    result=payload,
                    finished_at=now(),
                )
            )
            db.add(
                AuditEvent(
                    audit_id=audit_id,
                    kind="log",
                    level="ok" if ok else "warn",
                    message=f"competitor: score {result.score.total}/100" if ok else f"competitor: {result.state_reason}",
                    data={"url": result.final_url or url},
                )
            )
            await db.commit()

    async def _watch_cancel(self, audit_id: int, cancel: asyncio.Event) -> None:
        while not cancel.is_set():
            async with self.sessionmaker() as db:
                if await db.scalar(select(Audit.cancel_requested).where(Audit.id == audit_id)):
                    cancel.set()
                    break
            await asyncio.sleep(self.poll_interval)
        await self._event(audit_id, "log", level="warn", message="Stopping: websites in progress will finish, the rest are skipped")

    async def _event(
        self, audit_id: int, kind: str, *, level: str | None = None, message: str | None = None, data: dict | None = None
    ) -> None:
        async with self.sessionmaker() as db:
            db.add(AuditEvent(audit_id=audit_id, kind=kind, level=level, message=message, data=data or {}))
            await db.commit()

    async def _step(self, audit_id: int, site_id: int, event: ProgressEvent) -> None:
        async with self.sessionmaker() as db:
            site = await db.get(AuditSite, site_id)
            site.step = event.step
            if site.state == "pending":
                site.state, site.started_at = "running", now()
            db.add(
                AuditEvent(
                    audit_id=audit_id, kind="step", message=event.step, data={"site_id": site_id, "position": event.index, "url": event.url}
                )
            )
            await db.commit()

    async def _site_done(self, audit_id: int, site_id: int, position: int, result: ScanResult) -> None:
        payload = result.model_dump(mode="json")
        payload["screenshots"] = {name: self._relative(path) for name, path in result.screenshots.items()}
        payload["snapshots"] = {name: self._relative(path) for name, path in result.snapshots.items()}
        ok = result.state is SiteState.OK and result.score is not None
        async with self.sessionmaker() as db:
            site = await db.get(AuditSite, site_id)
            if site.state in FINAL_SITE_STATES:
                return  # already recorded
            if ok:
                payload = await self._apply_pasted_review(db, audit_id, result, payload)
            site.state, site.state_reason, site.step = result.state.value, result.state_reason, None
            # Read the score off the payload: a pasted review adds the design area and changes it.
            scored = payload.get("score") or None
            site.score = scored["total"] if scored else None
            site.category = scored["category"] if scored else None
            site.final_url, site.result, site.finished_at = result.final_url, payload, now()
            counters = {"done_count": Audit.done_count + 1}
            if not ok and result.state is not SiteState.CANCELLED:
                counters["error_count"] = Audit.error_count + 1
            await db.execute(update(Audit).where(Audit.id == audit_id).values(**counters))
            db.add(
                AuditEvent(
                    audit_id=audit_id,
                    kind="site_done",
                    level="ok"
                    if ok
                    else ("warn" if result.state in (SiteState.PROTECTED, SiteState.DISALLOWED, SiteState.CANCELLED) else "error"),
                    message=(f"score {site.score}/100 ({site.category})" if ok else result.state_reason),
                    data={
                        "site_id": site_id,
                        "position": position,
                        "url": result.final_url or result.url or result.input_url,
                        "state": site.state,
                        "score": site.score,
                        "category": site.category,
                    },
                )
            )
            await db.commit()

    async def _finish(self, audit_id: int, status: str) -> None:
        log.info("audit %s %s", audit_id, status)
        async with self.sessionmaker() as db:
            audit = await db.get(Audit, audit_id)
            audit.status, audit.finished_at = status, now()
            scores = [s for s in await db.scalars(select(AuditSite.score).where(AuditSite.audit_id == audit_id)) if s is not None]
            started = audit.started_at or audit.created_at
            started = started if started.tzinfo else started.replace(tzinfo=UTC)
            db.add(
                AuditEvent(
                    audit_id=audit_id,
                    kind="audit_done",
                    level={"done": "ok", "cancelled": "warn"}.get(status, "error"),
                    message={"done": "Audit finished", "cancelled": "Audit stopped"}.get(status, "Audit failed"),
                    data={
                        "status": status,
                        "total": audit.total,
                        "done": audit.done_count,
                        "errors": audit.error_count,
                        "scored": len(scores),
                        "average": round(sum(scores) / len(scores)) if scores else None,
                        "duration_s": round((audit.finished_at - started).total_seconds()),
                    },
                )
            )
            await db.commit()

    async def _apply_pasted_review(self, db: AsyncSession, audit_id: int, result: ScanResult, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach a design review the operator had Claude write before the audit, if there is one.

        It arrives as a CSV on the new-audit screen, waits in ``Audit.options`` until the website
        it belongs to has actually been scanned, and is then graded and scored exactly like a
        review from the API - the score cannot be computed any earlier, because until now there
        was nothing to add the design area to.
        """
        audit = await db.get(Audit, audit_id)
        pasted = (audit.options or {}).get("pasted_reviews") or {}
        domain = domain_of(result.final_url or result.url)
        review = pasted.get(domain)
        if not review:
            return payload
        try:
            updated = apply_review(payload, review, None, self._config)
        except Exception:  # noqa: BLE001 - a bad review must never cost the scan
            log.exception("pasted design review for %s could not be applied", domain)
            return payload
        db.add(
            AuditEvent(
                audit_id=audit_id,
                kind="log",
                level="ok",
                message=f"design review pasted from the Claude app applied ({review.get('score')}/100)",
                data={"url": result.final_url or result.url},
            )
        )
        return updated

    def _relative(self, path: str) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.settings.data_dir.resolve()))
        except ValueError:
            return path


def run() -> None:
    """Entry point for a standalone worker process (``webaudit-worker``)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()

    async def main() -> None:
        engine = make_engine(settings.database_url)
        await create_schema(engine)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        worker = AuditWorker(make_sessionmaker(engine), settings, KeyBox(settings.secret_key))
        log.info("worker started")
        await worker.run(stop)
        await engine.dispose()

    asyncio.run(main())
