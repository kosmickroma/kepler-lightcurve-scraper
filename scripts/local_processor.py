#!/usr/bin/env python3
"""
Local FITS File Processor

Processes downloaded Kepler FITS files locally - no API calls needed.
Reads files from disk, extracts features, uploads to Supabase.

This is the fast path for bulk processing when files are already downloaded.
"""

import sys
import os
import gc
from pathlib import Path
import logging
import time
from typing import Dict, List, Optional, Any
from concurrent.futures import ProcessPoolExecutor
import glob

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import lightkurve as lk
from lightkurve import LightCurveCollection
import astropy.io.fits as fitsio

# Disable memory-mapped I/O for WSL2 compatibility
fitsio.Conf.use_memmap = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def stitch_target_lightcurves(fits_dir: Path, kic_id: str) -> Optional[Any]:
    """
    Load and stitch all quarter lightcurves for a target.

    Args:
        fits_dir: Base directory containing KIC subdirectories
        kic_id: KIC identifier (just the number)

    Returns:
        Stitched LightCurve object or None if failed
    """
    # Normalize KIC ID to 9 digits
    kic_num = str(kic_id).zfill(9)

    # Find the target directory
    target_dir = fits_dir / kic_num

    if not target_dir.exists():
        # Try with leading zeros stripped for directory name
        alt_dirs = list(fits_dir.glob(f"*{kic_id}*"))
        if alt_dirs:
            target_dir = alt_dirs[0]
        else:
            logger.warning(f"No directory found for KIC {kic_id}")
            return None

    # Find all FITS files for this target
    fits_files = sorted(target_dir.glob("*.fits"))

    if not fits_files:
        logger.warning(f"No FITS files found for KIC {kic_id} in {target_dir}")
        return None

    # Load each quarter
    quarter_lcs = []
    for fits_file in fits_files:
        try:
            lc = lk.read(fits_file)
            quarter_lcs.append(lc)
        except Exception as e:
            logger.warning(f"Failed to read {fits_file.name}: {e}")
            continue

    if not quarter_lcs:
        logger.warning(f"No quarters loaded for KIC {kic_id}")
        return None

    # Stitch all quarters together
    try:
        if len(quarter_lcs) == 1:
            stitched = quarter_lcs[0]
        else:
            lc_collection = LightCurveCollection(quarter_lcs)
            stitched = lc_collection.stitch()

        logger.debug(f"KIC {kic_id}: Stitched {len(quarter_lcs)} quarters, {len(stitched.time)} points")
        return stitched

    except Exception as e:
        logger.error(f"Failed to stitch lightcurves for KIC {kic_id}: {e}")
        return None


def extract_features_from_local(
    fits_dir: str,
    kic_id: str,
    mission: str = 'Kepler'
) -> tuple:
    """
    Extract features from local FITS files for a single target.

    This is a standalone function for use with ProcessPoolExecutor.

    Args:
        fits_dir: Path to FITS cache directory
        kic_id: KIC identifier
        mission: Mission name

    Returns:
        Tuple of (kic_id, features dict, validity dict) or (kic_id, None, None) on failure
    """
    try:
        # Import inside function for multiprocessing
        import gc
        import astropy.io.fits as fitsio
        fitsio.Conf.use_memmap = False
        import numpy as np

        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from preprocessing.feature_extractor import FeatureExtractor

        # Load and stitch lightcurves
        fits_path = Path(fits_dir)
        lc = stitch_target_lightcurves(fits_path, kic_id)

        if lc is None:
            return (kic_id, None, None)

        # Extract flux and time arrays from the lightkurve object
        # Remove NaN values and normalize flux
        mask = np.isfinite(lc.flux.value) & np.isfinite(lc.time.value)
        flux = lc.flux.value[mask]
        time = lc.time.value[mask]

        if len(flux) == 0:
            logger.warning(f"KIC {kic_id}: No valid flux points after masking")
            return (kic_id, None, None)

        # Normalize flux to median
        median_flux = np.median(flux)
        if median_flux > 0:
            flux = flux / median_flux
        else:
            logger.warning(f"KIC {kic_id}: Zero median flux")
            return (kic_id, None, None)

        # Extract features (pass flux, time, mission, and lc for centroid features)
        extractor = FeatureExtractor()
        features, validity = extractor.extract_features(flux, time, mission, lc=lc)

        # Add temp metadata for database upload
        features['temp_n_points'] = len(flux)
        features['temp_duration_days'] = float(time[-1] - time[0]) if len(time) > 1 else 0

        # Determine processing_status based on timeout flags
        # (Gemini's "Flag and Fill" - timeouts are CLUES, not garbage)
        bls_timed_out = features.pop('_bls_timed_out', False)  # Remove internal flag
        lz_timed_out = features.pop('_lz_timed_out', False)  # Remove internal flag

        if bls_timed_out and lz_timed_out:
            features['processing_status'] = 'bls_lz_timeout'
        elif bls_timed_out:
            features['processing_status'] = 'bls_timeout'
        elif lz_timed_out:
            features['processing_status'] = 'lz_timeout'
        else:
            features['processing_status'] = 'success'

        logger.info(f"KIC {kic_id}: Extracted {sum(validity.values())}/{len(validity)} valid features (status: {features['processing_status']})")

        # Memory hygiene: prevent bloat over 900 stars
        # (Gemini's Guardrail 3: "Flush the toilet after each star")
        gc.collect()

        return (kic_id, features, validity)

    except Exception as e:
        logger.error(f"KIC {kic_id}: Feature extraction failed: {e}")
        gc.collect()  # Clean up even on failure
        return (kic_id, None, None)


