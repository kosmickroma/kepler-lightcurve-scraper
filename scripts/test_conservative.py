#!/usr/bin/env python3
"""
Conservative Stability Test

Purpose: Prove the scraper works reliably with safe defaults.
Focus: Stability > Speed

Test Configuration:
- 2 workers (conservative)
- 5 easy targets (low-profile KIC IDs, NOT famous multi-planet systems)
- 180s timeout (3 minutes per target)
- Per-quarter downloads (memory-safe)
- Full diagnostics (memory, timing, bottlenecks)

Success Criteria:
- 5/5 targets succeed (100% success rate)
- Peak memory < 4GB
- No crashes or OOM kills
- Clear identification of bottlenecks

This test proves the architecture is sound before scaling up.
"""

import asyncio
import sys
import logging
import time
from pathlib import Path
import psutil
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from preprocessing.streaming_worker import StreamingWorker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)


class MemoryMonitor:
    """Track memory usage during test."""

    def __init__(self):
        self.process = psutil.Process()
        self.peak_memory_mb = 0
        self.samples = []

    def sample(self):
        """Record current memory usage."""
        mem_mb = self.process.memory_info().rss / 1024 / 1024
        self.samples.append(mem_mb)
        if mem_mb > self.peak_memory_mb:
            self.peak_memory_mb = mem_mb
        return mem_mb

    def report(self):
        """Generate memory report."""
        if not self.samples:
            return "No samples"

        return (
            f"Memory: Peak={self.peak_memory_mb:.1f}MB, "
            f"Mean={np.mean(self.samples):.1f}MB, "
            f"Min={np.min(self.samples):.1f}MB"
        )


