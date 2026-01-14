"""
Main Feature Extractor - Orchestrates all 6 feature domains

Extracts all 47 features from a light curve FITS file.
Handles errors gracefully, tracks feature validity.
"""

import logging
import numpy as np
from pathlib import Path
from typing import Dict, Tuple, Optional
import lightkurve as lk

from preprocessing.features import (
    extract_statistical_features,
    extract_temporal_features,
    extract_frequency_features,
    extract_residual_features,
    extract_shape_features,
    extract_transit_features,
)

logger = logging.getLogger(__name__)


class FeatureExtractor:
    """
    Extract all 47 features from exoplanet light curves.

    Coordinates feature extraction across 6 signal domains:
    - Statistical (12 features)
    - Temporal (10 features)
    - Frequency (10 features)
    - Residual (8 features)
    - Shape (8 features)
    - Transit (7 features)

    Handles missing data gracefully with NULL values.
    """

    def __init__(self):
        """Initialize feature extractor."""
        self.feature_count = 47
        self.domain_extractors = {
            'statistical': extract_statistical_features,
            'temporal': extract_temporal_features,
            'frequency': extract_frequency_features,
            'residual': extract_residual_features,
            'shape': extract_shape_features,
            'transit': extract_transit_features,
        }

    def load_light_curve_from_fits(
        self,
        fits_path: Path,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Dict[str, any]]:
        """
        Load light curve from FITS file.

        Args:
            fits_path: Path to FITS file

        Returns:
            Tuple of (flux, time, metadata)
            Returns (None, None, {}) if loading fails
        """
        try:
            lc = lk.read(str(fits_path))

            # Remove NaN values
            mask = np.isfinite(lc.flux.value) & np.isfinite(lc.time.value)
            flux = lc.flux.value[mask]
            time = lc.time.value[mask]

            # Normalize flux to median
            median_flux = np.median(flux)
            if median_flux > 0:
                flux = flux / median_flux
            else:
                logger.warning(f"Zero median flux in {fits_path}")
                return None, None, {}

            # Metadata
            metadata = {
                'n_points_raw': len(lc.flux),
                'n_points_clean': len(flux),
                'mission': lc.meta.get('MISSION', 'unknown'),
                'target_id': lc.meta.get('OBJECT', 'unknown'),
            }

            return flux, time, metadata

        except Exception as e:
            logger.error(f"Failed to load {fits_path}: {e}")
            return None, None, {}

    def extract_features_from_fits(
        self,
        fits_path: Path,
        mission: str = 'kepler',
    ) -> Tuple[Dict[str, any], Dict[str, bool]]:
        """
        Extract all 47 features from FITS file.

        Args:
            fits_path: Path to FITS file
            mission: Mission name (for mission-specific parameters)

        Returns:
            Tuple of (features dict, validity dict)

        Features dict contains 47 features (or None if invalid)
        Validity dict contains 47 boolean flags
        """
        # Load light curve
        flux, time, metadata = self.load_light_curve_from_fits(fits_path)

        if flux is None or time is None:
            # Return all NULL features
            return self._get_null_features()

        # Extract features from all domains
        return self.extract_features(flux, time, mission)

    def extract_features(
        self,
        flux: np.ndarray,
        time: np.ndarray,
        mission: str = 'kepler',
    ) -> Tuple[Dict[str, any], Dict[str, bool]]:
        """
        Extract all 47 features from flux and time arrays.

        Args:
            flux: Normalized flux array
            time: Time array (BJD, days)
            mission: Mission name

        Returns:
            Tuple of (features dict, validity dict)
        """
        all_features = {}
        all_validity = {}

        # Extract from each domain
        for domain_name, extractor_func in self.domain_extractors.items():
            try:
                # Some extractors need mission parameter for normalization
                if domain_name in ['temporal', 'frequency']:
                    features, validity = extractor_func(flux, time, mission)
                else:
                    features, validity = extractor_func(flux, time)

                all_features.update(features)
                all_validity.update(validity)

                # Log domain completion
                n_valid = sum(validity.values())
                n_total = len(validity)
                logger.debug(
                    f"{domain_name.capitalize()}: {n_valid}/{n_total} features valid"
                )

            except Exception as e:
                logger.error(f"Failed to extract {domain_name} features: {e}")
                # Mark all features from this domain as NULL
                features, validity = self._get_null_features_for_domain(domain_name)
                all_features.update(features)
                all_validity.update(validity)

        # Verify we have all 47 features
        if len(all_features) != self.feature_count:
            logger.warning(
                f"Expected {self.feature_count} features, got {len(all_features)}"
            )

        return all_features, all_validity

    def _get_null_features(self) -> Tuple[Dict[str, any], Dict[str, bool]]:
        """
        Get dict of all 47 features set to None with validity False.

        Returns:
            Tuple of (features dict, validity dict)
        """
        feature_names = self._get_all_feature_names()
        features = {name: None for name in feature_names}
        validity = {name: False for name in feature_names}
        return features, validity

    def _get_null_features_for_domain(
        self,
        domain: str
    ) -> Tuple[Dict[str, any], Dict[str, bool]]:
        """
        Get NULL features for a specific domain.

        Args:
            domain: Domain name

        Returns:
            Tuple of (features dict, validity dict)
        """
        domain_features = {
            'statistical': [
                'stat_mean', 'stat_median', 'stat_std', 'stat_variance',
                'stat_mad', 'stat_range', 'stat_iqr', 'stat_skewness',
                'stat_kurtosis', 'stat_percentile_5', 'stat_percentile_95',
                'stat_beyond_1sigma'
            ],
            'temporal': [
                'temp_duration_days', 'temp_n_points', 'temp_cadence_median',
                'temp_cadence_std', 'temp_autocorr_1hr', 'temp_autocorr_1day',
                'temp_autocorr_1week', 'temp_memory_coefficient',
                'temp_trend_strength', 'temp_stationarity_pvalue'
            ],
            'frequency': [
                'freq_dominant_period', 'freq_dominant_power', 'freq_period_snr',
                'freq_n_significant_peaks', 'freq_spectral_entropy',
                'freq_low_freq_power', 'freq_high_freq_power', 'freq_power_ratio',
                'freq_harmonic_count', 'freq_quasi_periodic_score'
            ],
            'residual': [
                'resid_after_detrend_std', 'resid_after_detrend_autocorr',
                'resid_structure_score', 'resid_power_ratio', 'resid_entropy',
                'resid_run_test_pvalue', 'resid_ljung_box_pvalue', 'resid_complexity'
            ],
            'shape': [
                'shape_n_high_excursions', 'shape_n_low_excursions',
                'shape_max_excursion_up', 'shape_max_excursion_down',
                'shape_asymmetry', 'shape_max_consecutive_up',
                'shape_max_consecutive_down', 'shape_crossing_rate'
            ],
            'transit': [
                'transit_bls_power', 'transit_bls_period', 'transit_bls_depth',
                'transit_bls_duration', 'transit_n_detected',
                'transit_depth_consistency', 'transit_timing_consistency'
            ],
        }

        names = domain_features.get(domain, [])
        features = {name: None for name in names}
        validity = {name: False for name in names}
        return features, validity

    def _get_all_feature_names(self) -> list:
        """Get list of all 47 feature names."""
        all_names = []
        for domain in self.domain_extractors.keys():
            features, _ = self._get_null_features_for_domain(domain)
            all_names.extend(features.keys())
        return all_names

    def get_feature_summary(
        self,
        features: Dict[str, any],
        validity: Dict[str, bool]
    ) -> Dict[str, any]:
        """
        Generate summary statistics for extracted features.

        Args:
            features: Features dict
            validity: Validity dict

        Returns:
            Summary dict with counts and percentages
        """
        n_total = len(features)
        n_valid = sum(validity.values())
        n_null = n_total - n_valid

        # Count by domain
        domain_counts = {}
        for domain in self.domain_extractors.keys():
            domain_features, _ = self._get_null_features_for_domain(domain)
            domain_names = domain_features.keys()

            n_domain_total = len(domain_names)
            n_domain_valid = sum(validity.get(name, False) for name in domain_names)

            domain_counts[domain] = {
                'total': n_domain_total,
                'valid': n_domain_valid,
                'percentage': 100 * n_domain_valid / n_domain_total if n_domain_total > 0 else 0
            }

        return {
            'total_features': n_total,
            'valid_features': n_valid,
            'null_features': n_null,
            'validity_percentage': 100 * n_valid / n_total if n_total > 0 else 0,
            'by_domain': domain_counts,
        }
