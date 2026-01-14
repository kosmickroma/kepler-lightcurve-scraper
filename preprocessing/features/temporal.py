"""
Temporal Features (Domain 2) - 10 features

These capture time-domain behavior and memory effects.
Includes autocorrelation, Hurst exponent, trend analysis.

GAP HANDLING: Autocorrelation computed per-segment to avoid gap artifacts.
"""

import numpy as np
from typing import Dict, Tuple, List
from scipy import stats
from statsmodels.tsa.stattools import adfuller
from preprocessing.gap_handler import segment_light_curve, LightCurveSegment


def compute_autocorr_at_lag_segment_aware(
    flux: np.ndarray,
    time: np.ndarray,
    lag_points: int,
    min_segment_points: int = 100
) -> float:
    """
    Compute autocorrelation at specific lag, handling gaps properly.

    Segments light curve at large gaps, computes autocorrelation within
    each segment, then returns weighted average.

    Args:
        flux: Flux array
        time: Time array
        lag_points: Lag in number of data points
        min_segment_points: Minimum points per segment

    Returns:
        Weighted average autocorrelation coefficient
    """
    if lag_points >= len(flux) or lag_points < 1:
        return 0.0

    # Segment the light curve
    segments = segment_light_curve(
        flux, time,
        gap_threshold_multiplier=3.0,
        min_segment_points=max(min_segment_points, lag_points + 10)
    )

    if len(segments) == 0:
        # Fallback to simple autocorrelation
        return compute_autocorr_at_lag(flux, lag_points)

    # Compute autocorrelation per segment
    autocorrs = []
    weights = []

    for seg in segments:
        if len(seg.flux) < lag_points + 10:
            continue

        autocorr = compute_autocorr_at_lag(seg.flux, lag_points)
        autocorrs.append(autocorr)
        weights.append(len(seg.flux))  # Weight by segment length

    if len(autocorrs) == 0:
        return 0.0

    # Weighted average
    weights = np.array(weights)
    weights = weights / np.sum(weights)

    return float(np.average(autocorrs, weights=weights))


def compute_autocorr_at_lag(flux: np.ndarray, lag_points: int) -> float:
    """
    Compute autocorrelation at specific lag.

    Args:
        flux: Flux array
        lag_points: Lag in number of data points

    Returns:
        Autocorrelation coefficient
    """
    if lag_points >= len(flux) or lag_points < 1:
        return 0.0

    flux_norm = flux - np.mean(flux)
    c0 = np.dot(flux_norm, flux_norm) / len(flux)

    if c0 == 0:
        return 0.0

    c_lag = np.dot(flux_norm[:-lag_points], flux_norm[lag_points:]) / (
        len(flux) - lag_points
    )
    return c_lag / c0


def compute_hurst_exponent(flux: np.ndarray) -> float:
    """
    Compute Hurst exponent via R/S analysis.

    Args:
        flux: Flux array

    Returns:
        Hurst exponent H (0 to 1)
        H=0.5: random walk
        H>0.5: persistent (trending)
        H<0.5: anti-persistent (mean-reverting)
    """
    N = len(flux)
    if N < 100:
        return 0.5  # Not enough data

    max_k = int(np.log2(N))
    if max_k < 3:
        return 0.5

    RS_list = []
    n_list = []

    for k in range(2, max_k):
        n = 2 ** k
        n_list.append(n)

        RS_values = []
        for i in range(0, N - n, n):
            segment = flux[i:i+n]
            mean_seg = np.mean(segment)
            cumdev = np.cumsum(segment - mean_seg)
            R = np.max(cumdev) - np.min(cumdev)
            S = np.std(segment, ddof=1)

            if S > 0:
                RS_values.append(R / S)

        if RS_values:
            RS_list.append(np.mean(RS_values))

    # Fit log(R/S) vs log(n)
    if len(RS_list) > 2:
        log_n = np.log(n_list[:len(RS_list)])
        log_RS = np.log(RS_list)

        # Linear fit
        slope, _ = np.polyfit(log_n, log_RS, 1)
        return float(np.clip(slope, 0, 1))  # Clamp to valid range

    return 0.5


