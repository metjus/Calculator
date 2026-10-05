# Dashboard visual directions (stage 2 decision)

Mockups: https://claude.ai/artifact/XNpkDPAPZ5i6J5KfEWPFU3 (one artboard per direction, light mode on top, dark below).
The brief asks to pick one before any UI code is written. The chosen direction's tokens become the web app's theme.

All three share the information architecture from the brief: sidebar (Dashboard, Search, Audits, Customers with
follow-up badge, Settings), page title with actions top-right, 4 metric cards, score-category donut with the number
in the centre, most-common-problems bars, HTTPS / mobile / CMS donuts (CMS = top 5 + other), a separate
"Check manually" list (Cloudflare / not loaded / robots), and the worst-first table with search and filters.
Icons are Lucide (inline stroke SVG), no emoji, no gradients, no glass, no heavy shadows.

| | A · Cobalt | B · Petrol | C · Plum |
|---|---|---|---|
| Feel | calm, precise, product-like | grounded, editorial, B2B | warm, personal, boutique |
| Font | Geist | IBM Plex Sans | Schibsted Grotesk |
| Accent (light / dark) | `#2346d0` / `#7b96ff` | `#0b6e72` / `#4fb8b3` | `#7a2f6b` / `#d68ac6` |
| Page / surface (light) | `#f5f6f8` / `#ffffff` | `#f3f1ec` / `#fffdf9` | `#f6f1eb` / `#fffcf8` |
| Page / surface (dark) | `#0d1016` / `#151922` | `#101211` / `#181b1a` | `#141116` / `#1d1920` |
| Shape | 10 px radius, 1 px borders | 6 px radius, joined metric strip, dark graphite sidebar | 18 px radius, pill buttons and nav, filled hero metric |
| Trade-off | safest, but the most generic of the three | petrol accent sits near the “Good” green in hue (they differ in lightness) | most memorable, but rounder and softer than a “tool” usually looks |

## Score-category colours (shared by all directions)

Validated with the dataviz palette validator (`validate_palette.js`). Adjacent categories differ in lightness, so
charts survive greyscale and black-and-white printing; every use carries a text label as well.

| Category | Light | Dark |
|---|---|---|
| Critical | `#9b1111` | `#c92a4a` |
| Weak | `#cb5a1a` | `#ec8329` |
| OK | `#daa932` | `#f5d862` |
| Good | `#17a478` | `#2fb08a` |

- Light, all pairs: worst colour-blind ΔE 10.0, worst normal-vision ΔE 16.8, all hard gates pass. OK yellow sits
  under 3:1 on white, so it always appears with a visible label.
- Dark, in donut ring order: worst colour-blind ΔE 12.4, normal-vision ΔE 20.1, every colour ≥ 3:1 on `#17181b`.
  These are status colours, so they sit outside the categorical lightness band by design.

Binary donuts (HTTPS, mobile) colour only the problem share (Critical colour); the rest is a neutral grey.
The CMS donut uses a single-hue ramp of the accent, so it does not compete with the category colours.
Bars use the accent.