class LocalProcessor:
    """
    Process local FITS files and upload features to database.
    """

    def __init__(
        self,
        fits_dir: Path,
        database_client: Optional[Any] = None,
        max_workers: int = 2,
        delete_after_processing: bool = False,
    ):
        """
        Initialize local processor.

        Args:
            fits_dir: Directory containing downloaded FITS files
            database_client: Database client for uploads (None = dry run)
            max_workers: Number of parallel feature extraction processes
            delete_after_processing: Delete FITS files after feature extraction
        """
        self.fits_dir = Path(fits_dir)
        self.database_client = database_client
        self.max_workers = max_workers
        self.delete_after_processing = delete_after_processing

        # Process pool for CPU-bound feature extraction
        self.process_pool = ProcessPoolExecutor(
            max_workers=max_workers,
            max_tasks_per_child=1  # Fresh process per task to avoid memory issues
        )

        logger.info(
            f"LocalProcessor initialized: {max_workers} workers, "
            f"fits_dir: {fits_dir}, delete_after: {delete_after_processing}"
        )

    def get_available_targets(self) -> List[str]:
        """
        Find all KIC targets with downloaded FITS files.

        Returns:
            List of KIC IDs (as strings)
        """
        # Look for directories that look like KIC IDs
        kic_dirs = []
        for d in self.fits_dir.iterdir():
            if d.is_dir() and d.name.isdigit():
                # Check if it has FITS files
                fits_files = list(d.glob("*.fits"))
                if fits_files:
                    kic_dirs.append(d.name)

        return sorted(kic_dirs)

    async def process_target(self, kic_id: str, mission: str = 'Kepler', is_anomaly: bool = False) -> Dict[str, Any]:
        """
        Process a single target: extract features and upload to database.

        Args:
            kic_id: KIC identifier
            mission: Mission name
            is_anomaly: Ground truth label (False=quiet star, True=known planet host)

        Returns:
            Result dict with success status and metadata
        """
        import asyncio

        start_time = time.time()

        try:
            # Run feature extraction in process pool
            loop = asyncio.get_event_loop()
            kic, features, validity = await loop.run_in_executor(
                self.process_pool,
                extract_features_from_local,
                str(self.fits_dir),
                kic_id,
                mission
            )

            if features is None:
                return {
                    'kic_id': kic_id,
                    'success': False,
                    'error': 'Feature extraction failed',
                    'elapsed': time.time() - start_time
                }

            # Upload to database
            if self.database_client is not None:
                try:
                    # Standardize target ID format
                    # KIC IDs: pad to 9 digits (e.g., "KIC 007584294")
                    # Kepler names: keep as-is (e.g., "Kepler-10")
                    if str(kic_id).isdigit():
                        canonical_id = f"KIC {str(kic_id).zfill(9)}"
                    else:
                        canonical_id = str(kic_id)  # Keep Kepler-X names as-is

                    await self.database_client.insert_target(
                        target_id=canonical_id,
                        mission=mission,
                        n_points=features.get('temp_n_points', 0),
                        duration_days=features.get('temp_duration_days', 0),
                        is_anomaly=is_anomaly,  # Ground truth label
                    )

                    await self.database_client.insert_features(
                        target_id=canonical_id,
                        features=features,
                        validity=validity,
                        extraction_time=time.time() - start_time,
                    )

                    logger.info(f"{canonical_id}: Uploaded to database")

                except Exception as e:
                    logger.error(f"KIC {kic_id}: Database upload failed: {e}")
                    return {
                        'kic_id': kic_id,
                        'success': False,
                        'error': f'Database upload failed: {e}',
                        'elapsed': time.time() - start_time
                    }

            # Optionally delete FITS files
            if self.delete_after_processing:
                kic_dir = self.fits_dir / kic_id.zfill(9)
                if kic_dir.exists():
                    import shutil
                    shutil.rmtree(kic_dir)
                    logger.debug(f"KIC {kic_id}: Deleted FITS files")

            return {
                'kic_id': kic_id,
                'success': True,
                'n_features': sum(validity.values()),
                'elapsed': time.time() - start_time
            }

        except Exception as e:
            logger.error(f"KIC {kic_id}: Processing failed: {e}")
            return {
                'kic_id': kic_id,
                'success': False,
                'error': str(e),
                'elapsed': time.time() - start_time
            }

    async def process_batch(
        self,
        kic_ids: List[str],
        mission: str = 'Kepler',
        is_anomaly: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Process multiple targets.

        Args:
            kic_ids: List of KIC identifiers
            mission: Mission name
            is_anomaly: Ground truth label for all targets in batch

        Returns:
            List of result dicts
        """
        import asyncio

        label = "anomalies" if is_anomaly else "quiet stars"
        logger.info(f"Processing batch of {len(kic_ids)} {label}")

        tasks = [
            self.process_target(kic_id, mission, is_anomaly=is_anomaly)
            for kic_id in kic_ids
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'kic_id': kic_ids[i],
                    'success': False,
                    'error': str(result)
                })
            else:
                processed_results.append(result)

        # Summary
        successful = sum(1 for r in processed_results if r.get('success', False))
        logger.info(f"Batch complete: {successful}/{len(kic_ids)} successful")

        return processed_results

    def shutdown(self):
        """Shutdown the process pool."""
        self.process_pool.shutdown(wait=True)
        logger.info("Process pool shutdown complete")


async def main():
    """Main entry point for local processing."""
    if len(sys.argv) < 2:
        print("Usage: python local_processor.py <fits_dir> [--upload] [--delete]")
        print("")
        print("Examples:")
        print("  python local_processor.py data/fits_cache/           # Dry run")
        print("  python local_processor.py data/fits_cache/ --upload  # Upload to Supabase")
        print("  python local_processor.py data/fits_cache/ --upload --delete  # Upload and cleanup")
        sys.exit(1)

    fits_dir = Path(sys.argv[1])
    do_upload = '--upload' in sys.argv
    do_delete = '--delete' in sys.argv

    if not fits_dir.exists():
        print(f"Error: FITS directory not found: {fits_dir}")
        sys.exit(1)

    # Connect to database if uploading
    db = None
    if do_upload:
        from preprocessing.database import XenoscanDatabase
        db = XenoscanDatabase()
        logger.info("Connected to Supabase")

    # Initialize processor
    processor = LocalProcessor(
        fits_dir=fits_dir,
        database_client=db,
        max_workers=2,
        delete_after_processing=do_delete,
    )

    # Find available targets
    targets = processor.get_available_targets()
    logger.info(f"Found {len(targets)} targets with downloaded FITS files")

    if not targets:
        logger.warning("No targets found to process")
        sys.exit(0)

    # Process all targets
    start_time = time.time()
    results = await processor.process_batch(targets)

    # Final summary
    elapsed = time.time() - start_time
    successful = sum(1 for r in results if r.get('success', False))

    logger.info("")
    logger.info("=" * 60)
    logger.info("PROCESSING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total targets: {len(targets)}")
    logger.info(f"Successful: {successful} ({100*successful/len(targets):.1f}%)")
    logger.info(f"Failed: {len(targets) - successful}")
    logger.info(f"Time elapsed: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
    logger.info(f"Average: {elapsed/len(targets):.1f} sec/target")

    processor.shutdown()

    sys.exit(0 if successful == len(targets) else 1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
