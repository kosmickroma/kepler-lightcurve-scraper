"""
Shape Features (Domain 5) - 8 features

These capture excursion behavior and shape characteristics.
Focus on peaks, dips, and crossing patterns.
"""

import numpy as np
from typing import Dict, Tuple


def extract_shape_features(
    flux: np.ndarray,
    time: np.ndarray,
) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract 8 shape and excursion features from light curve.

    Args:
        flux: Normalized flux array
        time: Time array (BJD, days) - not used but kept for API consistency

    Returns:
        Tuple of (features dict, validity dict)

    Features:
        shape_n_high_excursions, shape_n_low_excursions,
        shape_max_excursion_up, shape_max_excursion_down,
        shape_asymmetry, shape_max_consecutive_up,
        shape_max_consecutive_down, shape_crossing_rate
    """
    features = {}
    validity = {}

    n_points = len(flux)

    # Check minimum requirements
    if n_points < 30:
        for key in [
            'shape_n_high_excursions', 'shape_n_low_excursions',
            'shape_max_excursion_up', 'shape_max_excursion_down',
            'shape_asymmetry', 'shape_max_consecutive_up',
            'shape_max_consecutive_down', 'shape_crossing_rate'
        ]:
            features[key] = None
            validity[key] = False
        return features, validity

    try:
        # Compute robust statistics
        median_val = np.median(flux)
        mad_val = np.median(np.abs(flux - median_val))

        # Convert MAD to standard deviation equivalent
        # For normal distribution: std ≈ 1.4826 * MAD
        mad_to_std = 1.4826
        robust_std = mad_val * mad_to_std

        if robust_std == 0:
            # Perfectly flat light curve
            for key in [
                'shape_n_high_excursions', 'shape_n_low_excursions',
                'shape_max_excursion_up', 'shape_max_excursion_down',
                'shape_asymmetry', 'shape_max_consecutive_up',
                'shape_max_consecutive_down', 'shape_crossing_rate'
            ]:
                features[key] = 0.0 if 'max' in key or 'asymmetry' in key else 0
                validity[key] = True
            return features, validity

        # Compute excursions in units of robust std
        excursions = (flux - median_val) / robust_std

        # Count high excursions (>3σ above median)
        high_excursions = np.sum(excursions > 3.0)
        features['shape_n_high_excursions'] = int(high_excursions)
        validity['shape_n_high_excursions'] = True

        # Count low excursions (>3σ below median)
        low_excursions = np.sum(excursions < -3.0)
        features['shape_n_low_excursions'] = int(low_excursions)
        validity['shape_n_low_excursions'] = True

        # Maximum excursions
        features['shape_max_excursion_up'] = float(np.max(excursions))
        features['shape_max_excursion_down'] = float(-np.min(excursions))  # Positive value
        validity['shape_max_excursion_up'] = True
        validity['shape_max_excursion_down'] = True

        # Asymmetry (ratio of up to down excursions)
        if low_excursions > 0:
            features['shape_asymmetry'] = float(high_excursions / low_excursions)
        else:
            features['shape_asymmetry'] = float(high_excursions + 1.0)  # If no dips, asymmetric
        validity['shape_asymmetry'] = True

        # Consecutive runs above/below median
        above_median = flux > median_val

        # Find consecutive runs
        def max_consecutive_run(boolean_array):
            """Find longest consecutive True run."""
            if len(boolean_array) == 0:
                return 0

            max_run = 0
            current_run = 0

            for val in boolean_array:
                if val:
                    current_run += 1
                    max_run = max(max_run, current_run)
                else:
                    current_run = 0

            return max_run

        features['shape_max_consecutive_up'] = int(max_consecutive_run(above_median))
        features['shape_max_consecutive_down'] = int(max_consecutive_run(~above_median))
        validity['shape_max_consecutive_up'] = True
        validity['shape_max_consecutive_down'] = True

        # Crossing rate (how often flux crosses median)
        if n_points > 1:
            crossings = np.sum(above_median[:-1] != above_median[1:])
            features['shape_crossing_rate'] = float(crossings / (n_points - 1))
        else:
            features['shape_crossing_rate'] = 0.0
        validity['shape_crossing_rate'] = True

    except Exception:
        # If any error, mark all as invalid
        for key in [
            'shape_n_high_excursions', 'shape_n_low_excursions',
            'shape_max_excursion_up', 'shape_max_excursion_down',
            'shape_asymmetry', 'shape_max_consecutive_up',
            'shape_max_consecutive_down', 'shape_crossing_rate'
        ]:
            features[key] = None
            validity[key] = False

    return features, validity
