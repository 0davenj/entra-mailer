#!/usr/bin/env python3
"""
Email sender module for batch email sending with Exchange limits
"""

import time
import logging
from typing import List, Dict

from graph_client import get_graph_client

logger = logging.getLogger(__name__)

def send_batch_emails(subject: str, body: str, recipients: List[str], 
                      sender_email: str, sender_name: str = None) -> Dict[str, int]:
    """
    Send emails in batches to respect Exchange Online limits.
    
    Args:
        subject: Email subject
        body: Email body (HTML)
        recipients: List of recipient email addresses
        sender_email: Sender email address
        sender_name: Sender display name
    
    Returns:
        Dict with 'sent' and 'failed' counts
    """
    # Filter out None/empty emails
    valid_recipients = [r for r in recipients if r and "@" in r]
    
    if not valid_recipients:
        logger.warning("No valid recipients found.")
        return {"sent": 0, "failed": 0}
    
    results = {"sent": 0, "failed": 0}
    graph_client = get_graph_client()
    
    # Exchange Online limit for BCC recipients
    batch_size = 50
    
    for i in range(0, len(valid_recipients), batch_size):
        batch = valid_recipients[i:i + batch_size]
        
        try:
            # Send email to batch
            success = graph_client.send_email(
                subject=subject,
                body=body,
                recipients=batch,
                sender_email=sender_email,
                sender_name=sender_name
            )
            
            if success:
                results["sent"] += len(batch)
                logger.info(f"Sent batch {i//batch_size + 1}/{(len(valid_recipients) + batch_size - 1)//batch_size} ({len(batch)} recipients)")
            else:
                results["failed"] += len(batch)
                logger.error(f"Failed to send batch {i//batch_size + 1}/{(len(valid_recipients) + batch_size - 1)//batch_size}")
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error sending batch {i//batch_size + 1}: {e}")
            results["failed"] += len(batch)
    
    return results