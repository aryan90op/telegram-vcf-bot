#!/usr/bin/env python3
"""
Full-featured Telegram bot (single file) ready for Replit + UptimeRobot 24/7 hosting.

Replace BOT_TOKEN and OWNER_ID below OR set environment variables BOT_TOKEN and OWNER_ID in Replit.

Features:
- TinyDB persistent user storage (users_db.json)
- Admin / Owner system with admin key (default 000000)
- /help
- TXT -> VCF (split, filename/contact name templates, auto-sequence)
- XLSX -> VCF
- VCF -> TXT
- Merge VCF / TXT
- Split VCF / TXT
- Admin + Neavy interactive flow
- Web endpoint (Flask) for uptime pings (keeps Replit alive with UptimeRobot)
"""

import os
import io
import re
import sys
import zipfile
import traceback
import threading
from pathlib import Path
from typing import List, Tuple

import telebot
from telebot.types import InputFile

import pandas as pd
from tinydb import TinyDB, Query
from flask import Flask, jsonify

# ---------------------------
# CONFIG - Replace / Env Var
# ---------------------------
BOT_TOKEN = os.getenv("8421126137:AAE3lsRd6DS4lRZ_bqGGGi3uvEDq9vUwkvw") or "REPLACE_WITH_YOUR_BOT_TOKEN"
OWNER_ID = int(os.getenv("6497509361") or "123456789")  # replace with your numeric id if not using env
ADMIN_KEY = os.getenv("ADMIN_KEY") or "000000"

# Replit port (UptimeRobot uses this)
WEB_PORT = int(os.getenv("PORT", 5000))

# ---------------------------
# Initialization
# ---------------------------
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask("bot_keepalive")

DB_FILE = "users_db.json"
db = TinyDB(DB_FILE)
table = db.table("access")  # stores records: {"role": "owner"/"admin"/"user", "id": <int>}

# Ensure owner recorded
if not table.search((Query().role == "owner") & (Query().id == OWNER_ID)):
    table.insert({"role": "owner", "id": OWNER_ID})

# ---------------------------
# DB helper functions
# ---------------------------
def get_owner_id() -> int:
    res = table.search(Query().role == "owner")
    return res[0]["id"] if res else OWNER_ID

def get_admin_ids() -> List[int]:
    return [r["id"] for r in table.search(Query().role == "admin")]

def get_user_ids() -> List[int]:
    return [r["id"] for r in table.search(Query().role == "user")]

def get_allowed_ids() -> List[int]:
    owner = get_owner_id()
    admins = set(get_admin_ids())
    users = set(get_user_ids())
    return list({owner} | admins | users)

def add_user_id(uid: int):
    if not table.search((Query().role == "user") & (Query().id == uid)):
        table.insert({"role": "user", "id": uid})

def remove_user_id(uid: int):
    table.remove((Query().role == "user") & (Query().id == uid))

def add_admin_id(uid: int):
    if not table.search((Query().role == "admin") & (Query().id == uid)):
        table.insert({"role":"admin","id":uid})

def remove_admin_id(uid: int):
    table.remove((Query().role == "admin") & (Query().id == uid))

# ---------------------------
# Utility functions
# ---------------------------
def is_owner(uid:int) -> bool:
    return uid == get_owner_id()

def is_admin(uid:int) -> bool:
    return uid in get_admin_ids() or is_owner(uid)

def is_allowed(uid:int) -> bool:
    return uid in get_allowed_ids() or is_admin(uid) or is_owner(uid)

def deny(chat_id):
    bot.send_message(chat_id, "Purchase access from @random_0988")

def normalize_phone(ph: str) -> str:
    ph = str(ph or "").strip()
    return re.sub(r"[^\d\+]", "", ph)

def vcard_entry(name: str, phone: str) -> str:
    return f"BEGIN:VCARD\r\nVERSION:3.0\r\nN:{name};;;;\r\nFN:{name}\r\nTEL;TYPE=CELL:{phone}\r\nEND:VCARD\r\n"

def make_vcf_bytes(contacts: List[Tuple[str,str]]) -> bytes:
    s = "".join(vcard_entry(n,p) for n,p in contacts)
    return s.encode("utf-8")

