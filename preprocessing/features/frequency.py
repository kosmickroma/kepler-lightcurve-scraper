"""
Frequency Features (Domain 3) - 10 features

These capture periodic and spectral behavior using Lomb-Scargle periodogram.
Optimized for speed with sensible frequency sampling.

NYQUIST NORMALIZATION: All frequencies divided by mission Nyquist frequency
to make features comparable across Kepler (30-min) and TESS (2-min) cadences.
"""

import numpy as np
from typing import Dict, Tuple
from scipy.signal import lombscargle
from astropy.timeseries import LombScargle

# Mission-specific parameters (from PROJECT_RULES Section 5.1)
MISSION_CONFIGS = {
    'kepler': {
        'cadence_minutes': 29.4,
        'typical_duration_days': 1470,
        'nyquist_frequency': 24.47,  # cycles/day
    },
    'k2': {
        'cadence_minutes': 29.4,
        'typical_duration_days': 80,
        'nyquist_frequency': 24.47,  # cycles/day
    },
    'tess': {
        'cadence_minutes': 2.0,
        'typical_duration_days': 27,
        'nyquist_frequency': 720,  # cycles/day
    },
    'other': {
        'cadence_minutes': 30.0,
        'typical_duration_days': 100,
        'nyquist_frequency': 24.0,  # cycles/day (assume Kepler-like)
    }
}


def get_nyquist_frequency(mission: str, cadence_days: float = None) -> float:
    """
    Get Nyquist frequency for mission.

    Args:
        mission: Mission name
        cadence_days: Optional cadence in days (will compute Nyquist)

    Returns:
        Nyquist frequency in cycles/day
    """
    mission_lower = mission.lower()

    if mission_lower in MISSION_CONFIGS:
        return MISSION_CONFIGS[mission_lower]['nyquist_frequency']

    # Compute from cadence if provided
    if cadence_days is not None and cadence_days > 0:
        return 1.0 / (2.0 * cadence_days)

    # Default to Kepler
    return 24.47


