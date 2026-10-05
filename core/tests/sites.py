"""Fixture websites served locally (the test environment has no internet).

``modern`` follows current good practice; ``legacy`` reproduces the problems a
typical 2010 small-business site has; ``cloudflare`` answers with a challenge;
``robots`` forbids crawling.
"""

from __future__ import annotations

from datetime import date

YEAR = date.today().year

MODERN_CSS = """
*{box-sizing:border-box} body{margin:0;font:17px/1.6 Inter,Arial,sans-serif;color:#1d232b;background:#fff}
header,main,footer{max-width:1100px;margin:0 auto;padding:16px}
nav a{display:inline-block;padding:12px 16px;min-height:48px}
.btn{display:inline-block;padding:14px 24px;background:#0f6e64;color:#fff;border-radius:8px}
img{max-width:100%;height:auto}
@media (max-width:600px){nav a{display:block}}
"""

MODERN_HOME = f"""<!doctype html>
<html lang="sk"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kaderníctvo Lena Trnava – strihy, farbenie a účesy</title>
<meta name="description" content="Kaderníctvo v centre Trnavy. Dámske a pánske strihy, farbenie a svadobné účesy. Objednajte sa online alebo telefonicky.">
<meta property="og:title" content="Kaderníctvo Lena Trnava"><meta property="og:description" content="Strihy a farbenie v centre Trnavy">
<meta property="og:image" content="/img/og.jpg">
<link rel="icon" href="/favicon.png"><link rel="stylesheet" href="/style.css">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"HairSalon","name":"Kaderníctvo Lena",
"address":{{"@type":"PostalAddress","streetAddress":"Hlavná 12","postalCode":"917 01","addressLocality":"Trnava"}}}}</script>
</head><body>
<header><nav><a href="/">Domov</a><a href="/sluzby">Služby</a><a href="/cennik">Cenník</a><a href="/kontakt">Kontakt</a></nav>
<a class="btn" href="tel:+421905123456">Zavolajte nám</a></header>
<main><h1>Kaderníctvo v centre Trnavy</h1>
<p>Strihy, farbenie a svadobné účesy. Objednajte sa telefonicky alebo e-mailom na info@lena-example.sk.</p>
<img src="/img/salon.jpg" alt="Interiér kaderníctva" width="600" height="400">
<p>Hlavná 12, 917 01 Trnava · <a href="https://maps.google.com/?q=Hlavna+12+Trnava">Navigovať</a></p>
<form><label for="name">Meno</label><input id="name" name="name"><button type="submit">Odoslať</button></form>
</main>
<footer><p>© {YEAR} Kaderníctvo Lena · <a href="https://www.facebook.com/kadernictvo.lena">Facebook</a></p></footer>
</body></html>"""

