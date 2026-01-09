"""Background worker for sending emails."""
import threading
import time
import logging
from typing import Optional, Dict
from datetime import datetime
import json

from config import Config
from db import get_db
from graph_client import get_graph_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailWorker:
    """Background worker that processes email tasks."""

    def __init__(self):
        """Initialize the email worker."""
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._graph_client = get_graph_client()
        self._db = get_db()
        self._check_interval = 5  # seconds

    def start(self) -> None:
        """Start the email worker in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Email worker already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Email worker started")

    def stop(self) -> None:
        """Stop the email worker."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            logger.info("Email worker stopped")

    def _run(self) -> None:
        """Main loop for processing email tasks."""
        while not self._stop_event.is_set():
            try:
                self._process_pending_tasks()
            except Exception as e:
                logger.error(f"Email worker error: {e}")

            # Wait before checking for new tasks
            self._stop_event.wait(self._check_interval)

    def _process_pending_tasks(self) -> None:
        """Process pending email tasks."""
        pending_tasks = self._db.get_email_tasks(status="pending", limit=10)

        for task in pending_tasks:
            if self._stop_event.is_set():
                break

            try:
                self._process_task(task)
            except Exception as e:
                logger.error(f"Failed to process task {task['id']}: {e}")
                self._db.update_email_task_status(
                    task["id"], "failed",
                    completed_at=datetime.utcnow().isoformat()
                )

    def _process_task(self, task: dict) -> None:
        """Process a single email task."""
        task_id = task["id"]
        subject = task["subject"]
        body = task["body"]
        selected_group_ids = json.loads(task["selected_group_ids"])

        # Update status to processing
        self._db.update_email_task_status(
            task_id, "processing",
            started_at=datetime.utcnow().isoformat()
        )

        # Get all recipients from selected groups
        users = self._db.get_users_by_group_ids(selected_group_ids)
        recipients = [user["mail"] for user in users if user["mail"]]

        if not recipients:
            self._db.update_email_task_status(
                task_id, "completed",
                completed_at=datetime.utcnow().isoformat(),
                sent_count=0,
                failed_count=0
            )
            logger.info(f"Task {task_id}: No recipients found")
            return

        # Update total recipients
        self._db.update_email_task_status(
            task_id, "processing",
            sent_count=0,
            failed_count=0
        )

        # Send emails in batches
        batch_size = Config.EMAIL_BATCH_SIZE
        sent_count = 0
        failed_count = 0

        for i in range(0, len(recipients), batch_size):
            if self._stop_event.is_set():
                break

            batch = recipients[i:i + batch_size]

            # Send email to batch
            results = self._graph_client.send_batch_emails(
                subject=subject,
                body=body,
                recipients=batch,
                batch_size=batch_size
            )

            sent_count += results["sent"]
            failed_count += results["failed"]

            # Log each recipient
            for email in batch:
                status = "sent" if email in batch[:results["sent"]] else "failed"
                self._db.log_email_send(task_id, email, status)

            # Update progress
            self._db.update_email_task_status(
                task_id, "processing",
                sent_count=sent_count,
                failed_count=failed_count
            )

            # Small delay between batches
            time.sleep(1)

        # Mark task as completed
        self._db.update_email_task_status(
            task_id, "completed",
            completed_at=datetime.utcnow().isoformat(),
            sent_count=sent_count,
            failed_count=failed_count
        )

        logger.info(f"Task {task_id}: Sent {sent_count}, Failed {failed_count}")

    def create_task(self, subject: str, body: str, selected_group_ids: list,
                    template_id: int = None, created_by: str = None) -> int:
        """Create a new email task."""
        return self._db.create_email_task(
            subject=subject,
            body=body,
            selected_group_ids=selected_group_ids,
            template_id=template_id,
            created_by=created_by
        )

    def get_task_status(self, task_id: int) -> dict:
        """Get status of a specific task."""
        task = self._db.get_email_task(task_id)
        if not task:
            return None

        stats = self._db.get_email_task_stats(task_id)
        return {
            "task": task,
            "stats": stats
        }

    def get_recent_tasks(self, limit: int = 10) -> list:
        """Get recent email tasks."""
        return self._db.get_email_tasks(limit=limit)

    def get_status(self) -> dict:
        """Get email worker status."""
        return {
            "running": self._thread.is_alive() if self._thread else False,
            "pending_tasks": len(self._db.get_email_tasks(status="pending")),
            "processing_tasks": len(self._db.get_email_tasks(status="processing"))
        }


# Global email worker instance
_email_worker: Optional[EmailWorker] = None


def get_email_worker() -> EmailWorker:
    """Get or create email worker instance."""
    global _email_worker
    if _email_worker is None:
        _email_worker = EmailWorker()
    return _email_worker


def start_email_worker() -> None:
    """Start the global email worker."""
    worker = get_email_worker()
    worker.start()


def stop_email_worker() -> None:
    """Stop the global email worker."""
    global _email_worker
    if _email_worker:
        _email_worker.stop()
        _email_worker = None
