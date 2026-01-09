# EntraID Group Email Sender

Python-based web application for sending emails to users in selected EntraID groups. Built with Streamlit, Microsoft Graph API, and SQLite.

## Features

- **Group Selection**: Search and filter thousands of cached groups
- **Email Sending**: Batch processing with BCC-only recipients
- **Template Editor**: Create and save HTML email templates
- **Background Sync**: Hourly synchronization of groups and users
- **Task Monitoring**: Real-time progress tracking and reports
- **Audit Logging**: Track user actions and email sends

## Requirements

- Docker and Docker Compose
- Azure AD App Registration with permissions:
  - `GroupMember.Read.All`
  - `Group.Read.All`
  - `User.Read.All`
  - `Mail.Send`

## Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd entra-mailer
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your Azure AD credentials
   ```

3. **Create data directory**
   ```bash
   mkdir -p data
   ```

4. **Build and run with Docker Compose**
   ```bash
   docker-compose up -d --build
   ```

5. **Access the application**
   - Open http://localhost:8501 in your browser

## Manual Run

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export AZURE_TENANT_ID=your-tenant-id
export AZURE_CLIENT_ID=your-client-id
export AZURE_CLIENT_SECRET=your-client-secret
export SENDER_EMAIL=your-sender@domain.com

# Run the application
streamlit run app.py
```

## Azure AD App Registration

Create an App Registration in Azure Portal:

1. Go to Azure Active Directory → App registrations
2. Click "New registration"
3. Configure:
   - Name: EntraID Email Sender
   - Supported account types: Single tenant
   - Redirect URI: Leave empty (not needed for client credentials)

4. Note the Application (client) ID and Directory (tenant) ID

5. Create a client secret:
   - Go to Certificates & secrets
   - Create new client secret
   - Note the secret value

6. Configure API permissions:
   - Microsoft Graph → Application permissions
   - Add: `GroupMember.Read.All`, `Group.Read.All`, `User.Read.All`, `Mail.Send`
   - Grant admin consent

7. Update `.env` file with credentials

## Architecture

```
User → CloudFlare Proxy → Streamlit WebUI
                              ↓
                    SQLite Database
                              ↓
         ┌────────────────────┼────────────────────┐
         ↓                    ↓                    ↓
   Sync Worker        Email Worker          Graph API
         ↓                    ↓                    ↓
    Graph API                                      EntraID
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| AZURE_TENANT_ID | Azure AD Tenant ID | Yes |
| AZURE_CLIENT_ID | App Registration Client ID | Yes |
| AZURE_CLIENT_SECRET | App Registration Secret | Yes |
| SENDER_EMAIL | Sender email address | Yes |
| SENDER_NAME | Sender display name | No |
| STREAMLIT_SERVER_PORT | Web UI port (default: 8501) | No |
| SYNC_INTERVAL_MINUTES | Sync interval (default: 60) | No |
| DATABASE_PATH | SQLite database path | No |

## Usage

1. **First Run**: The sync worker will automatically start and load all groups/users from EntraID
2. **Select Groups**: Use the search to find and select groups
3. **Create Template**: Use the template editor to create email content
4. **Send Email**: Review recipient count and send
5. **Monitor**: Track progress in the Task Monitoring page

## KISS & YAGNI Compliance

- No complex authentication (proxy handles it)
- No external message queue (SQLite suffices)
- No caching layer (minimal API calls needed)
- Simple but functional UI
