"""Command line interface (English, like the rest of the operator UI)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__, pagespeed
from .config import Config, export_defaults
from .inputs import SiteInput, read_csv
from .models import Category, LogLevel, ScanResult, SiteState, Status
from .report import area_label, category_label, check_label, client_issues
from .scanner import ProgressEvent, Scanner

ICONS = {LogLevel.OK: ("✔", "green"), LogLevel.WARN: ("⚠", "yellow"), LogLevel.ERROR: ("✖", "red"), LogLevel.INFO: ("·", "dim")}
STATUS_STYLE = {Status.FAIL: ("✖", "red"), Status.WARN: ("⚠", "yellow"), Status.PASS: ("✔", "green"), Status.NA: ("–", "dim")}
CATEGORY_STYLE = {
    Category.CRITICAL: "bold white on red",
    Category.WEAK: "bold black on dark_orange",
    Category.OK: "bold black on yellow",
    Category.GOOD: "bold white on green",
}
STATE_LABEL = {
    SiteState.UNREACHABLE: "Not loaded",
    SiteState.PROTECTED: "Protected – check manually",
    SiteState.DISALLOWED: "Not scanned (robots.txt)",
    SiteState.INVALID: "Invalid URL",
    SiteState.CANCELLED: "Stopped",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webaudit", description="Audit small-business websites and score them 0–100.")
    parser.add_argument("--version", action="version", version=f"webaudit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="audit one or more websites")
    scan.add_argument("urls", nargs="*", help="website addresses, e.g. kadernictvo-x.sk")
    scan.add_argument("--csv", help="CSV with columns url, nazov_firmy, konkurencia, projekt")
    scan.add_argument("--json", dest="json_out", metavar="FILE", help="write full results as JSON")
    scan.add_argument("--lang", choices=("sk", "cs", "en"), help="also print the client texts in this language")
    scan.add_argument("--no-browser", action="store_true", help="skip rendered checks (mobile, contrast, fonts...)")
    scan.add_argument(
        "--pagespeed-key", default=os.environ.get("PAGESPEED_API_KEY"), help="Google PageSpeed API key (or env PAGESPEED_API_KEY)"
    )
    scan.add_argument("--screenshots", metavar="DIR", help="save desktop and mobile screenshots here")
    scan.add_argument("--concurrency", type=int, default=2, help="websites scanned at the same time (default 2)")
    scan.add_argument("--config", metavar="DIR", help="folder with JSON overrides (see 'webaudit config export')")
    scan.add_argument("--allow-private", action="store_true", help="allow localhost/private addresses (testing only)")
    scan.add_argument("--quiet", action="store_true", help="no live log, only the results")

    config = sub.add_parser("config", help="work with the editable JSON configuration")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    export = config_sub.add_parser("export", help="copy default JSON files into a folder for editing")
    export.add_argument("directory")

    test_key = sub.add_parser("test-key", help="check that an API key works")
    test_key.add_argument("service", choices=("pagespeed",))
    test_key.add_argument("key")
    return parser


def _print_event(console: Console, event: ProgressEvent, multi: bool) -> None:
    prefix = f"[{event.index}/{event.total}] " if multi else ""
    if event.step and event.step != "done":
        console.print(Text(f"{prefix}{event.url}: {event.step}", style="dim"))
    elif event.level is not None:
        icon, style = ICONS[event.level]
        line = Text()
        line.append(event.time.astimezone().strftime("%H:%M:%S "), style="dim")
        line.append(f"{icon} ", style=style)
        line.append(f"{prefix}{event.url}: {event.message}")
        console.print(line)


def render_result(result: ScanResult, config: Config, lang: str | None = None) -> Panel:
    title = result.final_url or result.url or result.input_url
    if result.state is not SiteState.OK or result.score is None:
        body = Text(result.state_reason or STATE_LABEL.get(result.state, result.state.value))
        return Panel(body, title=title, subtitle=STATE_LABEL.get(result.state, result.state.value), border_style="yellow")

    score = result.score
    header = Text()
    header.append(f" {score.total}/100 ", style=CATEGORY_STYLE[score.category])
    header.append(f"  {category_label(config, score.category)}", style="bold")
    duration = result.duration_s
    if duration is not None:
        header.append(f"   scanned in {duration:.0f}s", style="dim")

    areas = Table.grid(padding=(0, 2))
    row = [f"{area_label(config, a.area)} [bold]{a.score}[/]" for a in sorted(score.areas, key=lambda a: -a.weight)]
    areas.add_row(*row)

    tech = [result.tech.cms + (f" {result.tech.cms_version}" if result.tech.cms_version else "")] if result.tech.cms else []
    tech += [
        f"{lib.name} {lib.version or ''}".strip() + (" (outdated)" if lib.status is Status.FAIL else "") for lib in result.tech.libraries
    ]

    issues = Table(show_header=True, header_style="bold", box=None, padding=(0, 1), expand=True)
    issues.add_column("", width=1)
    issues.add_column("Cost", justify="right", width=5)
    issues.add_column("Problem", ratio=2)
    issues.add_column("Details", ratio=3, style="dim")
    by_id = {c.id: c for c in result.checks}
    for issue in result.issues:
        icon, style = STATUS_STYLE[issue.status]
        check = by_id[issue.check_id]
        issues.add_row(Text(icon, style=style), f"−{issue.impact:.1f}", check_label(config, issue.check_id), check.summary)

    passed = sum(1 for c in result.checks if c.status is Status.PASS)
    skipped = [c for c in result.checks if c.status is Status.NA]
    parts: list = [header, Text(""), areas]
    if tech:
        parts += [Text(""), Text("Tech: " + " · ".join(tech), style="cyan")]
    parts += [Text(""), issues if result.issues else Text("No problems found.", style="green")]
    parts += [Text(""), Text(f"Passed {passed} · Problems {len(result.issues)} · Not evaluated {len(skipped)}", style="dim")]
    if lang:
        parts += [Text(""), Text(f"Client texts ({lang})", style="bold")]
        for item in client_issues(result, config, lang)[:8]:
            parts.append(Text(f"• {item['problem']} {item['impact']} {item['solution']}"))
    border = {"critical": "red", "weak": "dark_orange", "ok": "yellow", "good": "green"}[score.category.value]
    return Panel(Group(*parts), title=title, border_style=border)


def _summary(results: list[ScanResult], no_website: list[SiteInput]) -> Text:
    scored = [r for r in results if r.state is SiteState.OK and r.score]
    text = Text(f"{len(results)} websites · {len(scored)} scored")
    if scored:
        text.append(f" · average {sum(r.score.total for r in scored) / len(scored):.0f}/100")
    for state in (SiteState.PROTECTED, SiteState.UNREACHABLE, SiteState.DISALLOWED, SiteState.INVALID, SiteState.CANCELLED):
        count = sum(1 for r in results if r.state is state)
        if count:
            text.append(f" · {count} {STATE_LABEL[state].lower()}")
    if no_website:
        text.append(f" · {len(no_website)} without a website")
    return text


async def _run_scan(args: argparse.Namespace, console: Console) -> int:
    config = Config.load(args.config)
    urls: list[str] = list(args.urls)
    no_website: list[SiteInput] = []
    if args.csv:
        for item in read_csv(args.csv):
            if item.error:
                console.print(f"[red]✖[/] {item.company or ''} {item.error}")
            elif item.url:
                urls.append(item.url)
            else:
                no_website.append(item)
    if not urls and not no_website:
        console.print("[red]Give at least one URL or --csv FILE.[/]")
        return 2

    multi = len(urls) > 1
    on_event = None if args.quiet else (lambda e: _print_event(console, e, multi))
    console.print(
        f"[bold]webaudit {__version__}[/] · {len(urls)} website(s) · browser "
        f"{'off' if args.no_browser else 'on'} · PageSpeed {'on' if args.pagespeed_key else 'off (no API key)'}"
    )
    async with Scanner(
        config,
        pagespeed_key=args.pagespeed_key,
        use_browser=not args.no_browser,
        allow_private=args.allow_private,
        screenshots_dir=args.screenshots,
        on_event=on_event,
    ) as scanner:
        if scanner.browser_error:
            console.print(f"[yellow]⚠ Browser checks disabled: {scanner.browser_error}[/]")
        results = await scanner.scan_many(urls, concurrency=args.concurrency)

    console.print()
    for result in sorted(results, key=lambda r: r.score.total if r.score else 999):
        console.print(render_result(result, config, args.lang))
    for item in no_website:
        console.print(Panel(f"{item.company} – no website (lead for a new website)", border_style="blue"))
    console.print(_summary(results, no_website))

    if args.json_out:
        payload = [r.model_dump(mode="json") for r in results]
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        console.print(f"[dim]Results written to {args.json_out}[/]")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    console = Console()
    if args.command == "config":
        written = export_defaults(args.directory)
        console.print(f"Wrote {len(written)} file(s) to {args.directory}. Edit them and pass --config {args.directory}.")
        return 0
    if args.command == "test-key":
        ok, message = asyncio.run(pagespeed.test_key(args.key))
        console.print(("[green]✔ Valid[/] " if ok else "[red]✖ Invalid[/] ") + message)
        return 0 if ok else 1
    try:
        return asyncio.run(_run_scan(args, console))
    except KeyboardInterrupt:
        console.print("[yellow]Stopped.[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
