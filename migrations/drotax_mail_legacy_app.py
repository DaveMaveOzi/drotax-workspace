import os
import re
import ssl
import sqlite3
import hashlib
import secrets
import smtplib
import imaplib
import email
from email.message import EmailMessage
from email.header import decode_header
from email.utils import parseaddr
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DB_PATH = BASE_DIR / "drotax_mail.db"

st.set_page_config(page_title="Drotax Mail", page_icon="✉️", layout="wide", initial_sidebar_state="expanded")

# -------------------- DATABASE --------------------
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee',
            department TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            sender_email TEXT NOT NULL,
            subject TEXT DEFAULT '',
            body TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'sent',
            is_external INTEGER NOT NULL DEFAULT 0,
            message_id_header TEXT DEFAULT '',
            in_reply_to INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(in_reply_to) REFERENCES messages(id)
        );
        CREATE TABLE IF NOT EXISTS recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            user_id INTEGER,
            kind TEXT NOT NULL DEFAULT 'to',
            is_read INTEGER NOT NULL DEFAULT 0,
            is_archived INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            content_type TEXT DEFAULT 'application/octet-stream',
            data BLOB NOT NULL,
            FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_recipients_user ON recipients(user_id, is_deleted, is_archived);
        CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id);
        """)
init_db()

# -------------------- AUTH --------------------
def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return salt.hex() + "$" + digest.hex()

def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        return secrets.compare_digest(hash_password(password, bytes.fromhex(salt_hex)).split("$", 1)[1], digest_hex)
    except Exception:
        return False

def user_count():
    with db() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def create_user(full_name, email_addr, password, role="employee", department=""):
    email_addr = email_addr.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_addr):
        raise ValueError("Enter a valid email address.")
    if len(password) < 10:
        raise ValueError("Use a password with at least 10 characters.")
    with db() as con:
        con.execute(
            "INSERT INTO users(full_name,email,password_hash,role,department,created_at) VALUES(?,?,?,?,?,?)",
            (full_name.strip(), email_addr, hash_password(password), role, department.strip(), datetime.now().isoformat(timespec="seconds"))
        )

def current_user():
    return st.session_state.get("user")

def login_screen():
    st.markdown("<div class='login-wrap'><div class='brand'>✉️ Drotax <span>Mail</span></div><h1>Sign in to your workspace</h1><p class='muted'>Company email and communication</p></div>", unsafe_allow_html=True)
    with st.form("login_form"):
        email_addr = st.text_input("Company email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE email=? AND active=1", (email_addr.strip().lower(),)).fetchone()
        if user and verify_password(password, user["password_hash"]):
            st.session_state.user = dict(user)
            st.rerun()
        st.error("Email or password is incorrect.")

# -------------------- EMAIL HELPERS --------------------
def split_addresses(raw):
    values = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
    result = []
    for value in values:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError(f"Invalid email address: {value}")
        if value.lower() not in [v.lower() for v in result]:
            result.append(value)
    return result

def smtp_send(to_list, cc_list, bcc_list, subject, body, files, sender_email):
    host = os.getenv("SMTP_HOST", "")
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not username or not password:
        raise RuntimeError("External email is not configured. Add SMTP settings to your .env file first.")
    port = int(os.getenv("SMTP_PORT", "587"))
    from_email = os.getenv("SMTP_FROM_EMAIL", username)
    msg = EmailMessage()
    msg["Subject"] = subject or "(No subject)"
    msg["From"] = from_email
    msg["To"] = ", ".join(to_list) if to_list else ""
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg.set_content(body)
    for f in files:
        msg.add_attachment(f["data"], maintype=f["mime"].split("/")[0], subtype=f["mime"].split("/")[-1], filename=f["name"])
    recipients = list(dict.fromkeys(to_list + cc_list + bcc_list))
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=25) as server:
        server.starttls(context=context)
        server.login(username, password)
        server.send_message(msg, from_addr=from_email, to_addrs=recipients)

def save_message(sender, to_list, cc_list, bcc_list, subject, body, files, status="sent", reply_to=None):
    all_addresses = list(dict.fromkeys(to_list + cc_list + bcc_list))
    with db() as con:
        cur = con.execute(
            """INSERT INTO messages(sender_id,sender_email,subject,body,status,is_external,in_reply_to,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (sender["id"], sender["email"], subject, body, status,
             int(any(not internal_user(a) for a in all_addresses)), reply_to,
             datetime.now().isoformat(timespec="seconds"))
        )
        mid = cur.lastrowid
        for address in all_addresses:
            u = internal_user(address)
            kind = "to" if address in to_list else ("cc" if address in cc_list else "bcc")
            con.execute("INSERT INTO recipients(message_id,email,user_id,kind) VALUES(?,?,?,?)",
                        (mid, address, u["id"] if u else None, kind))
        for f in files:
            con.execute("INSERT INTO attachments(message_id,filename,content_type,data) VALUES(?,?,?,?)",
                        (mid, f["name"], f["mime"], sqlite3.Binary(f["data"])))
    return mid

