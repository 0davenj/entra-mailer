#!/usr/bin/env python3
"""
Simple CLI for EntraID Group Email Sender
"""

import argparse
import logging
import os
import sys
from typing import List, Dict, Optional

from simple_graph_client import get_simple_graph_client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global configuration
config = {
    "AZURE_TENANT_ID": None,
    "AZURE_CLIENT_ID": None,
    "AZURE_CLIENT_SECRET": None,
    "SENDER_EMAIL": None,
    "SENDER_NAME": None
}

# Global state
validated_groups = []
retrieved_users = []
email_template = {"subject": "", "body": ""}

def load_env_file(env_file_path=".env"):
    """Load environment variables from a .env file."""
    if not os.path.exists(env_file_path):
        logger.warning(f"Environment file {env_file_path} not found.")
        return
    
    with open(env_file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                os.environ[key] = value

def load_config():
    """Load configuration from environment variables."""
    # First try to load from .env file
    load_env_file()
    
    config["AZURE_TENANT_ID"] = os.getenv("AZURE_TENANT_ID")
    config["AZURE_CLIENT_ID"] = os.getenv("AZURE_CLIENT_ID")
    config["AZURE_CLIENT_SECRET"] = os.getenv("AZURE_CLIENT_SECRET")
    config["SENDER_EMAIL"] = os.getenv("SENDER_EMAIL")
    config["SENDER_NAME"] = os.getenv("SENDER_NAME", "EntraID Email Sender")

def validate_config():
    """Validate required configuration and return list of missing values."""
    errors = []
    for key, value in config.items():
        if not value:
            errors.append(key)
    return errors

def main_menu():
    """Display main menu for the CLI script."""
    print("\n" + "=" * 60)
    print("Welcome to the EntraID Group Email Sender CLI!")
    print("=" * 60)
    print("1. Validate Groups")
    print("2. Retrieve Users")
    print("3. Edit Email Template")
    print("4. Send Emails")
    print("5. Exit")
    print("=" * 60)

def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="EntraID Group Email Sender CLI")
    parser.add_argument("--csv", type=str, help="Path to the CSV file with group_id,group_name,description")
    parser.add_argument("--template", type=str, help="Path to the email template HTML file")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")
    args = parser.parse_args()
    return args

