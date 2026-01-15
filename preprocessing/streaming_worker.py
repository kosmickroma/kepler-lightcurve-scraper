"""
Streaming Pipeline Worker

Each worker performs the complete pipeline:
Download → Extract → Upload → Delete → Checkpoint

This is the REAL system - no shortcuts, all 55 features.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Any
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict
import os

from preprocessing.downloader import AsyncDownloader, DownloadResult
from preprocessing.feature_extractor import FeatureExtractor

logger = logging.getLogger(__name__)


# Module-level function for multiprocessing (must be pickleable)
def extract_features_standalone(fits_path_str: str, mission: str) -> tuple:
    """
    Standalone feature extraction function for ProcessPoolExecutor.

    MUST be module-level to be pickleable on Windows.

    Args:
        fits_path_str: Path to FITS file (as string)
        mission: Mission name

    Returns:
        Tuple of (features dict, validity dict)
    """
    try:
        from pathlib import Path
        import os
        import astropy.io.fits as fitsio
        fitsio.Conf.use_memmap = False  # Disable mmap for WSL2 compatibility
        from preprocessing.feature_extractor import FeatureExtractor
        import logging

        logger = logging.getLogger(__name__)

        extractor = FeatureExtractor()
        features, validity = extractor.extract_features_from_fits(
            Path(fits_path_str),
            mission=mission
        )

        # DEBUG: Log what we extracted
        if features:
            logger.info(f"[WORKER PID={os.getpid()}] Extracted from {Path(fits_path_str).name}: stat_mean={features.get('stat_mean'):.10f}, n_points={features.get('temp_n_points')}")

        return features, validity
    except Exception as e:
        import logging
        logging.error(f"Feature extraction failed: {e}")
        return None, None


@dataclass
class PipelineResult:
    """Result from complete pipeline execution."""
    target_id: str
    success: bool
    download_time: float
    extraction_time: float
    upload_time: float
    total_time: float
    n_points: int
    n_features_valid: int
    n_features_total: int
    error: Optional[str] = None
    filepath_deleted: bool = False


class StreamingWorker:
    """
    Streaming pipeline worker that processes targets end-to-end.

    Each target goes through:
    1. Download FITS file (async, ~17s)
    2. Extract 55 features (CPU-bound, ~32s)
    3. Upload to database (async, ~0.1s)
    4. Delete FITS file (save disk space)
    5. Return metrics

    Workers run in parallel via asyncio + ProcessPoolExecutor.
    """

    def __init__(
        self,
        output_dir: Path,
        database_client: Optional[Any] = None,
        max_workers: int = 2,  # Conservative default for stability
        timeout: float = 180.0,  # 3 minutes per target (rate-limit safe)
        delete_fits: bool = True,
    ):
        """
        Initialize streaming worker.

        Args:
            output_dir: Directory for temporary FITS files
            database_client: Database client for uploads (None = dry run)
            max_workers: Maximum concurrent workers
            timeout: Download timeout per target
            delete_fits: Delete FITS after extraction (recommended)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.database_client = database_client
        self.max_workers = max_workers
        self.timeout = timeout
        self.delete_fits = delete_fits

        # Downloader (async)
        self.downloader = AsyncDownloader(
            output_dir=output_dir,
            max_workers=max_workers,
            timeout=timeout,
        )

        # Feature extractor (will run in process pool)
        self.extractor = FeatureExtractor()

        # Process pool for CPU-bound extraction
        # Cap CPU-bound workers lower than I/O workers (memory safety)
        # Feature extraction is memory-intensive, limit parallel processes
        cpu_workers = min(max_workers, 2)  # Conservative: max 2 CPU processes
        # CRITICAL: max_tasks_per_child=1 prevents worker reuse and caching bugs
        # Without this, lightkurve caches FITS data at process level causing
        # identical feature values for different targets
        self.process_pool = ProcessPoolExecutor(
            max_workers=cpu_workers,
            max_tasks_per_child=1  # Fresh process for each extraction
        )

        logger.info(
            f"StreamingWorker initialized: {max_workers} I/O workers, "
            f"{cpu_workers} CPU workers (feature extraction)"
        )

        # Metrics
        self.targets_processed = 0
        self.targets_succeeded = 0
        self.targets_failed = 0
        self.upload_count = 0  # Track uploads for batch sleep

    async def process_target(
        self,
        target_id: str,
        mission: str = 'Kepler',
        cadence: str = 'long',
    ) -> PipelineResult:
        """
        Process single target through complete pipeline.

        Args:
            target_id: Target identifier
            mission: Mission name
            cadence: Cadence type

        Returns:
            PipelineResult with timing and success info
        """
        start_time = time.time()
        download_time = 0.0
        extraction_time = 0.0
        upload_time = 0.0

        try:
            # Step 1: Download FITS file
            logger.debug(f"[{target_id}] Downloading...")
            dl_start = time.time()

            results = await self.downloader.download_batch(
                [target_id],
                mission=mission,
                cadence=cadence,
                progress_callback=None,
            )

            download_result = results[0]
            download_time = time.time() - dl_start

            if not download_result.success:
                return PipelineResult(
                    target_id=target_id,
                    success=False,
                    download_time=download_time,
                    extraction_time=0.0,
                    upload_time=0.0,
                    total_time=time.time() - start_time,
                    n_points=0,
                    n_features_valid=0,
                    n_features_total=55,
                    error=f"Download failed: {download_result.error}",
                )

            fits_path = download_result.filepath

            # Step 2: Extract features (CPU-bound, run in process pool)
            logger.debug(f"[{target_id}] Extracting features...")
            ext_start = time.time()

            # Run extraction in process pool to avoid GIL
            # Use standalone function (not method) for Windows pickling
            loop = asyncio.get_event_loop()

            # DEBUG: Log what we're passing to executor
            fits_path_str = str(fits_path)
            logger.info(f"[PASS to executor] {target_id}: passing path={fits_path_str}")

            features, validity = await loop.run_in_executor(
                self.process_pool,
                extract_features_standalone,
                fits_path_str,  # Pass as string (pickleable)
                mission,
            )

            extraction_time = time.time() - ext_start

            if features is None:
                return PipelineResult(
                    target_id=target_id,
                    success=False,
                    download_time=download_time,
                    extraction_time=extraction_time,
                    upload_time=0.0,
                    total_time=time.time() - start_time,
                    n_points=download_result.n_points,
                    n_features_valid=0,
                    n_features_total=55,
                    error="Feature extraction failed",
                    filepath_deleted=False,
                )

            n_valid = sum(validity.values())

            # Step 3: Upload to database
            logger.debug(f"[{target_id}] Uploading to database...")
            upload_start = time.time()

            if self.database_client is not None:
                await self._upload_to_database(
                    target_id=target_id,
                    features=features,
                    validity=validity,
                    metadata={
                        'mission': mission,
                        'n_points': download_result.n_points,
                        'duration_days': download_result.duration_days,
                        'extraction_time': extraction_time,
                    }
                )

            upload_time = time.time() - upload_start

            # Step 4: Delete FITS file (save disk space)
            filepath_deleted = False
            if self.delete_fits and fits_path and fits_path.exists():
                try:
                    os.remove(fits_path)
                    filepath_deleted = True
                    logger.debug(f"[{target_id}] Deleted FITS: {fits_path}")
                except Exception as e:
                    logger.warning(f"[{target_id}] Failed to delete FITS: {e}")

            # Success!
            total_time = time.time() - start_time

            self.targets_processed += 1
            self.targets_succeeded += 1

            return PipelineResult(
                target_id=target_id,
                success=True,
                download_time=download_time,
                extraction_time=extraction_time,
                upload_time=upload_time,
                total_time=total_time,
                n_points=download_result.n_points,
                n_features_valid=n_valid,
                n_features_total=55,
                error=None,
                filepath_deleted=filepath_deleted,
            )

        except Exception as e:
            logger.error(f"[{target_id}] Pipeline failed: {e}", exc_info=True)
            self.targets_processed += 1
            self.targets_failed += 1

            return PipelineResult(
                target_id=target_id,
                success=False,
                download_time=download_time,
                extraction_time=extraction_time,
                upload_time=upload_time,
                total_time=time.time() - start_time,
                n_points=0,
                n_features_valid=0,
                n_features_total=55,
                error=str(e),
            )

    async def _upload_to_database(
        self,
        target_id: str,
        features: Dict[str, Any],
        validity: Dict[str, bool],
        metadata: Dict[str, Any],
    ) -> None:
        """
        Upload features to database.

        Args:
            target_id: Target identifier
            features: Features dict
            validity: Validity dict
            metadata: Additional metadata (mission, n_points, duration)
        """
        if self.database_client is None:
            logger.debug(f"[{target_id}] No database client, skipping upload")
            return

        try:
            # First, insert/update target metadata
            await self.database_client.insert_target(
                target_id=target_id,
                mission=metadata.get('mission', 'unknown'),
                n_points=metadata.get('n_points', 0),
                duration_days=metadata.get('duration_days', 0.0),
            )

            # DEBUG: Log what we're about to upload
            logger.info(f"[UPLOAD] {target_id}: stat_mean={features.get('stat_mean'):.10f}, n_points={features.get('temp_n_points')}")

            # Then insert features
            await self.database_client.insert_features(
                target_id=target_id,
                features=features,
                validity=validity,
                extraction_time=metadata.get('extraction_time', 0.0),
            )

            logger.debug(f"[{target_id}] Uploaded to database")

            # Batch sleep strategy: prevent Supabase throttling
            # Every 50 uploads, sleep for 1 second to give DB time to breathe
            self.upload_count += 1
            if self.upload_count % 50 == 0:
                logger.info(f"[BATCH SLEEP] {self.upload_count} uploads complete, sleeping 1s to prevent DB throttling...")
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"[{target_id}] Database upload failed: {e}")
            raise

    async def process_batch(
        self,
        target_ids: list,
        mission: str = 'Kepler',
        cadence: str = 'long',
    ) -> list[PipelineResult]:
        """
        Process batch of targets in parallel.

        Args:
            target_ids: List of target identifiers
            mission: Mission name
            cadence: Cadence type

        Returns:
            List of PipelineResults
        """
        tasks = [
            self.process_target(target_id, mission, cadence)
            for target_id in target_ids
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        pipeline_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Task failed for {target_ids[i]}: {result}")
                pipeline_results.append(
                    PipelineResult(
                        target_id=target_ids[i],
                        success=False,
                        download_time=0.0,
                        extraction_time=0.0,
                        upload_time=0.0,
                        total_time=0.0,
                        n_points=0,
                        n_features_valid=0,
                        n_features_total=55,
                        error=str(result),
                    )
                )
            else:
                pipeline_results.append(result)

        return pipeline_results

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get worker metrics.

        Returns:
            Dict with processing statistics
        """
        success_rate = (
            self.targets_succeeded / self.targets_processed
            if self.targets_processed > 0
            else 0.0
        )

        return {
            'targets_processed': self.targets_processed,
            'targets_succeeded': self.targets_succeeded,
            'targets_failed': self.targets_failed,
            'success_rate': success_rate,
        }

    async def shutdown(self):
        """Shutdown worker and cleanup resources."""
        logger.info("Shutting down streaming worker...")
        self.process_pool.shutdown(wait=True)
        logger.info("Process pool shutdown complete")
