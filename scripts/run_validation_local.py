#!/usr/bin/env python3
"""
Run Full Validation with Local Processing

This is the master script that:
1. Generates download URLs for validation targets (900 quiet + 100 anomalies)
2. Downloads FITS files directly from MAST (no API rate limits)
3. Processes files locally and uploads features to Supabase
4. Cleans up FITS files to save disk space

Run this to validate the full pipeline without API rate limiting issues.
"""

import sys
import os
from pathlib import Path
import logging
import time
import asyncio
import shutil

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("=" * 80)
    logger.info("XENOSCAN LOCAL VALIDATION PIPELINE")
    logger.info("=" * 80)
    logger.info("")
    logger.info("This script will:")
    logger.info("  1. Generate direct download URLs for 1000 validation targets")
    logger.info("  2. Download FITS files from MAST (no API rate limits)")
    logger.info("  3. Extract features locally and upload to Supabase")
    logger.info("  4. Clean up FITS files to save disk space")
    logger.info("")

    # Paths
    base_dir = Path(__file__).parent.parent
    data_dir = base_dir / "data"
    fits_cache = data_dir / "fits_cache"

    quiet_file = data_dir / "quiet_stars_900.txt"
    planet_file = data_dir / "known_planets_100.txt"

    quiet_urls = data_dir / "quiet_stars_900_urls.txt"
    planet_urls = data_dir / "known_planets_100_urls.txt"
    all_urls = data_dir / "validation_1000_urls.txt"

    # Check input files exist
    if not quiet_file.exists():
        logger.error(f"Missing: {quiet_file}")
        logger.error("Run: python scripts/fetch_quiet_stars.py")
        return 1

    if not planet_file.exists():
        logger.error(f"Missing: {planet_file}")
        logger.error("Run: python scripts/fetch_planet_hosts.py")
        return 1

    # ================================================================
    # STEP 1: Generate Download URLs
    # ================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 1: Generating Download URLs")
    logger.info("=" * 60)

    from scripts.generate_download_urls import process_target_list

    # Generate URLs for quiet stars
    if not quiet_urls.exists():
        logger.info(f"Generating URLs for quiet stars...")
        process_target_list(quiet_file, quiet_urls)
    else:
        logger.info(f"Using existing: {quiet_urls}")

    # Generate URLs for planet hosts (skip for now - MAST rate limiting)
    # TODO: Add planet hosts later with pre-built KIC lookup table
    if planet_urls.exists():
        logger.info(f"Using existing: {planet_urls}")
        with open(planet_urls, 'r') as f:
            planet_url_list = [line.strip() for line in f if line.strip()]
    else:
        logger.info(f"Skipping planet hosts for now (will add later)")
        logger.info(f"Proceeding with 900 quiet stars only")
        planet_url_list = []

    # Combine into single file
    logger.info(f"Combining URL files...")
    all_url_list = []

    with open(quiet_urls, 'r') as f:
        all_url_list.extend([line.strip() for line in f if line.strip()])

    all_url_list.extend(planet_url_list)

    with open(all_urls, 'w') as f:
        for url in all_url_list:
            f.write(url + '\n')

    logger.info(f"Total URLs: {len(all_url_list)}")

    # ================================================================
    # STEP 2: Download FITS Files
    # ================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2: Downloading FITS Files")
    logger.info("=" * 60)

    from scripts.bulk_downloader import BulkDownloader

    downloader = BulkDownloader(
        output_dir=fits_cache,
        max_workers=4,  # Direct downloads can be more parallel than API
        retry_attempts=3,
        timeout=60,
    )

    download_results = downloader.download_from_file(all_urls)

    download_success = sum(1 for r in download_results if r.success)
    logger.info(f"Downloaded: {download_success}/{len(download_results)} files")

    if download_success == 0:
        logger.error("No files downloaded! Check network connection.")
        return 1

    # ================================================================
    # STEP 3: Process Locally and Upload
    # ================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 3: Extracting Features and Uploading")
    logger.info("=" * 60)

    from scripts.local_processor import LocalProcessor
    from preprocessing.database import XenoscanDatabase

    # Connect to Supabase
    try:
        db = XenoscanDatabase()
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        logger.error("Check your .env file has SUPABASE_URL and SUPABASE_KEY")
        return 1

    processor = LocalProcessor(
        fits_dir=fits_cache,
        database_client=db,
        max_workers=2,  # CPU-bound, keep conservative
        delete_after_processing=True,  # Clean up to save disk space
    )

    # Find all downloaded targets
    targets = processor.get_available_targets()
    logger.info(f"Found {len(targets)} targets to process")

    # Process in batches
    batch_size = 50
    all_results = []

    for i in range(0, len(targets), batch_size):
        batch = targets[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(targets) + batch_size - 1) // batch_size

        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} targets)...")

        results = await processor.process_batch(batch)
        all_results.extend(results)

        # Progress update
        n_done = len(all_results)
        n_success = sum(1 for r in all_results if r.get('success', False))
        logger.info(f"  Progress: {n_success}/{n_done} successful ({100*n_success/n_done:.1f}%)")

    processor.shutdown()

    # ================================================================
    # FINAL SUMMARY
    # ================================================================
    logger.info("")
    logger.info("=" * 80)
    logger.info("VALIDATION COMPLETE")
    logger.info("=" * 80)

    n_success = sum(1 for r in all_results if r.get('success', False))
    n_failed = len(all_results) - n_success

    logger.info(f"Targets processed: {len(all_results)}")
    logger.info(f"Successful: {n_success} ({100*n_success/len(all_results):.1f}%)")
    logger.info(f"Failed: {n_failed}")
    logger.info("")

    # Check disk cleanup
    remaining_files = list(fits_cache.rglob("*.fits"))
    if remaining_files:
        logger.info(f"Note: {len(remaining_files)} FITS files still on disk")
        logger.info(f"  Location: {fits_cache}")
    else:
        logger.info("Disk cleanup complete - no FITS files remaining")

    logger.info("")
    logger.info("Features are now in Supabase. Run queries to validate:")
    logger.info("  SELECT COUNT(*) FROM features;")
    logger.info("  SELECT target_id, stat_mean, stat_std FROM features LIMIT 10;")

    if n_success >= 900:  # 90% success
        logger.info("")
        logger.info("VALIDATION PASSED!")
        return 0
    else:
        logger.warning("")
        logger.warning(f"VALIDATION INCOMPLETE - only {100*n_success/len(all_results):.1f}% success")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
