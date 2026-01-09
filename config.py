"""Configuration management for EntraID Group Email Sender."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Azure AD / EntraID App Registration
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
    AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")

    # Email sender configuration
    SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
    SENDER_NAME = os.getenv("SENDER_NAME", "")

    # Application settings
    STREAMLIT_SERVER_PORT = int(os.getenv("STREAMLIT_SERVER_PORT", "8501"))
    SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))

    # Database path
    DATABASE_PATH = os.getenv("DATABASE_PATH", "entra_mailer.db")

    # Microsoft Graph API settings
    GRAPH_API_BASE_URL = "https://graph.microsoft.com/v1.0"
    GRAPH_AUTH_URL = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token"
    GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

    # Email settings
    EMAIL_BATCH_SIZE = 50  # M365 limit for BCC recipients

    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration and return list of missing values."""
        errors = []
        if not cls.AZURE_TENANT_ID:
            errors.append("AZURE_TENANT_ID")
        if not cls.AZURE_CLIENT_ID:
            errors.append("AZURE_CLIENT_ID")
        if not cls.AZURE_CLIENT_SECRET:
            errors.append("AZURE_CLIENT_SECRET")
        if not cls.SENDER_EMAIL:
            errors.append("SENDER_EMAIL")
        return errors

    @classmethod
    def get_database_path(cls) -> Path:
        """Get the database file path, creating directory if needed."""
        path = Path(cls.DATABASE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
