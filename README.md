# Drotax Workspace

A unified Streamlit application for Drotax Mail, TeamTrack tickets/tasks, employee accounts and notifications.

## Included
- Shared sign-in and employee directory with Admin, IT Personnel, Team Lead, Member and Viewer roles.
- Overview dashboard, inbox, compose, employee directory and administration.
- Internal email delivery between registered workspace users.
- Recipient autocomplete by employee name or email, with full name and address suggestions.
- External SMTP sending when configured.
- Unread email and in-app notification counts with automatic 15-second polling while the workspace is open.
- Subtle sound attempt for new mail/notifications, with a mute control.
- TeamTrack ticket states: Open, Assigned, In Progress, Pending Approval, Rejected and Closed.
- Assigned staff can open tasks, comment, update progress and submit work for approval.
- Admin, IT Personnel and Team Lead can approve (which closes and locks a ticket) or reject (which returns it for further work).
- Closed tickets are read-only in the user interface; no assignment, status change or comment controls are shown.
- Light/dark theme and responsive Streamlit layout.
- Legacy source copies retained in `migrations/` for reference.

## Run in PyCharm on Windows
1. Extract the ZIP file.
2. Open the `Drotax_Workspace` folder in PyCharm.
3. Open the PyCharm Terminal.
4. Create a virtual environment:
   ```powershell
   python -m venv .venv
   ```
5. Activate it:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
6. Install dependencies:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
7. Run:
   ```powershell
   python -m streamlit run app.py
   ```
8. On first launch, create the first administrator account. Then use Administration to create employee accounts.

## Streamlit Community Cloud
- Repository: `DaveMaveOzi/drotax-workspace`
- Branch: `main`
- Main file: `app.py`
- Add SMTP values in App settings → Secrets if external email sending is required:
  ```toml
  SMTP_HOST = "smtp.your-provider.com"
  SMTP_PORT = "587"
  SMTP_USERNAME = "your-account"
  SMTP_PASSWORD = "your-app-password"
  SMTP_FROM_EMAIL = "mail@yourdomain.com"
  ```
- Never commit secrets, database files, employee records or attachments.

## Important behaviour and limitations
- Internal mail is exchanged only between accounts in this application's database. SMTP enables sending to external addresses; receiving mail from an external mailbox is not implemented here. External inbound mail requires an approved IMAP integration or inbound mail service.
- Notifications are polled every 15 seconds while the app is open in a browser. This is not push delivery and will not notify a user when the app/browser is closed.
- Browser autoplay policies may block sound until the user has interacted with the page. The app attempts to play a short sound when a new unread email or in-app notification is detected; sound is not guaranteed in every browser/device.
- Streamlit Community Cloud's local filesystem is not durable storage for a business application. SQLite data and uploaded files can be lost on restarts/redeployments. Before real company use, migrate to managed PostgreSQL and durable object storage, configure backups, audit logging, rate limiting, session/security controls and comprehensive permission tests.
- The closed-ticket lock is enforced by the application UI and conditional updates in this MVP. A production release should also enforce workflow transitions and authorisation in a dedicated backend/database layer.
- This package preserves the available legacy source files but does not automatically merge existing TeamTrack/Drotax Mail user databases or historical email/ticket records. Back up and test a controlled migration before replacing the existing apps.

## Database
The app creates `drotax_workspace.db` on first launch. Existing databases are not overwritten. A small migration adds approval metadata columns to the tickets table if they are missing.
