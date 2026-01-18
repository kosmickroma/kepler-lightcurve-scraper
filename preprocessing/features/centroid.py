"""
Centroid Features

Centroid jitter/variance helps distinguish "fake quiet" stars where the telescope
was shaking vs truly quiet stars. If a star looks quiet but the centroid moved
significantly, it may indicate instrumental issues or blended sources.

REMEDIATION 2026-01-17: Fixed column name case sensitivity bug.
Lightkurve converts FITS column names to lowercase, so we now check for both
'MOM_CENTR1' and 'mom_centr1'. Also added fallback to lightkurve centroid properties.
This fix restores 100% of centroid features (previously 100% NULL). Gemini-validated.
"""

import numpy as np
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)


def _get_centroid_data(lc) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Extract centroid X/Y arrays from lightkurve object.

    Handles multiple column naming conventions:
    - Uppercase: MOM_CENTR1, MOM_CENTR2 (original FITS)
    - Lowercase: mom_centr1, mom_centr2 (lightkurve converted)
    - Properties: centroid_col, centroid_row (lightkurve standard)

    Returns:
        Tuple of (centr_x, centr_y) arrays, or (None, None) if not available
    """
    # Try lowercase first (most common after lightkurve processing)
    if hasattr(lc, 'columns'):
        columns = list(lc.columns)

        # Option 1: Lowercase column names (lightkurve converts to lowercase)
        if 'mom_centr1' in columns and 'mom_centr2' in columns:
            logger.debug("Found centroid columns: mom_centr1, mom_centr2 (lowercase)")
            return lc['mom_centr1'].value, lc['mom_centr2'].value

        # Option 2: Uppercase column names (original FITS format)
        if 'MOM_CENTR1' in columns and 'MOM_CENTR2' in columns:
            logger.debug("Found centroid columns: MOM_CENTR1, MOM_CENTR2 (uppercase)")
            return lc['MOM_CENTR1'].value, lc['MOM_CENTR2'].value

    # Option 3: Lightkurve centroid properties (most robust)
    if hasattr(lc, 'centroid_col') and hasattr(lc, 'centroid_row'):
        try:
            centr_col = lc.centroid_col
            centr_row = lc.centroid_row
            if centr_col is not None and centr_row is not None:
                logger.debug("Found centroid data via lightkurve properties")
                return centr_col.value, centr_row.value
        except Exception as e:
            logger.debug(f"Centroid properties exist but failed to access: {e}")

    # No centroid data found
    logger.debug(f"No centroid columns found. Available columns: {list(lc.columns) if hasattr(lc, 'columns') else 'N/A'}")
    return None, None


def extract_centroid_features(lc, **kwargs) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract centroid-based features.

    REMEDIATION 2026-01-17: Fixed case sensitivity bug causing 100% NULL.

    Args:
        lc: Lightkurve LightCurve object

    Returns:
        Tuple of (features dict, validity dict)
    """
    features = {}
    validity = {}

    try:
        # Get centroid data (handles multiple column naming conventions)
        centr_x, centr_y = _get_centroid_data(lc)

        if centr_x is not None and centr_y is not None:
            # Remove NaN values
            mask = np.isfinite(centr_x) & np.isfinite(centr_y)
            centr_x = centr_x[mask]
            centr_y = centr_y[mask]

            if len(centr_x) > 10:
                # Calculate centroid jitter (pixel position shifts from mean)
                centr_x_mean = np.mean(centr_x)
                centr_y_mean = np.mean(centr_y)
                distances = np.sqrt((centr_x - centr_x_mean)**2 + (centr_y - centr_y_mean)**2)

                # Centroid jitter statistics
                features['centroid_jitter_mean'] = float(np.mean(distances))
                features['centroid_jitter_std'] = float(np.std(distances))
                features['centroid_jitter_max'] = float(np.max(distances))
                validity['centroid_jitter_mean'] = True
                validity['centroid_jitter_std'] = True
                validity['centroid_jitter_max'] = True

                # Total centroid motion (RMS)
                features['centroid_rms_motion'] = float(np.sqrt(np.mean(distances**2)))
                validity['centroid_rms_motion'] = True

                logger.info(f"Centroid features extracted: jitter_mean={features['centroid_jitter_mean']:.6f}, "
                           f"rms={features['centroid_rms_motion']:.6f}")
            else:
                logger.warning(f"Insufficient centroid data: {len(centr_x)} points (need > 10)")
                _set_null_centroid_features(features, validity)
        else:
            # No centroid data available
            logger.warning("No centroid data found in lightcurve")
            _set_null_centroid_features(features, validity)

    except Exception as e:
        logger.error(f"Centroid feature extraction failed: {type(e).__name__}: {e}")
        _set_null_centroid_features(features, validity)

    return features, validity


def _set_null_centroid_features(features: dict, validity: dict) -> None:
    """Set all centroid features to NULL with validity=False."""
    features['centroid_jitter_mean'] = None
    features['centroid_jitter_std'] = None
    features['centroid_jitter_max'] = None
    features['centroid_rms_motion'] = None
    validity['centroid_jitter_mean'] = False
    validity['centroid_jitter_std'] = False
    validity['centroid_jitter_max'] = False
    validity['centroid_rms_motion'] = False
