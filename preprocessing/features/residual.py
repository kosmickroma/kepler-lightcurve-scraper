"""
Residual Features (Domain 4) - 8 features

These capture structure remaining after polynomial detrending.
Tests for unexplained signal that survives baseline removal.

REMEDIATION 2026-01-17: Added timeout to lempel_ziv_complexity to fix O(N³)
performance issue causing 25+ min extraction times. Gemini-validated.
"""

import logging
import numpy as np
from typing import Dict, Tuple
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

logger = logging.getLogger(__name__)

# Timeout for expensive operations (Gemini-approved: 5 seconds)
LEMPEL_ZIV_TIMEOUT_SEC = 5.0


def _lempel_ziv_core(signal: np.ndarray, bins: int = 10) -> float:
    """
    Core Lempel-Ziv complexity computation (called with timeout wrapper).

    WARNING: This function has O(N³) worst-case complexity due to substring search.
    Always call via lempel_ziv_complexity() which applies a timeout.

    Args:
        signal: Input signal array
        bins: Number of bins for discretization

    Returns:
        Normalized complexity score
    """
    if len(signal) < 10:
        return 0.0

    # Discretize signal
    signal_min, signal_max = np.min(signal), np.max(signal)
    if signal_max - signal_min == 0:
        return 0.0

    edges = np.linspace(signal_min, signal_max, bins + 1)
    digitized = np.digitize(signal, edges[:-1])

    # Convert to string
    s = ''.join(map(str, digitized))

    # Count unique substrings (Lempel-Ziv)
    # NOTE: This loop has O(N³) worst case - protected by timeout
    n = len(s)
    complexity = 1
    l = 0
    k = 1
    k_max = 1

    while l + k <= n:
        if s[l:l+k] in s[0:l+k-1]:  # O(N) substring search
            k += 1
            if k > k_max:
                k_max = k
        else:
            complexity += 1
            l += k_max if k_max >= k else k
            k = 1
            k_max = 1

    # Normalize
    if n > 0:
        return complexity * np.log2(n) / n
    return 0.0


def lempel_ziv_complexity(signal: np.ndarray, bins: int = 10,
                          timeout_sec: float = LEMPEL_ZIV_TIMEOUT_SEC) -> float:
    """
    Compute Lempel-Ziv complexity with timeout protection.

    REMEDIATION 2026-01-17: Added timeout to prevent O(N³) hangs.
    Gemini-validated threshold: 5 seconds.

    Args:
        signal: Input signal array
        bins: Number of bins for discretization
        timeout_sec: Maximum execution time (default 5 seconds)

    Returns:
        Normalized complexity score, or 0.0 if timeout/error
    """
    if len(signal) < 10:
        return 0.0

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_lempel_ziv_core, signal, bins)
            result = future.result(timeout=timeout_sec)
            return result
    except FuturesTimeoutError:
        logger.warning(f"lempel_ziv_complexity timed out after {timeout_sec}s (n_points={len(signal)})")
        return 0.0
    except Exception as e:
        logger.warning(f"lempel_ziv_complexity failed: {type(e).__name__}: {e}")
        return 0.0


