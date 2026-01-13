# EntraID Group Email Sender CLI

A simplified command-line interface for sending emails to users in EntraID groups. This tool is designed to handle large-scale operations efficiently, with a focus on performance and simplicity.

## Features

- **CSV-based group input**: Process groups from a CSV file
- **Batch email sending**: Respect Exchange Online limits (50 recipients per email)
- **Progress tracking**: Real-time progress bars and detailed reporting
- **Template editor**: Create and edit email templates inline
- **Direct API calls**: No database overhead for better performance

## Requirements

- Python 3.7+
- Azure AD App Registration with the following permissions:
  - `GroupMember.Read.All`
  - `Group.Read.All`
  - `User.Read.All`
  - `Mail.Send`

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd entra-mailer
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Create an Azure AD App Registration:
   - Go to Azure Active Directory → App registrations
   - Click "New registration"
   - Configure:
     - Name: EntraID Email Sender CLI
     - Supported account types: Single tenant
     - Redirect URI: Leave empty (not needed for client credentials)

2. Note the Application (client) ID and Directory (tenant) ID

3. Create a client secret:
   - Go to Certificates & secrets
   - Create new client secret
   - Note the secret value

4. Configure API permissions:
   - Microsoft Graph → Application permissions
   - Add: `GroupMember.Read.All`, `Group.Read.All`, `User.Read.All`, `Mail.Send`
   - Grant admin consent

5. Set environment variables:
   ```bash
   export AZURE_TENANT_ID=your-tenant-id
   export AZURE_CLIENT_ID=your-client-id
   export AZURE_CLIENT_SECRET=your-client-secret
   export SENDER_EMAIL=your-sender@domain.com
   export SENDER_NAME="Your Name"
   ```

## Usage

### Interactive Mode

Run the script in interactive mode to use the menu-driven interface:

```bash
python simple_cli.py --interactive
```

### Non-Interactive Mode

Run the script with command-line arguments for automated processing:

```bash
python simple_cli.py --csv groups.csv --template template.html
```

### Command-Line Options

- `--csv`: Path to the CSV file with group_id,group_name,description
- `--template`: Path to the email template HTML file
- `--interactive`: Run in interactive mode

## CSV Format

The CSV file should have the following columns:

```csv
group_id,group_name,description
12345,Marketing Team,Marketing department staff
67890,Developers,Software development team
11111,Sales Team,Sales department members
```

## Email Template Format

Email templates should be in HTML format with the subject in a `<title>` tag and the body in a `<body>` tag:

```html
<title>Important Announcement</title>
<body>
  <h1>Hello Team!</h1>
  <p>This is an important announcement about our company policy.</p>
  <p>Please review the attached document.</p>
</body>
```

## Workflow

1. **Validate Groups**: Load and validate groups from the CSV file
2. **Retrieve Users**: Get users from the validated groups
3. **Edit Template**: Create or edit the email template
4. **Send Emails**: Send emails to the retrieved users in batches

## Performance

This CLI tool is optimized for large-scale operations:

- **Direct API calls**: No database overhead
- **Targeted queries**: Only fetch data for specified groups
- **Batch processing**: Process users in chunks to avoid memory issues
- **Progress tracking**: Real-time feedback on long-running operations

## Troubleshooting

### Authentication Issues

If you encounter authentication errors:

1. Verify your Azure AD App Registration has the correct permissions
2. Check that admin consent has been granted for the permissions
3. Ensure your environment variables are set correctly

### Group Not Found

If groups are not found in EntraID:

1. Verify the group IDs in your CSV file are correct
2. Check that the groups exist in your EntraID tenant
3. Ensure your app has the `Group.Read.All` permission

### Email Sending Issues

If emails fail to send:

1. Verify your sender email address is valid
2. Check that your app has the `Mail.Send` permission
3. Ensure you're not exceeding Exchange Online rate limits

## Migration from Web Interface

If you're migrating from the web interface:

1. Export your groups to a CSV file
2. Save your email templates as HTML files
3. Set the required environment variables
4. Run the CLI script with your CSV file and template

## Support

For issues and questions, please open an issue in the repository.