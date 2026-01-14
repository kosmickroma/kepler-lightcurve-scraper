"""
Gap Detection and Handling for Light Curves

Kepler and TESS data have gaps due to:
- Quarterly rolls (Kepler)
- Sector boundaries (TESS)
- Data downlink interruptions
- Instrument safe modes

If gaps are treated as continuous data, temporal/frequency features
will be dominated by gap edges (artifacts) rather than stellar physics.

This module provides robust gap detection and segment-based processing.
"""

import numpy as np
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class LightCurveSegment:
    """A continuous segment of a light curve (no large gaps)."""
    flux: np.ndarray
    time: np.ndarray
    start_idx: int
    end_idx: int
    duration_days: float
    n_points: int


def detect_gaps(
    time: np.ndarray,
    cadence_median: float,
    gap_threshold_multiplier: float = 3.0
) -> np.ndarray:
    """
    Detect large gaps in time series.

    A gap is defined as a time difference > threshold * median_cadence.

    Args:
        time: Time array (days)
        cadence_median: Median time between observations
        gap_threshold_multiplier: Gap threshold in units of cadence

    Returns:
        Boolean array where True = gap detected after this index
    """
    if len(time) < 2:
        return np.array([], dtype=bool)

    time_diffs = np.diff(time)
    gap_threshold = gap_threshold_multiplier * cadence_median

    # Gap detected where time_diff > threshold
    gaps = time_diffs > gap_threshold

    return gaps


def segment_light_curve(
    flux: np.ndarray,
    time: np.ndarray,
    gap_threshold_multiplier: float = 3.0,
    min_segment_points: int = 50
) -> List[LightCurveSegment]:
    """
    Break light curve into continuous segments at large gaps.

    Args:
        flux: Flux array
        time: Time array (days)
        gap_threshold_multiplier: Gap threshold in units of cadence
        min_segment_points: Minimum points to keep a segment

    Returns:
        List of LightCurveSegment objects
    """
    if len(time) < 2:
        return []

    # Compute median cadence
    time_diffs = np.diff(time)
    cadence_median = np.median(time_diffs)

    # Detect gaps
    gaps = detect_gaps(time, cadence_median, gap_threshold_multiplier)

    # Find gap indices
    gap_indices = np.where(gaps)[0] + 1  # +1 because gaps are after the index

    # Create segment boundaries
    boundaries = [0] + list(gap_indices) + [len(time)]

    # Build segments
    segments = []
    for i in range(len(boundaries) - 1):
        start_idx = boundaries[i]
        end_idx = boundaries[i + 1]

        # Skip segments that are too short
        if end_idx - start_idx < min_segment_points:
            continue

        seg_flux = flux[start_idx:end_idx]
        seg_time = time[start_idx:end_idx]

        segment = LightCurveSegment(
            flux=seg_flux,
            time=seg_time,
            start_idx=start_idx,
            end_idx=end_idx,
            duration_days=seg_time[-1] - seg_time[0],
            n_points=len(seg_flux)
        )

        segments.append(segment)

    return segments


def compute_gap_statistics(
    time: np.ndarray,
    cadence_median: float
) -> dict:
    """
    Compute statistics about gaps in light curve.

    Args:
        time: Time array (days)
        cadence_median: Median cadence

    Returns:
        Dict with gap statistics
    """
    if len(time) < 2:
        return {
            'n_gaps': 0,
            'gap_fraction': 0.0,
            'largest_gap_days': 0.0,
            'median_gap_days': 0.0,
        }

    gaps = detect_gaps(time, cadence_median, gap_threshold_multiplier=3.0)
    n_gaps = np.sum(gaps)

    if n_gaps == 0:
        return {
            'n_gaps': 0,
            'gap_fraction': 0.0,
            'largest_gap_days': 0.0,
            'median_gap_days': 0.0,
        }

    # Gap sizes
    time_diffs = np.diff(time)
    gap_sizes = time_diffs[gaps]

    # Total time span
    total_duration = time[-1] - time[0]

    # Expected duration if no gaps
    expected_duration = len(time) * cadence_median

    # Gap fraction
    gap_fraction = (total_duration - expected_duration) / total_duration if total_duration > 0 else 0

    return {
        'n_gaps': int(n_gaps),
        'gap_fraction': float(np.clip(gap_fraction, 0, 1)),
        'largest_gap_days': float(np.max(gap_sizes)),
        'median_gap_days': float(np.median(gap_sizes)),
    }


def interpolate_small_gaps(
    flux: np.ndarray,
    time: np.ndarray,
    max_gap_size: int = 5
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Interpolate small gaps (< max_gap_size missing cadences).

    This prevents FFT artifacts from small gaps while preserving
    large gaps as segment boundaries.

    Args:
        flux: Flux array
        time: Time array
        max_gap_size: Maximum gap size to interpolate (in cadences)

    Returns:
        Tuple of (interpolated_flux, interpolated_time)

    Note:
        This is for frequency-domain analysis only. Temporal features
        should use segmentation instead.
    """
    if len(time) < 2:
        return flux, time

    cadence_median = np.median(np.diff(time))

    # Find small gaps
    time_diffs = np.diff(time)
    gap_threshold = max_gap_size * cadence_median

    # For now, just return original (full interpolation is complex)
    # TODO: Implement if needed for frequency features
    return flux, time
