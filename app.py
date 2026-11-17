from __future__ import annotations
import os, re, sqlite3, hashlib, secrets, uuid, base64, io, wave, struct
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
import smtplib, ssl
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv('DATABASE_PATH', BASE / 'drotax_workspace.db'))
UPLOADS = BASE / 'uploads'
UPLOADS.mkdir(exist_ok=True)

st.set_page_config(page_title='Drotax Workspace', page_icon='✉️', layout='wide', initial_sidebar_state='expanded')

# -------------------- THEME --------------------
if 'theme' not in st.session_state: st.session_state.theme = 'Light'
DARK = st.session_state.theme == 'Dark'
P = {'bg':'#171B19','surface':'#222824','sidebar':'#1D2420','text':'#F3F5F1','muted':'#AAB4AA','border':'#374139','accent':'#89916B','soft':'#303A2E'} if DARK else {'bg':'#F4F5F2','surface':'#FFFFFF','sidebar':'#FFFFFF','text':'#202820','muted':'#5F6B60','border':'#DCE2D9','accent':'#4B5320','soft':'#E9EEDF'}
st.markdown(f'''<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');
:root{{--bg:{P['bg']};--surface:{P['surface']};--sidebar:{P['sidebar']};--text:{P['text']};--muted:{P['muted']};--border:{P['border']};--accent:{P['accent']};--soft:{P['soft']}}}
html,body,[class*="css"]{{font-family:Poppins,sans-serif!important}} .stApp,[data-testid="stAppViewContainer"]{{background:var(--bg);color:var(--text)}}
[data-testid="stSidebar"]{{background:var(--sidebar);border-right:1px solid var(--border)}}
[data-testid="stSidebar"] *{{color:var(--text)}} h1,h2,h3,h4,p,label{{color:var(--text)}}
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stForm"]{{background:var(--surface);border-color:var(--border);border-radius:12px}}
input,textarea{{background:var(--surface)!important;color:var(--text)!important}}
/* Consistent, high-contrast buttons in both themes. In light mode every
   button uses the Drotax army-green background with white lettering. */
div.stButton>button, div.stFormSubmitButton>button, [data-testid="stDownloadButton"] button{{
  border-radius:8px!important; border:1px solid var(--accent)!important; min-height:2.5rem;
  background:var(--accent)!important; color:#FFFFFF!important; font-weight:600!important;
}}
div.stButton>button *, div.stFormSubmitButton>button *, [data-testid="stDownloadButton"] button *{{color:#FFFFFF!important;fill:#FFFFFF!important}}
div.stButton>button:hover, div.stFormSubmitButton>button:hover, [data-testid="stDownloadButton"] button:hover{{
  background:#394018!important; border-color:#394018!important; color:#FFFFFF!important;
}}
[data-testid="stSidebar"] div.stButton>button{{background:var(--accent)!important;color:#FFFFFF!important}}
[data-testid="stSidebar"] div.stButton>button *{{color:#FFFFFF!important}}
[data-testid="stMetric"]{{background:var(--surface);border:1px solid var(--border);padding:14px;border-radius:10px}}
/* Keep requested empty-state and section messages readable in both themes. */
[data-testid="stAlert"] p, [data-testid="stAlert"] [data-testid="stMarkdownContainer"] * {{color:#FFFFFF!important}}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * {{color:#FFFFFF!important}}
[data-testid="stFileUploader"] button {{background:var(--accent)!important;border:1px solid var(--accent)!important;color:#FFFFFF!important}}
[data-testid="stFileUploader"] button * {{color:#FFFFFF!important}}
hr{{border-color:var(--border)}} .muted{{color:var(--muted)}}
</style>''', unsafe_allow_html=True)

# -------------------- DATABASE --------------------
def connect():
    c=sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

