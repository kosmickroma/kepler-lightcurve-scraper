#!/usr/bin/env python3
"""
Clear test data from Supabase before running validation tests.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

def main():
    # Load credentials
    env_path = Path(__file__).parent.parent.parent / '.env'
    load_dotenv(env_path)

    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_KEY')

    if not url or not key:
        print("ERROR: Missing Supabase credentials in .env")
        sys.exit(1)

    client = create_client(url, key)

    print("=" * 80)
    print("CLEARING TEST DATA FROM SUPABASE")
    print("=" * 80)
    print()
    print("This will delete:")
    print("  - All features for KIC 10002xxx targets (test data)")
    print("  - All targets for KIC 10002xxx (test data)")
    print()

    confirm = input("Continue? (yes/no): ")
    if confirm.lower() != 'yes':
        print("Aborted.")
        sys.exit(0)

    try:
        # Delete features first (foreign key constraint)
        print("Deleting features...")
        response = client.table('features').delete().like('target_id', 'KIC 10002%').execute()
        print(f"✅ Deleted feature records")

        # Delete targets
        print("Deleting targets...")
        response = client.table('targets').delete().like('target_id', 'KIC 10002%').execute()
        print(f"✅ Deleted target records")

        print()
        print("✅ Test data cleared successfully!")
        print()

    except Exception as e:
        print(f"❌ Error clearing data: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
