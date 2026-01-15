#!/usr/bin/env python3
"""
Clear validation test data from Supabase.

Removes all data for the 1000 validation targets:
- 900 quiet stars
- 100 planet hosts

Use this to reset before re-running validation.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from preprocessing.database import SupabaseClient
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def load_target_ids(quiet_file, planet_file):
    """Load target IDs from both files."""
    target_ids = []

    # Load quiet stars
    if Path(quiet_file).exists():
        with open(quiet_file, 'r') as f:
            target_ids.extend([line.strip() for line in f if line.strip()])

    # Load planet hosts
    if Path(planet_file).exists():
        with open(planet_file, 'r') as f:
            target_ids.extend([line.strip() for line in f if line.strip()])

    return target_ids

def main():
    logger.info("=" * 80)
    logger.info("CLEAR VALIDATION DATA FROM SUPABASE")
    logger.info("=" * 80)
    logger.info("")

    # Load target lists
    quiet_file = "data/quiet_stars_900.txt"
    planet_file = "data/known_planets_100.txt"

    target_ids = load_target_ids(quiet_file, planet_file)

    if not target_ids:
        logger.warning("No targets found. Nothing to delete.")
        return 0

    logger.info(f"Found {len(target_ids)} validation targets to delete")
    logger.info("")
    logger.info("This will delete from Supabase:")
    logger.info(f"  - {len(target_ids)} records from 'targets' table")
    logger.info(f"  - {len(target_ids)} records from 'features' table")
    logger.info("")

    # Confirm
    response = input("Continue? (yes/no): ")
    if response.lower() != 'yes':
        logger.info("Cancelled.")
        return 0

    # Connect to Supabase
    logger.info("")
    logger.info("Connecting to Supabase...")
    db = SupabaseClient()
    logger.info(f"Connected: {db.supabase_url}")
    logger.info("")

    # Delete from features table
    logger.info("Deleting from 'features' table...")
    for target_id in target_ids:
        try:
            db.client.table('features').delete().eq('target_id', target_id).execute()
        except Exception as e:
            logger.warning(f"  Failed to delete {target_id} from features: {e}")

    logger.info("✅ Deleted from 'features' table")

    # Delete from targets table
    logger.info("Deleting from 'targets' table...")
    for target_id in target_ids:
        try:
            db.client.table('targets').delete().eq('target_id', target_id).execute()
        except Exception as e:
            logger.warning(f"  Failed to delete {target_id} from targets: {e}")

    logger.info("✅ Deleted from 'targets' table")

    logger.info("")
    logger.info("=" * 80)
    logger.info("CLEANUP COMPLETE")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Supabase is now clear of validation data.")
    logger.info("You can re-run: python scripts/test_validation_1000.py")

    return 0

if __name__ == "__main__":
    sys.exit(main())
