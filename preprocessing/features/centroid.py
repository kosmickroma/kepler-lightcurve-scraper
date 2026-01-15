"""
Centroid Features

Centroid jitter/variance helps distinguish "fake quiet" stars where the telescope
was shaking vs truly quiet stars. If a star looks quiet but the centroid moved
significantly, it may indicate instrumental issues or blended sources.
"""

import numpy as np
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

def extract_centroid_features(lc, **kwargs) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract centroid-based features.

    Args:
        lc: Lightkurve LightCurve object

    Returns:
        Tuple of (features dict, validity dict)
    """
    features = {}
    validity = {}

    try:
        # Check if centroid columns exist (Kepler has MOM_CENTR1, MOM_CENTR2)
        has_centr1 = 'MOM_CENTR1' in lc.columns if hasattr(lc, 'columns') else False
        has_centr2 = 'MOM_CENTR2' in lc.columns if hasattr(lc, 'columns') else False

        if has_centr1 and has_centr2:
            # Get centroid data
            centr_x = lc['MOM_CENTR1'].value
            centr_y = lc['MOM_CENTR2'].value

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

                logger.debug(f"Centroid features: jitter_mean={features['centroid_jitter_mean']:.6f}, "
                           f"jitter_std={features['centroid_jitter_std']:.6f}, "
                           f"jitter_max={features['centroid_jitter_max']:.6f}, "
                           f"rms={features['centroid_rms_motion']:.6f}")
            else:
                logger.warning("Insufficient centroid data (< 10 points)")
                features['centroid_jitter_mean'] = None
                features['centroid_jitter_std'] = None
                features['centroid_jitter_max'] = None
                features['centroid_rms_motion'] = None
                validity['centroid_jitter_mean'] = False
                validity['centroid_jitter_std'] = False
                validity['centroid_jitter_max'] = False
                validity['centroid_rms_motion'] = False
        else:
            # No centroid data available (TESS might not have it)
            logger.debug("No centroid columns found (mission may not provide this data)")
            features['centroid_jitter_mean'] = None
            features['centroid_jitter_std'] = None
            features['centroid_jitter_max'] = None
            features['centroid_rms_motion'] = None
            validity['centroid_jitter_mean'] = False
            validity['centroid_jitter_std'] = False
            validity['centroid_jitter_max'] = False
            validity['centroid_rms_motion'] = False

    except Exception as e:
        logger.error(f"Centroid feature extraction failed: {e}")
        features['centroid_jitter_mean'] = None
        features['centroid_jitter_std'] = None
        features['centroid_jitter_max'] = None
        features['centroid_rms_motion'] = None
        validity['centroid_jitter_mean'] = False
        validity['centroid_jitter_std'] = False
        validity['centroid_jitter_max'] = False
        validity['centroid_rms_motion'] = False

    return features, validity
