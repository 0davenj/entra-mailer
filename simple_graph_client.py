#!/usr/bin/env python3
"""
Simplified Microsoft Graph API client for the CLI script
"""

import time
import requests
from typing import Optional, List, Dict, Any, Generator
from datetime import datetime

class SimpleGraphClient:
    """Simplified client for Microsoft Graph API with authentication and rate limiting."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        """Initialize the Graph client with credentials."""
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[float] = None
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        self.graph_api_base_url = "https://graph.microsoft.com/v1.0"
        self.graph_auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        self.graph_scope = ["https://graph.microsoft.com/.default"]

    def _get_access_token(self) -> str:
        """Get or refresh access token using client credentials."""
        if self.access_token and self.token_expires_at and time.time() < self.token_expires_at - 60:
            return self.access_token

        # Request new token using client credentials flow
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }

        response = self.session.post(
            self.graph_auth_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()

        token_data = response.json()
        self.access_token = token_data["access_token"]
        self.token_expires_at = time.time() + token_data["expires_in"]

        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}"
        })

        return self.access_token

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated request to Graph API with retry logic."""
        self._get_access_token()

        # Handle both full URLs and relative paths
        if endpoint.startswith("http"):
            url = endpoint
        else:
            url = f"{self.graph_api_base_url}{endpoint}"

        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, **kwargs)

                # Handle rate limiting
                if response.status_code == 429:
                    wait_time = int(response.headers.get("Retry-After", retry_delay))
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise

        return {}

    def _paginate(self, endpoint: str, key: str = "value") -> Generator[List[Dict], None, None]:
        """Paginate through Graph API results."""
        url = endpoint
        while url:
            data = self._request("GET", url)
            values = data.get(key, [])
            yield values
            # Check if nextLink is a full URL or just a path
            next_link = data.get("@odata.nextLink", "")
            if next_link.startswith("http"):
                url = next_link
            elif next_link:
                url = f"{self.graph_api_base_url}{next_link}"
            else:
                url = None

    def get_group_by_id(self, group_id: str) -> Optional[Dict]:
        """Get a group by ID."""
        try:
            group = self._request("GET", f"/groups/{group_id}")
            return {
                "id": group.get("id"),
                "display_name": group.get("displayName"),
                "description": group.get("description"),
                "member_count": group.get("members@odata.count", 0)
            }
        except requests.exceptions.HTTPError:
            return None

    def get_group_members(self, group_id: str) -> List[Dict]:
        """Get all members of a group."""
        members = []
        for batch in self._paginate(f"/groups/{group_id}/members"):
            for member in batch:
                if member.get("@odata.type") == "#microsoft.graph.user":
                    members.append({
                        "id": member.get("id"),
                        "mail": member.get("mail"),
                        "user_principal_name": member.get("userPrincipalName"),
                        "display_name": member.get("displayName")
                    })
        return members

    def send_email(self, subject: str, body: str, recipients: List[str],
                   sender_email: str, sender_name: str = None) -> bool:
        """
        Send an email to multiple recipients using BCC.

        Args:
            subject: Email subject
            body: Email body (HTML)
            recipients: List of recipient email addresses
            sender_email: Sender email address
            sender_name: Sender display name

        Returns:
            True if email was sent successfully
        """
        self._get_access_token()

        sender_display = sender_name or sender_email

        # Create message with all recipients in BCC
        message = {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body
            },
            "toRecipients": [
                {"emailAddress": {"address": sender_email}}  # Send to self, BCC others
            ],
            "bccRecipients": [
                {"emailAddress": {"address": email}} for email in recipients if email
            ]
        }

        try:
            self._request(
                "POST",
                f"/users/{sender_email}/sendMail",
                json={"message": message, "saveToSentItems": True}
            )
            return True
        except requests.exceptions.RequestException:
            return False


def get_simple_graph_client(tenant_id: str, client_id: str, client_secret: str) -> SimpleGraphClient:
    """Get or create a simplified Graph client instance."""
    return SimpleGraphClient(tenant_id, client_id, client_secret)