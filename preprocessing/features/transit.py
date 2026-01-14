"""
Transit Features (Domain 6) - 7 features

These characterize transit-like periodic dip signals using BLS.
Note: These are OPTIONAL features - NULL if no transit detected.
"""

import numpy as np
from typing import Dict, Tuple
from astropy.timeseries import BoxLeastSquares


def extract_transit_features(
    flux: np.ndarray,
    time: np.ndarray,
) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract 7 transit-specific features using BLS algorithm.

    Args:
        flux: Normalized flux array
        time: Time array (BJD, days)

    Returns:
        Tuple of (features dict, validity dict)

    Features:
        transit_bls_power, transit_bls_period, transit_bls_depth,
        transit_bls_duration, transit_n_detected,
        transit_depth_consistency, transit_timing_consistency

    Note:
        These features are OPTIONAL per project rules.
        If no transit detected or requirements not met, all = NULL.
    """
    features = {}
    validity = {}

    n_points = len(flux)
    duration = time[-1] - time[0]

    # Check minimum requirements
    if n_points < 500 or duration < 30:
        for key in [
            'transit_bls_power', 'transit_bls_period', 'transit_bls_depth',
            'transit_bls_duration', 'transit_n_detected',
            'transit_depth_consistency', 'transit_timing_consistency'
        ]:
            features[key] = None
            validity[key] = False
        return features, validity

    try:
        # Run BLS
        model = BoxLeastSquares(time, flux)

        # Period search range
        min_period = max(0.3, 2 * np.median(np.diff(time)))  # At least 2 cadences
        max_period = duration / 3.0  # At least 3 transits in baseline

        # Duration search (1-12 hours typical)
        durations = np.linspace(0.04, 0.5, 15)  # 1 hour to 12 hours

        # Run BLS periodogram
        periodogram = model.autopower(
            durations,
            minimum_period=min_period,
            maximum_period=max_period,
            frequency_factor=2.0,  # Moderate resolution for speed
        )

        # Best-fit parameters
        period = periodogram.period[np.argmax(periodogram.power)]
        power = np.max(periodogram.power)
        t0 = periodogram.transit_time[np.argmax(periodogram.power)]
        duration = periodogram.duration[np.argmax(periodogram.power)]
        depth = periodogram.depth[np.argmax(periodogram.power)]

        features['transit_bls_power'] = float(power)
        features['transit_bls_period'] = float(period)
        features['transit_bls_depth'] = float(abs(depth))
        features['transit_bls_duration'] = float(duration)
        validity['transit_bls_power'] = True
        validity['transit_bls_period'] = True
        validity['transit_bls_depth'] = True
        validity['transit_bls_duration'] = True

        # Count number of transits detected
        # Fold at best period and look for consistent dips
        n_transits = int(duration / period)
        features['transit_n_detected'] = max(0, n_transits)
        validity['transit_n_detected'] = True

        # Transit depth consistency
        # Phase fold and measure depth variation
        try:
            phase = ((time - t0) % period) / period
            in_transit = (phase < duration / period) | (phase > 1 - duration / period)

            if np.sum(in_transit) > 5:
                transit_depths = flux[in_transit]
                depth_std = np.std(transit_depths)
                depth_mean = np.mean(transit_depths)

                if abs(depth_mean) > 0:
                    features['transit_depth_consistency'] = float(depth_std / abs(depth_mean))
                else:
                    features['transit_depth_consistency'] = 0.0
            else:
                features['transit_depth_consistency'] = None
                validity['transit_depth_consistency'] = False

            validity['transit_depth_consistency'] = True
        except Exception:
            features['transit_depth_consistency'] = None
            validity['transit_depth_consistency'] = False

        # Transit timing consistency (TTV measure)
        # Measure deviations from predicted transit times
        try:
            # Find individual transit events
            transit_mask = in_transit.copy()

            # Expected transit times
            n_expected = int((time[-1] - t0) / period)
            expected_times = t0 + np.arange(n_expected + 1) * period
            expected_times = expected_times[
                (expected_times >= time[0]) & (expected_times <= time[-1])
            ]

            if len(expected_times) > 2:
                # This is a simplified TTV - full calculation requires
                # fitting each transit individually
                # For now, use RMS of phase jitter as proxy
                phase_residual = np.std((time[in_transit] - t0) % period)
                features['transit_timing_consistency'] = float(phase_residual * 24 * 60)  # minutes
            else:
                features['transit_timing_consistency'] = None
                validity['transit_timing_consistency'] = False

            validity['transit_timing_consistency'] = True
        except Exception:
            features['transit_timing_consistency'] = None
            validity['transit_timing_consistency'] = False

        # If BLS power is low, mark all transit features as NULL
        # (no significant transit detected)
        if power < 0.05:  # Threshold for "significant" transit
            for key in features.keys():
                features[key] = None
                validity[key] = False

    except Exception:
        # If BLS fails entirely, mark all as invalid
        for key in [
            'transit_bls_power', 'transit_bls_period', 'transit_bls_depth',
            'transit_bls_duration', 'transit_n_detected',
            'transit_depth_consistency', 'transit_timing_consistency'
        ]:
            features[key] = None
            validity[key] = False

    return features, validity