def extract_temporal_features(
    flux: np.ndarray,
    time: np.ndarray,
    mission: str = 'kepler',
) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract 10 temporal structure features from light curve.

    Args:
        flux: Normalized flux array
        time: Time array (BJD, days)
        mission: Mission name for cadence info

    Returns:
        Tuple of (features dict, validity dict)

    Features:
        temp_duration_days, temp_n_points, temp_cadence_median,
        temp_cadence_std, temp_autocorr_1hr, temp_autocorr_1day,
        temp_autocorr_1week, temp_memory_coefficient,
        temp_trend_strength, temp_stationarity_pvalue
    """
    features = {}
    validity = {}

    n_points = len(flux)
    duration_days = time[-1] - time[0]

    # Basic temporal properties (always computable)
    features['temp_duration_days'] = float(duration_days)
    features['temp_n_points'] = int(n_points)
    validity['temp_duration_days'] = True
    validity['temp_n_points'] = True

    # Cadence statistics
    if n_points > 1:
        time_diffs = np.diff(time)
        features['temp_cadence_median'] = float(np.median(time_diffs))
        features['temp_cadence_std'] = float(np.std(time_diffs, ddof=1))
        validity['temp_cadence_median'] = True
        validity['temp_cadence_std'] = True
        cadence_median = features['temp_cadence_median']
    else:
        features['temp_cadence_median'] = None
        features['temp_cadence_std'] = None
        validity['temp_cadence_median'] = False
        validity['temp_cadence_std'] = False
        cadence_median = 0.02  # Default Kepler cadence

    # Autocorrelation at different lags (GAP-AWARE)
    # Convert time lags to point lags based on cadence
    try:
        # 1 hour lag
        if n_points >= 50 and duration_days >= 1:
            lag_1hr_days = 1.0 / 24.0
            lag_1hr_points = max(1, int(lag_1hr_days / cadence_median))
            features['temp_autocorr_1hr'] = compute_autocorr_at_lag_segment_aware(
                flux, time, lag_1hr_points, min_segment_points=50
            )
            validity['temp_autocorr_1hr'] = True
        else:
            features['temp_autocorr_1hr'] = None
            validity['temp_autocorr_1hr'] = False

        # 1 day lag
        if n_points >= 100 and duration_days >= 7:
            lag_1day_points = max(1, int(1.0 / cadence_median))
            features['temp_autocorr_1day'] = compute_autocorr_at_lag_segment_aware(
                flux, time, lag_1day_points, min_segment_points=100
            )
            validity['temp_autocorr_1day'] = True
        else:
            features['temp_autocorr_1day'] = None
            validity['temp_autocorr_1day'] = False

        # 1 week lag
        if n_points >= 500 and duration_days >= 30:
            lag_1week_points = max(1, int(7.0 / cadence_median))
            features['temp_autocorr_1week'] = compute_autocorr_at_lag_segment_aware(
                flux, time, lag_1week_points, min_segment_points=500
            )
            validity['temp_autocorr_1week'] = True
        else:
            features['temp_autocorr_1week'] = None
            validity['temp_autocorr_1week'] = False

    except Exception:
        features['temp_autocorr_1hr'] = None
        features['temp_autocorr_1day'] = None
        features['temp_autocorr_1week'] = None
        validity['temp_autocorr_1hr'] = False
        validity['temp_autocorr_1day'] = False
        validity['temp_autocorr_1week'] = False

    # Hurst exponent (memory coefficient)
    try:
        if n_points >= 1000 and duration_days >= 90:
            features['temp_memory_coefficient'] = compute_hurst_exponent(flux)
            validity['temp_memory_coefficient'] = True
        else:
            features['temp_memory_coefficient'] = None
            validity['temp_memory_coefficient'] = False
    except Exception:
        features['temp_memory_coefficient'] = None
        validity['temp_memory_coefficient'] = False

    # Trend strength (R² of linear fit)
    try:
        if n_points >= 10:
            # Linear fit
            slope, intercept = np.polyfit(time, flux, 1)
            flux_pred = slope * time + intercept
            ss_res = np.sum((flux - flux_pred) ** 2)
            ss_tot = np.sum((flux - np.mean(flux)) ** 2)

            if ss_tot > 0:
                r_squared = 1 - (ss_res / ss_tot)
                features['temp_trend_strength'] = float(np.clip(r_squared, 0, 1))
            else:
                features['temp_trend_strength'] = 0.0

            validity['temp_trend_strength'] = True
        else:
            features['temp_trend_strength'] = None
            validity['temp_trend_strength'] = False
    except Exception:
        features['temp_trend_strength'] = None
        validity['temp_trend_strength'] = False

    # Stationarity test (Augmented Dickey-Fuller)
    try:
        if n_points >= 50:
            adf_result = adfuller(flux, autolag='AIC')
            features['temp_stationarity_pvalue'] = float(adf_result[1])
            validity['temp_stationarity_pvalue'] = True
        else:
            features['temp_stationarity_pvalue'] = None
            validity['temp_stationarity_pvalue'] = False
    except Exception:
        features['temp_stationarity_pvalue'] = None
        validity['temp_stationarity_pvalue'] = False

    return features, validity
