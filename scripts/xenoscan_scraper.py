#!/usr/bin/env python3
"""
🚀 XENOSCAN Production Async Scraper

Bulletproof light curve downloader with:
- 2 concurrent workers by default (conservative, scalable to 10)
- Per-quarter downloads (memory-safe)
- Adaptive rate limiting (auto-backoff on 429)
- Atomic checkpointing every 100 targets
- Real-time progress metrics
- Graceful interruption handling

Target Performance: Stability-first (0.5-2 targets/sec), scalable to 5+ after validation

Usage:
    python scripts/xenoscan_scraper.py --targets 100 --workers 2  # Stability test
    python scripts/xenoscan_scraper.py --resume  # Resume from checkpoint
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from preprocessing.downloader import AsyncDownloader, DownloadMetrics
from preprocessing.checkpoint import CheckpointManager
from preprocessing.rate_limiter import AdaptiveRateLimiter


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class XenoscanScraper:
    """
    Production-grade async scraper with all the bells and whistles.

    This is what impresses NASA.
    """

    def __init__(
        self,
        output_dir: Path = Path("data/raw"),
        checkpoint_dir: Path = Path("checkpoints"),
        max_workers: int = 12,
    ):
        """
        Initialize scraper.

        Args:
            output_dir: Directory to save FITS files
            checkpoint_dir: Directory for checkpoints
            max_workers: Concurrent workers (10-15 recommended)
        """
        self.output_dir = Path(output_dir)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.max_workers = max_workers

        # Initialize components
        self.downloader = AsyncDownloader(
            output_dir=self.output_dir,
            max_workers=self.max_workers,
        )
        self.checkpoint_mgr = CheckpointManager(self.checkpoint_dir)
        self.rate_limiter = AdaptiveRateLimiter()

        # State
        self.downloaded_targets = set()
        self.checkpoint_counter = 0

        logger.info(
            f"🚀 XENOSCAN Scraper initialized: {self.max_workers} workers, "
            f"output={self.output_dir}"
        )

    def load_checkpoint(self) -> dict:
        """Load previous checkpoint if exists."""
        state = self.checkpoint_mgr.load("scraper_checkpoint.json")

        if state:
            self.downloaded_targets = set(state.get('downloaded_targets', []))
            self.checkpoint_counter = state.get('checkpoint_counter', 0)

            logger.info(
                f"📂 Resumed from checkpoint: {len(self.downloaded_targets)} already downloaded"
            )

        return state or {}

    def save_checkpoint(self, target_list: list, current_idx: int) -> None:
        """Save current progress."""
        state = {
            'downloaded_targets': list(self.downloaded_targets),
            'checkpoint_counter': self.checkpoint_counter,
            'total_targets': len(target_list),
            'current_index': current_idx,
            'rate_limiter_stats': self.rate_limiter.get_stats(),
        }

        self.checkpoint_mgr.save(state, "scraper_checkpoint.json")
        self.checkpoint_counter += 1

    def progress_callback(self, metrics: DownloadMetrics) -> None:
        """Handle progress updates."""
        # Print beautiful progress line
        print(f"\r{metrics}", end='', flush=True)

        # Check rate limiter
        if metrics.completed % 100 == 0:
            stats = self.rate_limiter.get_stats()
            if stats['rate_limit_count'] > 0:
                logger.warning(
                    f"Rate limited {stats['rate_limit_count']} times, "
                    f"current backoff: {stats['current_backoff']:.1f}s"
                )

    async def run_batch(
        self,
        target_list: list,
        mission: str = "Kepler",
        cadence: str = "long",
        resume: bool = False,
    ) -> None:
        """
        Run full download batch with checkpointing.

        Args:
            target_list: List of target IDs
            mission: Mission name
            cadence: Cadence type
            resume: Whether to resume from checkpoint
        """
        # Load checkpoint if resuming
        if resume:
            self.load_checkpoint()

        # Filter already downloaded
        remaining = [t for t in target_list if t not in self.downloaded_targets]

        if len(remaining) == 0:
            logger.info("✅ All targets already downloaded!")
            return

        logger.info(
            f"Starting download: {len(remaining)}/{len(target_list)} remaining"
        )

        # Download in checkpointable chunks
        chunk_size = 100
        for i in range(0, len(remaining), chunk_size):
            chunk = remaining[i:i + chunk_size]

            logger.info(f"\n{'='*80}")
            logger.info(f"CHUNK {i//chunk_size + 1}: {len(chunk)} targets")
            logger.info(f"{'='*80}")

            # Download chunk
            results = await self.downloader.download_batch(
                chunk,
                mission=mission,
                cadence=cadence,
                progress_callback=self.progress_callback,
            )

            # Update downloaded set
            for result in results:
                if result.success:
                    self.downloaded_targets.add(result.target_id)

            # Save checkpoint
            self.save_checkpoint(target_list, i + len(chunk))

            print()  # New line after progress
            logger.info(
                f"✅ Chunk complete: {len([r for r in results if r.success])}/{len(chunk)} successful"
            )

        # Final summary
        print(f"\n{'='*80}")
        print("🎉 DOWNLOAD COMPLETE!")
        print(f"{'='*80}")

        final_metrics = self.downloader._calculate_metrics(len(target_list))
        print(f"\n{final_metrics}\n")

        # Save results
        results_path = self.output_dir.parent / "download_results.csv"
        df = self.downloader.save_results(results_path)

        print(f"Results saved: {results_path}")
        print(f"Total downloaded: {len(self.downloaded_targets)}")
        print(f"Success rate: {final_metrics.success_rate*100:.2f}%")


def get_kepler_targets(limit: int) -> list:
    """
    Get list of Kepler targets.

    For now, generates test IDs. In production, would query KIC catalog.

    Args:
        limit: Number of targets

    Returns:
        List of target IDs
    """
    # Sample Kepler targets
    known_targets = [
        'Kepler-10', 'Kepler-11', 'Kepler-16', 'Kepler-22', 'Kepler-62',
        'Kepler-69', 'Kepler-90', 'Kepler-186', 'Kepler-296', 'Kepler-442',
        'Kepler-452', 'Kepler-1649',
    ]

    # Generate KIC IDs
    kic_targets = [f'KIC {2437200 + i}' for i in range(max(0, limit - len(known_targets)))]

    return (known_targets + kic_targets)[:limit]


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='🚀 XENOSCAN Production Async Scraper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--targets',
        type=int,
        default=100,
        help='Number of targets to download (default: 100)',
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=2,
        help='Concurrent workers (conservative default: 2, up to 10 after validation)',
    )

    parser.add_argument(
        '--mission',
        type=str,
        default='Kepler',
        choices=['Kepler', 'TESS', 'K2'],
        help='Mission name (default: Kepler)',
    )

    parser.add_argument(
        '--cadence',
        type=str,
        default='long',
        choices=['long', 'short', 'fast'],
        help='Cadence type (default: long)',
    )

    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from previous checkpoint',
    )

    parser.add_argument(
        '--output',
        type=Path,
        default=Path('data/raw'),
        help='Output directory (default: data/raw)',
    )

    args = parser.parse_args()

    # Print banner
    print()
    print("="*80)
    print("🛸 XENOSCAN PRODUCTION ASYNC SCRAPER")
    print("="*80)
    print(f"Targets:  {args.targets}")
    print(f"Workers:  {args.workers}")
    print(f"Mission:  {args.mission}")
    print(f"Cadence:  {args.cadence}")
    print(f"Output:   {args.output}")
    print(f"Resume:   {args.resume}")
    print("="*80)
    print()

    # Initialize scraper
    scraper = XenoscanScraper(
        output_dir=args.output,
        max_workers=args.workers,
    )

    # Get target list
    target_list = get_kepler_targets(args.targets)

    # Run
    start_time = datetime.now()

    try:
        await scraper.run_batch(
            target_list,
            mission=args.mission,
            cadence=args.cadence,
            resume=args.resume,
        )

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        logger.info("Saving checkpoint before exit...")
        scraper.save_checkpoint(target_list, len(scraper.downloaded_targets))
        print("✅ Checkpoint saved. Run with --resume to continue.")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise

    finally:
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        print(f"\nTotal runtime: {elapsed/60:.1f} minutes")


if __name__ == "__main__":
    asyncio.run(main())
