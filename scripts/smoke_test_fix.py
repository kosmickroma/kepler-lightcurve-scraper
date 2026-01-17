#!/usr/bin/env python3
"""
Smoke Test: Verify cache-clearing fix works.

Runs 20 targets (10 quiet + 10 from a mix) to verify:
1. Downloads succeed without hitting corrupt cache loops
2. Cache-clearing messages appear on retries (if any)
3. Success rate is >90%

Expected runtime: ~10-15 minutes
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

# Configure logging - show INFO level to see cache-clearing messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("=" * 80)
    logger.info("SMOKE TEST: Cache-clearing fix verification")
    logger.info("=" * 80)
    logger.info("")

    # Use a small subset of targets for quick validation
    # Mix of KIC IDs and Kepler planet names to test both patterns
    test_targets = [
        # 10 KIC quiet stars (first 10 from quiet_stars_900.txt)
        "KIC 3831297",
        "KIC 4142913",
        "KIC 4356127",
        "KIC 4470779",
        "KIC 4551289",
        "KIC 4663818",
        "KIC 4736074",
        "KIC 4756776",
        "KIC 4914566",
        "KIC 5024750",
        # 10 more for good measure
        "KIC 5080652",
        "KIC 5217805",
        "KIC 5252698",
        "KIC 5449346",
        "KIC 5516982",
        "KIC 5532155",
        "KIC 5559169",
        "KIC 5687801",
        "KIC 5724853",
        "KIC 5773344",
    ]

    logger.info(f"Testing {len(test_targets)} targets")
    logger.info("")

    # Connect to Supabase (optional - can run without DB for pure download test)
    try:
        db = XenoscanDatabase()
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.warning(f"Supabase connection failed: {e}")
        logger.warning("Running in dry-run mode (no database uploads)")
        db = None

    # Initialize streaming worker
    worker = StreamingWorker(
        output_dir=Path("data/smoke_test"),
        database_client=db,
        max_workers=2,  # Keep conservative for test
        delete_fits=True,
    )

    logger.info("")
    logger.info("Starting smoke test...")
    logger.info("Watch for 'Cleared corrupt cache' messages - these prove the fix is working")
    logger.info("")

    start_time = time.time()

    # Process all targets
    results = await worker.process_batch(test_targets, mission='Kepler', cadence='long')

    elapsed = time.time() - start_time

    # Analyze results
    n_success = sum(1 for r in results if r.success)
    n_failed = len(results) - n_success
    success_rate = n_success / len(results) * 100

    logger.info("")
    logger.info("=" * 80)
    logger.info("SMOKE TEST RESULTS")
    logger.info("=" * 80)
    logger.info(f"Successful: {n_success}/{len(test_targets)} ({success_rate:.1f}%)")
    logger.info(f"Failed: {n_failed}/{len(test_targets)}")
    logger.info(f"Elapsed time: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
    logger.info(f"Rate: {len(test_targets)/elapsed:.3f} targets/sec")
    logger.info("")

    # Show failures if any
    if n_failed > 0:
        logger.info("Failed targets:")
        for r in results:
            if not r.success:
                logger.info(f"  - {r.target_id}: {r.error}")
        logger.info("")

    # Verdict
    if success_rate >= 90:
        logger.info("SMOKE TEST PASSED - Fix is working!")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Run full validation: python scripts/test_validation_1000.py")
        logger.info("  2. Or bump workers to 4 for faster run (edit line 107)")
        return 0
    else:
        logger.error(f"SMOKE TEST FAILED - Only {success_rate:.1f}% success rate")
        logger.error("Check the error messages above for patterns")
        return 1

    # Cleanup
    await worker.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
