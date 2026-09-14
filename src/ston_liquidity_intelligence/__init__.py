"""STON.fi Liquidity & Execution Analytics.

A Python service that connects to the STON.fi public HTTP API, collects market
and liquidity data, uses swap simulation to measure execution conditions across
different trade sizes and exposes the results through a report, a REST API and
a lightweight dashboard.
"""

__version__ = "0.1.0"

from .client import StonApiClient, StonApiError
from .models import Asset, Pool, Router, SwapSimulation
from .config import Settings

__all__ = [
    "__version__",
    "StonApiClient",
    "StonApiError",
    "Asset",
    "Pool",
    "Router",
    "SwapSimulation",
    "Settings",
]