def parse_txt_contacts(text: str) -> List[Tuple[str,str]]:
    out=[]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r"[,\t\|:]+", line)
        if len(parts) == 1:
            phone = normalize_phone(parts[0])
            name = phone
        else:
            phone = None
            for p in parts[::-1]:
                if re.search(r"\d", p):
                    phone = normalize_phone(p)
                    break
            name_parts = [p.strip() for p in parts if p.strip() and normalize_phone(p) != phone]
            name = name_parts[0] if name_parts else phone
        if phone:
            out.append((name, phone))
    return out

def parse_vcf_to_contacts(b: bytes) -> List[Tuple[str,str]]:
    txt = b.decode("utf-8", errors="ignore")
    entries = re.split(r"END:VCARD", txt, flags=re.IGNORECASE)
    contacts=[]
    for ent in entries:
        if not ent.strip(): continue
        m_tel = re.search(r"TEL[^:]*:([+\d\-\s\(\)]+)", ent, flags=re.IGNORECASE)
        m_fn = re.search(r"FN:(.+)", ent, flags=re.IGNORECASE)
        tel = normalize_phone(m_tel.group(1)) if m_tel else None
        fn = m_fn.group(1).strip() if m_fn else tel
        if tel:
            contacts.append((fn, tel))
    return contacts

def parse_xlsx_contacts_bytes(b: bytes) -> List[Tuple[str,str]]:
    df = pd.read_excel(io.BytesIO(b), engine="openpyxl")
    phone_col = None
    name_col = None
    for c in df.columns:
        lc = str(c).lower()
        if any(k in lc for k in ("phone","tel","mobile","number","contact")) and phone_col is None:
            phone_col = c
        if any(k in lc for k in ("name","fullname","contact","姓名")) and name_col is None:
            name_col = c
    if phone_col is None:
        for c in df.columns:
            if df[c].dropna().apply(lambda x: bool(re.search(r"\d", str(x)))).sum() > 0:
                phone_col = c; break
    if name_col is None:
        for c in df.columns:
            if c != phone_col:
                name_col = c; break
    contacts=[]
    if phone_col is None:
        return contacts
    for _, row in df.iterrows():
        phone = normalize_phone(row[phone_col]) if not pd.isna(row[phone_col]) else None
        if not phone: continue
        name = row[name_col] if (name_col is not None and not pd.isna(row[name_col])) else phone
        contacts.append((str(name).strip(), phone))
    return contacts

# ---------------------------
# sequence utilities (A2D -> A3D)
# ---------------------------
def detect_sequence_template(s: str):
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    return (s[:m.start()], int(m.group(1)), s[m.end():])

def generate_sequence_from_template(template: str, count: int):
    template = (template or "").strip()
    if not template:
        return [f"file{i+1}.vcf" for i in range(count)]
    if " " in template:
        parts = [p.strip() for p in template.split() if p.strip()]
        if len(parts) >= count:
            return parts[:count]
        last = parts[-1]
        tpl = detect_sequence_template(last)
        seq = parts[:]
        if tpl:
            prefix, num, suffix = tpl
            while len(seq) < count:
                num += 1
                seq.append(f"{prefix}{num}{suffix}")
            return seq
        while len(seq) < count:
            seq.append(parts[-1])
        return seq
    tpl = detect_sequence_template(template)
    seq=[]
    if tpl:
        prefix,num,suffix = tpl
        for i in range(count):
            seq.append(f"{prefix}{num + i}{suffix}")
        return seq
    else:
        for i in range(1, count+1):
            seq.append(f"{template}{i}")
        return seq

# ---------------------------
# session & merge storage
# ---------------------------
user_sessions = {}         # chat_id -> session dict
merge_vcf_store = {}       # chat_id -> [bytes]
merge_txt_store = {}       # chat_id -> [str]