def validate_groups():
    """Validate groups from CSV."""
    import csv
    
    if not args.csv:
        print("Error: No CSV file provided. Please provide a CSV file with group_id,group_name,description.")
        return
    
    if not os.path.exists(args.csv):
        print(f"Error: File {args.csv} not found.")
        return
    
    print(f"Validating groups from {args.csv}...")
    
    try:
        with open(args.csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Check if required columns exist
            if not all(col in reader.fieldnames for col in ['group_id', 'group_name', 'description']):
                print("Error: CSV file must contain group_id, group_name, and description columns.")
                return
            
            # Parse and validate groups
            group_ids = []
            for row in reader:
                group_ids.append(row['group_id'])
            
            # Initialize Graph client
            graph_client = get_simple_graph_client(
                tenant_id=config["AZURE_TENANT_ID"],
                client_id=config["AZURE_CLIENT_ID"],
                client_secret=config["AZURE_CLIENT_SECRET"]
            )
            
            validated = []
            
            # Initialize progress tracker
            from progress_tracker import create_progress_bar
            progress = create_progress_bar("Validating Groups", len(group_ids))
            
            for group_id in group_ids:
                group = graph_client.get_group_by_id(group_id)
                if group:
                    validated.append({
                        'group_id': group_id,
                        'group_name': group['display_name'],
                        'description': group.get('description', ''),
                        'member_count': group.get('member_count', 0)
                    })
                    progress.log_success(f"Validated group: {group['display_name']} ({group_id})")
                else:
                    print(f"Warning: Group {group_id} not found in EntraID.")
                    progress.log_error(f"Group not found: {group_id}")
                
                # Update progress
                progress.update()
            
            global validated_groups
            validated_groups = validated
            
            # Complete progress tracking
            progress.complete()
            
            print(f"Validation complete: {len(validated_groups)} valid groups found.")
            
    except Exception as e:
        print(f"Error validating groups: {e}")

def retrieve_users():
    """Retrieve users for validated groups."""
    if not validated_groups:
        print("Error: No validated groups. Please validate groups first (option 1).")
        return
    
    print(f"Retrieving users for {len(validated_groups)} groups...")
    
    # Initialize Graph client
    graph_client = get_simple_graph_client(
        tenant_id=config["AZURE_TENANT_ID"],
        client_id=config["AZURE_CLIENT_ID"],
        client_secret=config["AZURE_CLIENT_SECRET"]
    )
    
    # Get unique user emails from all groups
    all_users = []
    
    # Initialize progress tracker
    from progress_tracker import create_progress_bar
    progress = create_progress_bar("Retrieving Users", len(validated_groups))
    
    for group in validated_groups:
        group_id = group['group_id']
        print(f"Processing group: {group['group_name']} ({group_id})")
        
        try:
            members = graph_client.get_group_members(group_id)
            for member in members:
                if member.get('mail'):  # Only include users with valid email addresses
                    all_users.append({
                        'id': member['id'],
                        'mail': member['mail'],
                        'display_name': member.get('display_name', ''),
                        'group_id': group_id
                    })
        except Exception as e:
            print(f"Error retrieving members for group {group_id}: {e}")
            progress.log_error(f"Error retrieving members for group {group_id}: {e}")
        
        # Update progress
        progress.update()
    
    # Remove duplicates based on user ID
    unique_users = {}
    for user in all_users:
        if user['id'] not in unique_users:
            unique_users[user['id']] = user
    
    global retrieved_users
    retrieved_users = list(unique_users.values())
    
    # Complete progress tracking
    progress.complete()
    
    print(f"User retrieval complete: {len(retrieved_users)} unique users found.")

def edit_template():
    """Edit email template interactively."""
    print("\nEmail Template Editor")
    print("=" * 60)
    
    # Load existing template if specified
    if args.template:
        try:
            with open(args.template, 'r', encoding='utf-8') as f:
                content = f.read()
                # Simple parsing - assume HTML format with title in <title> tag and body in <body> tag
                title_start = content.find('<title>')
                title_end = content.find('</title>')
                if title_start != -1 and title_end != -1:
                    email_template['subject'] = content[title_start+7:title_end]
                
                body_start = content.find('<body>')
                body_end = content.find('</body>')
                if body_start != -1 and body_end != -1:
                    email_template['body'] = content[body_start+6:body_end]
                else:
                    email_template['body'] = content
                
                print(f"Loaded template from {args.template}")
        except Exception as e:
            print(f"Error loading template: {e}")
    
    # Edit subject
    print("\nCurrent Subject:")
    print(f"  {email_template['subject']}")
    new_subject = input("Enter new subject (or press Enter to keep current): ").strip()
    if new_subject:
        email_template['subject'] = new_subject
    
    # Edit body
    print("\nCurrent Body (first 100 chars):")
    if email_template['body']:
        print(f"  {email_template['body'][:100]}...")
    new_body = input("Enter new body (or press Enter to keep current): ").strip()
    if new_body:
        email_template['body'] = new_body
    
    # Preview
    print("\nTemplate Preview:")
    print("=" * 60)
    print(f"Subject: {email_template['subject']}")
    print("-" * 60)
    print(f"Body: {email_template['body']}")
    print("=" * 60)
    
    # Save option
    save = input("Save template to file? (y/n): ").strip().lower()
    if save == 'y':
        filename = input("Enter filename: ").strip()
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"<title>{email_template['subject']}</title>\n")
                f.write(f"<body>\n{email_template['body']}\n</body>")
            print(f"Template saved to {filename}")
        except Exception as e:
            print(f"Error saving template: {e}")

