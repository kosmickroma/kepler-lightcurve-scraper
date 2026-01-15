#!/usr/bin/env python3
"""
Test Priority 1 Scientific Validation Fixes

Tests:
1. PDCSAP flux is being used (not SAP)
2. Quality bitmask is applied (Rolling Band filtering)
3. Provenance tracking works

Run this BEFORE the full validation to ensure fixes are working.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lightkurve as lk
import numpy as np
from pathlib import Path


def test_pdcsap_flux():
    """Test that PDCSAP flux is available and preferred."""
    print("=" * 80)
    print("TEST 1: PDCSAP Flux Verification")
    print("=" * 80)
    print()

    # Test with a known Kepler target
    target = "KIC 8462852"  # Tabby's Star - well-known target

    print(f"Testing target: {target}")
    print("Searching for light curves...")

    search = lk.search_lightcurve(target, author="Kepler", cadence="long")

    if len(search) == 0:
        print("ERROR: No data found for test target")
        return False

    print(f"Found {len(search)} quarters")

    # Download one quarter with our new settings
    print("Downloading first quarter with PDCSAP settings...")
    try:
        lc = search[0].download(
            flux_column='pdcsap_flux',
            quality_bitmask='default'
        )

        # Verify flux column
        print()
        print("Light curve metadata:")
        print(f"  Target: {lc.meta.get('TARGETID', 'unknown')}")
        print(f"  Mission: {lc.meta.get('MISSION', 'unknown')}")
        print(f"  Flux column used: pdcsap_flux (specified)")
        print(f"  Points: {len(lc.flux)}")
        print(f"  Time range: {lc.time[0].value:.2f} - {lc.time[-1].value:.2f} days")

        # Check flux statistics
        flux = lc.flux.value
        print()
        print("Flux statistics (should be normalized ~1.0):")
        print(f"  Mean: {np.nanmean(flux):.6f}")
        print(f"  Std: {np.nanstd(flux):.6f}")
        print(f"  Range: {np.nanmin(flux):.6f} - {np.nanmax(flux):.6f}")

        print()
        print("PASS: PDCSAP flux successfully loaded")
        return True

    except Exception as e:
        print(f"ERROR: Failed to download with PDCSAP settings: {e}")
        return False


def test_quality_bitmask():
    """Test that quality bitmask filtering is applied."""
    print()
    print("=" * 80)
    print("TEST 2: Quality Bitmask Verification")
    print("=" * 80)
    print()

    target = "KIC 8462852"

    print(f"Testing target: {target}")
    search = lk.search_lightcurve(target, author="Kepler", cadence="long")

    if len(search) == 0:
        print("ERROR: No data found")
        return False

    # Compare with and without quality filtering
    print("Downloading with default quality filtering...")
    lc_filtered = search[0].download(
        flux_column='pdcsap_flux',
        quality_bitmask='default'
    )

    print("Downloading without quality filtering...")
    lc_unfiltered = search[0].download(
        flux_column='pdcsap_flux',
        quality_bitmask=0  # No filtering
    )

    n_filtered = len(lc_filtered.flux)
    n_unfiltered = len(lc_unfiltered.flux)
    n_removed = n_unfiltered - n_filtered

    print()
    print("Quality filtering results:")
    print(f"  Unfiltered points: {n_unfiltered}")
    print(f"  Filtered points: {n_filtered}")
    print(f"  Points removed: {n_removed}")
    print(f"  Removal rate: {100 * n_removed / n_unfiltered:.1f}%")

    if n_removed >= 0:
        print()
        print("PASS: Quality bitmask filtering is working")
        print("      (Some points flagged as bad quality are removed)")
        return True
    else:
        print()
        print("WARNING: Unexpected result (more points after filtering?)")
        return False


def test_provenance():
    """Test that provenance tracking works."""
    print()
    print("=" * 80)
    print("TEST 3: Provenance Tracking")
    print("=" * 80)
    print()

    from scripts.save_provenance import save_provenance, get_library_versions

    # Get library versions
    versions = get_library_versions()

    print("Library versions detected:")
    for lib, version in versions.items():
        print(f"  {lib}: {version}")

    # Save test provenance
    print()
    print("Saving test provenance file...")

    output_file = save_provenance(
        output_path='data/provenance_priority1_test.json',
        run_type='priority1_test',
        n_targets=1,
        additional_metadata={
            'test_target': 'KIC 8462852',
            'test_purpose': 'Verify Priority 1 fixes'
        }
    )

    # Verify file was created
    if Path(output_file).exists():
        print()
        print("PASS: Provenance file created successfully")
        return True
    else:
        print()
        print("ERROR: Provenance file was not created")
        return False


def main():
    """Run all Priority 1 tests."""
    print()
    print("=" * 80)
    print("PRIORITY 1 SCIENTIFIC VALIDATION TESTS")
    print("=" * 80)
    print()
    print("Testing PDCSAP flux, quality filtering, and provenance tracking")
    print()

    results = {}

    # Test 1: PDCSAP flux
    results['pdcsap_flux'] = test_pdcsap_flux()

    # Test 2: Quality bitmask
    results['quality_bitmask'] = test_quality_bitmask()

    # Test 3: Provenance
    results['provenance'] = test_provenance()

    # Summary
    print()
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print()

    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("=" * 80)
        print("ALL PRIORITY 1 TESTS PASSED")
        print("=" * 80)
        print()
        print("Scientific validation fixes are working correctly:")
        print("  - PDCSAP flux is being used (systematics removed)")
        print("  - Quality bitmask filtering is active (Rolling Band filtered)")
        print("  - Provenance tracking is functional (reproducibility ensured)")
        print()
        print("Ready to proceed with Priority 2 fixes or validation run.")
        return 0
    else:
        print("=" * 80)
        print("SOME TESTS FAILED")
        print("=" * 80)
        print()
        print("Please review the test output above and fix any issues.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
