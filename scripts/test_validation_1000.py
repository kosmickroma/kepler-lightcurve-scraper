#!/usr/bin/env python3
"""
1000-Target Validation Test

Tests:
- 900 quiet stars (baseline, should have "normal" features)
- 100 known planet hosts (should show transit signatures, different features)

Purpose:
1. Validate pipeline at scale (1000 targets)
2. Verify database handles batch processing
3. Confirm features discriminate between quiet vs planet-hosting stars
4. Build baseline for ML training
"""

import sys
import asyncio
from pathlib import Path
import logging
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from preprocessing.streaming_worker import StreamingWorker
from preprocessing.database import XenoscanDatabase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def load_targets(quiet_file, planet_file):
    """Load both target lists and label them."""
    quiet_targets = []
    planet_targets = []

    # Load quiet stars
    quiet_path = Path(quiet_file)
    if not quiet_path.exists():
        raise FileNotFoundError(f"Quiet stars file not found: {quiet_file}")

    with open(quiet_path, 'r') as f:
        quiet_targets = [line.strip() for line in f if line.strip()]

    logger.info(f"Loaded {len(quiet_targets)} quiet stars from {quiet_file}")

    # Load planet hosts
    planet_path = Path(planet_file)
    if not planet_path.exists():
        raise FileNotFoundError(f"Planet hosts file not found: {planet_file}")

    with open(planet_path, 'r') as f:
        planet_targets = [line.strip() for line in f if line.strip()]

    logger.info(f"Loaded {len(planet_targets)} planet hosts from {planet_file}")

    return quiet_targets, planet_targets


