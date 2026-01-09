"""Microsoft Graph API client for EntraID Group Email Sender."""
import time
import requests
from typing import Optional, List, Dict, Any, Generator
from datetime import datetime

from config import Config
from db import get_db


class GraphClient:
    """Client for Microsoft Graph API with authentication and rate limiting."""

    def __init__(self):
        """Initialize the Graph client."""
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[float] = None
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def _get_access_token(self) -> str:
        """Get or refresh access token using client credentials."""
        if self.access_token and self.token_expires_at and time.time() < self.token_expires_at - 60:
            return self.access_token

        # Request new token using client credentials flow
        data = {
            "client_id": Config.AZURE_CLIENT_ID,
            "client_secret": Config.AZURE_CLIENT_SECRET,
            "scope": " ".join(Config.GRAPH_SCOPE),
            "grant_type": "client_credentials"
        }

        response = self.session.post(Config.GRAPH_AUTH_URL, data=data)
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

        url = f"{Config.GRAPH_API_BASE_URL}{endpoint}"
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
            url = data.get("@odata.nextLink")

    # Groups operations
    def get_groups(self, search: str = None, limit: int = 100) -> List[Dict]:
        """Get all groups from EntraID."""
        if search:
            endpoint = f"/groups?$filter=startswith(displayName,'{search}')&$top={limit}"
        else:
            endpoint = f"/groups?$top={limit}"

        groups = []
        for batch in self._paginate(endpoint):
            for group in batch:
                groups.append({
                    "id": group.get("id"),
                    "display_name": group.get("displayName"),
                    "description": group.get("description"),
                    "mail": group.get("mail"),
                    "security_enabled": group.get("securityEnabled")
                })

        return groups

    def get_all_groups(self) -> List[Dict]:
        """Get all groups with full pagination."""
        all_groups = []
        for batch in self._paginate("/groups?$top=999"):
            for group in batch:
                all_groups.append({
                    "id": group.get("id"),
                    "display_name": group.get("displayName"),
                    "description": group.get("description"),
                    "mail": group.get("mail"),
                    "security_enabled": group.get("securityEnabled")
                })
        return all_groups

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

    def get_transitive_group_members(self, group_id: str) -> List[Dict]:
        """Get all transitive members of a group (includes nested groups)."""
        members = []
        for batch in self._paginate(f"/groups/{group_id}/transitiveMembers"):
            for member in batch:
                if member.get("@odata.type") == "#microsoft.graph.user":
                    members.append({
                        "id": member.get("id"),
                        "mail": member.get("mail"),
                        "user_principal_name": member.get("userPrincipalName"),
                        "display_name": member.get("displayName")
                    })
        return members

    # Users operations
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get a user by ID."""
        try:
            user = self._request("GET", f"/users/{user_id}")
            return {
                "id": user.get("id"),
                "mail": user.get("mail"),
                "user_principal_name": user.get("userPrincipalName"),
                "display_name": user.get("displayName")
            }
        except requests.exceptions.HTTPError:
            return None

    def search_users(self, query: str, limit: int = 25) -> List[Dict]:
        """Search for users."""
        users = []
        for batch in self._paginate(f"/users?$filter=startswith(mail,'{query}') or startswith(displayName,'{query}')&$top={limit}"):
            for user in batch:
                users.append({
                    "id": user.get("id"),
                    "mail": user.get("mail"),
                    "user_principal_name": user.get("userPrincipalName"),
                    "display_name": user.get("displayName")
                })
        return users

    # Email operations
    def send_email(self, subject: str, body: str, recipients: List[str],
                   sender_email: str = None, sender_name: str = None) -> bool:
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

        sender = sender_email or Config.SENDER_EMAIL
        sender_display = sender_name or Config.SENDER_NAME

        # Create message with all recipients in BCC
        message = {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body
            },
            "toRecipients": [
                {"emailAddress": {"address": sender}}  # Send to self, BCC others
            ],
            "bccRecipients": [
                {"emailAddress": {"address": email}} for email in recipients if email
            ]
        }

        try:
            self._request(
                "POST",
                f"/users/{sender}/sendMail",
                json={"message": message, "saveToSentItems": True}
            )
            return True
        except requests.exceptions.RequestException:
            return False

    def send_batch_emails(self, subject: str, body: str, recipients: List[str],
                          batch_size: int = 50) -> Dict[str, int]:
        """
        Send emails in batches.

        Args:
            subject: Email subject
            body: Email body (HTML)
            recipients: List of recipient email addresses
            batch_size: Number of recipients per email

        Returns:
            Dict with 'sent' and 'failed' counts
        """
        results = {"sent": 0, "failed": 0}

        # Filter out None/empty emails
        valid_recipients = [r for r in recipients if r and "@" in r]

        for i in range(0, len(valid_recipients), batch_size):
            batch = valid_recipients[i:i + batch_size]
            if self.send_email(subject, body, batch):
                results["sent"] += len(batch)
            else:
                results["failed"] += len(batch)

            # Small delay to avoid rate limiting
            time.sleep(0.5)

        return results


# Global Graph client instance
_graph_client: Optional[GraphClient] = None


def get_graph_client() -> GraphClient:
    """Get or create Graph client instance."""
    global _graph_client
    if _graph_client is None:
        _graph_client = GraphClient()
    return _graph_client
