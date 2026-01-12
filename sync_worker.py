"""Background worker for syncing groups and users from EntraID."""
import threading
import time
import logging
import queue
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any, Set
from datetime import datetime

from config import Config
from db import get_db
from graph_client import get_graph_client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Pipeline configuration
NUM_MEMBER_WORKERS = 5
GROUP_QUEUE_SIZE = 1000
DB_QUEUE_SIZE = 5000

class SyncWorker:
    """Background worker that syncs groups and users from EntraID using a pipeline."""

    def __init__(self, interval_minutes: int = None):
        """Initialize the sync worker."""
        self.interval = interval_minutes or Config.SYNC_INTERVAL_MINUTES
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._graph_client = get_graph_client()
        self._db = get_db()
        self._sync_progress = {"status": "idle", "message": "", "percent": 0}
        
        # Pipelines queues
        self.group_queue = queue.Queue(maxsize=GROUP_QUEUE_SIZE)
        self.db_queue = queue.Queue(maxsize=DB_QUEUE_SIZE)
        
        # State tracking
        self.total_groups = 0
        self.processed_groups = 0
        self.total_users = 0
        self.updated_groups_count = 0
        self.updated_users_count = 0

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
                # Run sync logic
                # self._run_pipeline_sync() # Disabled auto-start
                pass

                # Wait for next interval
                logger.info(f"Sync sleeping for {self.interval} minutes...")
                if self._stop_event.wait(self.interval * 60):
                    break

            except Exception as e:
                logger.error(f"Sync worker loop error: {e}", exc_info=True)
                self._set_progress("error", str(e))
                time.sleep(60)

    def trigger_sync(self) -> bool:
        """Manually trigger a sync operation."""
        # Check if already running (simplified check)
        if self._sync_progress["status"] == "running":
            logger.warning("Sync already in progress")
            return False
            
        try:
            # We start a dedicated thread just for this ad-hoc run if main loop is too slow
            # But simpler: just wake up the main loop if possible, or start a parallel run? 
            # Given the request, let's keep it simple: Start a thread that runs one pass.
            thread = threading.Thread(target=self._run_pipeline_sync, daemon=True)
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
            "running": self._sync_progress["status"] == "running",
            "interval_minutes": self.interval,
            "last_groups_sync": last_groups_sync,
            "last_users_sync": last_users_sync,
            "progress": self._sync_progress
        }

    # ==================================================================================
    # PIPELINE IMPLEMENTATION
    # ==================================================================================

    def _run_pipeline_sync(self):
        """Orchestrate the sync pipeline."""
        logger.info("Starting pipeline sync...")
        self._set_progress("running", "Initializing sync pipeline...", 0)
        
        # Reset counters
        self.total_groups = 0
        self.processed_groups = 0
        self.total_users = 0
        self.updated_groups_count = 0 
        self.updated_users_count = 0
        
        sync_id_groups = self._db.log_sync_start("groups")
        sync_id_users = self._db.log_sync_start("users")

        # Create thread pool for member fetchers
        member_worker_pool = ThreadPoolExecutor(max_workers=NUM_MEMBER_WORKERS)
        
        # Start DB writer thread
        db_writer_thread = threading.Thread(target=self._db_writer_loop, daemon=True)
        db_writer_thread.start()

        # Start Group Producer (Main thread acts as producer for simplicity, or separate)
        # We'll run producer in main thread to easily track total_groups
        try:
            # 1. Start Member Workers
            # We submit tasks that just continuously pull from queue until sentinel
            futures = []
            for _ in range(NUM_MEMBER_WORKERS):
                futures.append(member_worker_pool.submit(self._member_worker_loop))

            # 2. Run Producer
            self._group_producer()
            
            # 3. Wait for Queue to behave (Producer done)
            # Signal member workers to stop
            for _ in range(NUM_MEMBER_WORKERS):
                self.group_queue.put(None) # Sentinel
            
            # Wait for member workers
            for f in futures:
                f.result()
            
            # 4. Signal DB writer to stop
            self.db_queue.put(None) # Sentinel
            db_writer_thread.join()

            # Log completion
            self._db.log_sync_complete(sync_id_groups, self.total_groups)
            self._db.log_sync_complete(sync_id_users, self.total_users)
            
            msg = f"Sync finalized. {self.updated_groups_count} groups updated, {self.updated_users_count} users updated."
            logger.info(msg)
            self._set_progress("completed", msg, 100)

        except Exception as e:
            logger.error(f"Pipeline sync failed: {e}", exc_info=True)
            self._db.log_sync_error(sync_id_groups, str(e))
            self._db.log_sync_error(sync_id_users, str(e))
            self._set_progress("error", f"Sync failed: {e}")
        finally:
            member_worker_pool.shutdown(wait=False)

    def _group_producer(self):
        """Fetches groups using Delta Query."""
        logger.info("Producer: Starting to fetch groups (Delta)...")
        self._set_progress("running", "Fetching groups (Delta)...", 5)
        
        count = 0
        try:
            # 1. Load Delta Link
            delta_link = self._db.get_state("groups_delta_link")
            if delta_link:
                logger.info("Producer: Found existing delta token. Performing incremental sync.")
            else:
                logger.info("Producer: No delta token found. Performing full initial sync.")

            # 2. Fetch Changes
            changes, new_delta_link = self._graph_client.get_groups_delta(delta_link)
            
            logger.info(f"Producer: Fetched {len(changes)} changes. New delta link type: {type(new_delta_link)}")
            
            # 3. Process Changes
            self.total_groups = len(changes) # This is "Total Changed Groups" now, not Total Total.
            # If we are in delta mode, 0 changes is fine.
            
            for group in changes:
                group_id = group.get("id")
                
                # Check if deleted
                if group.get("removed"):
                    logger.info(f"Producer: Group {group_id} was deleted.")
                    self.db_queue.put(("delete_group", group_id))
                    count += 1
                    continue
                
                # Upsert Group
                self.db_queue.put(("upsert_group", group))
                
                # Queue for member fetching
                # Note: If passing 'group' directly, it might miss fields in delta response if they didn't change?
                # MS Graph Delta returns minimal info if changed? 
                # Actually for "Groups", it usually returns the resource. 
                # But safer to maybe fetch fresh if critical? 
                # For member fetching, we just need ID.
                self.group_queue.put(group)
                count += 1
                
                if count % 100 == 0:
                    logger.info(f"Producer: Queued {count} changes...")

            # 4. Save New Token
            if new_delta_link:
                self._db.set_state("groups_delta_link", new_delta_link)
                logger.info("Producer: Saved new delta token.")
            else:
                logger.warning("Producer: No new delta token received!")

        except Exception as e:
            logger.error(f"Producer failed: {e}")
            raise

    def _member_worker_loop(self):
        """Worker that fetches members for groups."""
        while True:
            try:
                group = self.group_queue.get(timeout=5) # wait a bit for queue
                if group is None:
                    break # Sentinel
            except queue.Empty:
                continue

            try:
                group_id = group["id"]
                # 1. Fetch current members from Graph
                # logger.debug(f"Worker: Fetching members for {group.get('display_name', group_id)}")
                members = self._graph_client.get_group_members(group_id)
                member_count = len(members)
                
                if member_count > 0:
                    logger.debug(f"Worker: Found {member_count} members for {group.get('display_name', group_id)}")
                
                # 2. Get existing members from DB for diffing
                # ... 
                
                self.db_queue.put(("sync_members", {
                    "group_id": group_id, 
                    "members": members,
                    "count": member_count
                }))
                
                self.total_users += member_count

            except Exception as e:
                logger.error(f"Worker failed for group {group.get('id')}: {e}")
            finally:
                self.group_queue.task_done()

    def _db_writer_loop(self):
        """Thread that handles all DB writes sequentially."""
        while True:
            try:
                item = self.db_queue.get(timeout=5)
                if item is None:
                    break # Sentinel
            except queue.Empty:
                continue
                
            try:
                action, data = item
                
                if action == "upsert_group":
                    self._db.upsert_group(
                        group_id=data["id"],
                        display_name=data.get("display_name", "Unknown"), # Delta might not send display name if not changed?
                        description=data.get("description"),
                        # member_count will be updated when members are synced
                    )
                
                elif action == "delete_group":
                    self._db.delete_group(data) # data is group_id
                    
                elif action == "sync_members":
                    group_id = data["group_id"]
                    members = data["members"]
                    count = data["count"]
                    
                    # 1. Upsert all users (optimized in DB to only write if changed)
                    for member in members:
                        self._db.upsert_user(
                            user_id=member["id"],
                            mail=member.get("mail"),
                            user_principal_name=member.get("user_principal_name"),
                            display_name=member.get("display_name")
                        )
                    
                    # 2. Update Membership
                    #   Get current DB members
                    current_ids = set(self._db.get_group_members_ids(group_id))
                    new_ids = set(m["id"] for m in members)
                    
                    #   Calculate diff
                    to_add = new_ids - current_ids
                    to_remove = current_ids - new_ids
                    
                    #   Apply changes
                    for uid in to_add:
                        self._db.add_membership(group_id, uid)
                    
                    for uid in to_remove:
                        self._db.remove_membership(group_id, uid)
                        
                    # 3. Update group count
                    # We always update the count because upsert_group might have reset it to 0
                    self._db.update_group_member_count(group_id, count)
                    
                    if len(to_add) > 0 or len(to_remove) > 0:
                        self.updated_groups_count += 1
                        
                    self.processed_groups += 1
                    
                    # Update progress periodically
                    if self.processed_groups % 20 == 0 and self.total_groups > 0:
                        pct = int((self.processed_groups / self.total_groups) * 100)
                        self._set_progress("running", f"Synced {self.processed_groups}/{self.total_groups} groups", pct)
                        logger.info(f"Synced {self.processed_groups}/{self.total_groups} groups ({pct}%)")

            except Exception as e:
                logger.error(f"DB Writer failed: {e}")
            finally:
                self.db_queue.task_done()

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
