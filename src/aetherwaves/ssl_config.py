"""SSL CA Bundle and HTTPS configuration for NASA SVS and external services."""
from __future__ import annotations

import os
import ssl
from pathlib import Path


def get_ca_bundle_path() -> str | None:
    """Return the path to the bundled NASA CA bundle or certifi."""
    bundle = Path(__file__).resolve().parent / "nasa_ca_bundle.pem"
    if bundle.is_file():
        return str(bundle)
    try:
        import certifi
        return certifi.where()
    except Exception:
        return None


def get_ssl_context() -> ssl.SSLContext:
    """Create an SSLContext trusting the bundled CAs including NASA SVS intermediates."""
    ca_path = get_ca_bundle_path()
    if ca_path:
        return ssl.create_default_context(cafile=ca_path)
    return ssl.create_default_context()


def configure_global_ssl() -> None:
    """Configure default SSL context and environment variables globally."""
    ca_path = get_ca_bundle_path()
    if ca_path:
        os.environ.setdefault("SSL_CERT_FILE", ca_path)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
        try:
            ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=ca_path)
        except Exception:
            pass


# Execute on module import
configure_global_ssl()