def internal_user(address):
    with db() as con:
        row = con.execute("SELECT id,email,full_name FROM users WHERE email=? COLLATE NOCASE AND active=1", (address,)).fetchone()
    return dict(row) if row else None

def deliver(sender, to_list, cc_list, bcc_list, subject, body, files, reply_to=None):
    all_addresses = list(dict.fromkeys(to_list + cc_list + bcc_list))
    external = [a for a in all_addresses if not internal_user(a)]
    # Send externally first so a failed SMTP attempt does not create a false sent record.
    if external:
        smtp_send(to_list, cc_list, bcc_list, subject, body, files, sender["email"])
    return save_message(sender, to_list, cc_list, bcc_list, subject, body, files, "sent", reply_to)

def fetch_imap_mail():
    host = os.getenv("IMAP_HOST", "")
    username = os.getenv("IMAP_USERNAME", "")
    password = os.getenv("IMAP_PASSWORD", "")
    if not host or not username or not password:
        raise RuntimeError("IMAP is not configured in .env.")
    owner = internal_user(username)
    if not owner:
        raise RuntimeError("Create an employee account whose email matches IMAP_USERNAME.")
    port = int(os.getenv("IMAP_PORT", "993"))
    mailbox = imaplib.IMAP4_SSL(host, port)
    imported = 0
    try:
        mailbox.login(username, password)
        mailbox.select(os.getenv("IMAP_FOLDER", "INBOX"))
        status, data = mailbox.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Could not search the mailbox.")
        for num in data[0].split():
            status, parts = mailbox.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            parsed = email.message_from_bytes(parts[0][1])
            message_header_id = parsed.get("Message-ID", "")
            with db() as con:
                exists = con.execute("SELECT id FROM messages WHERE message_id_header=?", (message_header_id,)).fetchone() if message_header_id else None
            if exists:
                continue
            subject = decode_mime(parsed.get("Subject", "(No subject)"))
            from_email = parseaddr(parsed.get("From", ""))[1] or "unknown@unknown.invalid"
            body = ""
            if parsed.is_multipart():
                for part in parsed.walk():
                    if part.get_content_type() == "text/plain" and not part.get_filename():
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                            break
            else:
                payload = parsed.get_payload(decode=True)
                if payload:
                    body = payload.decode(parsed.get_content_charset() or "utf-8", errors="replace")
            with db() as con:
                cur = con.execute("""INSERT INTO messages(sender_id,sender_email,subject,body,status,is_external,message_id_header,created_at)
                    VALUES(NULL,?,?,?,'received',1,?,?)""",
                    (from_email, subject, body, message_header_id, datetime.now().isoformat(timespec="seconds")))
                con.execute("INSERT INTO recipients(message_id,email,user_id,kind) VALUES(?,?,?,'to')",
                            (cur.lastrowid, owner["email"], owner["id"]))
            imported += 1
        return imported
    finally:
        try:
            mailbox.logout()
        except Exception:
            pass

def decode_mime(value):
    parts = decode_header(value or "")
    output = []
    for part, charset in parts:
        output.append(part.decode(charset or "utf-8", errors="replace") if isinstance(part, bytes) else part)
    return "".join(output)

# -------------------- UI --------------------


# -------------------- THEME + UI --------------------
if "theme" not in st.session_state:
    st.session_state.theme = "Light"
if "active_page" not in st.session_state:
    st.session_state.active_page = "Inbox"

