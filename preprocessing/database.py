"""
Supabase Database Client for XENOSCAN

Handles all database operations:
- Target metadata storage
- Feature uploads (batch)
- Processing state tracking
- Resume capability
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from supabase import create_client, Client
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class XenoscanDatabase:
    """
    Database client for XENOSCAN feature storage and tracking.

    Handles batch uploads of targets and features to Supabase.
    """

    def __init__(self, env_path: Optional[Path] = None):
        """
        Initialize database client.

        Args:
            env_path: Path to .env file (default: project root)
        """
        # Load environment variables
        if env_path is None:
            env_path = Path(__file__).parent.parent / '.env'

        load_dotenv(env_path)

        # Get credentials
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')

        if not url or not key:
            raise ValueError(
                "Missing Supabase credentials. Create .env file with:\n"
                "SUPABASE_URL=your-url\n"
                "SUPABASE_KEY=your-key"
            )

        # Create client
        self.client: Client = create_client(url, key)
        logger.info(f"Connected to Supabase: {url}")

    async def insert_target(
        self,
        target_id: str,
        mission: str,
        n_points: int = None,
        duration_days: float = None,
        st_cdpp3_0: float = None,
        st_cdpp6_0: float = None,
        st_cdpp12_0: float = None,
        st_crowding: float = None,
        st_teff: float = None,
        st_rad: float = None,
        st_mass: float = None,
        koi_count: int = None,
    ) -> bool:
        """
        Insert or update target metadata.

        Args:
            target_id: Target identifier
            mission: Mission name
            n_points: Number of data points
            duration_days: Observation duration
            st_cdpp3_0: CDPP at 3-hour timescale (ppm)
            st_cdpp6_0: CDPP at 6-hour timescale (ppm)
            st_cdpp12_0: CDPP at 12-hour timescale (ppm)
            st_crowding: Crowding metric (0-1)
            st_teff: Effective temperature (K)
            st_rad: Stellar radius (Rsun)
            st_mass: Stellar mass (Msun)
            koi_count: Number of planet candidates

        Returns:
            True if successful
        """
        try:
            data = {
                'target_id': target_id,
                'mission': mission.lower(),
                'n_points': n_points,
                'duration_days': duration_days,
                'features_extracted': False,
            }

            # Add optional metadata if provided
            if st_cdpp3_0 is not None:
                data['st_cdpp3_0'] = st_cdpp3_0
            if st_cdpp6_0 is not None:
                data['st_cdpp6_0'] = st_cdpp6_0
            if st_cdpp12_0 is not None:
                data['st_cdpp12_0'] = st_cdpp12_0
            if st_crowding is not None:
                data['st_crowding'] = st_crowding
            if st_teff is not None:
                data['st_teff'] = st_teff
            if st_rad is not None:
                data['st_rad'] = st_rad
            if st_mass is not None:
                data['st_mass'] = st_mass
            if koi_count is not None:
                data['koi_count'] = koi_count

            # Upsert (insert or update if exists)
            response = self.client.table('targets').upsert(
                data,
                on_conflict='target_id'
            ).execute()

            logger.debug(f"Inserted target: {target_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to insert target {target_id}: {e}")
            return False

    async def insert_features(
        self,
        target_id: str,
        features: Dict[str, Any],
        validity: Dict[str, bool],
        extraction_time: float = None,
    ) -> bool:
        """
        Insert feature data for a target.

        Args:
            target_id: Target identifier
            features: Dict of 55 features
            validity: Dict of validity flags
            extraction_time: Time taken to extract (seconds)

        Returns:
            True if successful
        """
        try:
            # Build feature record
            data = {
                'target_id': target_id,
                'extraction_time_seconds': extraction_time,
                'n_features_valid': sum(validity.values()),
                'n_features_total': len(validity),
                **features  # All 55 features
            }

            # Insert
            response = self.client.table('features').upsert(
                data,
                on_conflict='target_id'
            ).execute()

            # Update target status
            self.client.table('targets').update({
                'features_extracted': True,
                'features_extracted_at': datetime.utcnow().isoformat()
            }).eq('target_id', target_id).execute()

            logger.debug(f"Inserted features for {target_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to insert features for {target_id}: {e}")
            return False

    async def batch_insert_targets(
        self,
        targets: List[Dict[str, Any]]
    ) -> int:
        """
        Batch insert multiple targets.

        Args:
            targets: List of target dicts

        Returns:
            Number of targets successfully inserted
        """
        try:
            response = self.client.table('targets').upsert(
                targets,
                on_conflict='target_id'
            ).execute()

            logger.info(f"Batch inserted {len(targets)} targets")
            return len(targets)

        except Exception as e:
            logger.error(f"Batch insert failed: {e}")
            return 0

    async def batch_insert_features(
        self,
        features_list: List[Dict[str, Any]]
    ) -> int:
        """
        Batch insert multiple feature records.

        Args:
            features_list: List of feature dicts

        Returns:
            Number of records successfully inserted
        """
        try:
            # Insert features
            response = self.client.table('features').upsert(
                features_list,
                on_conflict='target_id'
            ).execute()

            # Update target statuses
            target_ids = [f['target_id'] for f in features_list]
            for target_id in target_ids:
                self.client.table('targets').update({
                    'features_extracted': True,
                    'features_extracted_at': datetime.utcnow().isoformat()
                }).eq('target_id', target_id).execute()

            logger.info(f"Batch inserted {len(features_list)} feature records")
            return len(features_list)

        except Exception as e:
            logger.error(f"Batch feature insert failed: {e}")
            return 0

    def get_targets_pending_extraction(self, limit: int = 100) -> List[str]:
        """
        Get list of targets that need feature extraction.

        Args:
            limit: Maximum number to return

        Returns:
            List of target IDs
        """
        try:
            response = self.client.table('targets')\
                .select('target_id')\
                .eq('features_extracted', False)\
                .limit(limit)\
                .execute()

            target_ids = [row['target_id'] for row in response.data]
            return target_ids

        except Exception as e:
            logger.error(f"Failed to get pending targets: {e}")
            return []

    def get_extraction_summary(self) -> Dict[str, Any]:
        """
        Get summary of extraction progress.

        Returns:
            Dict with counts and percentages
        """
        try:
            response = self.client.table('extraction_summary')\
                .select('*')\
                .execute()

            if response.data and len(response.data) > 0:
                return response.data[0]

            return {
                'total_targets': 0,
                'extracted': 0,
                'pending': 0,
                'percent_complete': 0.0
            }

        except Exception as e:
            logger.error(f"Failed to get extraction summary: {e}")
            return {}

    async def log_processing_batch(
        self,
        batch_number: int,
        targets_processed: int,
        targets_succeeded: int,
        targets_failed: int,
        avg_download_time: float,
        avg_extraction_time: float,
        started_at: datetime,
        completed_at: datetime,
        notes: str = None
    ) -> bool:
        """
        Log processing batch for tracking.

        Args:
            batch_number: Batch sequence number
            targets_processed: Total targets in batch
            targets_succeeded: Successful targets
            targets_failed: Failed targets
            avg_download_time: Average download time
            avg_extraction_time: Average extraction time
            started_at: Batch start time
            completed_at: Batch end time
            notes: Optional notes

        Returns:
            True if successful
        """
        try:
            data = {
                'batch_number': batch_number,
                'targets_processed': targets_processed,
                'targets_succeeded': targets_succeeded,
                'targets_failed': targets_failed,
                'avg_download_time': avg_download_time,
                'avg_extraction_time': avg_extraction_time,
                'started_at': started_at.isoformat(),
                'completed_at': completed_at.isoformat(),
                'notes': notes
            }

            response = self.client.table('processing_log').insert(data).execute()
            logger.info(f"Logged batch {batch_number}")
            return True

        except Exception as e:
            logger.error(f"Failed to log batch: {e}")
            return False

    def test_connection(self) -> bool:
        """
        Test database connection.

        Returns:
            True if connection works
        """
        try:
            response = self.client.table('targets').select('count').limit(1).execute()
            logger.info("✅ Database connection successful")
            return True
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            return False
