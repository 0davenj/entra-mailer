"""Streamlit WebUI for EntraID Group Email Sender."""
import streamlit as st
import json
from datetime import datetime
from typing import List, Dict, Optional
from streamlit_autorefresh import st_autorefresh

from config import Config
from db import get_db
from sync_worker import get_sync_worker, start_sync_worker
from email_worker import get_email_worker, start_email_worker

# Page configuration
st.set_page_config(
    page_title="EntraID Group Email Sender",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize database and workers
db = get_db()
sync_worker = get_sync_worker()
email_worker = get_email_worker()


def init_session_state():
    """Initialize session state variables."""
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = True  # Auto-login for testing
    if "user_id" not in st.session_state:
        st.session_state.user_id = "web_user"
    if "selected_groups" not in st.session_state:
        st.session_state.selected_groups = []
    if "template_subject" not in st.session_state:
        st.session_state.template_subject = ""
    if "template_body" not in st.session_state:
        st.session_state.template_body = "<html><body><h1>Hello</h1><p>This is an announcement.</p></body></html>"


def login_page():
    """Display login page."""
    st.title("🔐 EntraID Group Email Sender")

    st.markdown("""
    This application allows you to send emails to users in selected EntraID groups.

    **Note:** Authentication is handled by your proxy (CloudFlare). 
    Simply access this page through your authenticated proxy.
    """)

    # Check for proxy authentication headers (if available)
    # This is a placeholder - adjust based on your proxy setup
    if st.button("Login"):
        st.session_state.logged_in = True
        st.session_state.user_id = "web_user"
        st.rerun()


def sidebar_status():
    """Display status in sidebar."""
    st.sidebar.header("📊 Status")

    # Add auto-refresh to show progress
    st_autorefresh(interval=5000, key="status_refresh")

    # Sync status
    sync_status = sync_worker.get_status()
    st.sidebar.markdown("### 🔄 Sync Worker")
    st.sidebar.write(f"Running: {'✅' if sync_status['running'] else '❌'}")
    st.sidebar.write(f"Interval: {sync_status['interval_minutes']} min")
    if sync_status['last_groups_sync']:
        st.sidebar.write(f"Last sync: {sync_status['last_groups_sync'][:19].replace('T', ' ')}")
    
    # Sync progress
    progress = sync_status.get('progress', {})
    if progress.get('status') == 'running':
        st.sidebar.info(f"🔄 {progress.get('message', 'Syncing...')}")
        percent = progress.get('percent', 0)
        st.sidebar.progress(percent / 100)
    elif progress.get('status') == 'completed':
        st.sidebar.success("✅ Sync completed")
    elif progress.get('status') == 'error':
        st.sidebar.error(f"❌ {progress.get('message', 'Sync error')}")

    if st.sidebar.button("🔄 Trigger Sync", disabled=progress.get('status') == 'running'):
        if sync_worker.trigger_sync():
            st.sidebar.success("Sync triggered!")
        else:
            st.sidebar.error("Failed to trigger sync")

    # Email worker status
    email_status = email_worker.get_status()
    st.sidebar.markdown("### 📧 Email Worker")
    st.sidebar.write(f"Running: {'✅' if email_status['running'] else '❌'}")
    st.sidebar.write(f"Pending: {email_status['pending_tasks']}")
    st.sidebar.write(f"Processing: {email_status['processing_tasks']}")

    # Configuration check
    st.sidebar.markdown("### ⚙️ Configuration")
    errors = Config.validate()
    if errors:
        st.sidebar.error("Missing config:")
        for e in errors:
            st.sidebar.write(f"- {e}")
    else:
        st.sidebar.success("✅ Config valid")


def group_selection_page():
    """Display group selection page."""
    st.title("👥 Group Selection")

    # Search box
    search_query = st.text_input("🔍 Search groups", placeholder="Enter group name...")

    # Get groups from local cache
    groups = db.get_groups(search=search_query if search_query else None, limit=100)
    total_groups = db.get_group_count(search=search_query if search_query else None)

    st.markdown(f"**Found {len(groups)} of {total_groups} groups**")

    # Pagination controls (simplified)
    col1, col2 = st.columns([3, 1])
    with col2:
        st.write("Use search to filter")

    # Group selection
    st.markdown("### Select Groups")

    # Create a DataFrame-like display
    if groups:
        # Group by selection state
        selected_ids = set(st.session_state.selected_groups)

        for group in groups:
            col1, col2, col3, col4 = st.columns([1, 3, 4, 1])
            is_selected = group["id"] in selected_ids

            with col1:
                checkbox_key = f"group_{group['id']}"
                new_state = st.checkbox(
                    "",
                    value=is_selected,
                    key=checkbox_key,
                    on_change=toggle_group_selection,
                    args=(group["id"],)
                )

            with col2:
                st.write(f"**{group['display_name']}**")
            with col3:
                st.write(group.get("description", "") or "No description")
            with col4:
                st.write(f"👥 {group.get('member_count', 0)}")

        # Summary
        st.markdown("---")
        st.markdown(f"**Selected: {len(st.session_state.selected_groups)} groups**")

        if st.session_state.selected_groups:
            # Calculate total recipients
            users = db.get_users_by_group_ids(st.session_state.selected_groups)
            valid_users = [u for u in users if u.get("mail")]
            st.info(f"Total unique recipients: {len(valid_users)}")

            if st.button("Clear Selection"):
                st.session_state.selected_groups = []
                st.rerun()
    else:
        st.warning("No groups found. Trigger a sync to load groups from EntraID.")


def toggle_group_selection(group_id: str):
    """Toggle group selection."""
    if group_id in st.session_state.selected_groups:
        st.session_state.selected_groups.remove(group_id)
    else:
        st.session_state.selected_groups.append(group_id)


def template_editor_page():
    """Display template editor page."""
    st.title("📝 Email Template")

    # Get existing templates
    templates = db.get_templates()

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### Saved Templates")
        if templates:
            template_names = [t["name"] for t in templates]
            selected_template = st.selectbox("Load template", [""] + template_names)

            if selected_template:
                template = next(t for t in templates if t["name"] == selected_template)
                st.session_state.template_subject = template["subject"]
                st.session_state.template_body = template["body"]
        else:
            st.info("No saved templates")

    with col2:
        st.markdown("### Save Current Template")
        template_name = st.text_input("Template name")
        if st.button("Save Template") and template_name:
            try:
                db.create_template(template_name, st.session_state.template_subject, st.session_state.template_body)
                st.success(f"Template '{template_name}' saved!")
            except Exception as e:
                st.error(f"Failed to save template: {e}")

    st.markdown("---")

    # Email composition
    st.markdown("### Compose Email")

    subject = st.text_input("Subject", value=st.session_state.template_subject, key="email_subject")
    body = st.text_area("Email Body (HTML)", value=st.session_state.template_body, height=300, key="email_body")

    # Preview
    if st.expander("👁️ Email Preview"):
        st.markdown(body, unsafe_allow_html=True)

    # Update session state
    st.session_state.template_subject = subject
    st.session_state.template_body = body

    return subject, body


def send_email_page():
    """Display send email page."""
    st.title("📤 Send Email")

    # Summary of selected groups
    if not st.session_state.selected_groups:
        st.warning("No groups selected. Please select groups first.")
        if st.button("Go to Group Selection"):
            st.rerun()
        return

    # Get recipient count
    users = db.get_users_by_group_ids(st.session_state.selected_groups)
    valid_users = [u for u in users if u.get("mail")]

    st.markdown("### Summary")
    st.write(f"Selected groups: {len(st.session_state.selected_groups)}")
    st.write(f"Total recipients: {len(valid_users)}")
    st.write(f"Batch size: {Config.EMAIL_BATCH_SIZE}")
    st.write(f"Estimated batches: {(len(valid_users) + Config.EMAIL_BATCH_SIZE - 1) // Config.EMAIL_BATCH_SIZE}")

    # Show selected groups
    with st.expander("View selected groups"):
        for gid in st.session_state.selected_groups:
            groups = db.get_groups()
            group = next((g for g in groups if g["id"] == gid), None)
            if group:
                st.write(f"- {group['display_name']}")

    st.markdown("---")

    # Template (use from session or create new)
    st.markdown("### Email Content")

    # Option to use saved template
    templates = db.get_templates()
    use_template = st.checkbox("Use saved template")
    if use_template:
        template_names = [t["name"] for t in templates]
        selected_template = st.selectbox("Select template", template_names)
        if selected_template:
            template = next(t for t in templates if t["name"] == selected_template)
            subject = template["subject"]
            body = template["body"]
    else:
        subject = st.text_input("Subject", value="Important Announcement")
        body = st.text_area("Body (HTML)", value="<html><body><h1>Hello</h1><p>Your message here.</p></body></html>", height=200)

    # Preview
    with st.expander("Preview"):
        st.markdown(body, unsafe_allow_html=True)

    # Send button
    st.markdown("---")
    if st.button("📤 Send Email", type="primary"):
        if not valid_users:
            st.error("No valid recipients found!")
            return

        # Create task
        try:
            task_id = email_worker.create_task(
                subject=subject,
                body=body,
                selected_group_ids=st.session_state.selected_groups,
                created_by=st.session_state.user_id
            )
            st.success(f"Email task #{task_id} created and queued for processing!")

            # Log activity
            db.log_activity(
                user_id=st.session_state.user_id,
                action="send_email",
                details=f"Task {task_id}: {len(valid_users)} recipients",
                ip_address=st.remote_ip if hasattr(st, "remote_ip") else None
            )

            # Clear selection
            st.session_state.selected_groups = []

        except Exception as e:
            st.error(f"Failed to create task: {e}")


def task_monitoring_page():
    """Display task monitoring page."""
    st.title("📊 Task Monitoring")

    # Get recent tasks
    tasks = email_worker.get_recent_tasks(limit=20)

    # Summary stats
    col1, col2, col3, col4 = st.columns(4)
    pending = len([t for t in tasks if t["status"] == "pending"])
    processing = len([t for t in tasks if t["status"] == "processing"])
    completed = len([t for t in tasks if t["status"] == "completed"])
    failed = len([t for t in tasks if t["status"] == "failed"])

    col1.metric("Pending", pending)
    col2.metric("Processing", processing)
    col3.metric("Completed", completed)
    col4.metric("Failed", failed)

    st.markdown("---")

    # Task list
    st.markdown("### Recent Tasks")

    if tasks:
        for task in tasks:
            with st.expander(f"Task #{task['id']} - {task['status'].upper()} - {task['created_at'][:19].replace('T', ' ')}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Subject:** {task['subject']}")
                    st.write(f"**Status:** {task['status']}")
                    st.write(f"**Created:** {task['created_at'][:19].replace('T', ' ')}")
                with col2:
                    st.write(f"**Total:** {task['total_recipients'] or 'Calculating...'}")
                    st.write(f"**Sent:** {task['sent_count']}")
                    st.write(f"**Failed:** {task['failed_count']}")

                # Progress bar
                if task["status"] == "processing" and task["total_recipients"]:
                    progress = (task["sent_count"] + task["failed_count"]) / task["total_recipients"]
                    st.progress(progress)

                # Groups
                selected_groups = json.loads(task["selected_group_ids"])
                st.write(f"**Groups:** {len(selected_groups)}")
                for gid in selected_groups[:5]:
                    groups = db.get_groups()
                    group = next((g for g in groups if g["id"] == gid), None)
                    if group:
                        st.write(f"  - {group['display_name']}")
                if len(selected_groups) > 5:
                    st.write(f"  - ... and {len(selected_groups) - 5} more")
    else:
        st.info("No tasks yet")


def activity_log_page():
    """Display activity log page."""
    st.title("📋 Activity Log")

    # Get recent activity (simplified - would need full implementation)
    st.info("Activity logging is enabled. Check database for full logs.")

    st.markdown("""
    The following actions are logged:
    - Email sends (task creation)
    - Group selections
    - Template modifications
    - Sync operations
    """)


def main():
    """Main application entry point."""
    # Initialize session state
    init_session_state()

    # Check configuration
    errors = Config.validate()
    if errors:
        st.error("Missing configuration:")
        for e in errors:
            st.write(f"- {e}")
        st.stop()

    # Start background workers (only once)
    if "workers_started" not in st.session_state:
        start_sync_worker()
        start_email_worker()
        st.session_state.workers_started = True

    # Show login page if not logged in
    if not st.session_state.logged_in:
        login_page()
        return

    # Main application
    sidebar_status()

    # Navigation
    pages = {
        "Group Selection": group_selection_page,
        "Template Editor": template_editor_page,
        "Send Email": send_email_page,
        "Task Monitoring": task_monitoring_page,
        "Activity Log": activity_log_page
    }

    page = st.sidebar.selectbox("Navigation", list(pages.keys()))

    # Render selected page
    pages[page]()


if __name__ == "__main__":
    main()
