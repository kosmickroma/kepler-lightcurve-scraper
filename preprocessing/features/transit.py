"""
Transit Features (Domain 6) - 7 features + 2 physical validation features

These characterize transit-like periodic dip signals using BLS.
Note: These are OPTIONAL features - NULL if no transit detected.

SCIENTIFIC VALIDATION: Includes physical plausibility check
to identify false positives (eclipsing binaries masquerading as planets).
"""

import numpy as np
from typing import Dict, Tuple, Optional
from astropy.timeseries import BoxLeastSquares

# Physical constants for planet radius validation
R_JUPITER_R_EARTH = 11.2  # Jupiter radius in Earth radii
R_SUN_R_EARTH = 109.1     # Solar radius in Earth radii
MAX_PLANET_R_JUPITER = 2.0  # Maximum plausible planet radius in R_Jupiter


def extract_transit_features(
    flux: np.ndarray,
    time: np.ndarray,
    st_rad: Optional[float] = None,
) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract 10 transit-specific features using BLS algorithm.

    Args:
        flux: Normalized flux array
        time: Time array (BJD, days)
        st_rad: Stellar radius in solar radii (optional, for physical validation)

    Returns:
        Tuple of (features dict, validity dict)

    Features (7 original + 3 scientific validation):
        transit_bls_power, transit_bls_period, transit_bls_depth,
        transit_bls_duration, transit_n_detected,
        transit_depth_consistency, transit_timing_consistency,
        transit_implied_r_planet_rjup, transit_physically_plausible,
        transit_odd_even_consistent

    SCIENTIFIC VALIDATION:
        1. Physical plausibility: If st_rad is provided, calculates implied
           planet radius from transit depth and stellar radius. Flags as
           "not physically plausible" if implied R_planet > 2.0 R_Jupiter
           (likely eclipsing binary).

        2. Odd-even consistency: Compares odd vs even transit depths to
           detect eclipsing binaries (which have alternating depths due to
           two stars of different sizes/temperatures).

    Note:
        These features are OPTIONAL per project rules.
        If no transit detected or requirements not met, all = NULL.
    """
    features = {}
    validity = {}

    n_points = len(flux)
    duration = time[-1] - time[0]

    # All feature keys (7 original + 2 physical validation + 1 odd-even check)
    all_feature_keys = [
        'transit_bls_power', 'transit_bls_period', 'transit_bls_depth',
        'transit_bls_duration', 'transit_n_detected',
        'transit_depth_consistency', 'transit_timing_consistency',
        'transit_implied_r_planet_rjup', 'transit_physically_plausible',
        'transit_odd_even_consistent'  # Eclipsing binary detection
    ]

    # Check minimum requirements
    if n_points < 500 or duration < 30:
        for key in all_feature_keys:
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

        # SCIENTIFIC VALIDATION: Physical plausibility check
        # Calculate implied planet radius from transit depth and stellar radius
        # If R_planet > 2.0 R_Jupiter, it's likely an eclipsing binary, not a planet
        if st_rad is not None and st_rad > 0 and abs(depth) > 0:
            # Transit depth δ = (R_p / R_*)^2
            # R_p / R_* = sqrt(δ)
            # R_p = R_* × sqrt(δ) × R_sun_in_R_earth / R_jup_in_R_earth

            # Depth is in flux units (fraction), typically ~0.001-0.01 for planets
            transit_depth_fraction = abs(depth)

            # R_planet / R_star = sqrt(depth)
            r_planet_over_r_star = np.sqrt(transit_depth_fraction)

            # R_planet in Earth radii
            r_planet_r_earth = r_planet_over_r_star * st_rad * R_SUN_R_EARTH

            # R_planet in Jupiter radii
            r_planet_r_jupiter = r_planet_r_earth / R_JUPITER_R_EARTH

            features['transit_implied_r_planet_rjup'] = float(r_planet_r_jupiter)
            validity['transit_implied_r_planet_rjup'] = True

            # Physical plausibility: planets can't be larger than ~2 R_Jupiter
            # Larger objects are brown dwarfs or stellar companions
            if r_planet_r_jupiter <= MAX_PLANET_R_JUPITER:
                features['transit_physically_plausible'] = 1.0  # Boolean as float for DB
            else:
                features['transit_physically_plausible'] = 0.0
            validity['transit_physically_plausible'] = True
        else:
            # No stellar radius provided, can't calculate
            features['transit_implied_r_planet_rjup'] = None
            features['transit_physically_plausible'] = None
            validity['transit_implied_r_planet_rjup'] = False
            validity['transit_physically_plausible'] = False

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

        # SCIENTIFIC VALIDATION: Odd-even transit consistency check
        # Eclipsing binaries have alternating transit depths because two stars
        # of different sizes/temperatures are involved. Planets produce
        # consistent depths.
        try:
            # Get transit times based on period and t0
            n_transits_expected = int((time[-1] - t0) / period)
            transit_times = t0 + np.arange(n_transits_expected + 1) * period
            transit_times = transit_times[
                (transit_times >= time[0]) & (transit_times <= time[-1])
            ]

            if len(transit_times) >= 4:  # Need at least 2 odd and 2 even
                odd_depths = []
                even_depths = []

                for i, t_transit in enumerate(transit_times):
                    # Find points near this transit
                    transit_mask = np.abs(time - t_transit) < duration * 0.5
                    if np.sum(transit_mask) >= 3:
                        transit_flux = flux[transit_mask]
                        # Depth = 1 - min(flux) for dipping transits
                        transit_depth = 1.0 - np.min(transit_flux)

                        if i % 2 == 0:
                            even_depths.append(transit_depth)
                        else:
                            odd_depths.append(transit_depth)

                if len(odd_depths) >= 2 and len(even_depths) >= 2:
                    odd_mean = np.mean(odd_depths)
                    even_mean = np.mean(even_depths)
                    all_depths = odd_depths + even_depths
                    depth_std = np.std(all_depths)

                    if depth_std > 0:
                        # Difference in sigmas
                        diff_sigma = abs(odd_mean - even_mean) / depth_std

                        # If difference > 3 sigma, likely eclipsing binary
                        if diff_sigma <= 3.0:
                            features['transit_odd_even_consistent'] = 1.0  # Consistent = planet
                        else:
                            features['transit_odd_even_consistent'] = 0.0  # Inconsistent = binary
                        validity['transit_odd_even_consistent'] = True
                    else:
                        features['transit_odd_even_consistent'] = 1.0  # No variation = consistent
                        validity['transit_odd_even_consistent'] = True
                else:
                    features['transit_odd_even_consistent'] = None
                    validity['transit_odd_even_consistent'] = False
            else:
                features['transit_odd_even_consistent'] = None
                validity['transit_odd_even_consistent'] = False
        except Exception:
            features['transit_odd_even_consistent'] = None
            validity['transit_odd_even_consistent'] = False

        # If BLS power is low, mark all transit features as NULL
        # (no significant transit detected)
        if power < 0.05:  # Threshold for "significant" transit
            for key in features.keys():
                features[key] = None
                validity[key] = False

    except Exception:
        # If BLS fails entirely, mark all as invalid
        for key in all_feature_keys:
            features[key] = None
            validity[key] = False

    return features, validity
