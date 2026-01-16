#!/usr/bin/env python3
"""
Generate Direct Download URLs for Kepler FITS Files

Takes a list of KIC IDs or Kepler planet names and generates
direct MAST download URLs - no API calls needed for downloading.

URL Pattern:
https://archive.stsci.edu/missions/kepler/lightcurves/{first4}/{kic9}/kplr{kic9}-{timestamp}_llc.fits
"""

import sys
from pathlib import Path
import logging
import requests
from typing import List, Tuple, Optional
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Base URL for Kepler lightcurves
MAST_BASE = "https://archive.stsci.edu/missions/kepler/lightcurves"


def kic_to_url_components(kic_id: str) -> Tuple[str, str]:
    """
    Convert a KIC ID to URL path components.

    Args:
        kic_id: KIC identifier like "KIC 7584294" or "7584294"

    Returns:
        Tuple of (first4digits, kic9digit)
    """
    # Extract just the number
    kic_num = re.sub(r'[^0-9]', '', kic_id)

    # Pad to 9 digits
    kic9 = kic_num.zfill(9)

    # First 4 digits for directory
    first4 = kic9[:4]

    return first4, kic9


def resolve_kepler_name_to_kic(kepler_name: str) -> Optional[str]:
    """
    Resolve a Kepler planet name (like "Kepler-10") to its KIC ID.
    Uses lightkurve's search function which handles name resolution well.

    Args:
        kepler_name: Planet name like "Kepler-10" or "Kepler-442"

    Returns:
        KIC ID string or None if not found
    """
    import lightkurve as lk

    # Clean up the name
    name = kepler_name.strip()

    try:
        # Use lightkurve to search - it resolves names via MAST
        search_result = lk.search_lightcurve(name, author='Kepler', cadence='long')

        if len(search_result) > 0:
            # Extract KIC ID from the target name in search results
            # Format is typically "kplr012345678" or similar
            target_name = search_result[0].target_name

            # Handle MaskedArray or other array types
            if hasattr(target_name, 'item'):
                target_name = target_name.item()
            if hasattr(target_name, '__iter__') and not isinstance(target_name, str):
                target_name = str(target_name[0]) if len(target_name) > 0 else ''
            target_name = str(target_name)

            # Try to extract the numeric KIC ID
            if 'kplr' in target_name.lower():
                kic_num = target_name.lower().replace('kplr', '').split('-')[0].split('_')[0]
                # Remove leading zeros for cleaner ID
                kic_id = str(int(kic_num))
                return kic_id
            elif target_name.isdigit():
                return target_name
            else:
                # Try the target_name directly
                return target_name.replace('KIC ', '').strip()

    except Exception as e:
        logger.warning(f"Failed to resolve {kepler_name} via lightkurve: {e}")

    # Fallback: Try NASA Exoplanet Archive
    try:
        tap_url = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
        query = f"SELECT DISTINCT kepid FROM pscomppars WHERE hostname = '{name}' AND kepid IS NOT NULL"

        response = requests.get(tap_url, params={
            'query': query,
            'format': 'json'
        }, timeout=30)

        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                kic = str(data[0].get('kepid', ''))
                if kic:
                    return kic
    except Exception as e:
        logger.debug(f"TAP fallback also failed for {kepler_name}: {e}")

    return None


def get_fits_urls_for_target(kic_id: str) -> List[str]:
    """
    Get all FITS file URLs for a given KIC target.

    This scrapes the MAST directory listing to find all available files.

    Args:
        kic_id: KIC identifier

    Returns:
        List of full URLs to FITS files
    """
    first4, kic9 = kic_to_url_components(kic_id)

    # Directory URL for this target
    dir_url = f"{MAST_BASE}/{first4}/{kic9}/"

    try:
        response = requests.get(dir_url, timeout=30)

        if response.status_code == 404:
            logger.warning(f"No data found for KIC {kic_id}")
            return []

        if response.status_code != 200:
            logger.warning(f"Failed to fetch directory for KIC {kic_id}: HTTP {response.status_code}")
            return []

        # Parse HTML to find FITS file links
        # Looking for: href="kplr007584294-2009131105131_llc.fits"
        fits_pattern = re.compile(r'href="(kplr\d+-\d+_llc\.fits)"')
        matches = fits_pattern.findall(response.text)

        # Build full URLs
        urls = [f"{dir_url}{filename}" for filename in matches]

        return urls

    except Exception as e:
        logger.error(f"Error fetching URLs for KIC {kic_id}: {e}")
        return []


def process_target_list(input_file: Path, output_file: Path):
    """
    Process a target list file and generate download URLs.

    Args:
        input_file: Path to file with target IDs (one per line)
        output_file: Path to write URLs (one per line)
    """
    # Read targets
    with open(input_file, 'r') as f:
        targets = [line.strip() for line in f if line.strip()]

    logger.info(f"Processing {len(targets)} targets from {input_file}")

    all_urls = []
    kic_mapping = {}  # For reference: target_name -> KIC

    for i, target in enumerate(targets):
        # Check if it's a Kepler planet name (needs resolution)
        if target.lower().startswith('kepler-'):
            logger.info(f"[{i+1}/{len(targets)}] Resolving {target}...")
            kic = resolve_kepler_name_to_kic(target)
            if kic:
                kic_mapping[target] = kic
                logger.info(f"  -> KIC {kic}")
            else:
                logger.warning(f"  -> Could not resolve {target}, skipping")
                continue
        else:
            # Already a KIC ID
            kic = target
            kic_mapping[target] = kic

        # Get FITS URLs for this target
        urls = get_fits_urls_for_target(kic)

        if urls:
            all_urls.extend(urls)
            logger.info(f"[{i+1}/{len(targets)}] {target}: {len(urls)} files")
        else:
            logger.warning(f"[{i+1}/{len(targets)}] {target}: no files found")

    # Write URLs to output file
    with open(output_file, 'w') as f:
        for url in all_urls:
            f.write(url + '\n')

    logger.info(f"")
    logger.info(f"Summary:")
    logger.info(f"  Targets processed: {len(targets)}")
    logger.info(f"  Total FITS files: {len(all_urls)}")
    logger.info(f"  URLs written to: {output_file}")

    # Also write KIC mapping for reference
    mapping_file = output_file.parent / f"{output_file.stem}_kic_mapping.txt"
    with open(mapping_file, 'w') as f:
        for target, kic in kic_mapping.items():
            f.write(f"{target}\t{kic}\n")
    logger.info(f"  KIC mapping written to: {mapping_file}")

    return all_urls


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python generate_download_urls.py <input_file> [output_file]")
        print("")
        print("Examples:")
        print("  python generate_download_urls.py data/quiet_stars_900.txt")
        print("  python generate_download_urls.py data/known_planets_100.txt data/planet_urls.txt")
        sys.exit(1)

    input_file = Path(sys.argv[1])

    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Default output file
    if len(sys.argv) >= 3:
        output_file = Path(sys.argv[2])
    else:
        output_file = input_file.parent / f"{input_file.stem}_urls.txt"

    process_target_list(input_file, output_file)


if __name__ == "__main__":
    main()
