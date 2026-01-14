"""
XENOSCAN Preprocessing Package

Production-grade async data acquisition and preprocessing pipeline.
"""

import warnings
from astropy.utils.exceptions import AstropyWarning

# Suppress noisy warnings that flood logs
# (Quality mask warnings, cadence warnings - these are expected for Kepler data)
warnings.simplefilter("ignore", AstropyWarning)
warnings.simplefilter("ignore", UserWarning)

__version__ = "1.0.0"


class XenoscanError(Exception):
    """Base exception for XENOSCAN."""
    pass


class DownloadError(XenoscanError):
    """Download operation failed."""
    pass


class RateLimitError(XenoscanError):
    """Rate limit exceeded."""
    pass


class CheckpointError(XenoscanError):
    """Checkpoint save/load failed."""
    pass


class FeatureExtractionError(XenoscanError):
    """Feature extraction failed."""
    pass
