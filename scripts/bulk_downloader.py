#!/usr/bin/env python3
"""
Bulk FITS File Downloader

Downloads Kepler FITS files directly from MAST using HTTP requests.
No API rate limiting - just direct file downloads.

Features:
- Parallel downloads (configurable workers)
- Resume capability (skips already downloaded files)
- Progress tracking
- Retry logic for failed downloads
"""

import sys
import os
from pathlib import Path
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
import time
from dataclasses import dataclass
from datetime import datetime
import hashlib

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Result of a single file download."""
    url: str
    filepath: Optional[Path]
    success: bool
    size_bytes: int
    elapsed_seconds: float
    error: Optional[str] = None
    skipped: bool = False


class BulkDownloader:
    """
    Parallel file downloader for MAST FITS files.

    Uses direct HTTP downloads instead of API calls to avoid rate limiting.
    """

    def __init__(
        self,
        output_dir: Path,
        max_workers: int = 4,
        retry_attempts: int = 3,
        timeout: int = 60,
        chunk_size: int = 8192,
    ):
        """
        Initialize the bulk downloader.

        Args:
            output_dir: Directory to save downloaded files
            max_workers: Number of parallel download threads
            retry_attempts: Number of retries for failed downloads
            timeout: Request timeout in seconds
            chunk_size: Download chunk size in bytes
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.max_workers = max_workers
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.chunk_size = chunk_size

        # Progress tracking
        self.total_files = 0
        self.completed_files = 0
        self.failed_files = 0
        self.skipped_files = 0
        self.total_bytes = 0

        # Progress file for resume capability
        self.progress_file = self.output_dir / ".download_progress.txt"

        logger.info(f"BulkDownloader initialized: {max_workers} workers, output: {output_dir}")

    def _get_local_path(self, url: str) -> Path:
        """
        Determine local file path from URL.

        Preserves KIC directory structure:
        URL: .../lightcurves/0075/007584294/kplr007584294-2009131105131_llc.fits
        Local: output_dir/007584294/kplr007584294-2009131105131_llc.fits
        """
        # Extract KIC directory and filename from URL
        parts = url.rstrip('/').split('/')
        filename = parts[-1]  # kplr007584294-2009131105131_llc.fits
        kic_dir = parts[-2]   # 007584294

        # Create KIC subdirectory
        local_dir = self.output_dir / kic_dir
        local_dir.mkdir(parents=True, exist_ok=True)

        return local_dir / filename

    def _download_file(self, url: str) -> DownloadResult:
        """
        Download a single file with retry logic.

        Args:
            url: URL to download

        Returns:
            DownloadResult with status and metadata
        """
        local_path = self._get_local_path(url)

        # Skip if already exists
        if local_path.exists() and local_path.stat().st_size > 0:
            return DownloadResult(
                url=url,
                filepath=local_path,
                success=True,
                size_bytes=local_path.stat().st_size,
                elapsed_seconds=0,
                skipped=True
            )

        # Download with retries
        for attempt in range(1, self.retry_attempts + 1):
            try:
                start_time = time.time()

                response = requests.get(
                    url,
                    timeout=self.timeout,
                    stream=True
                )

                if response.status_code == 200:
                    # Write to temp file first, then rename (atomic)
                    temp_path = local_path.with_suffix('.tmp')

                    with open(temp_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=self.chunk_size):
                            if chunk:
                                f.write(chunk)

                    # Rename to final path
                    temp_path.rename(local_path)

                    elapsed = time.time() - start_time
                    size = local_path.stat().st_size

                    return DownloadResult(
                        url=url,
                        filepath=local_path,
                        success=True,
                        size_bytes=size,
                        elapsed_seconds=elapsed
                    )

                elif response.status_code == 404:
                    return DownloadResult(
                        url=url,
                        filepath=None,
                        success=False,
                        size_bytes=0,
                        elapsed_seconds=0,
                        error="File not found (404)"
                    )

                else:
                    if attempt < self.retry_attempts:
                        time.sleep(2 ** attempt)  # Exponential backoff
                    continue

            except requests.exceptions.Timeout:
                if attempt < self.retry_attempts:
                    logger.warning(f"Timeout on attempt {attempt}/{self.retry_attempts}: {url}")
                    time.sleep(2 ** attempt)
                continue

            except Exception as e:
                if attempt < self.retry_attempts:
                    logger.warning(f"Error on attempt {attempt}/{self.retry_attempts}: {e}")
                    time.sleep(2 ** attempt)
                continue

        # All retries failed
        return DownloadResult(
            url=url,
            filepath=None,
            success=False,
            size_bytes=0,
            elapsed_seconds=0,
            error=f"Failed after {self.retry_attempts} attempts"
        )

    def download_urls(self, urls: List[str], progress_interval: int = 10) -> List[DownloadResult]:
        """
        Download multiple files in parallel.

        Args:
            urls: List of URLs to download
            progress_interval: Log progress every N files

        Returns:
            List of DownloadResults
        """
        self.total_files = len(urls)
        self.completed_files = 0
        self.failed_files = 0
        self.skipped_files = 0
        self.total_bytes = 0

        results = []
        start_time = time.time()

        logger.info(f"Starting download of {len(urls)} files with {self.max_workers} workers")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all downloads
            future_to_url = {
                executor.submit(self._download_file, url): url
                for url in urls
            }

            # Process completions
            for future in as_completed(future_to_url):
                result = future.result()
                results.append(result)

                if result.success:
                    if result.skipped:
                        self.skipped_files += 1
                    else:
                        self.total_bytes += result.size_bytes
                    self.completed_files += 1
                else:
                    self.failed_files += 1
                    logger.warning(f"Failed: {result.url} - {result.error}")

                # Progress logging
                total_done = self.completed_files + self.failed_files
                if total_done % progress_interval == 0 or total_done == len(urls):
                    elapsed = time.time() - start_time
                    rate = total_done / elapsed if elapsed > 0 else 0
                    mb_downloaded = self.total_bytes / (1024 * 1024)

                    logger.info(
                        f"Progress: {total_done}/{len(urls)} "
                        f"({100*total_done/len(urls):.1f}%) | "
                        f"Success: {self.completed_files} | "
                        f"Failed: {self.failed_files} | "
                        f"Skipped: {self.skipped_files} | "
                        f"Downloaded: {mb_downloaded:.1f} MB | "
                        f"Rate: {rate:.2f} files/sec"
                    )

        # Final summary
        elapsed = time.time() - start_time
        logger.info("")
        logger.info("=" * 60)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total files: {len(urls)}")
        logger.info(f"Successful: {self.completed_files} ({100*self.completed_files/len(urls):.1f}%)")
        logger.info(f"Failed: {self.failed_files}")
        logger.info(f"Skipped (existing): {self.skipped_files}")
        logger.info(f"Data downloaded: {self.total_bytes / (1024*1024):.1f} MB")
        logger.info(f"Time elapsed: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        logger.info(f"Average rate: {len(urls)/elapsed:.2f} files/sec")

        return results

    def download_from_file(self, url_file: Path, **kwargs) -> List[DownloadResult]:
        """
        Download files from a URL list file.

        Args:
            url_file: Path to file containing URLs (one per line)
            **kwargs: Additional arguments passed to download_urls

        Returns:
            List of DownloadResults
        """
        with open(url_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        logger.info(f"Loaded {len(urls)} URLs from {url_file}")

        return self.download_urls(urls, **kwargs)


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python bulk_downloader.py <url_file> <output_dir> [workers]")
        print("")
        print("Examples:")
        print("  python bulk_downloader.py data/quiet_stars_900_urls.txt data/fits_cache/ 4")
        print("  python bulk_downloader.py data/all_urls.txt data/fits_cache/ 8")
        sys.exit(1)

    url_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    if not url_file.exists():
        print(f"Error: URL file not found: {url_file}")
        sys.exit(1)

    downloader = BulkDownloader(
        output_dir=output_dir,
        max_workers=workers
    )

    results = downloader.download_from_file(url_file)

    # Exit with error code if any failures
    failed = sum(1 for r in results if not r.success)
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