async def main():
    logger.info("=" * 80)
    logger.info("CONSERVATIVE STABILITY TEST")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Philosophy: Prove it works correctly FIRST, optimize speed LATER")
    logger.info("")

    # Test configuration - Using REAL Kepler targets with confirmed data
    test_targets = [
        'Kepler-10',    # Known to work (52K points, 1470 days from previous test)
        'KIC 757076',   # Real early Kepler target
        'KIC 757137',   # Real early Kepler target
        'KIC 757450',   # Real early Kepler target
        'KIC 757567',   # Real early Kepler target
    ]

    n_targets = len(test_targets)
    n_workers = 2  # Conservative
    timeout = 180.0  # 3 minutes

    logger.info("Configuration:")
    logger.info(f"  Targets:       {n_targets}")
    logger.info(f"  Workers:       {n_workers} (conservative)")
    logger.info(f"  Timeout:       {timeout}s (3 minutes)")
    logger.info(f"  Download Mode: Per-quarter (memory-safe)")
    logger.info(f"  Features:      All 47")
    logger.info("")
    logger.info("Targets: " + ", ".join(test_targets))
    logger.info("")

    # Success criteria
    logger.info("Success Criteria:")
    logger.info("  ✓ 5/5 targets succeed (100% success rate)")
    logger.info("  ✓ Peak memory < 4GB")
    logger.info("  ✓ No crashes or timeouts")
    logger.info("  ✓ Clear bottleneck identification")
    logger.info("")
    logger.info("=" * 80)
    logger.info("")

    # Initialize components
    worker = StreamingWorker(
        output_dir=Path("data/raw"),
        database_client=None,  # Dry run
        max_workers=n_workers,
        timeout=timeout,
        delete_fits=True,
    )

    memory_monitor = MemoryMonitor()

    # Baseline memory
    baseline_mb = memory_monitor.sample()
    logger.info(f"Baseline memory: {baseline_mb:.1f}MB")
    logger.info("")
    logger.info("-" * 80)
    logger.info("Starting pipeline...")
    logger.info("-" * 80)
    logger.info("")

    # Run test
    start_time = time.time()

    results = await worker.process_batch(
        test_targets,
        mission='Kepler',
        cadence='long',
    )

    total_elapsed = time.time() - start_time

    # Final memory sample
    final_mb = memory_monitor.sample()

    # Analyze results
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST RESULTS")
    logger.info("=" * 80)
    logger.info("")

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    # Overall metrics
    logger.info("Overall Performance:")
    logger.info(f"  Success:     {len(successful)}/{n_targets} ({100*len(successful)/n_targets:.0f}%)")
    logger.info(f"  Failed:      {len(failed)}/{n_targets}")
    logger.info(f"  Total time:  {total_elapsed:.1f}s ({total_elapsed/60:.1f} minutes)")
    logger.info(f"  {memory_monitor.report()}")
    logger.info("")

    # Per-target breakdown
    if successful:
        logger.info("Per-Target Timing:")
        logger.info(f"  {'Target':<15} {'Total':>8} {'Download':>10} {'Extract':>10} {'Upload':>8}")
        logger.info(f"  {'-'*15} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")

        for r in successful:
            logger.info(
                f"  {r.target_id:<15} "
                f"{r.total_time:>7.1f}s "
                f"{r.download_time:>9.1f}s "
                f"{r.extraction_time:>9.1f}s "
                f"{r.upload_time:>7.2f}s"
            )

        logger.info("")

        # Statistics
        total_times = [r.total_time for r in successful]
        download_times = [r.download_time for r in successful]
        extraction_times = [r.extraction_time for r in successful]

        logger.info("Timing Breakdown:")
        logger.info(f"  Total:       {np.mean(total_times):>6.1f}s avg  (range: {np.min(total_times):.1f}s - {np.max(total_times):.1f}s)")
        logger.info(f"  Download:    {np.mean(download_times):>6.1f}s avg  ({100*np.mean(download_times)/np.mean(total_times):.1f}% of total)")
        logger.info(f"  Extraction:  {np.mean(extraction_times):>6.1f}s avg  ({100*np.mean(extraction_times)/np.mean(total_times):.1f}% of total)")
        logger.info("")

        # Bottleneck identification
        mean_download = np.mean(download_times)
        mean_extraction = np.mean(extraction_times)

        logger.info("Bottleneck Analysis:")
        if mean_extraction > mean_download:
            ratio = mean_extraction / mean_download
            logger.info(f"  Current bottleneck: FEATURE EXTRACTION ({ratio:.1f}x slower than download)")
            logger.info(f"  Recommendation: Optimize feature extraction before scaling workers")
        else:
            ratio = mean_download / mean_extraction
            logger.info(f"  Current bottleneck: DOWNLOAD ({ratio:.1f}x slower than extraction)")
            logger.info(f"  Recommendation: Can safely scale workers (download is I/O bound)")
        logger.info("")

    # Failed targets
    if failed:
        logger.info("Failed Targets:")
        for r in failed:
            logger.info(f"  ❌ {r.target_id}: {r.error}")
        logger.info("")

    # Success criteria check
    logger.info("=" * 80)
    logger.info("SUCCESS CRITERIA EVALUATION")
    logger.info("=" * 80)
    logger.info("")

    criteria_met = 0
    criteria_total = 4

    # Criterion 1: Success rate
    success_rate = len(successful) / n_targets
    if success_rate == 1.0:
        logger.info("✓ 100% success rate (5/5 targets)")
        criteria_met += 1
    else:
        logger.info(f"✗ Success rate: {100*success_rate:.0f}% (expected 100%)")

    # Criterion 2: Memory
    if memory_monitor.peak_memory_mb < 4096:
        logger.info(f"✓ Peak memory {memory_monitor.peak_memory_mb:.1f}MB < 4GB limit")
        criteria_met += 1
    else:
        logger.info(f"✗ Peak memory {memory_monitor.peak_memory_mb:.1f}MB exceeds 4GB limit")

    # Criterion 3: No timeouts
    timeout_errors = [r for r in results if r.error and 'timeout' in r.error.lower()]
    if not timeout_errors:
        logger.info("✓ No timeout errors")
        criteria_met += 1
    else:
        logger.info(f"✗ {len(timeout_errors)} timeout errors detected")

    # Criterion 4: Bottleneck identified
    if successful:
        logger.info("✓ Bottleneck identified (see analysis above)")
        criteria_met += 1
    else:
        logger.info("✗ Cannot identify bottleneck (no successful targets)")

    logger.info("")
    logger.info(f"Criteria met: {criteria_met}/{criteria_total}")
    logger.info("")

    # Final verdict
    if criteria_met == criteria_total:
        logger.info("=" * 80)
        logger.info("🎉 TEST PASSED - Architecture is stable and ready for scaling")
        logger.info("=" * 80)
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Test with 100 targets (same workers)")
        logger.info("  2. If stable, increase to 4 workers")
        logger.info("  3. Test again with 100 targets")
        logger.info("  4. Repeat until bottleneck shifts or memory pressure appears")
        exit_code = 0
    else:
        logger.info("=" * 80)
        logger.info("⚠️  TEST FAILED - Fix issues before scaling")
        logger.info("=" * 80)
        exit_code = 1

    # Cleanup
    await worker.shutdown()

    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