def send_emails():
    """Send emails to retrieved users."""
    if not retrieved_users:
        print("Error: No retrieved users. Please retrieve users first (option 2).")
        return
    
    if not email_template['subject'] or not email_template['body']:
        print("Error: Email template is incomplete. Please edit template first (option 3).")
        return
    
    print(f"\nSending emails to {len(retrieved_users)} users...")
    print(f"Template: {email_template['subject']}")
    
    confirm = input("Proceed with sending? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Email sending cancelled.")
        return
    
    # Prepare recipients
    recipients = [user['mail'] for user in retrieved_users]
    
    # Initialize Graph client
    graph_client = get_simple_graph_client(
        tenant_id=config["AZURE_TENANT_ID"],
        client_id=config["AZURE_CLIENT_ID"],
        client_secret=config["AZURE_CLIENT_SECRET"]
    )
    
    # Send emails in batches
    from email_sender import send_batch_emails
    
    batch_size = 50  # Exchange Online limit
    sent_count = 0
    failed_count = 0
    
    # Initialize progress tracker
    from progress_tracker import create_progress_bar
    total_batches = (len(recipients) + batch_size - 1) // batch_size
    progress = create_progress_bar("Sending Emails", total_batches)
    
    for i in range(0, len(recipients), batch_size):
        batch = recipients[i:i+batch_size]
        print(f"Sending batch {i//batch_size + 1}/{total_batches} ({len(batch)} recipients)")
        
        try:
            result = send_batch_emails(
                subject=email_template['subject'],
                body=email_template['body'],
                recipients=batch,
                graph_client=graph_client,
                sender_email=config['SENDER_EMAIL'],
                sender_name=config['SENDER_NAME']
            )
            sent_count += result['sent']
            failed_count += result['failed']
            
            # Log success/failure
            if result['sent'] > 0:
                progress.log_success(f"Sent batch {i//batch_size + 1}/{total_batches} ({result['sent']} recipients)")
            if result['failed'] > 0:
                progress.log_error(f"Failed to send batch {i//batch_size + 1}/{total_batches} ({result['failed']} recipients)")
                
        except Exception as e:
            print(f"Error sending batch: {e}")
            progress.log_error(f"Error sending batch {i//batch_size + 1}: {e}")
            failed_count += len(batch)
        
        # Update progress
        progress.update()
    
    # Complete progress tracking
    progress.complete()
    
    print("\nEmail sending complete!")
    print(f"Sent: {sent_count}")
    print(f"Failed: {failed_count}")
    print(f"Total: {sent_count + failed_count}")

def run():
    """Main function to run the CLI script."""
    global args
    args = parse_arguments()
    load_config()
    errors = validate_config()
    
    if errors:
        logger.error("Missing configuration:")
        for e in errors:
            logger.error(f"- {e}")
        logger.error("Please set these environment variables before running the script.")
        return
    
    # Graph client initialization for validation
    try:
        # Initialize Graph client
        graph_client = get_simple_graph_client(
            tenant_id=config["AZURE_TENANT_ID"],
            client_id=config["AZURE_CLIENT_ID"],
            client_secret=config["AZURE_CLIENT_SECRET"]
        )
        logger.info("Graph client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Graph client: {e}")
        return
    
    if args.interactive:
        while True:
            main_menu()
            choice = input("Enter your choice (1-5): ").strip()
            print()
            
            if choice == "1":
                validate_groups()
            elif choice == "2":
                retrieve_users()
            elif choice == "3":
                edit_template()
            elif choice == "4":
                send_emails()
            elif choice == "5":
                logger.info("Exiting...")
                break
            else:
                logger.error("Invalid choice. Please enter a number between 1 and 5.")
                
            input("\nPress Enter to continue...")
    else:
        # Non-interactive mode
        if args.csv:
            validate_groups()
        else:
            logger.error("No CSV file provided. Use --csv or run with --interactive.")
            sys.exit(1)
        
        if retrieved_users:
            retrieve_users()
        
        if email_template['subject'] and email_template['body']:
            send_emails()

if __name__ == "__main__":
    run()