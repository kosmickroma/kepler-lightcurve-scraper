"""
Atomic Checkpoint Manager

Provides atomic save/load operations for download state.
Uses write-to-temp-then-rename pattern for POSIX atomicity.
Prevents corruption even if process killed mid-write.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import CheckpointError


logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    Manages atomic checkpoint saves and loads.

    Uses temp file + atomic rename to prevent corruption.
    """

    def __init__(self, checkpoint_dir: Path):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoints
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"CheckpointManager initialized: {self.checkpoint_dir}")

    def save(
        self,
        state: Dict[str, Any],
        checkpoint_name: str = "scraper_state.json",
    ) -> None:
        """
        Atomically save checkpoint state.

        Args:
            state: State dictionary to save
            checkpoint_name: Name of checkpoint file

        Raises:
            CheckpointError: If save fails
        """
        checkpoint_path = self.checkpoint_dir / checkpoint_name
        temp_path = checkpoint_path.with_suffix('.tmp')

        try:
            # Add metadata
            state['last_updated'] = datetime.utcnow().isoformat()
            state['checkpoint_version'] = '1.0'

            # Write to temp file
            with open(temp_path, 'w') as f:
                json.dump(state, f, indent=2, default=str)

            # Atomic rename (POSIX guarantee)
            os.replace(temp_path, checkpoint_path)

            logger.info(f"✅ Checkpoint saved: {checkpoint_path}")

        except Exception as e:
            logger.error(f"Checkpoint save failed: {e}")
            if temp_path.exists():
                temp_path.unlink()  # Clean up temp file
            raise CheckpointError(f"Failed to save checkpoint: {e}")

    def load(
        self,
        checkpoint_name: str = "scraper_state.json",
    ) -> Optional[Dict[str, Any]]:
        """
        Load checkpoint state.

        Args:
            checkpoint_name: Name of checkpoint file

        Returns:
            State dictionary if found, None otherwise

        Raises:
            CheckpointError: If load fails (corrupted file)
        """
        checkpoint_path = self.checkpoint_dir / checkpoint_name

        if not checkpoint_path.exists():
            logger.info(f"No checkpoint found: {checkpoint_path}")
            return None

        try:
            with open(checkpoint_path, 'r') as f:
                state = json.load(f)

            logger.info(
                f"📂 Checkpoint loaded: {checkpoint_name} "
                f"(updated: {state.get('last_updated', 'unknown')})"
            )

            return state

        except json.JSONDecodeError as e:
            logger.error(f"Checkpoint corrupted: {e}")
            raise CheckpointError(f"Corrupted checkpoint: {e}")

        except Exception as e:
            logger.error(f"Checkpoint load failed: {e}")
            raise CheckpointError(f"Failed to load checkpoint: {e}")

    def list_checkpoints(self) -> List[Path]:
        """List all checkpoint files."""
        return sorted(self.checkpoint_dir.glob("*.json"))

    def backup_checkpoint(
        self,
        checkpoint_name: str = "scraper_state.json",
    ) -> Optional[Path]:
        """
        Create timestamped backup of checkpoint.

        Args:
            checkpoint_name: Name of checkpoint to backup

        Returns:
            Path to backup file, or None if checkpoint doesn't exist
        """
        checkpoint_path = self.checkpoint_dir / checkpoint_name

        if not checkpoint_path.exists():
            return None

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{checkpoint_path.stem}_{timestamp}.backup.json"
        backup_path = self.checkpoint_dir / backup_name

        try:
            import shutil
            shutil.copy2(checkpoint_path, backup_path)
            logger.info(f"Checkpoint backed up: {backup_path}")
            return backup_path

        except Exception as e:
            logger.warning(f"Backup failed: {e}")
            return None