async def main():
    logger.info("=" * 80)
    logger.info("1000-TARGET VALIDATION TEST")
    logger.info("=" * 80)
    logger.info("")
    logger.info("This test will:")
    logger.info("  1. Download 900 quiet stars + 100 planet hosts")
    logger.info("  2. Extract all 62 features")
    logger.info("  3. Upload to Supabase")
    logger.info("  4. Verify feature uniqueness")
    logger.info("  5. Compare quiet vs planet-hosting feature distributions")
    logger.info("")
    logger.info("IMPORTANT: This validates the full pipeline before production!")
    logger.info("")

    # Load target lists
    quiet_file = "data/quiet_stars_900.txt"
    planet_file = "data/known_planets_100.txt"

    try:
        quiet_targets, planet_targets = load_targets(quiet_file, planet_file)
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        logger.error("")
        logger.error("Run these first:")
        logger.error("  python scripts/fetch_quiet_stars.py")
        logger.error("  python scripts/fetch_planet_hosts.py")
        return 1

    all_targets = quiet_targets + planet_targets
    logger.info(f"Total targets: {len(all_targets)} (900 quiet + 100 planet hosts)")
    logger.info("")

    # Connect to Supabase
    logger.info("Connecting to Supabase...")
    db = XenoscanDatabase()
    logger.info("Connected to Supabase")

    # Initialize streaming worker (creates its own downloader internally)
    worker = StreamingWorker(
        output_dir=Path("data/validation_1000"),
        database_client=db,
        max_workers=2,  # Conservative for stability
        delete_fits=True,
    )

    logger.info("")
    logger.info("Starting download + feature extraction + upload...")
    logger.info(f"Processing {len(all_targets)} targets...")
    logger.info("")

    # Track start time
    start_time = time.time()

    # Process in batches to show progress
    batch_size = 50
    all_results = []

    for i in range(0, len(all_targets), batch_size):
        batch = all_targets[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(all_targets) + batch_size - 1) // batch_size

        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} targets)...")

        try:
            results = await worker.process_batch(batch, mission='Kepler', cadence='long')
            all_results.extend(results)

            # Progress update
            n_done = len(all_results)
            n_success = sum(1 for r in all_results if r.success)
            elapsed = time.time() - start_time
            rate = n_done / elapsed if elapsed > 0 else 0
            eta = (len(all_targets) - n_done) / rate / 3600 if rate > 0 else 0

            logger.info(f"  Batch complete: {sum(1 for r in results if r.success)}/{len(results)} successful")
            logger.info(f"  Overall: {n_success}/{n_done} ({100*n_success/n_done:.1f}%)")
            logger.info(f"  Rate: {rate:.2f} targets/sec, ETA: {eta:.1f} hours")
            logger.info("")

        except Exception as e:
            logger.error(f"Batch {batch_num} failed: {e}")
            import traceback
            traceback.print_exc()

    elapsed = time.time() - start_time
    elapsed_hours = elapsed / 3600

    # Count successes (PipelineResult has .success attribute)
    n_success = sum(1 for r in all_results if r.success)
    n_failed = len(all_results) - n_success

    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST RESULTS")
    logger.info("=" * 80)
    logger.info(f"Successful: {n_success}/{len(all_targets)}")
    logger.info(f"Failed: {n_failed}/{len(all_targets)}")
    logger.info(f"Elapsed time: {elapsed_hours:.2f} hours ({elapsed/60:.1f} minutes)")
    logger.info("")

    # Verify data in Supabase
    logger.info("=" * 80)
    logger.info("VERIFYING SUPABASE DATA")
    logger.info("=" * 80)
    logger.info("")

    # Check uniqueness of features
    logger.info("Checking feature uniqueness...")
    response = db.client.table('features').select('target_id,stat_mean,temp_n_points').execute()
    df_features = response.data

    if len(df_features) == 0:
        logger.error("No features found in database!")
        await worker.shutdown()
        return 1

    logger.info(f"Total records: {len(df_features)}")

    # Check uniqueness
    import pandas as pd
    df = pd.DataFrame(df_features)
    unique_means = df['stat_mean'].nunique()

    logger.info(f"Unique stat_mean values: {unique_means}")

    if unique_means == len(df_features):
        logger.info("All stat_mean values are unique!")
    else:
        logger.warning(f"Some duplicate stat_mean values found!")
        duplicates = df[df.duplicated(subset=['stat_mean'], keep=False)]
        logger.warning(f"Duplicates: {len(duplicates)} records")

    logger.info("")

    # Compare quiet vs planet-hosting distributions
    logger.info("=" * 80)
    logger.info("FEATURE DISTRIBUTION COMPARISON")
    logger.info("=" * 80)
    logger.info("")

    # Separate quiet vs planet hosts
    df_quiet = df[df['target_id'].isin(quiet_targets)]
    df_planet = df[df['target_id'].isin(planet_targets)]

    logger.info(f"Quiet stars in DB: {len(df_quiet)}")
    logger.info(f"Planet hosts in DB: {len(df_planet)}")
    logger.info("")

    # Compare stat_mean distributions
    if len(df_quiet) > 0 and len(df_planet) > 0:
        logger.info("stat_mean comparison:")
        logger.info(f"  Quiet:   mean={df_quiet['stat_mean'].mean():.10f}, std={df_quiet['stat_mean'].std():.10f}")
        logger.info(f"  Planets: mean={df_planet['stat_mean'].mean():.10f}, std={df_planet['stat_mean'].std():.10f}")
        logger.info("")

    # Shutdown worker
    logger.info("Shutting down streaming worker...")
    await worker.shutdown()

    logger.info("=" * 80)
    logger.info("TEST COMPLETE")
    logger.info("=" * 80)
    logger.info("")
    logger.info(f"{n_success}/{len(all_targets)} targets processed successfully")
    logger.info(f"Total time: {elapsed_hours:.2f} hours")
    logger.info("")

    if n_success >= 950:  # 95% success rate
        logger.info("VALIDATION PASSED - Pipeline ready for production!")
        return 0
    else:
        logger.warning(f"Only {n_success/len(all_targets)*100:.1f}% success rate")
        logger.warning("Investigate failures before production run")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