# ---------------------------
# help text
# ---------------------------
HELP_TEXT = f"""
📚 Commands & who can use them:

Public / Allowed:
 - /help
 - /txt2vcf     -> interactive: upload TXT doc
 - /xlsx2vcf    -> interactive: upload XLSX
 - /vcf2txt     -> upload VCF -> returns TXT
 - /merge_vcf   -> send many VCF docs then /done_merge
 - /merge_txt   -> send many TXT docs then /done_merge_txt
 - /split_vcf   -> upload VCF then specify per-file count
 - /split_txt   -> upload TXT then specify per-file count
 - /adminneavy  -> interactive Admin+Neavy VCF creator

Admin / Owner:
 - /admin <admin_key>       (owner uses this)
 - /adduser <telegram_user_id>
 - /removeuser <telegram_user_id>  (owner cannot be removed)
 - /addadmin <admin_key> <telegram_user_id>
 - /removeadmin <admin_key> <telegram_user_id>

Notes:
 - Default admin key: {ADMIN_KEY}
 - Unauthorized users see: 'Purchase access from @random_0988'
 - Attempt to remove owner -> 'BAAP SE PANGA NHI 😁'
"""

# ---------------------------
# command handlers
# ---------------------------
@bot.message_handler(commands=['start','help'])
def handle_help(msg):
    uid = msg.from_user.id
    if not is_allowed(uid):
        deny(msg.chat.id); return
    bot.send_message(msg.chat.id, HELP_TEXT)

@bot.message_handler(commands=['admin'])
def handle_admin(msg):
    parts = msg.text.strip().split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "Usage: /admin <admin_key> (owner only)")
        return
    key = parts[1]
    if key != ADMIN_KEY:
        bot.send_message(msg.chat.id, "Invalid admin key.")
        return
    if not is_owner(msg.from_user.id):
        bot.send_message(msg.chat.id, "Only owner can activate admin via this.")
        return
    add_admin_id(msg.from_user.id)
    bot.send_message(msg.chat.id, "You are now an admin (owner is always admin).")

@bot.message_handler(commands=['adduser'])
def handle_adduser(msg):
    if not is_admin(msg.from_user.id):
        bot.send_message(msg.chat.id, "Only admin/owner can add users."); return
    parts = msg.text.strip().split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "Usage: /adduser <telegram_user_id>"); return
    try:
        tid = int(parts[1])
    except:
        bot.send_message(msg.chat.id, "telegram_user_id must be a number"); return
    add_user_id(tid)
    bot.send_message(msg.chat.id, f"User {tid} added to allowed users.")

@bot.message_handler(commands=['removeuser'])
def handle_removeuser(msg):
    if not is_admin(msg.from_user.id):
        bot.send_message(msg.chat.id, "Only admin/owner can remove users."); return
    parts = msg.text.strip().split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "Usage: /removeuser <telegram_user_id>"); return
    try:
        tid = int(parts[1])
    except:
        bot.send_message(msg.chat.id, "telegram_user_id must be a number"); return
    if tid == get_owner_id():
        bot.send_message(msg.chat.id, "BAAP SE PANGA NHI 😁"); return
    remove_user_id(tid)
    bot.send_message(msg.chat.id, f"User {tid} removed from allowed users.")

@bot.message_handler(commands=['addadmin'])
def handle_addadmin(msg):
    parts = msg.text.strip().split()
    if len(parts) < 3:
        bot.send_message(msg.chat.id, "Usage: /addadmin <admin_key> <telegram_user_id>"); return
    key = parts[1]
    try:
        tid = int(parts[2])
    except:
        bot.send_message(msg.chat.id, "telegram_user_id must be a number"); return
    if key != ADMIN_KEY:
        bot.send_message(msg.chat.id, "Invalid admin key"); return
    add_admin_id(tid)
    bot.send_message(msg.chat.id, f"Added admin {tid}.")

@bot.message_handler(commands=['removeadmin'])
def handle_removeadmin(msg):
    parts = msg.text.strip().split()
    if len(parts) < 3:
        bot.send_message(msg.chat.id, "Usage: /removeadmin <admin_key> <telegram_user_id>"); return
    key = parts[1]
    try:
        tid = int(parts[2])
    except:
        bot.send_message(msg.chat.id, "telegram_user_id must be a number"); return
    if key != ADMIN_KEY:
        bot.send_message(msg.chat.id, "Invalid admin key"); return
    if tid == get_owner_id():
        bot.send_message(msg.chat.id, "BAAP SE PANGA NHI 😁"); return
    remove_admin_id(tid)
    bot.send_message(msg.chat.id, f"Removed admin {tid}.")