MODERN_SUBPAGE = """<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Kontakt – Kaderníctvo Lena</title></head>
<body><h1>Kontakt</h1><p>Telefón: <a href="tel:+421905123456">0905 123 456</a></p></body></html>"""

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>/</loc></url></urlset>"""

LEGACY_HOME = """<html><head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>Home</title>
<script src="/js/jquery-1.8.3.min.js"></script>
<script async src="/www.google-analytics.com/ga.js"></script>
<style>body,td{font-family:Verdana;font-size:11px;color:#aaaaaa;background:#ffffff}
h2{font-family:Georgia} .a{font-family:Tahoma} .b{font-family:"Comic Sans MS"} .c{font-family:Impact} .d{font-family:Courier}</style>
</head><body bgcolor="#ffffff">
<center>
<table width="980" border="0" cellpadding="0" cellspacing="0" bgcolor="#eeeeee">
<tr><td><img src="/img/logo.gif"><table><tr><td><a href="/onas">O nás</a> | <a href="/stara-stranka">Akcie</a> | <a href="/galeria">Galéria</a></td></tr></table></td></tr>
<tr><td><font size="2">Vitajte na stránke nášho autoservisu. Opravujeme všetky značky.</font>
<marquee>Akcia: prezutie pneumatík za výhodnú cenu!</marquee>
<p class="a">Servis osobných aj úžitkových vozidiel, pneuservis, diagnostika. Sme tu pre vás už od roku 1998 a radi vám poradíme s akoukoľvek opravou.</p>
<p class="b">Otvorené Po–Pia 8:00–17:00.</p><p class="c">Tel: 0905 123 456</p><p class="d">Diagnostika všetkých značiek.</p>
<h2>Kontaktujte nás</h2>
<form><input type="text" name="q"><input type="submit" value="Hľadať"></form>
<a href="https://facebook.com/"><i class="fa fa-facebook"></i></a>
</font></td></tr>
<tr><td><div id="footer">Copyright © 2012 Autoservis Novák</div></td></tr>
</table></center>
</body></html>"""

LEGACY_SUBPAGE = """<html><head><title>O nás</title></head><body><p>O nás</p></body></html>"""

JQUERY_183 = "window.jQuery = window.$ = {fn: {jquery: '1.8.3'}};"

CLOUDFLARE_CHALLENGE = """<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title></head>
<body><div id="challenge-platform"></div><noscript>Enable JavaScript and cookies to continue</noscript></body></html>"""

# A hostile page: once the browser renders it, it tries to reach an internal
# service through redirects (iframe, image), a WebSocket and a direct fetch.
ATTACKER_HOME = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Regular business site</title></head>
<body><h1>Welcome</h1>
<iframe src="/redir-frame" width="600" height="200" title="frame"></iframe>
<img src="/redir-img" alt="photo" width="10" height="10">
<script>
try { new WebSocket("ws://{internal_hostport}/ws"); } catch (e) {}
fetch("{internal}/fetch", {mode: "no-cors"}).catch(() => {});
</script>
</body></html>"""

# path -> (status, headers, body)
Route = tuple[int, dict[str, str], bytes | str]

HTML = {"Content-Type": "text/html; charset=utf-8"}

SITES: dict[str, dict[str, Route]] = {
    "modern": {
        "/": (200, HTML, MODERN_HOME),
        "/style.css": (200, {"Content-Type": "text/css"}, MODERN_CSS),
        "/kontakt": (200, HTML, MODERN_SUBPAGE),
        "/sluzby": (200, HTML, MODERN_SUBPAGE.replace("Kontakt", "Služby")),
        "/cennik": (200, HTML, MODERN_SUBPAGE.replace("Kontakt", "Cenník")),
        "/robots.txt": (200, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow: /admin/\nSitemap: {origin}/sitemap.xml\n"),
        "/sitemap.xml": (200, {"Content-Type": "application/xml"}, SITEMAP),
        "/favicon.png": (200, {"Content-Type": "image/png"}, b"\x89PNG\r\n\x1a\n"),
        "/img/salon.jpg": (200, {"Content-Type": "image/jpeg"}, b"\xff\xd8\xff" + b"0" * 2048),
        "/img/og.jpg": (200, {"Content-Type": "image/jpeg"}, b"\xff\xd8\xff"),
    },
    "legacy": {
        "/": (200, {"Content-Type": "text/html"}, LEGACY_HOME),
        "/onas": (200, {"Content-Type": "text/html"}, LEGACY_SUBPAGE),
        "/galeria": (200, {"Content-Type": "text/html"}, LEGACY_SUBPAGE),
        "/js/jquery-1.8.3.min.js": (200, {"Content-Type": "application/javascript"}, JQUERY_183),
        "/img/logo.gif": (200, {"Content-Type": "image/gif"}, b"GIF89a\x10\x00\x10\x00" + b"\x00" * 400_000),
    },
    "cloudflare": {
        "/": (
            403,
            {"Content-Type": "text/html", "Server": "cloudflare", "CF-RAY": "8a1b2c3d4e5f-VIE", "cf-mitigated": "challenge"},
            CLOUDFLARE_CHALLENGE,
        ),
    },
    "attacker": {
        "/": (200, HTML, ATTACKER_HOME),
        "/redir-frame": (302, {"Location": "{internal}/secret"}, ""),
        "/redir-img": (302, {"Location": "{internal}/img.png"}, ""),
    },
    "internal": {
        "/secret": (200, HTML, "<h1>INTERNAL SECRET</h1>"),
    },
    "robots": {
        "/": (200, HTML, MODERN_HOME),
        "/robots.txt": (200, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow: /\n"),
    },
}
