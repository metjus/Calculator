# Design system – direction B “Petrol”

The visual direction chosen in stage 2 ([mockups](../docs/DESIGN-DIRECTIONS.md)).
Calm, warm-neutral surfaces, one petrol accent, a graphite sidebar, light
300-weight numbers for metrics. Tokens live in `src/styles/tokens.css`,
component styles in `src/styles/app.css`, React components in
`src/components/ui.tsx`.

**Rules**

1. Components use **role tokens** (`--surface`, `--text-2`, `--accent` …), never raw hex.
   The only exception is Leaflet shapes in `MapPreview.tsx`, which need literal colours.
2. Dark mode is **designed, not inverted**: every role has its own dark value.
3. Colour never carries meaning alone: score badges show the number and the
   word, status tags have a text label, log lines have an icon with a label.
4. One accent. Status colours appear only on small marks (dots, badge borders, icons).
5. No emoji, gradients, glass or heavy shadows. Lucide icons at 16/18 px.

## Tokens

### Colour roles

| Role | Light | Dark | Use |
|---|---|---|---|
| `--page` | `#f3f1ec` | `#101211` | App background |
| `--surface` | `#fffdf9` | `#181b1a` | Cards, inputs, popovers |
| `--surface-2` | `#f7f4ee` | `#1e2221` | Hover rows, expanded detail, segmented track |
| `--border` / `--border-strong` | `#e2ddd4` / `#cbc4b8` | `#2a2f2d` / `#3a403d` | Dividers / control outlines |
| `--text` / `--text-2` / `--muted` | `#1d1b18` / `#57524a` / `#6e685f` | `#eeebe4` / `#c2bcb2` / `#9a948a` | Primary / secondary / hints, timestamps |
| `--accent` (+ `-hover`, `-weak`) | `#0b6e72` | `#4fb8b3` | Primary buttons, links, focus, progress |
| `--on-accent` | `#ffffff` | `#06201f` | Text on accent |
| `--track` / `--neutral` | `#ebe7df` / `#cdc7bc` | `#242826` / `#3d4240` | Progress track / “waiting” dots |
| `--side*` | graphite `#1e2220` | `#0a0c0b` | Sidebar in both modes |

### Score categories (validated)

Adjacent categories differ in lightness, not only hue, so they stay distinct for
colour-blind users and in greyscale print.

| Category | Score | Light | Dark |
|---|---|---|---|
| Critical | 0–39 | `--crit` `#9b1111` | `#c92a4a` |
| Weak | 40–59 | `--weak` `#cb5a1a` | `#ec8329` |
| OK | 60–79 | `--ok` `#daa932` | `#f5d862` |
| Good | 80–100 | `--good` `#17a478` | `#2fb08a` |

Feedback roles: `--danger`, `--warning`, `--success` with `-weak` tints for banners.

### Type, space, shape

| Token | Value |
|---|---|
| Font | IBM Plex Sans 300/400/500/600, self-hosted (`@fontsource`, no Google Fonts request) |
| Page title | 30 px / 500 · section (card) title: 12 px / 600 uppercase, letter-spacing 0.08 em |
| Eyebrow | 11 px / 500 uppercase, `--muted` |
| Body | 14 px / 400, line-height 1.5 · hints 13 px |
| Metric numbers | 44 px / 300, tabular figures (`.num`) |
| Spacing | 4-px scale `--space-1…10`; cards pad 20/24 px; grid gap 20 px |
| Radius | `--radius` 6 px, `--radius-sm` 4 px |
| Control height | `--control-h` 44 px (touch target) |
| Motion | `--fast` 120 ms, `--ease` |

## Components

| Component | Variants / props | States | Accessibility |
|---|---|---|---|
| `Button` | `variant`: primary · secondary (default) · ghost · danger; `size`: md · sm; `icon`; icon-only when no children | hover, focus ring, disabled, `loading` (spinner, `aria-busy`) | Icon-only buttons need `aria-label` |
| `Field` | `label`, `hint`, `error`; render-prop `(id, describedBy)` | error text in `--danger` with `role="alert"` | Label bound with `htmlFor`; hint/error via `aria-describedby` |
| `TextInput`, `Select`, `TextArea` | native props | focus: accent outline; disabled: muted | Native semantics |
| `Checkbox` | `label`, `hint` | disabled greys label | Real `<input type="checkbox">` inside `<label>` |
| `Segmented` | `options`, `value`, `label` | active option on `--surface` | `role="group"`, buttons with `aria-pressed` |
| `Card` | `title`, `meta` (right side), `id` | – | `<section>` labelled by its title when `id` is given |
| `PageHeader` | `eyebrow`, `title`, `sub`, `actions` | – | One `<h1>` per page |
| `ScoreBadge` | `score`, `category` | “—” when not scored | Number + category word |
| `Tag` | `color` (dot) | – | Text always present |
| `ProgressBar` | `value`, `max`, `label` | – | `role="progressbar"` with values |
| `Banner` | `kind`: info · warn · error · success | – | `role="status"`, errors `role="alert"` |
| Toasts (`useToast`) | ok · error | auto-dismiss 5 s | `aria-live="polite"` region |
| `EmptyState` | `icon`, `title`, text, `action` | – | Explains what to do next and offers the button |
| `AreaCombobox` | country-restricted autocomplete | loading, empty, error | ARIA combobox: ↑/↓, Enter, Esc, `aria-activedescendant` |
| `MapPreview` | radius circle or region box | placeholder until an area is chosen | `role="img"` with a text label; scroll-zoom off |
| Live log (`AuditRun`) | levels ok · warn · error · info | auto-scrolls only when already at the bottom | Icon has a text label; times in `<time>` |

## Patterns

- **Page**: sidebar (Dashboard, Search, Audits, Customers, Settings) + main
  area with `PageHeader`, actions top-right, content in cards. Collapses to one
  column below 900 px; the live audit view goes two-column from 1280 px. Usable
  from 1024 px laptops to large monitors.
- **Forms**: label above control, hint below, primary action bottom-left.
  Two-column `form-grid` on wide cards.
- **Tables**: uppercase 11 px headers, 1 px row dividers, clickable rows get
  `surface-2` on hover and a real link or button inside for keyboard users.
  Wide tables scroll inside `.table-box`, never the page.
- **Feedback**: inline `Banner` for state that persists (missing key, estimate,
  errors), toast for confirmations after an action.
- **Empty states** always say what is missing and offer the next step
  (“No audits yet – start the first one”).

## Do / don’t

| Do | Don’t |
|---|---|
| Use `var(--accent)` for the one main action per view | Put two primary buttons side by side |
| Show missing configuration as a sentence with a link to Settings | Hide or crash a feature because a key is missing |
| Label every number (“2 websites not scored”) | Show bare numbers or colours without text |
| Keep client-facing wording hedged and without invented figures | Promise results (“+30 % sales”) in UI or reports |
