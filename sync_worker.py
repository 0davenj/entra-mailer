"""Background worker for syncing groups and users from EntraID."""
import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from datetime import datetime, timedelta

from config import Config
from db import get_db
from graph_client import get_graph_client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Number of parallel threads for fetching group members
SYNC_WORKERS = 10


class SyncWorker:
    """Background worker that syncs groups and users from EntraID."""

    def __init__(self, interval_minutes: int = None):
        """Initialize the sync worker."""
        self.interval = interval_minutes or Config.SYNC_INTERVAL_MINUTES
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._graph_client = get_graph_client()
        self._db = get_db()
        self._sync_progress = {"status": "idle", "message": "", "percent": 0}

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

    def _set_progress(self, status: str, message: str, percent: int = 0):
        """Update sync progress."""
        self._sync_progress = {"status": status, "message": message, "percent": percent}

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
                self._set_progress("error", str(e))
                # Wait before retrying after error
                time.sleep(60)

    def _fetch_group_members(self, group: dict) -> tuple:
        """Fetch members for a single group (used in parallel)."""
        try:
            group_id = group["id"]
            group_name = group["display_name"]
            members = self._graph_client.get_group_members(group_id)
            return (group_id, group_name, members, None)
        except Exception as e:
            return (group.get("id"), group.get("display_name"), [], str(e))

    def _full_sync(self) -> None:
        """Perform a full sync of all groups and users."""
        logger.info("Starting full sync...")
        self._set_progress("running", "Starting full sync...", 0)

        # Sync groups
        sync_id = self._db.log_sync_start("groups")
        try:
            logger.info("Fetching groups from Microsoft Graph...")
            self._set_progress("running", "Fetching groups from Microsoft Graph...", 5)
            groups = self._graph_client.get_all_groups()
            total_groups = len(groups)
            logger.info(f"Found {total_groups} groups, saving to database...")

            for i, group in enumerate(groups):
                self._db.upsert_group(
                    group_id=group["id"],
                    display_name=group["display_name"],
                    description=group.get("description")
                )
                # Progress update every 100 groups
                if (i + 1) % 100 == 0:
                    percent = min(30, int((i + 1) / total_groups * 30))
                    self._set_progress("running", f"Saving groups: {i + 1}/{total_groups}", percent)
                    logger.info(f"Synced {i + 1}/{total_groups} groups")

            self._db.log_sync_complete(sync_id, len(groups))
            logger.info(f"Synced {len(groups)} groups")
            self._set_progress("running", f"Groups synced: {len(groups)}", 30)

        except Exception as e:
            self._db.log_sync_error(sync_id, str(e))
            logger.error(f"Failed to sync groups: {e}")
            self._set_progress("error", f"Failed to sync groups: {e}")
            return

        # Sync users for each group in parallel
        sync_id = self._db.log_sync_start("users")
        try:
            total_users = 0
            all_users = set()

            logger.info(f"Fetching members for {total_groups} groups using {SYNC_WORKERS} parallel workers...")
            self._set_progress("running", f"Fetching members with {SYNC_WORKERS} parallel workers...", 35)

            # Use ThreadPoolExecutor to fetch group members in parallel
            with ThreadPoolExecutor(max_workers=SYNC_WORKERS) as executor:
                future_to_group = {
                    executor.submit(self._fetch_group_members, group): group 
                    for group in groups
                }
                
                completed = 0
                for future in as_completed(future_to_group):
                    group_id, group_name, members, error = future.result()
                    
                    completed += 1
                    if completed % 100 == 0:
                        percent = 35 + int(completed / total_groups * 55)
                        self._set_progress("running", f"Processing: {completed}/{total_groups} groups", percent)

                    if error:
                        logger.warning(f"Failed to fetch members for {group_name}: {error}")
                        continue

                    # Process members
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
                    self._db.clear_memberships(group_id)
                    for member in members:
                        self._db.add_membership(group_id, member["id"])

                    # Update member count
                    member_count = self._db.get_group_member_count(group_id)
                    self._db.upsert_group(
                        group_id=group_id,
                        display_name=group_name,
                        description=next((g.get("description") for g in groups if g["id"] == group_id), None),
                        member_count=member_count
                    )

            self._db.log_sync_complete(sync_id, len(all_users))
            logger.info(f"Synced {len(all_users)} users from {total_groups} groups")
            self._set_progress("completed", f"Sync completed: {len(groups)} groups, {len(all_users)} users", 100)

        except Exception as e:
            self._db.log_sync_error(sync_id, str(e))
            logger.error(f"Failed to sync users: {e}")
            self._set_progress("error", f"Failed to sync users: {e}")

        logger.info("Full sync completed")

    def _incremental_sync(self) -> None:
        """Perform an incremental sync (updates only)."""
        logger.info("Starting incremental sync...")
        self._set_progress("running", "Starting incremental sync...", 0)

        # For simplicity, we'll do a full sync but could be optimized
        # to only fetch changed items using delta links
        try:
            self._full_sync()
        except Exception as e:
            logger.error(f"Incremental sync failed: {e}")
            self._set_progress("error", f"Incremental sync failed: {e}")

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
            "last_users_sync": last_users_sync,
            "progress": self._sync_progress
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
