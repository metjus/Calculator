"""webaudit: polite website auditing core (no GUI dependencies)."""

__version__ = "0.1.0"

from .config import Config  # noqa: E402
from .models import ScanResult, SiteState, Status  # noqa: E402
from .scanner import Scanner, scan_url  # noqa: E402

__all__ = ["Config", "ScanResult", "Scanner", "SiteState", "Status", "scan_url", "__version__"]
