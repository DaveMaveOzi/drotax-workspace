# Drotax Workspace

A unified Streamlit application combining a shared employee directory, internal email, ticket/task workflows and notifications.

## Included in this starter build
- One sign-in and shared user directory.
- Admin, IT Personnel, Team Lead, Member and Viewer roles.
- Overview dashboard.
- Internal email inbox and compose screen.
- Recipient name/email matching with selectable full email suggestions.
- New-mail unread counter and a subtle sound alert while the workspace is open (15-second polling); sound can be muted.
- TeamTrack ticket creation, assignment, status updates and comments.
- Shared in-app notifications.
- Light/dark theme.
- Legacy source copies in `migrations/` for reference during migration.

## Run in PyCharm (Windows)
1. Extract this folder.
2. Open the folder in PyCharm.
3. Open Terminal and create a virtual environment: `python -m venv .venv`
4. Activate it: `.venv\\Scripts\\activate`
5. Install packages: `python -m pip install -r requirements.txt`
6. Run: `python -m streamlit run app.py`
7. On first launch, create the first administrator account.

## Email configuration
Internal messages are stored and delivered to Drotax Workspace accounts. For external email delivery, configure Streamlit secrets or environment variables:

```toml
SMTP_HOST = "smtp.your-provider.com"
SMTP_PORT = "587"
SMTP_USERNAME = "your-account"
SMTP_PASSWORD = "your-app-password"
SMTP_FROM_EMAIL = "mail@yourdomain.com"
```

The current implementation reads SMTP values from environment variables. For Streamlit Community Cloud, add a small secrets-to-environment adapter or update `send_external_email` to read `st.secrets` before using external delivery. Never commit credentials.

## Important limitations before production
This is an integration MVP, not yet a production migration of every legacy screen. The TeamTrack module currently includes core ticket creation, assignment, status and comments; the legacy source is retained under `migrations/` for porting the remaining reports, workspace settings, registration flows and other existing screens. The legacy Drotax Mail source is also retained for porting remaining Sent, Drafts, Contacts, IMAP import and administration features.

The database currently uses SQLite for local development. Do not use this local database on Streamlit Community Cloud for durable company records. Before real company use, migrate to managed PostgreSQL and durable attachment storage, implement backups, rate limiting, audit logging, stronger authorization tests and secure deployment secrets.

The notification sound requires the browser to permit audio playback. A user may need to interact with the page first. The current mail polling only detects messages delivered into this unified app; it does not independently monitor an external IMAP mailbox.

## Legacy migration
Do not copy a production database over the new database. Back up both existing databases and implement/test a controlled migration for user accounts, password hash schemes, messages, recipients, tickets, comments, attachments and notifications before switching users to this application. The legacy source files are reference copies, not an automatic data migration.
