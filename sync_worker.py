"""Background worker for syncing groups and users from EntraID."""
import threading
import time
import logging
from typing import Optional
from datetime import datetime, timedelta

from config import Config
from db import get_db
from graph_client import get_graph_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SyncWorker:
    """Background worker that syncs groups and users from EntraID."""

    def __init__(self, interval_minutes: int = None):
        """Initialize the sync worker."""
        self.interval = interval_minutes or Config.SYNC_INTERVAL_MINUTES
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._graph_client = get_graph_client()
        self._db = get_db()

    def start(self) -> None:
        """Start the sync worker in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Sync worker already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"Sync worker started with interval: {self.interval} minutes")

    def stop(self) -> None:
        """Stop the sync worker."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            logger.info("Sync worker stopped")

    def _run(self) -> None:
        """Main loop for the sync worker."""
        while not self._stop_event.is_set():
            try:
                # Run initial full sync on startup
                self._full_sync()

                # Then run periodic syncs
                while not self._stop_event.wait(self.interval * 60):
                    self._incremental_sync()

            except Exception as e:
                logger.error(f"Sync worker error: {e}")
                # Wait before retrying after error
                time.sleep(60)

    def _full_sync(self) -> None:
        """Perform a full sync of all groups and users."""
        logger.info("Starting full sync...")

        # Sync groups
        sync_id = self._db.log_sync_start("groups")
        try:
            groups = self._graph_client.get_all_groups()
            for group in groups:
                self._db.upsert_group(
                    group_id=group["id"],
                    display_name=group["display_name"],
                    description=group.get("description")
                )
            self._db.log_sync_complete(sync_id, len(groups))
            logger.info(f"Synced {len(groups)} groups")
        except Exception as e:
            self._db.log_sync_error(sync_id, str(e))
            logger.error(f"Failed to sync groups: {e}")
            return

        # Sync users for each group
        sync_id = self._db.log_sync_start("users")
        try:
            total_users = 0
            all_users = set()

            # Collect all users from all groups
            for group in groups:
                members = self._graph_client.get_group_members(group["id"])
                for member in members:
                    if member["id"] not in all_users:
                        all_users.add(member["id"])
                        self._db.upsert_user(
                            user_id=member["id"],
                            mail=member.get("mail"),
                            user_principal_name=member.get("user_principal_name"),
                            display_name=member.get("display_name")
                        )
                total_users += len(members)

                # Clear and rebuild group memberships
                self._db.clear_memberships(group["id"])
                for member in members:
                    self._db.add_membership(group["id"], member["id"])

                # Update member count
                member_count = self._db.get_group_member_count(group["id"])
                self._db.upsert_group(
                    group_id=group["id"],
                    display_name=group["display_name"],
                    description=group.get("description"),
                    member_count=member_count
                )

                # Small delay to avoid rate limiting
                time.sleep(0.2)

            self._db.log_sync_complete(sync_id, len(all_users))
            logger.info(f"Synced {len(all_users)} users")

        except Exception as e:
            self._db.log_sync_error(sync_id, str(e))
            logger.error(f"Failed to sync users: {e}")

        logger.info("Full sync completed")

    def _incremental_sync(self) -> None:
        """Perform an incremental sync (updates only)."""
        logger.info("Starting incremental sync...")

        # For simplicity, we'll do a full sync but could be optimized
        # to only fetch changed items using delta links
        try:
            self._full_sync()
        except Exception as e:
            logger.error(f"Incremental sync failed: {e}")

    def trigger_sync(self) -> bool:
        """Manually trigger a sync operation."""
        try:
            thread = threading.Thread(target=self._full_sync, daemon=True)
            thread.start()
            return True
        except Exception as e:
            logger.error(f"Failed to trigger sync: {e}")
            return False

    def get_status(self) -> dict:
        """Get sync worker status."""
        last_groups_sync = self._db.get_last_sync_time("groups")
        last_users_sync = self._db.get_last_sync_time("users")

        return {
            "running": self._thread.is_alive() if self._thread else False,
            "interval_minutes": self.interval,
            "last_groups_sync": last_groups_sync,
            "last_users_sync": last_users_sync
        }


# Global sync worker instance
_sync_worker: Optional[SyncWorker] = None


def get_sync_worker() -> SyncWorker:
    """Get or create sync worker instance."""
    global _sync_worker
    if _sync_worker is None:
        _sync_worker = SyncWorker()
    return _sync_worker


def start_sync_worker() -> None:
    """Start the global sync worker."""
    worker = get_sync_worker()
    worker.start()


def stop_sync_worker() -> None:
    """Stop the global sync worker."""
    global _sync_worker
    if _sync_worker:
        _sync_worker.stop()
        _sync_worker = None
