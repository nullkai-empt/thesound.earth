"""AetherWaves adapter package — one adapter per data source."""
from .base import AdapterBase, load_land_regions
from .oscar import OscarAdapter
from .video import VideoAdapter
from .fires import FIRMSAdapter
from .canopy import CanopyAdapter

__all__ = [
    "AdapterBase",
    "load_land_regions",
    "OscarAdapter",
    "VideoAdapter",
    "FIRMSAdapter",
    "CanopyAdapter",
]