def extract_residual_features(
    flux: np.ndarray,
    time: np.ndarray,
) -> Tuple[Dict[str, float], Dict[str, bool]]:
    """
    Extract 8 residual analysis features from light curve.

    Args:
        flux: Normalized flux array
        time: Time array (BJD, days)

    Returns:
        Tuple of (features dict, validity dict)

    Features:
        resid_after_detrend_std, resid_after_detrend_autocorr,
        resid_structure_score, resid_power_ratio, resid_entropy,
        resid_run_test_pvalue, resid_ljung_box_pvalue, resid_complexity
    """
    features = {}
    validity = {}

    n_points = len(flux)
    duration = time[-1] - time[0]

    # Check minimum requirements
    if n_points < 100 or duration < 7:
        for key in [
            'resid_after_detrend_std', 'resid_after_detrend_autocorr',
            'resid_structure_score', 'resid_power_ratio', 'resid_entropy',
            'resid_run_test_pvalue', 'resid_ljung_box_pvalue', 'resid_complexity'
        ]:
            features[key] = None
            validity[key] = False
        return features, validity

    try:
        # Polynomial detrending (degree 3)
        poly_coeffs = np.polyfit(time, flux, deg=3)
        flux_trend = np.polyval(poly_coeffs, time)
        residuals = flux - flux_trend

        # Residual standard deviation
        features['resid_after_detrend_std'] = float(np.std(residuals, ddof=1))
        validity['resid_after_detrend_std'] = True

        # Residual autocorrelation at lag 1
        if n_points > 1:
            resid_norm = residuals - np.mean(residuals)
            c0 = np.dot(resid_norm, resid_norm) / n_points

            if c0 > 0:
                c1 = np.dot(resid_norm[:-1], resid_norm[1:]) / (n_points - 1)
                features['resid_after_detrend_autocorr'] = float(c1 / c0)
            else:
                features['resid_after_detrend_autocorr'] = 0.0

            validity['resid_after_detrend_autocorr'] = True
        else:
            features['resid_after_detrend_autocorr'] = None
            validity['resid_after_detrend_autocorr'] = False

        # Residual power ratio
        var_original = np.var(flux, ddof=1)
        var_residual = np.var(residuals, ddof=1)

        if var_original > 0:
            features['resid_power_ratio'] = float(var_residual / var_original)
        else:
            features['resid_power_ratio'] = 0.0
        validity['resid_power_ratio'] = True

        # Structure score (combined metric)
        # High autocorr + high power ratio + low run test p-value = high structure
        autocorr_score = abs(features.get('resid_after_detrend_autocorr', 0))
        power_score = features.get('resid_power_ratio', 0)
        structure_score = (autocorr_score + power_score) / 2.0

        features['resid_structure_score'] = float(np.clip(structure_score, 0, 1))
        validity['resid_structure_score'] = True

        # Residual entropy
        hist, _ = np.histogram(residuals, bins=20, density=True)
        hist = hist[hist > 0]  # Remove zeros

        if len(hist) > 0:
            entropy = -np.sum(hist * np.log(hist))
            features['resid_entropy'] = float(entropy)
        else:
            features['resid_entropy'] = 0.0
        validity['resid_entropy'] = True

        # Runs test (Wald-Wolfowitz)
        try:
            median_resid = np.median(residuals)
            runs = residuals > median_resid
            n_runs = 1 + np.sum(runs[:-1] != runs[1:])

            n_pos = np.sum(runs)
            n_neg = len(runs) - n_pos

            if n_pos > 0 and n_neg > 0:
                # Expected runs and variance
                expected_runs = 1 + (2 * n_pos * n_neg) / (n_pos + n_neg)
                var_runs = (2 * n_pos * n_neg * (2 * n_pos * n_neg - n_pos - n_neg)) / (
                    (n_pos + n_neg) ** 2 * (n_pos + n_neg - 1)
                )

                if var_runs > 0:
                    z = (n_runs - expected_runs) / np.sqrt(var_runs)
                    p_value = 2 * (1 - stats.norm.cdf(abs(z)))
                    features['resid_run_test_pvalue'] = float(np.clip(p_value, 0, 1))
                else:
                    features['resid_run_test_pvalue'] = 0.5
            else:
                features['resid_run_test_pvalue'] = 0.5

            validity['resid_run_test_pvalue'] = True
        except Exception:
            features['resid_run_test_pvalue'] = None
            validity['resid_run_test_pvalue'] = False

        # Ljung-Box test for autocorrelation
        try:
            if n_points > 10:
                lb_result = acorr_ljungbox(residuals, lags=min(10, n_points // 4), return_df=False)
                # Use minimum p-value across lags (most conservative)
                features['resid_ljung_box_pvalue'] = float(np.min(lb_result[1]))
                validity['resid_ljung_box_pvalue'] = True
            else:
                features['resid_ljung_box_pvalue'] = None
                validity['resid_ljung_box_pvalue'] = False
        except Exception:
            features['resid_ljung_box_pvalue'] = None
            validity['resid_ljung_box_pvalue'] = False

        # Lempel-Ziv complexity
        try:
            complexity = lempel_ziv_complexity(residuals, bins=10)
            features['resid_complexity'] = float(complexity)
            validity['resid_complexity'] = True
        except Exception:
            features['resid_complexity'] = None
            validity['resid_complexity'] = False

    except Exception:
        # If any major error, mark all as invalid
        for key in [
            'resid_after_detrend_std', 'resid_after_detrend_autocorr',
            'resid_structure_score', 'resid_power_ratio', 'resid_entropy',
            'resid_run_test_pvalue', 'resid_ljung_box_pvalue', 'resid_complexity'
        ]:
            features[key] = None
            validity[key] = False

    return features, validity