LIGHT = {
    "page": "#F4F5F2", "surface": "#FFFFFF", "sidebar": "#FFFFFF",
    "text": "#202820", "muted": "#5F6B60", "border": "#DCE2D9",
    "accent": "#4B5320", "accent_text": "#FFFFFF", "soft": "#E9EEDF",
    "input": "#FFFFFF", "sidebar_text": "#263328", "sidebar_muted": "#687568",
    "sidebar_hover": "#F1F3F0", "sidebar_active": "#E9EDDF",
}
DARK = {
    "page": "#171B19", "surface": "#222824", "sidebar": "#1D2420",
    "text": "#F3F5F1", "muted": "#AAB4AA", "border": "#374139",
    "accent": "#89916B", "accent_text": "#11170F", "soft": "#303A2E",
    "input": "#29312C", "sidebar_text": "#EDF1EA", "sidebar_muted": "#AAB4AA",
    "sidebar_hover": "#2A332D", "sidebar_active": "#3B4737",
}
palette = DARK if st.session_state.theme == "Dark" else LIGHT

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');
:root {{ color-scheme: {"dark" if st.session_state.theme == "Dark" else "light"}; }}
html, body, [class*="css"] {{ font-family:'Poppins',sans-serif !important; }}
.stApp, [data-testid="stAppViewContainer"] {{ background:{palette["page"]}; color:{palette["text"]}; }}
[data-testid="stHeader"] {{ background:{palette["page"]}; }}
.block-container {{ padding:1.35rem 2rem 2.5rem; max-width:1600px; }}
h1,h2,h3,h4,p,label,li {{ color:{palette["text"]}; font-family:'Poppins',sans-serif !important; }}
h1 {{ font-size:1.85rem !important; font-weight:600 !important; letter-spacing:-.04em; }}
h2 {{ font-size:1.35rem !important; font-weight:600 !important; }}
[data-testid="stCaptionContainer"] {{ color:{palette["muted"]} !important; }}
hr {{ border-color:{palette["border"]}; }}
[data-testid="stSidebar"] {{
  display:block !important; min-width:245px !important; max-width:245px !important;
  background:{palette["sidebar"]} !important; border-right:1px solid {palette["border"]};
}}
[data-testid="stSidebar"] > div:first-child {{ background:{palette["sidebar"]} !important; }}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p {{ color:{palette["sidebar_text"]} !important; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{ color:{palette["sidebar_muted"]} !important; }}
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] {{ gap:5px; }}
[data-testid="stSidebar"] [data-testid="stRadio"] label {{
  background:transparent; border-radius:9px; padding:8px 10px; margin:1px 0;
}}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {{ background:{palette["sidebar_hover"]}; }}
[data-testid="stSidebar"] [data-testid="stRadio"] label p {{ color:{palette["sidebar_text"]} !important; font-weight:500; }}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {{
  background:{palette["sidebar_active"]} !important; border-left:3px solid {palette["accent"]}; padding-left:7px;
}}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p {{ color:{palette["text"]} !important; font-weight:600; }}
/* Sidebar: consistent left edge, deliberate section spacing and aligned controls */
[data-testid="stSidebar"] > div:first-child {{
  padding:1rem 1rem 1.25rem !important;
}}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap:.38rem !important; }}
.sidebar-gap {{ height:16px; width:100%; }}
.sidebar-gap-large {{ height:22px; width:100%; }}
.sidebar-section {{ padding:0 9px 10px !important; margin:0 !important; }}
.sidebar-brand {{ margin-bottom:20px !important; }}
.sidebar-user {{ margin-bottom:26px !important; padding:13px !important; }}
[data-testid="stSidebar"] [data-testid="stButton"] > button {{ min-height:45px !important; }}
[data-testid="stSidebar"] .sidebar-footer {{ margin-top:25px !important; padding:16px 7px 0 !important; }}
.sidebar-brand {{
  display:flex; align-items:center; gap:11px; min-height:46px;
  margin:0 0 17px !important; padding:0 4px !important;
}}
.sidebar-user {{ margin:0 0 22px !important; padding:12px !important; }}
.sidebar-section {{
  display:block; line-height:1.4; padding:0 9px 9px !important;
  margin:0 !important; font-size:9px; letter-spacing:.14em;
}}
[data-testid="stSidebar"] [data-testid="stButton"] {{
  width:100%; margin:0 !important; padding:0 !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button {{
  display:flex !important; align-items:center !important; justify-content:flex-start !important;
  gap:12px !important; width:100% !important; min-height:42px !important;
  text-align:left !important; padding:0 12px !important; margin:0 !important;
  border-radius:8px !important; box-shadow:none !important;
  font-size:12px !important; font-weight:500 !important; line-height:1.2 !important;
}}
/* Pin both icon and label to the same left alignment line. */
[data-testid="stSidebar"] [data-testid="stButton"] > button > div {{
  display:flex !important; flex-direction:row !important; align-items:center !important;
  justify-content:flex-start !important; width:100% !important; gap:12px !important; margin:0 !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button [data-testid="stMarkdownContainer"] {{
  display:flex !important; align-items:center !important; justify-content:flex-start !important;
  flex:1 1 auto !important; text-align:left !important; width:auto !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button [data-testid="stMarkdownContainer"] p {{
  text-align:left !important; margin:0 !important; width:100% !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button [data-testid="stIconMaterial"],
[data-testid="stSidebar"] [data-testid="stButton"] > button [data-testid="stIcon"],
[data-testid="stSidebar"] [data-testid="stButton"] > button svg {{
  display:inline-flex !important; align-items:center !important; justify-content:center !important;
  flex:0 0 18px !important; width:18px !important; height:18px !important;
  min-width:18px !important; opacity:1 !important; visibility:visible !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="tertiary"] {{
  background:transparent !important; border:1px solid transparent !important;
  color:{palette["sidebar_text"]} !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="tertiary"] *,
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="tertiary"] svg {{
  color:{palette["sidebar_text"]} !important; fill:{palette["sidebar_text"]} !important;
  stroke:{palette["sidebar_text"]} !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="tertiary"]:hover {{
  background:{palette["sidebar_hover"]} !important; color:{palette["text"]} !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] {{
  background:{palette["accent"]} !important; color:#FFFFFF !important;
  border:1px solid {palette["accent"]} !important;
}}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] *,
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] svg {{
  color:#FFFFFF !important; fill:#FFFFFF !important; stroke:#FFFFFF !important;
}}
[data-testid="stSidebar"] .preferences-section {{ margin-top:15px !important; padding-top:5px !important; }}
[data-testid="stSidebar"] .account-section {{ margin-top:0 !important; padding-top:0 !important; padding-bottom:12px !important; }}
[data-testid="stSidebar"] [data-testid="stButton"] > button[aria-label*="Switch to"] {{
  width:42px !important; min-height:40px !important; height:40px !important;
  padding:0 !important; justify-content:center !important; margin-left:8px !important;
  background:{palette["sidebar_hover"]} !important; border:1px solid {palette["border"]} !important;
  color:{palette["sidebar_text"]} !important; border-radius:9px !important;
}}

[data-testid="stSidebar"] [data-testid="stToggle"] label {{
  display:flex !important; align-items:center !important; gap:10px !important;
}}
[data-testid="stSidebar"] [data-testid="stToggle"] label p {{
  color:{palette["sidebar_text"]} !important; font-size:12px !important;
}}
[data-testid="stSidebar"] .sidebar-footer {{ margin-top:22px !important; padding:14px 7px 0 !important;
  margin-top:22px; padding:14px 9px 8px; line-height:1.8; border-top:1px solid {palette["border"]};
}}

.sidebar-brand {{ display:flex; align-items:center; gap:10px; padding:7px 5px 24px; }}
.sidebar-logo {{ display:grid; place-items:center; width:34px; height:34px; border-radius:10px; background:{palette["accent"]}; color:white; font-size:19px; font-weight:700; }}
.sidebar-brand-name {{ color:{palette["text"]}; font-size:19px; font-weight:600; letter-spacing:-.04em; }}
.sidebar-brand-sub {{ color:{palette["sidebar_muted"]}; font-size:9px; text-transform:uppercase; letter-spacing:.12em; margin-top:2px; }}
.sidebar-user {{ background:{palette["sidebar_hover"]}; border:1px solid {palette["border"]}; border-radius:10px; padding:11px; margin:0 0 14px; }}
.sidebar-user-name {{ color:{palette["text"]}; font-weight:600; font-size:12px; }}
.sidebar-user-email {{ color:{palette["sidebar_muted"]}; font-size:10px; overflow-wrap:anywhere; margin-top:3px; }}
.sidebar-section {{ color:{palette["sidebar_muted"]}; font-size:9px; font-weight:600; letter-spacing:.13em; padding:13px 9px 5px; }}
.sidebar-footer {{ color:{palette["sidebar_muted"]}; font-size:10px; padding:12px 7px; }}
.app-eyebrow {{ color:{palette["muted"]}; font-size:10px; font-weight:600; letter-spacing:.13em; text-transform:uppercase; margin-bottom:5px; }}
.app-subtitle {{ color:{palette["muted"]}; font-size:12px; margin-top:-5px; }}
.login-wrap {{ text-align:center; margin:6vh auto 20px; max-width:470px; background:{palette["surface"]}; padding:34px; border:1px solid {palette["border"]}; border-radius:16px; box-shadow:0 8px 28px rgba(20,30,20,.05); }}
.login-wrap h1 {{ margin-top:18px; }}
.stButton > button, .stFormSubmitButton > button, [data-testid="stDownloadButton"] button {{
  border-radius:8px !important; min-height:2.25rem; font-size:12px !important; font-weight:500 !important;
  border:1px solid {palette["accent"]} !important; background:{palette["accent"]} !important;
  color:#FFFFFF !important; padding:0.35rem 1rem !important;
}}
.stButton > button *, .stFormSubmitButton > button *, [data-testid="stDownloadButton"] button * {{
  color:#FFFFFF !important; fill:#FFFFFF !important; font-weight:500 !important;
}}
.stButton > button [data-testid="stIconMaterial"], .stButton > button svg {{ color:#FFFFFF !important; fill:#FFFFFF !important; stroke:#FFFFFF !important; }}
.stButton > button:hover, .stFormSubmitButton > button:hover, [data-testid="stDownloadButton"] button:hover {{
  background:{palette["soft"]} !important; border-color:{palette["accent"]} !important;
  color:{palette["text"]} !important;
}}
.stButton > button:hover *, .stFormSubmitButton > button:hover *, [data-testid="stDownloadButton"] button:hover * {{
  color:{palette["text"]} !important; fill:{palette["text"]} !important;
}}
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
  background:{palette["input"]} !important; color:{palette["text"]} !important;
  border:1px solid {palette["border"]} !important; border-radius:8px !important;
}}
[data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {{ color:{palette["muted"]} !important; opacity:1; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background:{palette["surface"]}; border:1px solid {palette["border"]}; border-radius:12px; box-shadow:0 3px 12px rgba(20,30,20,.025); }}
[data-testid="stMetric"] {{ background:{palette["surface"]}; border:1px solid {palette["border"]}; padding:13px 15px; border-radius:11px; }}
[data-testid="stFileUploader"] section {{ background:{palette["surface"]}; border:1px dashed {palette["border"]}; border-radius:10px; }}
[data-testid="stAlert"] {{ border-radius:9px; background:#4B5320 !important; border:1px solid #4B5320 !important; }}
[data-testid="stAlert"] *, [data-testid="stAlert"] p, [data-testid="stAlert"] span {{
  color:#FFFFFF !important; fill:#FFFFFF !important;
}}
[data-testid="stToast"] {{ background:#4B5320 !important; color:#FFFFFF !important; }}
[data-testid="stToast"] * {{ color:#FFFFFF !important; }}
@media(max-width:850px) {{ [data-testid="stSidebar"] {{ min-width:220px !important; max-width:220px !important; }} .block-container {{ padding-left:1rem; padding-right:1rem; }} }}
</style>
""", unsafe_allow_html=True)

if user_count() == 0:
    st.markdown("<div class='login-wrap'><div class='brand'>✉️ Drotax <span>Mail</span></div><h1>Set up your administrator</h1><p class='muted'>Create the first account for this local installation.</p></div>", unsafe_allow_html=True)
    with st.form("first_admin"):
        name = st.text_input("Full name")
        email_addr = st.text_input("Company email address")
        password = st.text_input("Password (minimum 10 characters)", type="password")
        confirm = st.text_input("Confirm password", type="password")
        go = st.form_submit_button("Create administrator", type="primary")
    if go:
        if password != confirm:
            st.error("Passwords do not match.")
        else:
            try:
                create_user(name, email_addr, password, "admin")
                st.success("Administrator created. Sign in now.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    st.stop()

if not current_user():
    login_screen()
    st.stop()

user = current_user()

with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
      <div class="sidebar-logo">D</div>
      <div><div class="sidebar-brand-name">drotax mail</div>
      <div class="sidebar-brand-sub">Company workspace</div></div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(
        f"<div class='sidebar-user'><div class='sidebar-user-name'>{user['full_name']}</div>"
        f"<div class='sidebar-user-email'>{user['email']}</div></div>",
        unsafe_allow_html=True
    )
    st.markdown("<div class='sidebar-section'>WORKSPACE</div>", unsafe_allow_html=True)
    nav_items = ["Inbox", "Sent", "Drafts", "Compose", "Contacts"]
    if user["role"] == "admin":
        nav_items.append("Administration")
    if st.session_state.get("page_override") in nav_items:
        st.session_state.active_page = st.session_state.pop("page_override")
    if st.session_state.active_page not in nav_items:
        st.session_state.active_page = "Inbox"
    nav_icons = {
        "Inbox": ":material/inbox:",
        "Sent": ":material/send:",
        "Drafts": ":material/drafts:",
        "Compose": ":material/edit_square:",
        "Contacts": ":material/people:",
        "Administration": ":material/admin_panel_settings:",
    }
    for item in nav_items:
        selected = st.session_state.active_page == item
        if st.button(
            item,
            key=f"nav_{item.lower()}",
            icon=nav_icons.get(item, ":material/chevron_right:"),
            type="primary" if selected else "tertiary",
            use_container_width=True,
        ):
            st.session_state.active_page = item
            st.session_state.pop("open_message", None)
            st.rerun()
    page = st.session_state.active_page
    st.markdown("<div class='sidebar-gap'></div><div class='sidebar-section'>PREFERENCES</div>", unsafe_allow_html=True)
    is_dark = st.session_state.theme == "Dark"
    appearance_icon = ":material/light_mode:" if is_dark else ":material/dark_mode:"
    appearance_tip = "Switch to light mode" if is_dark else "Switch to dark mode"
    if st.button("", icon=appearance_icon, help=appearance_tip, key="appearance_icon", type="tertiary"):
        st.session_state.theme = "Light" if is_dark else "Dark"
        st.rerun()
    st.markdown("<div class='sidebar-gap-large'></div><div class='sidebar-section'>ACCOUNT</div>", unsafe_allow_html=True)
    if st.button("Sign out", icon=":material/logout:", use_container_width=True, key="sidebar_signout"):
        st.session_state.pop("user", None)
        st.session_state.active_page = "Inbox"
        st.rerun()
    st.markdown("<div class='sidebar-footer'>Drotax internal communications<br>Secure company workspace</div>", unsafe_allow_html=True)

st.markdown(f"<div class='app-eyebrow'>DROTAX MAIL / {page.upper()}</div><h1>{page}</h1>", unsafe_allow_html=True)

if page == "Inbox":
    st.markdown("<div class='app-subtitle'>Your messages, conversations and company updates.</div>", unsafe_allow_html=True)
    search = st.text_input("Search inbox", placeholder="Search subject, sender or message")
    with db() as con:
        rows = con.execute("""SELECT m.*,r.id recipient_id,r.is_read FROM recipients r JOIN messages m ON m.id=r.message_id
            WHERE r.user_id=? AND r.is_deleted=0 AND r.is_archived=0 AND m.status IN ('sent','received')
            ORDER BY m.created_at DESC""", (user["id"],)).fetchall()
    if search:
        rows = [r for r in rows if search.lower() in (r["subject"] + " " + r["sender_email"] + " " + r["body"]).lower()]
    if not rows:
        st.info("Your inbox is empty.")
    for row in rows:
        label = "● " if not row["is_read"] else ""
        with st.container(border=True):
            c1,c2 = st.columns([5,1])
            with c1:
                st.markdown(f"**{label}{row['subject'] or '(No subject)'}**")
                st.caption(f"From: {row['sender_email']}  ·  {row['created_at']}")
                st.write((row["body"] or "").replace("\n", " ")[:180])
            with c2:
                if st.button("Open", key=f"open_{row['id']}"):
                    st.session_state.open_message = row["id"]
                    with db() as con:
                        con.execute("UPDATE recipients SET is_read=1 WHERE id=?", (row["recipient_id"],))
                    st.rerun()
    if st.session_state.get("open_message"):
        mid = st.session_state.open_message
        with db() as con:
            msg = con.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
            atts = con.execute("SELECT * FROM attachments WHERE message_id=?", (mid,)).fetchall()
        if msg:
            st.divider()
            st.subheader(msg["subject"] or "(No subject)")
            st.caption(f"From: {msg['sender_email']} · {msg['created_at']}")
            st.write(msg["body"])
            for att in atts:
                st.download_button(f"Download {att['filename']}", bytes(att["data"]), file_name=att["filename"], key=f"att_{att['id']}")
            if st.button("Reply", key="reply_open"):
                st.session_state.reply_to = mid
                st.session_state.reply_email = msg["sender_email"]
                st.session_state.reply_subject = "Re: " + (msg["subject"] or "")
                st.session_state.page_override = "Compose"
                st.rerun()
            if st.button("Close message"):
                st.session_state.pop("open_message", None)
                st.rerun()

elif page == "Sent":
    with db() as con:
        rows = con.execute("SELECT * FROM messages WHERE sender_id=? AND status='sent' ORDER BY created_at DESC", (user["id"],)).fetchall()
    if not rows:
        st.info("You have not sent any messages yet.")
    for row in rows:
        with st.container(border=True):
            st.markdown(f"**{row['subject'] or '(No subject)'}**")
            st.caption(f"Sent {row['created_at']} · {'External delivery included' if row['is_external'] else 'Internal'}")
            st.write((row["body"] or "")[:180])

elif page == "Drafts":
    st.info("Draft saving is scheduled for the next development milestone. The initial version currently supports sending messages.")

elif page == "Compose":
    reply_to = st.session_state.get("reply_to")
    default_to = st.session_state.get("reply_email", "")
    default_subject = st.session_state.get("reply_subject", "")
    with st.form("compose_form", clear_on_submit=True):
        to_raw = st.text_input("To", value=default_to, help="Separate multiple email addresses with commas.")
        cc_raw = st.text_input("Cc")
        bcc_raw = st.text_input("Bcc")
        subject = st.text_input("Subject", value=default_subject)
        body = st.text_area("Message", height=260)
        uploaded = st.file_uploader("Attach files", accept_multiple_files=True)
        send = st.form_submit_button("Send message", type="primary")
    if send:
        try:
            to_list, cc_list, bcc_list = split_addresses(to_raw), split_addresses(cc_raw), split_addresses(bcc_raw)
            if not (to_list or cc_list or bcc_list):
                raise ValueError("Add at least one recipient.")
            files = [{"name": f.name, "mime": f.type or "application/octet-stream", "data": f.getvalue()} for f in (uploaded or [])]
            mid = deliver(user, to_list, cc_list, bcc_list, subject, body, files, reply_to)
            st.success("Message sent and recorded.")
            st.session_state.pop("reply_to", None)
            st.session_state.pop("reply_email", None)
            st.session_state.pop("reply_subject", None)
        except Exception as e:
            st.error(str(e))

elif page == "Contacts":
    with db() as con:
        people = con.execute("SELECT full_name,email,department FROM users WHERE active=1 ORDER BY full_name").fetchall()
    st.caption("Active Drotax Mail users")
    for person in people:
        with st.container(border=True):
            st.markdown(f"**{person['full_name']}**")
            st.write(person["email"])
            if person["department"]:
                st.caption(person["department"])

elif page == "Administration":
    st.subheader("Create employee account")
    with st.form("new_employee"):
        name = st.text_input("Employee full name")
        email_addr = st.text_input("Employee email address")
        department = st.text_input("Department")
        password = st.text_input("Temporary password (minimum 10 characters)", type="password")
        role = st.selectbox("Role", ["employee", "admin"])
        create = st.form_submit_button("Create account")
    if create:
        try:
            create_user(name, email_addr, password, role, department)
            st.success("Employee account created.")
        except Exception as e:
            st.error(str(e))
    st.divider()
    st.subheader("External mailbox synchronisation")
    st.caption("Imports unread mail from the single IMAP mailbox configured in .env. The mailbox address must match an employee account.")
    if st.button("Fetch external inbox now"):
        try:
            count = fetch_imap_mail()
            st.success(f"Imported {count} message(s).")
        except Exception as e:
            st.error(str(e))
    with db() as con:
        people = con.execute("SELECT id,full_name,email,role,department,active FROM users ORDER BY full_name").fetchall()
    st.subheader("Employee accounts")
    for person in people:
        st.write(f"{person['full_name']} · {person['email']} · {person['department'] or 'No department'} · {person['role']} · {'Active' if person['active'] else 'Disabled'}")

st.divider()
st.caption("Drotax Mail · Local development build. External email requires approved SMTP/IMAP provider settings.")
