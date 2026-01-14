"""
Statistical Features (Domain 1) - 12 features

These capture the overall distribution properties of the flux values.
Fast, vectorized numpy operations.
"""

import numpy as np
from typing import Dict, Tuple
from scipy import stats


def extract_statistical_features(
    flux: np.ndarray,
    time: np.ndarray,
) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract 12 statistical distribution features from light curve.

    Args:
        flux: Normalized flux array
        time: Time array (BJD) - not used here but kept for API consistency

    Returns:
        Tuple of (features dict, validity dict)

    Features:
        stat_mean, stat_median, stat_std, stat_variance, stat_mad,
        stat_range, stat_iqr, stat_skewness, stat_kurtosis,
        stat_percentile_5, stat_percentile_95, stat_beyond_1sigma
    """
    features = {}
    validity = {}

    # Check minimum requirements
    n_points = len(flux)
    if n_points < 10:
        # Not enough data - all features invalid
        for key in [
            'stat_mean', 'stat_median', 'stat_std', 'stat_variance',
            'stat_mad', 'stat_range', 'stat_iqr', 'stat_skewness',
            'stat_kurtosis', 'stat_percentile_5', 'stat_percentile_95',
            'stat_beyond_1sigma'
        ]:
            features[key] = None
            validity[key] = False
        return features, validity

    # All features valid
    valid = True

    try:
        # Basic statistics (vectorized)
        mean_val = np.mean(flux)
        median_val = np.median(flux)
        std_val = np.std(flux, ddof=1)

        features['stat_mean'] = float(mean_val)
        features['stat_median'] = float(median_val)
        features['stat_std'] = float(std_val)
        features['stat_variance'] = float(std_val ** 2)

        # Robust statistics
        mad_val = np.median(np.abs(flux - median_val))
        features['stat_mad'] = float(mad_val)

        # Range and IQR
        features['stat_range'] = float(np.max(flux) - np.min(flux))

        q25, q75 = np.percentile(flux, [25, 75])
        features['stat_iqr'] = float(q75 - q25)

        # Shape statistics
        features['stat_skewness'] = float(stats.skew(flux))
        features['stat_kurtosis'] = float(stats.kurtosis(flux))

        # Percentiles
        features['stat_percentile_5'] = float(np.percentile(flux, 5))
        features['stat_percentile_95'] = float(np.percentile(flux, 95))

        # Beyond 1 sigma
        if std_val > 0:
            beyond_1sigma = np.sum(np.abs(flux - mean_val) > std_val) / n_points
            features['stat_beyond_1sigma'] = float(beyond_1sigma)
        else:
            features['stat_beyond_1sigma'] = 0.0

        # All features valid
        for key in features.keys():
            validity[key] = True

    except Exception as e:
        # If any error, mark all as invalid
        for key in features.keys():
            features[key] = None
            validity[key] = False

    return features, validity
