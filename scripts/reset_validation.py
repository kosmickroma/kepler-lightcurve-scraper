#!/usr/bin/env python3
"""
Reset Validation Data for Fresh Run

Clears all data from Supabase and optionally clears FITS cache.
Use this before re-running validation with fixed code.

REMEDIATION 2026-01-17: Created for fresh start after code fixes.
"""

import sys
import os
from pathlib import Path
import shutil

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from supabase import create_client


def reset_database():
    """Clear all targets and features from Supabase."""
    # Load environment
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(env_path)

    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_KEY')

    if not url or not key:
        print("ERROR: Missing Supabase credentials in .env")
        return False

    client = create_client(url, key)

    print("Clearing Supabase tables...")

    # Delete all features first (foreign key constraint)
    try:
        # Delete in batches to avoid timeout
        # First, get count
        result = client.table('features').select('id', count='exact').execute()
        feature_count = result.count if result.count else 0
        print(f"  Features to delete: {feature_count}")

        if feature_count > 0:
            # Delete all features
            client.table('features').delete().neq('id', -1).execute()
            print("  Features table cleared")
    except Exception as e:
        print(f"  Warning clearing features: {e}")

    # Delete all targets
    try:
        result = client.table('targets').select('id', count='exact').execute()
        target_count = result.count if result.count else 0
        print(f"  Targets to delete: {target_count}")

        if target_count > 0:
            client.table('targets').delete().neq('id', -1).execute()
            print("  Targets table cleared")
    except Exception as e:
        print(f"  Warning clearing targets: {e}")

    print("Database reset complete!")
    return True


def reset_fits_cache(fits_dir: Path):
    """Clear all downloaded FITS files."""
    if not fits_dir.exists():
        print(f"FITS cache not found: {fits_dir}")
        return True

    # Count files
    fits_files = list(fits_dir.rglob("*.fits"))
    kic_dirs = [d for d in fits_dir.iterdir() if d.is_dir()]

    print(f"FITS cache: {len(kic_dirs)} targets, {len(fits_files)} files")

    if len(fits_files) == 0:
        print("  Already empty")
        return True

    # Confirm
    response = input(f"Delete {len(fits_files)} FITS files? [y/N]: ")
    if response.lower() != 'y':
        print("  Skipped")
        return False

    # Delete
    for kic_dir in kic_dirs:
        try:
            shutil.rmtree(kic_dir)
        except Exception as e:
            print(f"  Warning deleting {kic_dir}: {e}")

    print("  FITS cache cleared!")
    return True


def main():
    print("=" * 60)
    print("XENOSCAN VALIDATION RESET")
    print("=" * 60)
    print()
    print("This will clear ALL validation data for a fresh run.")
    print()

    # Paths
    base_dir = Path(__file__).parent.parent
    fits_cache = base_dir / "data" / "fits_cache"

    # Confirm
    print("Actions:")
    print("  1. Clear all targets from Supabase")
    print("  2. Clear all features from Supabase")
    print("  3. Optionally clear FITS cache")
    print()

    response = input("Proceed with database reset? [y/N]: ")
    if response.lower() != 'y':
        print("Aborted")
        return 1

    print()

    # Reset database
    if not reset_database():
        print("Database reset failed!")
        return 1

    print()

    # Reset FITS cache (optional)
    reset_fits_cache(fits_cache)

    print()
    print("=" * 60)
    print("RESET COMPLETE")
    print("=" * 60)
    print()
    print("Ready for fresh validation run:")
    print("  python scripts/run_validation_local.py")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