def init_db():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, hash_scheme TEXT NOT NULL DEFAULT 'pbkdf2', role TEXT NOT NULL DEFAULT 'Member', department TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1, sound_enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, sender_id TEXT, sender_email TEXT NOT NULL, subject TEXT DEFAULT '', body TEXT DEFAULT '', created_at TEXT NOT NULL, FOREIGN KEY(sender_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS recipients(id TEXT PRIMARY KEY, message_id TEXT NOT NULL, user_id TEXT, email TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'To', is_read INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY, message_id TEXT NOT NULL, filename TEXT NOT NULL, content_type TEXT, data BLOB, FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, ticket_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL, description TEXT NOT NULL, department TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Open', reporter_id TEXT NOT NULL, assignee_id TEXT, due_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(reporter_id) REFERENCES users(id), FOREIGN KEY(assignee_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS ticket_comments(id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, user_id TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, category TEXT NOT NULL, message TEXT NOT NULL, target_id TEXT, is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE INDEX IF NOT EXISTS idx_recipient_user ON recipients(user_id,is_read);
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,is_read);
        CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee_id,status);
        ''')
init_db()

def q(sql,args=()):
    with connect() as c: return c.execute(sql,args).fetchone()
def qall(sql,args=()):
    with connect() as c: return c.execute(sql,args).fetchall()
def run(sql,args=()):
    with connect() as c: c.execute(sql,args); c.commit()

def hash_pw(password):
    salt=secrets.token_bytes(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,310000)
    return salt.hex()+'$'+digest.hex()
def verify_pw(password, stored, scheme='pbkdf2'):
    try:
        if scheme=='bcrypt':
            import bcrypt
            return bcrypt.checkpw(password.encode(), stored if isinstance(stored,bytes) else stored.encode())
        salt,digest=stored.split('$',1)
        return secrets.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),310000).hex(),digest)
    except Exception: return False

def notify(uid, category, message, target=None):
    run('INSERT INTO notifications(id,user_id,category,message,target_id,created_at) VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),uid,category,message,target,now()))

def users(): return qall('SELECT id,full_name,email,role,department FROM users WHERE active=1 ORDER BY full_name COLLATE NOCASE')

# -------------------- AUTH --------------------
def register_user(full_name,email,password,department='Operations',role='Member'):
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',email): raise ValueError('Enter a valid email address.')
    if len(password)<10: raise ValueError('Password must contain at least 10 characters.')
    run('INSERT INTO users(id,full_name,email,password_hash,hash_scheme,role,department,created_at) VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),full_name.strip(),email.strip().lower(),hash_pw(password),'pbkdf2',role,department,now()))

def login_view():
    """Text-led landing and sign-in page; intentionally contains no hero image."""
    first=q('SELECT COUNT(*) n FROM users')['n']==0
    st.markdown("""
    <style>
      [data-testid="stSidebar"] {display:none!important}
      [data-testid="stMainBlockContainer"] {max-width:1120px!important;padding-top:3rem!important}
      .dw-landing {padding:2.2rem 2rem 2.4rem;border-radius:18px;background:linear-gradient(135deg,#263019 0%,#4B5320 100%);color:#fff;margin-bottom:1.6rem}
      .dw-kicker {font-size:.78rem;letter-spacing:.16em;text-transform:uppercase;color:#E5E9D8;font-weight:600}
      .dw-title {font-size:clamp(2rem,4vw,3.25rem);line-height:1.12;font-weight:700;letter-spacing:-.045em;color:#fff;margin:.7rem 0}
      .dw-subtitle {font-size:1rem;line-height:1.7;color:#F0F2E9;max-width:720px;margin:0}
      .dw-feature {height:100%;padding:1.15rem;border:1px solid #DCE2D9;border-radius:12px;background:#fff;color:#263019}
      .dw-feature strong {display:block;color:#263019;margin-bottom:.35rem}
      .dw-feature span {font-size:.86rem;line-height:1.55;color:#5F6B60}
      @media(max-width:700px){.dw-landing{padding:1.5rem 1.2rem}.dw-title{font-size:2rem}}
    </style>
    <div class="dw-landing">
      <div class="dw-kicker">DROTAX · CONNECTED WORKPLACE</div>
      <div class="dw-title">Work, communicate<br>and stay connected.</div>
      <p class="dw-subtitle">One secure workspace for company email, team requests, tasks and everyday collaboration.</p>
    </div>
    """,unsafe_allow_html=True)
    left,right=st.columns([1.05,1],gap='large')
    with left:
        st.markdown('### Everything in one workspace')
        st.markdown('<div class="dw-feature"><strong>Drotax Mail</strong><span>Send and receive company emails, manage conversations and stay informed with new-message alerts.</span></div>',unsafe_allow_html=True)
        st.write('')
        st.markdown('<div class="dw-feature"><strong>TeamTrack</strong><span>Raise requests, assign work, follow ticket progress and keep team activity organised.</span></div>',unsafe_allow_html=True)
        st.write('')
        st.markdown('<div class="dw-feature"><strong>One employee account</strong><span>Access the tools and information permitted by your organisation in one place.</span></div>',unsafe_allow_html=True)
    with right:
        with st.container(border=True):
            st.subheader('Create your workspace administrator account' if first else 'Welcome back')
            st.caption('Set up your account to continue to Drotax Workspace.' if first else 'Sign in with your company email address.')
            if first:
                with st.form('bootstrap_admin'):
                    n=st.text_input('Full name'); e=st.text_input('Company email'); p=st.text_input('Password',type='password'); p2=st.text_input('Confirm password',type='password'); ok=st.form_submit_button('Create administrator',type='primary',use_container_width=True)
                if ok:
                    try:
                        if p!=p2: raise ValueError('Passwords do not match.')
                        register_user(n,e,p,role='Admin'); st.success('Administrator created. Sign in to continue.'); st.rerun()
                    except Exception as ex: st.error(str(ex))
            else:
                with st.form('login'):
                    e=st.text_input('Company email'); p=st.text_input('Password',type='password'); ok=st.form_submit_button('Sign in',type='primary',use_container_width=True)
                if ok:
                    u=q('SELECT * FROM users WHERE email=? COLLATE NOCASE AND active=1',(e.strip(),))
                    if u and verify_pw(p,u['password_hash'],u['hash_scheme']):
                        st.session_state.user=dict(u); st.session_state.last_mail_count=q('SELECT COUNT(*) n FROM recipients WHERE user_id=?',(u['id'],))['n']; st.rerun()
                    else: st.error('Email or password is incorrect.')
    st.caption('Drotax Workspace · Company communication and team operations')

if 'user' not in st.session_state: st.session_state.user=None

# -------------------- EMAIL SERVICES --------------------
def send_external_email(to,cc,bcc,subject,body,files):
    host=os.getenv('SMTP_HOST',''); username=os.getenv('SMTP_USERNAME',''); password=os.getenv('SMTP_PASSWORD','')
    if not all([host,username,password]): raise RuntimeError('External SMTP is not configured. Configure SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD in deployment secrets.')
    msg=EmailMessage(); msg['Subject']=subject or '(No subject)'; msg['From']=os.getenv('SMTP_FROM_EMAIL',username); msg['To']=', '.join(to)
    if cc: msg['Cc']=', '.join(cc)
    msg.set_content(body)
    for f in files: msg.add_attachment(f.getvalue(),maintype=f.type.split('/')[0],subtype=f.type.split('/')[-1],filename=f.name)
    with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587')),timeout=25) as server:
        server.starttls(context=ssl.create_default_context()); server.login(username,password); server.send_message(msg,to_addrs=list(dict.fromkeys(to+cc+bcc)))

def send_message(sender, recipients, cc, bcc, subject, body, files):
    allrec=[]
    for kind, addresses in [('To',recipients),('CC',cc),('BCC',bcc)]:
        for addr in addresses:
            if addr.lower() not in [x[0].lower() for x in allrec]: allrec.append((addr,kind))
    if not allrec: raise ValueError('Add at least one recipient.')
    known={u['email'].lower():u for u in users()}
    external=[a for a,k in allrec if a.lower() not in known]
    if external: send_external_email(recipients,cc,bcc,subject,body,files)
    mid=str(uuid.uuid4())
    with connect() as c:
        c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',(mid,sender['id'],sender['email'],subject,body,now()))
        for address,kind in allrec:
            uid=known.get(address.lower(),{}).get('id')
            c.execute('INSERT INTO recipients(id,message_id,user_id,email,kind) VALUES(?,?,?,?,?)',(str(uuid.uuid4()),mid,uid,address,kind))
            if uid: c.execute('INSERT INTO notifications(id,user_id,category,message,target_id,created_at) VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),uid,'Email',f'New email from {sender["full_name"]}: {subject or "(No subject)"}',mid,now()))
        for f in files: c.execute('INSERT INTO attachments(id,message_id,filename,content_type,data) VALUES(?,?,?,?,?)',(str(uuid.uuid4()),mid,f.name,f.type,f.getvalue()))
        c.commit()

# -------------------- SOUND NOTIFICATIONS --------------------
def make_sound_data():
    buf=io.BytesIO()
    with wave.open(buf,'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        frames=[]
        for i in range(int(22050*.22)):
            amp=int(5000*(1-i/(22050*.22))*__import__('math').sin(2*__import__('math').pi*740*i/22050))
            frames.append(struct.pack('<h',amp))
        w.writeframes(b''.join(frames))
    return base64.b64encode(buf.getvalue()).decode()

# -------------------- AUTHENTICATED WORKSPACE --------------------
if not st.session_state.user:
    login_view(); st.stop()
user=dict(st.session_state.user)
# Refresh account state to honour administrator deactivation/role changes.
current=q('SELECT * FROM users WHERE id=? AND active=1',(user['id'],))
if not current: st.session_state.user=None; st.rerun()
user=dict(current)

# Sidebar navigation
with st.sidebar:
    logo=BASE/'assets'/'teamtrack_logo.png'
    if logo.exists(): st.image(str(logo),width=150)
    st.markdown('## Drotax Workspace')
    st.caption(f'{user["full_name"]} · {user["role"]}')
    unread_mail=q('SELECT COUNT(*) n FROM recipients WHERE user_id=? AND is_read=0',(user['id'],))['n']
    unread_notif=q('SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0',(user['id'],))['n']
    pages=['Overview','Drotax Mail','Compose','TeamTrack','My Tasks','Notifications']
    if user['role']=='Admin': pages += ['Employee Directory','Administration']
    if 'page' not in st.session_state: st.session_state.page='Overview'
    for pg in pages:
        label=pg
        if pg=='Drotax Mail' and unread_mail: label+=f'  ({unread_mail})'
        if pg=='Notifications' and unread_notif: label+=f'  ({unread_notif})'
        if st.button(label,key='nav_'+pg,use_container_width=True,type='primary' if st.session_state.page==pg else 'secondary'):
            st.session_state.page=pg; st.rerun()
    st.divider()
    # Compact icon-only controls: moon switches to dark, sun switches to light.
    theme_icon='☀️' if DARK else '🌙'
    if st.button(theme_icon,help='Switch to light mode' if DARK else 'Switch to dark mode',key='theme_icon_button',use_container_width=True):
        st.session_state.theme='Light' if DARK else 'Dark'; st.rerun()
    sound_icon='🔔' if user['sound_enabled'] else '🔕'
    if st.button(sound_icon,help='Mute email sound' if user['sound_enabled'] else 'Enable email sound',key='sound_icon_button',use_container_width=True):
        run('UPDATE users SET sound_enabled=? WHERE id=?',(0 if user['sound_enabled'] else 1,user['id']))
        st.rerun()
    if st.button('Sign out',use_container_width=True): st.session_state.user=None; st.rerun()

# New mail poll: Streamlit reruns on a short interval while this page is open.
@st.fragment(run_every='15s')
def live_mail_status():
    count=q('SELECT COUNT(*) n FROM recipients WHERE user_id=? AND is_read=0',(user['id'],))['n']
    previous=st.session_state.get('mail_unread_snapshot',count)
    if count>previous and user['sound_enabled']:
        wav=make_sound_data()
        components.html(f'''<audio autoplay><source src="data:audio/wav;base64,{wav}" type="audio/wav"></audio><script>document.title='New email · Drotax Workspace';</script>''',height=0)
        st.toast('You have a new email.',icon='✉️')
    st.session_state.mail_unread_snapshot=count
    st.caption(f'Inbox · {count} unread')

page=st.session_state.page
if page=='Overview':
    st.title(f'Good to see you, {user["full_name"].split()[0]}')
    st.caption('Your company communication and work, in one place.')
    inbox=q('SELECT COUNT(*) n FROM recipients WHERE user_id=? AND is_read=0',(user['id'],))['n']
    mytasks=q("SELECT COUNT(*) n FROM tickets WHERE assignee_id=? AND status NOT IN ('Resolved','Closed')",(user['id'],))['n']
    opened=q("SELECT COUNT(*) n FROM tickets WHERE status NOT IN ('Resolved','Closed')")['n']
    notes=q('SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0',(user['id'],))['n']
    a,b,c,d=st.columns(4); a.metric('Unread emails',inbox); b.metric('My active tasks',mytasks); c.metric('Open tickets',opened); d.metric('Notifications',notes)
    live_mail_status()
    st.subheader('Recent activity')
    rows=qall('SELECT category,message,created_at FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 8',(user['id'],))
    if not rows: st.info('You are all caught up. New emails and task updates will appear here.')
    for r in rows: st.write(f'**{r["category"]}** · {r["message"]}'); st.caption(r['created_at'])
elif page=='Drotax Mail':
    st.title('Inbox')
    live_mail_status()
    rows=qall('''SELECT r.id rid,r.is_read,m.*,u.full_name sender_name FROM recipients r JOIN messages m ON m.id=r.message_id LEFT JOIN users u ON u.id=m.sender_id WHERE r.user_id=? AND r.kind!='BCC' ORDER BY m.created_at DESC''',(user['id'],))
    if not rows: st.info('Your inbox is empty.')
    for r in rows:
        with st.container(border=True):
            col1,col2=st.columns([5,1]); col1.markdown(('**' if not r['is_read'] else '')+f'{r["subject"] or "(No subject)"}'+('**' if not r['is_read'] else ''))
            col1.caption(f'From: {r["sender_name"] or r["sender_email"]} · {r["created_at"]}')
            if col2.button('Open',key='openmail_'+r['rid']): st.session_state.open_message=r['id']; run('UPDATE recipients SET is_read=1 WHERE id=?',(r['rid'],)); st.rerun()
    if st.session_state.get('open_message'):
        m=q('SELECT * FROM messages WHERE id=?',(st.session_state.open_message,))
        if m:
            st.divider(); st.subheader(m['subject'] or '(No subject)'); st.caption(f'From {m["sender_email"]} · {m["created_at"]}'); st.write(m['body'])
            for f in qall('SELECT filename,data FROM attachments WHERE message_id=?',(m['id'],)): st.download_button('Download '+f['filename'],f['data'],file_name=f['filename'],key='dl_'+f['filename'])
            if st.button('Close message'): st.session_state.pop('open_message',None); st.rerun()
elif page=='Compose':
    st.title('Compose email')
    directory=users()
    typed=st.text_input('To start typing a colleague name or email',key='recipient_search')
    suggestions=[u for u in directory if typed and (typed.lower() in u['full_name'].lower() or typed.lower() in u['email'].lower())]
    options={f"{u['full_name']} <{u['email']}>":u['email'] for u in suggestions[:12]}
    if options:
        selected=st.multiselect('Matching employees — select to add',list(options),key='recipient_matches')
        selected_emails=[options[x] for x in selected]
    else:
        selected_emails=[]
        if typed: st.caption('No matching employee found. You can enter an external address below.')
    with st.form('compose_email'):
        manual=st.text_input('Additional email addresses (comma separated)')
        cc_raw=st.text_input('CC (optional)'); bcc_raw=st.text_input('BCC (optional)')
        subject=st.text_input('Subject'); body=st.text_area('Message',height=220); files=st.file_uploader('Attachments',accept_multiple_files=True)
        submitted=st.form_submit_button('Send email',type='primary')
    if submitted:
        try:
            def parse(s): return [x.strip() for x in s.replace(';',',').split(',') if x.strip()]
            to=list(dict.fromkeys(selected_emails+parse(manual))); cc=parse(cc_raw); bcc=parse(bcc_raw)
            for addr in to+cc+bcc:
                if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',addr): raise ValueError(f'Invalid email address: {addr}')
            send_message(user,to,cc,bcc,subject,body,files or [])
            st.success('Email sent. Internal recipients will receive an inbox notification.')
            st.session_state.page='Drotax Mail'; st.rerun()
        except Exception as ex: st.error(str(ex))
elif page=='TeamTrack':
    st.title('TeamTrack')
    st.caption('Create and manage company tickets and requests.')
    if user['role']!='Viewer':
        with st.expander('Create a ticket',expanded=False):
            with st.form('create_ticket'):
                title=st.text_input('Title'); desc=st.text_area('Description')
                known_departments=sorted({(u['department'] or '').strip() for u in users() if (u['department'] or '').strip()} | {'IT','HR','Marketing','Operations','Finance','Customer Support','Product','Design'})
                dep=st.selectbox('Department',known_departments,index=known_departments.index(user['department']) if user['department'] in known_departments else 0)
                active_users=users(); assignee_options={'Unassigned':None}|{f"{u['full_name']} — {u['email']}":u['id'] for u in active_users}
                assigned_label=st.selectbox('Assigned to',list(assignee_options.keys()))
                priority=st.selectbox('Priority',['Low','Medium','High','Critical']); due=st.date_input('Due date',value=None); submit=st.form_submit_button('Create ticket',type='primary')
            if submit and title.strip():
                tid=str(uuid.uuid4()); key='TT-'+datetime.now().strftime('%y%m%d')+'-'+uuid.uuid4().hex[:4].upper()
                assignee_id=assignee_options[assigned_label]
                run('INSERT INTO tickets(id,ticket_key,title,description,department,priority,status,reporter_id,assignee_id,due_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(tid,key,title.strip(),desc,dep,priority,'Assigned' if assignee_id else 'Open',user['id'],assignee_id,str(due) if due else None,now(),now()))
                if assignee_id: notify(assignee_id,'TeamTrack',f'You have been assigned {key}: {title.strip()}',tid)
                st.success('Ticket created.'); st.rerun()
    tickets=qall('''SELECT t.*,r.full_name reporter,a.full_name assignee FROM tickets t JOIN users r ON r.id=t.reporter_id LEFT JOIN users a ON a.id=t.assignee_id ORDER BY t.created_at DESC''')
    for t in tickets:
        with st.container(border=True):
            x,y,z=st.columns([5,2,2]); x.markdown(f'**{t["ticket_key"]} · {t["title"]}**'); x.caption(f'{t["department"]} · Reported by {t["reporter"]} · Assigned to {t["assignee"] or "Unassigned"}')
            y.write(t['priority']); z.write(t['status'])
            with st.expander('Ticket details'):
                st.write(t['description'])
                if user['role'] in ['Admin','IT Personnel','Team Lead']:
                    active_users=users(); choices={'Unassigned':None}|{f"{u['full_name']} ({u['department']})":u['id'] for u in active_users}
                    current_label=next((k for k,v in choices.items() if v==t['assignee_id']),'Unassigned')
                    assignee=st.selectbox('Assign to',list(choices),index=list(choices).index(current_label),key='assign_'+t['id'])
                    status=st.selectbox('Status',['Open','Assigned','In Progress','On Hold','Resolved','Closed'],index=['Open','Assigned','In Progress','On Hold','Resolved','Closed'].index(t['status']),key='status_'+t['id'])
                    if st.button('Save ticket changes',key='save_'+t['id']):
                        run('UPDATE tickets SET assignee_id=?,status=?,updated_at=? WHERE id=?',(choices[assignee],status,now(),t['id']))
                        if choices[assignee]: notify(choices[assignee],'TeamTrack',f'You have been assigned {t["ticket_key"]}: {t["title"]}',t['id'])
                        st.rerun()
                comment=st.text_input('Add a comment',key='comment_'+t['id'])
                if st.button('Post comment',key='post_'+t['id']) and comment.strip():
                    run('INSERT INTO ticket_comments VALUES(?,?,?,?,?)',(str(uuid.uuid4()),t['id'],user['id'],comment.strip(),now()))
                    if t['reporter_id']!=user['id']: notify(t['reporter_id'],'TeamTrack',f'New comment on {t["ticket_key"]}',t['id'])
                    st.rerun()
                for cm in qall('SELECT c.body,c.created_at,u.full_name FROM ticket_comments c JOIN users u ON u.id=c.user_id WHERE c.ticket_id=? ORDER BY c.created_at',(t['id'],)):
                    st.caption(f'{cm["full_name"]} · {cm["created_at"]}'); st.write(cm['body'])
elif page=='My Tasks':
    st.title('My Tasks')
    rows=qall('SELECT * FROM tickets WHERE assignee_id=? ORDER BY updated_at DESC',(user['id'],))
    if not rows: st.info('No tasks have been assigned to you.')
    for t in rows:
        with st.container(border=True): st.markdown(f'**{t["ticket_key"]} · {t["title"]}**'); st.caption(f'{t["department"]} · {t["priority"]} · {t["status"]}'); st.write(t['description'])
elif page=='Notifications':
    st.title('Notifications')
    rows=qall('SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC',(user['id'],))
    if st.button('Mark all as read'): run('UPDATE notifications SET is_read=1 WHERE user_id=?',(user['id'],)); st.rerun()
    for n in rows:
        with st.container(border=True): st.write(('🔵 ' if not n['is_read'] else '')+n['message']); st.caption(f'{n["category"]} · {n["created_at"]}')
elif page=='Employee Directory':
    st.title('Employee Directory')
    st.dataframe([dict(u) for u in users()],use_container_width=True,hide_index=True)
elif page=='Administration':
    st.title('Administration')
    if user['role']!='Admin': st.error('Administrator access required.')
    else:
        with st.expander('Create employee account',expanded=True):
            with st.form('new_employee'):
                name=st.text_input('Full name'); email=st.text_input('Email address'); pw=st.text_input('Temporary password',type='password'); dept=st.text_input('Department'); role=st.selectbox('Role',['Admin','IT Personnel','Team Lead','Member','Viewer']); create=st.form_submit_button('Create account',type='primary')
            if create:
                try: register_user(name,email,pw,dept,role); st.success('Account created.'); st.rerun()
                except Exception as ex: st.error(str(ex))
        st.subheader('Manage employees')
        for u in qall('SELECT id,full_name,email,role,department,active FROM users ORDER BY full_name'):
            with st.container(border=True):
                x,y,z=st.columns([4,2,2]); x.write(f'**{u["full_name"]}**'); x.caption(u['email']); y.write(f'{u["role"]} · {u["department"]}');
                if u['id']!=user['id'] and z.button('Deactivate' if u['active'] else 'Reactivate',key='toggle_'+u['id']): run('UPDATE users SET active=? WHERE id=?',(0 if u['active'] else 1,u['id'])); st.rerun()

st.caption('Drotax Workspace · Unified Mail and TeamTrack')