# ---------------------------
# flows start
# ---------------------------
@bot.message_handler(commands=['txt2vcf'])
def cmd_txt2vcf(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    user_sessions[msg.chat.id] = {'flow':'txt2vcf_wait_file'}
    bot.send_message(msg.chat.id, "Send the TXT file as a *document*. Each line: phone OR name,phone OR name<TAB>phone", parse_mode='Markdown')

@bot.message_handler(commands=['xlsx2vcf'])
def cmd_xlsx2vcf(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    user_sessions[msg.chat.id] = {'flow':'xlsx2vcf_wait_file'}
    bot.send_message(msg.chat.id, "Send the XLSX file as a *document*. Bot will try to detect columns", parse_mode='Markdown')

@bot.message_handler(commands=['vcf2txt'])
def cmd_vcf2txt(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    user_sessions[msg.chat.id] = {'flow':'vcf2txt_wait_file'}
    bot.send_message(msg.chat.id, "Send the VCF file as a document")

@bot.message_handler(commands=['merge_vcf'])
def cmd_merge_vcf(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    merge_vcf_store[msg.chat.id] = []
    bot.send_message(msg.chat.id, "Send VCF files (documents) one by one. When done send /done_merge")

@bot.message_handler(commands=['done_merge'])
def cmd_done_merge(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    col = merge_vcf_store.get(msg.chat.id, [])
    if not col:
        bot.send_message(msg.chat.id, "No files collected"); return
    contacts=[]
    for b in col:
        contacts += parse_vcf_to_contacts(b)
    if not contacts:
        bot.send_message(msg.chat.id, "No contacts parsed"); merge_vcf_store.pop(msg.chat.id, None); return
    out = make_vcf_bytes(contacts)
    bot.send_document(msg.chat.id, InputFile(io.BytesIO(out), filename="merged.vcf"))
    merge_vcf_store.pop(msg.chat.id, None)

@bot.message_handler(commands=['merge_txt'])
def cmd_merge_txt(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    merge_txt_store[msg.chat.id] = []
    bot.send_message(msg.chat.id, "Send TXT files (documents) one by one. When done send /done_merge_txt")

@bot.message_handler(commands=['done_merge_txt'])
def cmd_done_merge_txt(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    col = merge_txt_store.get(msg.chat.id, [])
    if not col:
        bot.send_message(msg.chat.id, "No files collected"); return
    text = "\n".join(col)
    bot.send_document(msg.chat.id, InputFile(io.BytesIO(text.encode('utf-8')), filename="merged.txt"))
    merge_txt_store.pop(msg.chat.id, None)

@bot.message_handler(commands=['split_vcf'])
def cmd_split_vcf(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    user_sessions[msg.chat.id] = {'flow':'split_vcf_wait_file'}
    bot.send_message(msg.chat.id, "Send VCF file as document to split")

@bot.message_handler(commands=['split_txt'])
def cmd_split_txt(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    user_sessions[msg.chat.id] = {'flow':'split_txt_wait_file'}
    bot.send_message(msg.chat.id, "Send TXT file as document to split")

@bot.message_handler(commands=['adminneavy'])
def cmd_adminneavy(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    user_sessions[msg.chat.id] = {'flow':'adminneavy_wait_admin_number'}
    bot.send_message(msg.chat.id, "Enter ADMIN number (phone):")

# ---------------------------
# document handler
# ---------------------------
@bot.message_handler(content_types=['document'])
def handle_document(msg):
    if not is_allowed(msg.from_user.id):
        deny(msg.chat.id); return
    doc = msg.document
    file_info = bot.get_file(doc.file_id)
    b = bot.download_file(file_info.file_path)
    fname = doc.file_name or ""
    sess = user_sessions.get(msg.chat.id, {})
    flow = sess.get('flow')

    # collect for merges
    if msg.chat.id in merge_vcf_store and fname.lower().endswith('.vcf'):
        merge_vcf_store[msg.chat.id].append(b)
        bot.send_message(msg.chat.id, f"Collected {len(merge_vcf_store[msg.chat.id])} vcf(s). Send more or /done_merge")
        return
    if msg.chat.id in merge_txt_store and fname.lower().endswith('.txt'):
        txt = b.decode('utf-8', errors='ignore')
        merge_txt_store[msg.chat.id].append(txt)
        bot.send_message(msg.chat.id, f"Collected {len(merge_txt_store[msg.chat.id])} txt(s). Send more or /done_merge_txt")
        return

    # flows
    if flow == 'txt2vcf_wait_file':
        if not fname.lower().endswith('.txt'):
            bot.send_message(msg.chat.id, "Please send a .txt file as document"); user_sessions.pop(msg.chat.id, None); return
        text = b.decode('utf-8', errors='ignore')
        contacts = parse_txt_contacts(text)
        if not contacts:
            bot.send_message(msg.chat.id, "No contacts found in TXT."); user_sessions.pop(msg.chat.id, None); return
        user_sessions[msg.chat.id] = {'flow':'txt2vcf_wait_options','contacts':contacts}
        bot.send_message(msg.chat.id, f"Found {len(contacts)} contacts.\nReply with options:\n<contacts_per_vcf>,<vcf_prefix>,<contact_name_prefix>\nOR: single,<vcf_prefix>,<contact_name_prefix>\nYou can give sequence template like 'A2D' or explicit 'A2D A3D A4D'")
        return

    if flow == 'xlsx2vcf_wait_file':
        if not (fname.lower().endswith('.xlsx') or fname.lower().endswith('.xls')):
            bot.send_message(msg.chat.id, "Please send an Excel (.xlsx) file as document"); user_sessions.pop(msg.chat.id,None); return
        try:
            contacts = parse_xlsx_contacts_bytes(b)
        except Exception as e:
            bot.send_message(msg.chat.id, f"Failed to parse Excel: {e}"); user_sessions.pop(msg.chat.id,None); return
        if not contacts:
            bot.send_message(msg.chat.id, "No contacts found in Excel."); user_sessions.pop(msg.chat.id,None); return
        user_sessions[msg.chat.id] = {'flow':'xlsx2vcf_wait_options','contacts':contacts}
        bot.send_message(msg.chat.id, f"Found {len(contacts)} contacts in Excel.\nReply with options like TXT flow.")
        return

    if flow == 'vcf2txt_wait_file':
        if not fname.lower().endswith('.vcf'):
            bot.send_message(msg.chat.id, "Please send a .vcf file."); user_sessions.pop(msg.chat.id,None); return
        contacts = parse_vcf_to_contacts(b)
        if not contacts:
            bot.send_message(msg.chat.id, "No contacts found in VCF."); user_sessions.pop(msg.chat.id,None); return
        lines = [f"{n}|{p}" for n,p in contacts]
        outname = Path(fname).stem + ".txt"
        bot.send_document(msg.chat.id, InputFile(io.BytesIO("\n".join(lines).encode('utf-8')), filename=outname))
        user_sessions.pop(msg.chat.id,None); return

    if flow == 'split_vcf_wait_file':
        if not fname.lower().endswith('.vcf'):
            bot.send_message(msg.chat.id, "Please send a .vcf file."); user_sessions.pop(msg.chat.id,None); return
        contacts = parse_vcf_to_contacts(b)
        if not contacts:
            bot.send_message(msg.chat.id, "No contacts parsed"); user_sessions.pop(msg.chat.id,None); return
        user_sessions[msg.chat.id] = {'flow':'split_vcf_wait_count', 'contacts':contacts}
        bot.send_message(msg.chat.id, "Enter number of contacts per output VCF (integer):")
        return

    if flow == 'split_txt_wait_file':
        if not fname.lower().endswith('.txt'):
            bot.send_message(msg.chat.id, "Please send a .txt file."); user_sessions.pop(msg.chat.id,None); return
        text = b.decode('utf-8', errors='ignore')
        contacts = parse_txt_contacts(text)
        if not contacts:
            bot.send_message(msg.chat.id, "No contacts parsed"); user_sessions.pop(msg.chat.id,None); return
        user_sessions[msg.chat.id] = {'flow':'split_txt_wait_count','contacts':contacts}
        bot.send_message(msg.chat.id, "Enter number of contacts per output TXT (integer):")
        return

    # default convert 