def compute_lombscargle_periodogram(
    time: np.ndarray,
    flux: np.ndarray,
    min_period: float = 0.1,
    max_period: float = 100.0,
    samples_per_peak: int = 10,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute Lomb-Scargle periodogram efficiently.

    Args:
        time: Time array (days)
        flux: Flux array (normalized)
        min_period: Minimum period to search (days)
        max_period: Maximum period to search (days)
        samples_per_peak: Frequency resolution

    Returns:
        Tuple of (frequency, power, periods)
    """
    # Use astropy's optimized Lomb-Scargle
    ls = LombScargle(time, flux - np.mean(flux), normalization='standard')

    # Frequency range
    freq_min = 1.0 / max_period
    freq_max = 1.0 / min_period

    # Auto-grid (efficient sampling)
    frequency, power = ls.autopower(
        minimum_frequency=freq_min,
        maximum_frequency=freq_max,
        samples_per_peak=samples_per_peak,
    )

    periods = 1.0 / frequency

    return frequency, power, periods


def extract_frequency_features(
    flux: np.ndarray,
    time: np.ndarray,
    mission: str = 'kepler',
) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract 10 frequency-space features from light curve.

    Args:
        flux: Normalized flux array
        time: Time array (BJD, days)
        mission: Mission name for Nyquist normalization

    Returns:
        Tuple of (features dict, validity dict)

    Features:
        freq_dominant_period, freq_dominant_power, freq_period_snr,
        freq_n_significant_peaks, freq_spectral_entropy,
        freq_low_freq_power, freq_high_freq_power, freq_power_ratio,
        freq_harmonic_count, freq_quasi_periodic_score

    Note:
        All frequency features normalized by mission Nyquist frequency
        for cross-mission compatibility (PROJECT_RULES Section 5.1).
    """
    features = {}
    validity = {}

    n_points = len(flux)
    duration = time[-1] - time[0]

    # Get Nyquist frequency for normalization
    cadence_median = np.median(np.diff(time)) if len(time) > 1 else 0.02
    nyquist_freq = get_nyquist_frequency(mission, cadence_median)

    # Check minimum requirements
    if n_points < 200 or duration < 10:
        for key in [
            'freq_dominant_period', 'freq_dominant_power', 'freq_period_snr',
            'freq_n_significant_peaks', 'freq_spectral_entropy',
            'freq_low_freq_power', 'freq_high_freq_power', 'freq_power_ratio',
            'freq_harmonic_count', 'freq_quasi_periodic_score'
        ]:
            features[key] = None
            validity[key] = False
        return features, validity

    try:
        # Compute periodogram
        max_period = min(duration / 2, 100.0)
        min_period = max(0.1, 2 * np.median(np.diff(time)))

        frequency, power, periods = compute_lombscargle_periodogram(
            time, flux,
            min_period=min_period,
            max_period=max_period,
            samples_per_peak=5,  # Faster sampling
        )

        # Dominant period and power
        peak_idx = np.argmax(power)
        features['freq_dominant_period'] = float(periods[peak_idx])
        features['freq_dominant_power'] = float(power[peak_idx])
        validity['freq_dominant_period'] = True
        validity['freq_dominant_power'] = True

        # Period SNR
        median_power = np.median(power)
        if median_power > 0:
            features['freq_period_snr'] = float(power[peak_idx] / median_power)
        else:
            features['freq_period_snr'] = 0.0
        validity['freq_period_snr'] = True

        # Number of significant peaks (above 99th percentile)
        threshold = np.percentile(power, 99)
        n_peaks = np.sum(power > threshold)
        features['freq_n_significant_peaks'] = int(n_peaks)
        validity['freq_n_significant_peaks'] = True

        # Spectral entropy
        power_norm = power / np.sum(power)
        power_norm = power_norm[power_norm > 0]
        entropy = -np.sum(power_norm * np.log(power_norm))
        features['freq_spectral_entropy'] = float(entropy)
        validity['freq_spectral_entropy'] = True

        # Low frequency power (<0.1 * Nyquist)
        # Normalized: low = 0.1 * Nyquist (e.g., 2.4 c/d for Kepler, 72 c/d for TESS)
        low_freq_cutoff = 0.1 * nyquist_freq
        low_freq_mask = frequency < low_freq_cutoff
        if np.any(low_freq_mask):
            features['freq_low_freq_power'] = float(np.sum(power[low_freq_mask]))
        else:
            features['freq_low_freq_power'] = 0.0
        validity['freq_low_freq_power'] = True

        # High frequency power (>0.5 * Nyquist)
        # Normalized: high = 0.5 * Nyquist (e.g., 12 c/d for Kepler, 360 c/d for TESS)
        high_freq_cutoff = 0.5 * nyquist_freq
        high_freq_mask = frequency > high_freq_cutoff
        if np.any(high_freq_mask):
            features['freq_high_freq_power'] = float(np.sum(power[high_freq_mask]))
        else:
            features['freq_high_freq_power'] = 0.0
        validity['freq_high_freq_power'] = True

        # Power ratio
        if features['freq_high_freq_power'] > 0:
            features['freq_power_ratio'] = float(
                features['freq_low_freq_power'] / features['freq_high_freq_power']
            )
        else:
            features['freq_power_ratio'] = 0.0
        validity['freq_power_ratio'] = True

        # Harmonic count (check 2f, 3f, 4f of dominant frequency)
        dominant_freq = 1.0 / features['freq_dominant_period']
        harmonic_count = 0

        for n in [2, 3, 4]:
            harmonic_freq = n * dominant_freq
            # Find closest frequency in periodogram
            idx = np.argmin(np.abs(frequency - harmonic_freq))

            if np.abs(frequency[idx] - harmonic_freq) / harmonic_freq < 0.1:
                # Within 10% of harmonic
                if power[idx] > threshold:
                    harmonic_count += 1

        features['freq_harmonic_count'] = int(harmonic_count)
        validity['freq_harmonic_count'] = True

        # Quasi-periodic score (coherence measure)
        # Simplified: inverse of peak width
        peak_power = power[peak_idx]
        half_power = peak_power / 2.0

        # Find width at half maximum
        left_idx = peak_idx
        while left_idx > 0 and power[left_idx] > half_power:
            left_idx -= 1

        right_idx = peak_idx
        while right_idx < len(power) - 1 and power[right_idx] > half_power:
            right_idx += 1

        peak_width = frequency[right_idx] - frequency[left_idx]
        if peak_width > 0:
            quasi_score = 1.0 / (1.0 + peak_width * 100)  # Narrower = more periodic
        else:
            quasi_score = 1.0

        features['freq_quasi_periodic_score'] = float(np.clip(quasi_score, 0, 1))
        validity['freq_quasi_periodic_score'] = True

    except Exception:
        # If periodogram fails, mark all as invalid
        for key in [
            'freq_dominant_period', 'freq_dominant_power', 'freq_period_snr',
            'freq_n_significant_peaks', 'freq_spectral_entropy',
            'freq_low_freq_power', 'freq_high_freq_power', 'freq_power_ratio',
            'freq_harmonic_count', 'freq_quasi_periodic_score'
        ]:
            features[key] = None
            validity[key] = False

    return features, validity
