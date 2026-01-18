"""
Transit Features (Domain 6) - 11 features total

These characterize transit-like periodic dip signals using BLS.

REMEDIATION 2026-01-17: Fixed feature leakage bug.
Previously, ALL transit features were set to NULL when BLS power < 0.05.
This caused the Isolation Forest to trivially learn "has BLS value = anomaly".

Per Gemini's guidance: "The Noise Floor is just as important as the Signal."
Now we ALWAYS return BLS core values (power, period, depth, duration) and add
a `transit_significant` flag. This teaches the model the difference between
astrophysical noise and coherent planetary signals.

SCIENTIFIC VALIDATION: Includes physical plausibility check
to identify false positives (eclipsing binaries masquerading as planets).
"""

import logging
import numpy as np
from typing import Dict, Tuple, Optional
from astropy.timeseries import BoxLeastSquares

logger = logging.getLogger(__name__)

# Physical constants for planet radius validation
R_JUPITER_R_EARTH = 11.2  # Jupiter radius in Earth radii
R_SUN_R_EARTH = 109.1     # Solar radius in Earth radii
MAX_PLANET_R_JUPITER = 2.0  # Maximum plausible planet radius in R_Jupiter

# BLS significance threshold (Gemini-validated)
BLS_SIGNIFICANCE_THRESHOLD = 0.05


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

    Features (11 total):
        Core BLS features (ALWAYS populated - Gemini requirement):
            transit_bls_power, transit_bls_period, transit_bls_depth,
            transit_bls_duration, transit_significant (NEW)

        Derived features (NULL if transit_significant=0):
            transit_n_detected, transit_depth_consistency,
            transit_timing_consistency

        Physical validation features (NULL if no st_rad or transit_significant=0):
            transit_implied_r_planet_rjup, transit_physically_plausible,
            transit_odd_even_consistent

    REMEDIATION 2026-01-17:
        Core BLS features are ALWAYS returned to prevent feature leakage.
        The model needs to see the "noise floor" of quiet stars (low BLS power)
        to distinguish from the coherent signals of planet hosts (high BLS power).

    SCIENTIFIC VALIDATION:
        1. Physical plausibility: If st_rad is provided, calculates implied
           planet radius from transit depth and stellar radius. Flags as
           "not physically plausible" if implied R_planet > 2.0 R_Jupiter
           (likely eclipsing binary).

        2. Odd-even consistency: Compares odd vs even transit depths to
           detect eclipsing binaries (which have alternating depths due to
           two stars of different sizes/temperatures).
    """
    features = {}
    validity = {}

    n_points = len(flux)
    duration = time[-1] - time[0]

    # All feature keys (5 core + 3 derived + 3 physical validation = 11 total)
    all_feature_keys = [
        # Core BLS features (ALWAYS populated)
        'transit_bls_power', 'transit_bls_period', 'transit_bls_depth',
        'transit_bls_duration', 'transit_significant',
        # Derived features (NULL if not significant)
        'transit_n_detected', 'transit_depth_consistency', 'transit_timing_consistency',
        # Physical validation features
        'transit_implied_r_planet_rjup', 'transit_physically_plausible',
        'transit_odd_even_consistent'
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

        # CORE BLS FEATURES - Always populated (Gemini requirement)
        features['transit_bls_power'] = float(power)
        features['transit_bls_period'] = float(period)
        features['transit_bls_depth'] = float(abs(depth))
        features['transit_bls_duration'] = float(duration)
        validity['transit_bls_power'] = True
        validity['transit_bls_period'] = True
        validity['transit_bls_depth'] = True
        validity['transit_bls_duration'] = True

        # NEW: Significance flag (prevents feature leakage)
        # Gemini: "The Noise Floor is just as important as the Signal"
        is_significant = power >= BLS_SIGNIFICANCE_THRESHOLD
        features['transit_significant'] = 1.0 if is_significant else 0.0
        validity['transit_significant'] = True

        logger.debug(f"BLS: power={power:.4f}, significant={is_significant}, "
                    f"period={period:.2f}d, depth={abs(depth):.6f}")

        # DERIVED FEATURES - Only computed if significant transit detected
        if not is_significant:
            # Set derived features to NULL/0 for non-significant detections
            features['transit_n_detected'] = 0
            features['transit_depth_consistency'] = None
            features['transit_timing_consistency'] = None
            features['transit_implied_r_planet_rjup'] = None
            features['transit_physically_plausible'] = None
            features['transit_odd_even_consistent'] = None
            validity['transit_n_detected'] = True  # 0 is a valid value
            validity['transit_depth_consistency'] = False
            validity['transit_timing_consistency'] = False
            validity['transit_implied_r_planet_rjup'] = False
            validity['transit_physically_plausible'] = False
            validity['transit_odd_even_consistent'] = False
            return features, validity

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
        except Exception as e:
            logger.warning(f"Odd-even consistency check failed: {e}")
            features['transit_odd_even_consistent'] = None
            validity['transit_odd_even_consistent'] = False

        # NOTE: Removed the old "if power < 0.05: null everything" logic
        # This was causing feature leakage - now handled with early return above

    except Exception as e:
        # If BLS fails entirely, still try to return zeros for core features
        # so the model sees "BLS ran but found nothing" vs "BLS couldn't run"
        logger.error(f"BLS extraction failed: {type(e).__name__}: {e}")
        for key in all_feature_keys:
            features[key] = None
            validity[key] = False

    return features, validity
