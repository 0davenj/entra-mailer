"""Database layer for EntraID Group Email Sender."""
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from pathlib import Path

from config import Config


class Database:
    """SQLite database manager for the application."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database connection."""
        self.db_path = db_path or Config.get_database_path()
        self._init_db()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Groups table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    description TEXT,
                    member_count INTEGER DEFAULT 0,
                    last_sync_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    mail TEXT,
                    user_principal_name TEXT,
                    display_name TEXT,
                    last_sync_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Group memberships (junction table)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_memberships (
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, user_id),
                    FOREIGN KEY (group_id) REFERENCES groups(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            # Email templates table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Email tasks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    selected_group_ids TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    total_recipients INTEGER DEFAULT 0,
                    sent_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    started_at TEXT,
                    completed_at TEXT,
                    created_by TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (template_id) REFERENCES templates(id)
                )
            """)

            # Email logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    recipient_email TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    sent_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES email_tasks(id)
                )
            """)

            # Sync history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    records_synced INTEGER DEFAULT 0,
                    error_message TEXT
                )
            """)

            # User activity log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_groups_name
                ON groups(display_name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_mail
                ON users(mail)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memberships_user
                ON group_memberships(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_email_tasks_status
                ON email_tasks(status)
            """)

            # Insert default template
            cursor.execute("SELECT COUNT(*) FROM templates")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO templates (name, subject, body)
                    VALUES (?, ?, ?)
                """, (
                    "Default Template",
                    "Important Announcement",
                    "<html><body><h1>Hello</h1><p>This is an announcement.</p></body></html>"
                ))

    # Groups operations
    def upsert_group(self, group_id: str, display_name: str, description: str = None,
                     member_count: int = 0) -> None:
        """Insert or update a group."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO groups (id, display_name, description, member_count, last_sync_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    description = excluded.description,
                    member_count = excluded.member_count,
                    last_sync_at = excluded.last_sync_at,
                    updated_at = CASE 
                        WHEN groups.display_name != excluded.display_name 
                             OR (groups.description IS NOT NULL AND groups.description != excluded.description)
                             OR (groups.description IS NULL AND excluded.description IS NOT NULL)
                             OR groups.member_count != excluded.member_count
                        THEN excluded.updated_at 
                        ELSE groups.updated_at 
                    END
            """, (group_id, display_name, description, member_count, datetime.utcnow().isoformat(),
                  datetime.utcnow().isoformat()))

    def get_groups(self, search: str = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get groups with optional search filter."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if search:
                cursor.execute("""
                    SELECT * FROM groups
                    WHERE display_name LIKE ? OR description LIKE ?
                    ORDER BY display_name
                    LIMIT ? OFFSET ?
                """, (f"%{search}%", f"%{search}%", limit, offset))
            else:
                cursor.execute("""
                    SELECT * FROM groups
                    ORDER BY display_name
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            return [dict(row) for row in cursor.fetchall()]

    def get_group_count(self, search: str = None) -> int:
        """Get total group count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if search:
                cursor.execute("""
                    SELECT COUNT(*) FROM groups
                    WHERE display_name LIKE ? OR description LIKE ?
                """, (f"%{search}%", f"%{search}%"))
            else:
                cursor.execute("SELECT COUNT(*) FROM groups")
            return cursor.fetchone()[0]

    # Users operations
    def upsert_user(self, user_id: str, mail: str = None, user_principal_name: str = None,
                    display_name: str = None) -> None:
        """Insert or update a user."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (id, mail, user_principal_name, display_name, last_sync_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    mail = excluded.mail,
                    user_principal_name = excluded.user_principal_name,
                    display_name = excluded.display_name,
                    last_sync_at = excluded.last_sync_at,
                    updated_at = CASE 
                        WHEN (users.mail IS NOT NULL AND users.mail != excluded.mail) OR (users.mail IS NULL AND excluded.mail IS NOT NULL)
                             OR (users.user_principal_name IS NOT NULL AND users.user_principal_name != excluded.user_principal_name) OR (users.user_principal_name IS NULL AND excluded.user_principal_name IS NOT NULL)
                             OR (users.display_name IS NOT NULL AND users.display_name != excluded.display_name) OR (users.display_name IS NULL AND excluded.display_name IS NOT NULL)
                        THEN excluded.updated_at 
                        ELSE users.updated_at 
                    END
            """, (user_id, mail, user_principal_name, display_name, datetime.utcnow().isoformat(),
                  datetime.utcnow().isoformat()))

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get a user by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_users_by_group_ids(self, group_ids: List[str]) -> List[Dict]:
        """Get all users in specified groups."""
        if not group_ids:
            return []
        placeholders = ",".join("?" * len(group_ids))
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT DISTINCT u.* FROM users u
                INNER JOIN group_memberships gm ON u.id = gm.user_id
                WHERE gm.group_id IN ({placeholders})
            """, group_ids)
            return [dict(row) for row in cursor.fetchall()]

    # Group memberships operations
    def clear_memberships(self, group_id: str) -> None:
        """Clear all memberships for a group."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM group_memberships WHERE group_id = ?", (group_id,))

    def add_membership(self, group_id: str, user_id: str) -> None:
        """Add a group membership."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO group_memberships (group_id, user_id, added_at)
                VALUES (?, ?, ?)
            """, (group_id, user_id, datetime.utcnow().isoformat()))

    def remove_membership(self, group_id: str, user_id: str) -> None:
        """Remove a group membership."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM group_memberships WHERE group_id = ? AND user_id = ?", (group_id, user_id))

    def get_group_member_count(self, group_id: str) -> int:
        """Get member count for a group."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM group_memberships WHERE group_id = ?", (group_id,))
            cursor.execute("SELECT COUNT(*) FROM group_memberships WHERE group_id = ?", (group_id,))
            return cursor.fetchone()[0]

    def get_group_members_ids(self, group_id: str) -> List[str]:
        """Get all member user IDs for a group."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM group_memberships WHERE group_id = ?", (group_id,))
            return [row[0] for row in cursor.fetchall()]

    # Templates operations
    def create_template(self, name: str, subject: str, body: str) -> int:
        """Create a new template."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO templates (name, subject, body, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (name, subject, body, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
            cursor.execute("SELECT last_insert_rowid()")
            return cursor.fetchone()[0]

    def get_templates(self) -> List[Dict]:
        """Get all templates."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM templates ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]

    def get_template(self, template_id: int) -> Optional[Dict]:
        """Get a template by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # Email tasks operations
    def create_email_task(self, subject: str, body: str, selected_group_ids: List[str],
                          template_id: int = None, created_by: str = None) -> int:
        """Create a new email task."""
        import json
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO email_tasks (template_id, subject, body, selected_group_ids, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (template_id, subject, body, json.dumps(selected_group_ids), created_by,
                  datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
            cursor.execute("SELECT last_insert_rowid()")
            return cursor.fetchone()[0]

    def get_email_task(self, task_id: int) -> Optional[Dict]:
        """Get an email task by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM email_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_email_tasks(self, status: str = None, limit: int = 50) -> List[Dict]:
        """Get email tasks with optional status filter."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute("""
                    SELECT * FROM email_tasks
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (status, limit))
            else:
                cursor.execute("""
                    SELECT * FROM email_tasks
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def update_email_task_status(self, task_id: int, status: str,
                                  started_at: str = None, completed_at: str = None,
                                  sent_count: int = None, failed_count: int = None) -> None:
        """Update email task status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = ["status = ?", "updated_at = ?"]
            params = [status, datetime.utcnow().isoformat()]
            if started_at:
                updates.append("started_at = ?")
                params.append(started_at)
            if completed_at:
                updates.append("completed_at = ?")
                params.append(completed_at)
            if sent_count is not None:
                updates.append("sent_count = ?")
                params.append(sent_count)
            if failed_count is not None:
                updates.append("failed_count = ?")
                params.append(failed_count)
            params.append(task_id)
            cursor.execute(f"""
                UPDATE email_tasks
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)

    def log_email_send(self, task_id: str, recipient_email: str, status: str,
                       error_message: str = None) -> None:
        """Log an email send attempt."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO email_logs (task_id, recipient_email, status, error_message, sent_at)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, recipient_email, status, error_message,
                  datetime.utcnow().isoformat() if status == "sent" else None))

    def get_email_task_stats(self, task_id: int) -> Dict:
        """Get statistics for an email task."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(CASE WHEN status = 'sent' THEN 1 END) as sent,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
                FROM email_logs
                WHERE task_id = ?
            """, (task_id,))
            row = cursor.fetchone()
            return {"sent": row[0], "failed": row[1]}

    # Sync history operations
    def log_sync_start(self, sync_type: str) -> int:
        """Log sync start."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sync_history (sync_type, status, started_at)
                VALUES (?, 'started', ?)
            """, (sync_type, datetime.utcnow().isoformat()))
            cursor.execute("SELECT last_insert_rowid()")
            return cursor.fetchone()[0]

    def log_sync_complete(self, sync_id: int, records_synced: int) -> None:
        """Log sync complete."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sync_history
                SET status = 'completed', completed_at = ?, records_synced = ?
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), records_synced, sync_id))

    def log_sync_error(self, sync_id: int, error_message: str) -> None:
        """Log sync error."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sync_history
                SET status = 'failed', completed_at = ?, error_message = ?
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), error_message, sync_id))

    def get_last_sync_time(self, sync_type: str) -> Optional[str]:
        """Get the last successful sync time."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT completed_at FROM sync_history
                WHERE sync_type = ? AND status = 'completed'
                ORDER BY completed_at DESC
                LIMIT 1
            """, (sync_type,))
            row = cursor.fetchone()
            return row[0] if row else None

    # User activity logging
    def log_activity(self, user_id: str, action: str, details: str = None,
                     ip_address: str = None) -> None:
        """Log user activity."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_activity (user_id, action, details, ip_address, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, action, details, ip_address, datetime.utcnow().isoformat()))


# Global database instance
_db: Optional[Database] = None


def get_db() -> Database:
    """Get or create database instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db
