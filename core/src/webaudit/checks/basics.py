from __future__ import annotations

from ..context import ScanContext
from ..models import Area, Status
from . import check, na, result

A = Area.BASICS


@check("basics.https", A)
def https(ctx: ScanContext):
    if ctx.is_https:
        return result("basics.https", A, Status.PASS, "Site loads over HTTPS", value=True)
    return result("basics.https", A, Status.FAIL, "Site is served over plain HTTP", value=False)


@check("basics.ssl_valid", A)
def ssl_valid(ctx: ScanContext):
    if not ctx.is_https:
        return na("basics.ssl_valid", A, "No HTTPS, nothing to verify")
    tls = ctx.home.tls
    if tls is None:
        return na("basics.ssl_valid", A, "Certificate details unavailable")
    if not tls.valid:
        return result("basics.ssl_valid", A, Status.FAIL, f"Invalid certificate: {tls.error}", value={"error": tls.error})
    value = {"days_left": tls.days_left, "issuer": tls.issuer}
    if tls.days_left is not None and tls.days_left < ctx.t("ssl_expiry_warn_days"):
        return result("basics.ssl_valid", A, Status.WARN, f"Certificate expires in {tls.days_left} days", value=value)
    return result("basics.ssl_valid", A, Status.PASS, "Certificate is valid", value=value)


@check("basics.http_redirect", A)
def http_redirect(ctx: ScanContext):
    if not ctx.is_https:
        return na("basics.http_redirect", A, "No HTTPS version to redirect to")
    probe = ctx.http_probe
    if probe is None:
        return na("basics.http_redirect", A, "HTTP version not tested")
    if probe.status is None:
        return result("basics.http_redirect", A, Status.WARN, f"http:// address does not respond ({probe.error})", value=None)
    if probe.final_url.startswith("https://"):
        return result("basics.http_redirect", A, Status.PASS, "http:// redirects to https://", value=True)
    return result("basics.http_redirect", A, Status.FAIL, "http:// serves the page without redirecting to https://", value=False)
