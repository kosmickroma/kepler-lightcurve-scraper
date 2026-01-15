#!/usr/bin/env python3
"""
Upload NASA Catalog Metadata to Supabase

Reads metadata CSV files (CDPP, crowding, stellar params) and uploads to Supabase.
This enriches the targets table with NASA catalog data for scientific analysis.

Run AFTER fetching target lists, BEFORE running validation.
"""

import sys
from pathlib import Path
import pandas as pd
import logging

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from preprocessing.database import SupabaseClient
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

async def upload_metadata(metadata_file: str, db: SupabaseClient):
    """Upload metadata from CSV to Supabase."""
    logger.info(f"Reading metadata from {metadata_file}...")

    # Read CSV
    df = pd.read_csv(metadata_file)
    logger.info(f"Loaded {len(df)} records")

    # Upload each record
    success_count = 0
    fail_count = 0

    for idx, row in df.iterrows():
        target_id = f"KIC {int(row['kepid'])}"

        try:
            await db.insert_target(
                target_id=target_id,
                mission='kepler',
                st_cdpp3_0=float(row['st_cdpp3_0']) if pd.notna(row.get('st_cdpp3_0')) else None,
                st_cdpp6_0=float(row['st_cdpp6_0']) if pd.notna(row.get('st_cdpp6_0')) else None,
                st_cdpp12_0=float(row['st_cdpp12_0']) if pd.notna(row.get('st_cdpp12_0')) else None,
                st_crowding=float(row['st_crowding']) if pd.notna(row.get('st_crowding')) else None,
                st_teff=float(row['st_teff']) if pd.notna(row.get('st_teff')) else None,
                st_rad=float(row['st_rad']) if pd.notna(row.get('st_rad')) else None,
                st_mass=float(row['st_mass']) if pd.notna(row.get('st_mass')) else None,
                koi_count=int(row['koi_count']) if pd.notna(row.get('koi_count')) else 0,
            )
            success_count += 1

            if (idx + 1) % 50 == 0:
                logger.info(f"Progress: {idx + 1}/{len(df)} ({success_count} success, {fail_count} failed)")

        except Exception as e:
            logger.error(f"Failed to upload {target_id}: {e}")
            fail_count += 1

    logger.info(f"✅ Upload complete: {success_count} success, {fail_count} failed")
    return success_count, fail_count

async def main():
    logger.info("=" * 80)
    logger.info("UPLOAD NASA CATALOG METADATA TO SUPABASE")
    logger.info("=" * 80)
    logger.info("")

    # Check for metadata files
    quiet_metadata = "data/quiet_stars_900_metadata.csv"
    planet_metadata = "data/known_planets_100_metadata.csv"

    if not Path(quiet_metadata).exists():
        logger.error(f"❌ {quiet_metadata} not found!")
        logger.error("   Run: python scripts/fetch_quiet_stars.py")
        return 1

    if not Path(planet_metadata).exists():
        logger.error(f"❌ {planet_metadata} not found!")
        logger.error("   Run: python scripts/fetch_planet_hosts.py")
        return 1

    # Connect to Supabase
    logger.info("Connecting to Supabase...")
    db = SupabaseClient()
    logger.info(f"Connected: {db.supabase_url}")
    logger.info("")

    # Upload quiet stars metadata
    logger.info("Uploading quiet stars metadata...")
    quiet_success, quiet_fail = await upload_metadata(quiet_metadata, db)
    logger.info("")

    # Upload planet hosts metadata
    logger.info("Uploading planet hosts metadata...")
    planet_success, planet_fail = await upload_metadata(planet_metadata, db)
    logger.info("")

    # Summary
    total_success = quiet_success + planet_success
    total_fail = quiet_fail + planet_fail

    logger.info("=" * 80)
    logger.info("UPLOAD COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Total uploaded: {total_success}/{total_success + total_fail}")
    logger.info(f"Quiet stars: {quiet_success} success, {quiet_fail} failed")
    logger.info(f"Planet hosts: {planet_success} success, {planet_fail} failed")
    logger.info("")

    if total_fail > 0:
        logger.warning(f"⚠️  {total_fail} records failed to upload")
        return 1
    else:
        logger.info("✅ All metadata uploaded successfully!")
        logger.info("")
        logger.info("Next step:")
        logger.info("  python scripts/test_validation_1000.py")
        return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
