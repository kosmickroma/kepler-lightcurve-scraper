#!/usr/bin/env python3
"""
Supabase Integration Test - 10 Targets

Validates that features are correctly uploaded to database with unique values.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from preprocessing.streaming_worker import StreamingWorker
from preprocessing.database import XenoscanDatabase

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("=" * 80)
    logger.info("SUPABASE INTEGRATION TEST")
    logger.info("=" * 80)
    logger.info("")
    logger.info("This test will:")
    logger.info("  1. Download 10 Kepler targets")
    logger.info("  2. Extract all 55 features")
    logger.info("  3. Upload to Supabase")
    logger.info("  4. Verify data format")
    logger.info("")
    logger.info("⚠️  CRITICAL: This validates data format before full run!")
    logger.info("")

    # Load targets from official list
    target_file = Path("data/targets_all_kepler.txt")

    if not target_file.exists():
        logger.error("❌ Target list not found!")
        logger.error(f"   Expected: {target_file}")
        return

    # Get first 10 targets (known good from previous test)
    with open(target_file) as f:
        all_targets = [line.strip() for line in f if line.strip()]

    test_targets = all_targets[:10]

    logger.info(f"Test targets: {test_targets}")
    logger.info("")

    # Initialize database client
    logger.info("Connecting to Supabase...")
    try:
        db = XenoscanDatabase()
        logger.info("✅ Connected to Supabase")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Supabase: {e}")
        logger.error("   Check .env file has SUPABASE_URL and SUPABASE_KEY")
        return

    # Initialize worker
    output_dir = Path("data/test_supabase")
    output_dir.mkdir(parents=True, exist_ok=True)

    worker = StreamingWorker(
        output_dir=output_dir,
        database_client=db,  # Pass database client
        max_workers=2,  # Conservative for test
        delete_fits=True,  # Clean up after
    )
    logger.info("")

    # Process targets
    logger.info("Starting download + feature extraction + upload...")
    logger.info("")

    results = await worker.process_batch(
        test_targets,
        mission="Kepler",
        cadence="long",
    )

    # Analyze results
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST RESULTS")
    logger.info("=" * 80)

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    logger.info(f"Successful: {len(successful)}/{len(test_targets)}")
    logger.info(f"Failed: {len(failed)}/{len(test_targets)}")
    logger.info("")

    if failed:
        logger.warning("Failed targets:")
        for r in failed:
            logger.warning(f"  ❌ {r.target_id}: {r.error}")
        logger.info("")

    # Verify database
    logger.info("=" * 80)
    logger.info("VERIFYING SUPABASE DATA")
    logger.info("=" * 80)
    logger.info("")

    for target_id in [r.target_id for r in successful]:
        logger.info(f"Checking {target_id}...")

        # Check targets table
        try:
            response = db.client.table('targets').select('*').eq('target_id', target_id).execute()
            if response.data:
                target = response.data[0]
                logger.info(f"  ✅ Target found in 'targets' table")
                logger.info(f"     - n_points: {target.get('n_points')}")
                logger.info(f"     - duration_days: {target.get('duration_days')}")
            else:
                logger.warning(f"  ❌ Target not found in 'targets' table")
        except Exception as e:
            logger.error(f"  ❌ Error querying targets: {e}")

        # Check features table
        try:
            response = db.client.table('features').select('*').eq('target_id', target_id).execute()
            if response.data:
                features = response.data[0]

                # Count non-null features
                feature_cols = [k for k in features.keys() if k.startswith(('stat_', 'temp_', 'freq_', 'resid_', 'shape_', 'transit_'))]
                non_null = sum(1 for col in feature_cols if features.get(col) is not None)

                logger.info(f"  ✅ Features found in 'features' table")
                logger.info(f"     - Features extracted: {non_null}/{len(feature_cols)}")
                logger.info(f"     - Sample values:")
                logger.info(f"       stat_mean: {features.get('stat_mean')}")
                logger.info(f"       stat_std: {features.get('stat_std')}")
                logger.info(f"       temp_n_points: {features.get('temp_n_points')}")
            else:
                logger.warning(f"  ❌ Features not found in 'features' table")
        except Exception as e:
            logger.error(f"  ❌ Error querying features: {e}")

        logger.info("")

    # Final check: Verify uniqueness
    logger.info("=" * 80)
    logger.info("UNIQUENESS CHECK")
    logger.info("=" * 80)
    logger.info("")

    try:
        response = db.client.table('features').select('target_id, stat_mean, temp_n_points').like('target_id', 'KIC 10002%').execute()

        if response.data:
            stat_means = [r['stat_mean'] for r in response.data if r['stat_mean'] is not None]
            unique_means = len(set(stat_means))

            logger.info(f"Total records: {len(response.data)}")
            logger.info(f"Unique stat_mean values: {unique_means}")

            if unique_means == len(stat_means):
                logger.info("✅ All stat_mean values are unique!")
            else:
                logger.warning(f"⚠️  Found duplicate stat_mean values!")
                logger.warning(f"   {len(stat_means)} total, {unique_means} unique")
        else:
            logger.warning("No data found for uniqueness check")
    except Exception as e:
        logger.error(f"Error checking uniqueness: {e}")

    logger.info("")

    # Cleanup
    await worker.shutdown()

    logger.info("=" * 80)
    logger.info("TEST COMPLETE")
    logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
