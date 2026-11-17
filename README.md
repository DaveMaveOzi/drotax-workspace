# Drotax Mail — Streamlit starter

This is the Streamlit rebuild of Drotax Mail. It uses SQLite locally, includes a visible high-contrast navigation sidebar and a Light/Dark appearance switch, and supports:
- First-run administrator setup
- Employee account creation by an administrator
- Login with salted PBKDF2 password hashes
- Internal email delivery between registered employees
- Inbox, sent items, contacts, compose, reply entry point and attachments
- SMTP outbound integration for external recipients
- IMAP import of unread mail from one configured mailbox

## Important limitations
This is an MVP foundation, not a production-ready Outlook replacement or a complete mail server.
- External email requires a real company domain and an approved email provider or properly operated mail server.
- The IMAP importer currently synchronises one mailbox into the employee account whose address matches `IMAP_USERNAME`.
- Draft saving, robust conversation threading, multi-mailbox synchronisation, attachment import from IMAP, HTML email rendering, spam/malware scanning, audit logs, background jobs and production-grade security remain future work.
- Internal email accounts are application accounts. They do not automatically become internet email mailboxes.

## Run in PyCharm on Windows
1. Extract the ZIP.
2. Open the `Drotax_Mail_Streamlit` folder in PyCharm.
3. Configure the project interpreter to use the Python installation already on your computer. If PyCharm already has a working interpreter, select it; do not create a new virtual environment if Windows fails to create one.
4. Open the PyCharm Terminal.
5. Install dependencies:
   `python -m pip install -r requirements.txt`
6. Copy `.env.example` to `.env`. Leave the SMTP and IMAP fields blank for local internal-email testing.
7. Start the app:
   `python -m streamlit run app.py`
8. Open the local URL printed in the terminal, usually `http://localhost:8501`.
9. On first launch, create the administrator account. Use Administration to create at least one more employee account.
10. Sign in as employee A and send a message to employee B's registered email address. Sign in as employee B to view it.

## External email configuration
When Drotax chooses its domain and provider, obtain the provider's SMTP and IMAP hostnames, ports, and app-specific credentials. Add them to `.env` using the field names in `.env.example`. Never put credentials in source code or commit `.env`.

SMTP is used to send external messages. IMAP is used by the administrator's Fetch external inbox now action to import unread messages from the configured mailbox.

## Before internal deployment
Move from SQLite to PostgreSQL; run behind a production web server/reverse proxy with HTTPS; add secure secrets management; enforce attachment size/type limits and malware scanning; implement audit logs, rate limits, backups, monitoring, permission tests and a formal security review. Streamlit's built-in interaction model is suitable for an internal MVP, but a high-concurrency enterprise mail client may eventually need a separate API/backend and a more specialised frontend.
