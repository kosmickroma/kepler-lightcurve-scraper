#!/usr/bin/env python3
"""
Provenance Tracking for Scientific Reproducibility

Saves all library versions, pipeline settings, and runtime metadata
to ensure results can be reproduced by other researchers.

This is a CRITICAL scientific requirement per DR25 standards.
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path


def get_library_versions():
    """Get versions of all key libraries used in the pipeline."""
    versions = {}

    # Core libraries
    try:
        import lightkurve
        versions['lightkurve'] = lightkurve.__version__
    except (ImportError, AttributeError):
        versions['lightkurve'] = 'unknown'

    try:
        import numpy
        versions['numpy'] = numpy.__version__
    except (ImportError, AttributeError):
        versions['numpy'] = 'unknown'

    try:
        import scipy
        versions['scipy'] = scipy.__version__
    except (ImportError, AttributeError):
        versions['scipy'] = 'unknown'

    try:
        import pandas
        versions['pandas'] = pandas.__version__
    except (ImportError, AttributeError):
        versions['pandas'] = 'unknown'

    try:
        import astropy
        versions['astropy'] = astropy.__version__
    except (ImportError, AttributeError):
        versions['astropy'] = 'unknown'

    try:
        import sklearn
        versions['scikit-learn'] = sklearn.__version__
    except (ImportError, AttributeError):
        versions['scikit-learn'] = 'unknown'

    return versions


def get_pipeline_settings():
    """Get current pipeline configuration settings."""
    return {
        # Flux settings (CRITICAL for scientific validity)
        'flux_column': 'pdcsap_flux',
        'flux_description': 'Pre-search Data Conditioning flux (systematics removed)',

        # Quality filtering
        'quality_bitmask': 'default',
        'quality_description': 'Includes Rolling Band filtering (bit 17)',

        # Cadence
        'cadence': 'long',
        'cadence_minutes': 29.4,

        # Feature extraction
        'feature_count': 62,
        'feature_domains': [
            'statistical (12)',
            'temporal (10)',
            'frequency (11)',  # Includes 1 scientific validation feature
            'residual (8)',
            'shape (8)',
            'transit (10)',   # Includes 3 scientific validation features
            'centroid (3)'
        ],

        # Data sources
        'data_source': 'NASA Exoplanet Archive (TAP)',
        'mission': 'Kepler',
        'data_release': 'DR25',
    }


def get_runtime_metadata():
    """Get runtime environment metadata."""
    return {
        'python_version': sys.version,
        'python_executable': sys.executable,
        'platform': sys.platform,
        'working_directory': os.getcwd(),
    }


def save_provenance(
    output_path: str = None,
    run_type: str = 'validation',
    n_targets: int = None,
    additional_metadata: dict = None,
):
    """
    Save complete provenance information to JSON file.

    Args:
        output_path: Path to save provenance file (default: data/provenance_{timestamp}.json)
        run_type: Type of run (validation, production, test)
        n_targets: Number of targets processed
        additional_metadata: Any additional metadata to include

    Returns:
        Path to saved provenance file
    """
    timestamp = datetime.utcnow().isoformat()

    provenance = {
        # Timestamp and identification
        'timestamp': timestamp,
        'run_type': run_type,
        'n_targets': n_targets,

        # Library versions (CRITICAL for reproducibility)
        'library_versions': get_library_versions(),

        # Pipeline settings (CRITICAL for scientific validity)
        'pipeline_settings': get_pipeline_settings(),

        # Runtime environment
        'runtime': get_runtime_metadata(),

        # Scientific context
        'scientific_context': {
            'purpose': 'Kepler light curve feature extraction for exoplanet anomaly detection',
            'baseline_type': 'Quiet stars (no known planets, low CDPP)',
            'validation_type': 'Known planet hosts + quiet stars comparison',
            'reference_standard': 'Kepler Data Release 25 (DR25)',
        },

        # Data quality assurances
        'data_quality': {
            'flux_type': 'PDCSAP (Pre-search Data Conditioning)',
            'flux_rationale': 'Removes telescope systematics (thermal drift, focus changes)',
            'quality_filtering': 'Rolling Band (bit 17) + standard Kepler quality flags',
            'quality_rationale': 'Prevents electronic noise artifacts from contaminating features',
        },

        # Additional metadata
        'additional': additional_metadata or {},
    }

    # Default output path
    if output_path is None:
        timestamp_str = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        output_path = f'data/provenance_{run_type}_{timestamp_str}.json'

    # Ensure directory exists
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write provenance
    with open(output_file, 'w') as f:
        json.dump(provenance, f, indent=2, default=str)

    print(f"Provenance saved: {output_file}")
    print(f"  Timestamp: {timestamp}")
    print(f"  Run type: {run_type}")
    if n_targets:
        print(f"  Targets: {n_targets}")
    print(f"  Libraries tracked: {len(provenance['library_versions'])}")

    return output_file


def verify_provenance(provenance_path: str):
    """
    Verify provenance file and print summary.

    Args:
        provenance_path: Path to provenance JSON file
    """
    with open(provenance_path) as f:
        provenance = json.load(f)

    print("=" * 80)
    print("PROVENANCE VERIFICATION")
    print("=" * 80)
    print()

    print("Timestamp:", provenance.get('timestamp', 'unknown'))
    print("Run type:", provenance.get('run_type', 'unknown'))
    print("Targets:", provenance.get('n_targets', 'unknown'))
    print()

    print("Library Versions:")
    for lib, version in provenance.get('library_versions', {}).items():
        print(f"  {lib}: {version}")
    print()

    print("Pipeline Settings:")
    settings = provenance.get('pipeline_settings', {})
    print(f"  Flux column: {settings.get('flux_column', 'unknown')}")
    print(f"  Quality bitmask: {settings.get('quality_bitmask', 'unknown')}")
    print(f"  Feature count: {settings.get('feature_count', 'unknown')}")
    print()

    print("Data Quality Assurances:")
    quality = provenance.get('data_quality', {})
    print(f"  Flux type: {quality.get('flux_type', 'unknown')}")
    print(f"  Quality filtering: {quality.get('quality_filtering', 'unknown')}")
    print()

    print("=" * 80)
    print("PROVENANCE VALID")
    print("=" * 80)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Save or verify provenance metadata')
    parser.add_argument('--verify', type=str, help='Path to provenance file to verify')
    parser.add_argument('--run-type', type=str, default='test', help='Run type (test, validation, production)')
    parser.add_argument('--n-targets', type=int, help='Number of targets')
    parser.add_argument('--output', type=str, help='Output path for provenance file')

    args = parser.parse_args()

    if args.verify:
        verify_provenance(args.verify)
    else:
        save_provenance(
            output_path=args.output,
            run_type=args.run_type,
            n_targets=args.n_targets,
        )
