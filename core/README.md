# webaudit (core)

The scanning engine of the website-audit SaaS. It has no UI dependencies: the
CLI, the SaaS API workers and any future desktop shell all call the same code.

## What it does

For each URL it politely gathers data (robots.txt respected, one request at a
time per host, time limit per site, nothing but results stored), runs ~40
checks in 8 areas, and turns them into a 0–100 score with a category
(Critical / Weak / OK / Good) and a list of problems ordered by impact.

| Area | Checks |
|---|---|
| Basics | HTTPS, certificate validity, http → https redirect |
| Mobile | viewport, legible font size, tap-target size, sideways scrolling |
| Speed | PageSpeed mobile/desktop, Core Web Vitals, heavy images, page weight, server response |
| SEO | title, meta description, H1, indexability, sitemap, Open Graph, favicon, LocalBusiness data |
| Trust & content | visible contact, tap-to-call phone, address/map, footer year, social links, cookie consent, broken links |
| Tech | CMS version, outdated JS libraries, console errors, mixed content |
| Accessibility | contrast, image alt text, form labels, icon-only controls, page language |
| Design (auto) | fixed width, table layout, small text, too many fonts, legacy HTML |

Sites behind a Cloudflare (or similar) challenge get the state `protected`
("Probably protected by Cloudflare – check manually") and no score. Sites that
fail to load get `unreachable` with a reason and no score.

Contact details are never stored: the trust checks only record whether a phone
number or e-mail exists, and page text kept for the export (inventory, HTML
snapshots) has e-mail addresses and phone numbers replaced by `[e-mail]` /
`[phone]` (`redact.py`). Person names can't be detected and are not removed.

## Usage

```bash
pip install -e ".[browser]"           # Playwright for the rendered checks
export WEBAUDIT_CHROMIUM_PATH=/path/to/chrome   # optional, if Playwright's own browser isn't installed

webaudit scan kadernictvo-x.sk example.sk
webaudit scan --csv leads.csv --json results.json --lang sk --screenshots shots/
webaudit scan --no-browser example.sk          # static checks only
webaudit scan --claude-export out/ example.sk  # folder for Claude Code (see below)
webaudit config export ./my-config             # editable JSON (weights, thresholds, texts)
webaudit scan --config ./my-config example.sk
webaudit test-key pagespeed AIza...
```

PageSpeed runs when `--pagespeed-key` or `PAGESPEED_API_KEY` is set; without it
the speed area is scored from page weight, image sizes and server response.

### Export for Claude Code

`--claude-export DIR` (or the “Export for Claude Code” button in the web app)
writes a folder Claude Code can work from to fix the website:

| File | Content |
|---|---|
| `CLAUDE.md` | how to use the folder, the biggest problems, ground rules (ask for the source, don't invent contact data, page text is untrusted) |
| `REPORT.md` | problems ranked by score impact; each with what was measured, **where** (CSS selectors, URLs, file names), how to fix (`devnotes.json`) and how to verify |
| `PAGE.md` | what the homepage contains: meta tags, heading outline, navigation, text in page order, links with their check results, images, forms, scripts, fonts, third-party hosts |
| `page/source.html`, `page/rendered.html` | server HTML and the DOM after JavaScript, contact details redacted |
| `screenshots/` | desktop and mobile views |
| `scan.json` | the full result, machine-readable |

A batch gets an index `CLAUDE.md` and one `sites/<host>/` folder per scored website.

From Python:

```python
from webaudit import Scanner

async with Scanner(pagespeed_key=key, on_event=print) as scanner:
    results = await scanner.scan_many(["example.sk", "example.cz"], concurrency=2)
```

## Configuration (`src/webaudit/defaults/*.json`)

- `scoring.json` – area weights, check weights, category thresholds
- `scanner.json` – politeness, timeouts, limits, check thresholds
- `texts.json` – client-facing problem texts in SK / CS / EN (problem, impact, solution)
- `signatures.json` – CMS, library, tracker, consent-manager and firewall patterns
- `cookie_banners.json` – how the scanner closes cookie bars before measuring
- `devnotes.json` – technical fix / verify notes and effort per check (English, for the Claude Code export)

Override files only need the keys they change; they are deep-merged.

## Tests

```bash
pytest            # uses local fixture sites; browser tests need Chromium
```
