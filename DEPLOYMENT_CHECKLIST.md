# Deployment checklist

## Before pushing to GitHub
- [ ] Confirm `.gitignore` excludes `.env`, `.streamlit/secrets.toml`, database files and `uploads/`.
- [ ] Do not add `teamtrack.db`, `drotax_workspace.db`, employee data, attachments or credentials.
- [ ] Review `migrations/` and ensure it contains source code only, not live company data.

## Streamlit Community Cloud
- Repository: `DaveMaveOzi/drotax-workspace`
- Branch: `main`
- Main file: `app.py`
- Add SMTP credentials through App settings → Secrets, not GitHub.
- Test with demo accounts and non-sensitive test tickets/messages first.

## Before real company use
- Move SQLite to managed PostgreSQL and uploads to durable object storage.
- Implement and test controlled migration of existing accounts and records.
- Configure external inbound email (IMAP or provider webhook); SMTP alone sends mail and does not receive mail.
- Validate approval authority, department scope, tenant isolation and closed-ticket immutability.
- Configure backups, monitoring, audit retention, rate limits and account recovery.
