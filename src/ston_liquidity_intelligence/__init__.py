"""STON.fi Liquidity & Execution Intelligence Engine.

A Python-based service that connects to STON.fi's public HTTP API, collects
market and liquidity data, uses swap simulation to evaluate execution quality
across trade sizes and publishes structured analytics through a report, a REST
API and a lightweight dashboard.
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