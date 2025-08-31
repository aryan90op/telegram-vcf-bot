#!/usr/bin/env python3
"""
Velorse-style Contact Toolkit Bot
Features:
 - Command-driven: many /commands as requested
 - TXT -> VCF (split), VCF -> TXT (merge), TXT auto Admin/Neavy modes
 - XLSX->VCF (reads first column or specified column)
 - Filename-increment: detects number inside filename (HUH1OK -> HUH2OK)
 - Preview (first 5 contacts) before sending
 - Batching: sends up to 10 files per grouped message; if <10, sends all at once
 - Admin panel: /admin <key>, /add <id>, /remove <id>, /list
 - BOT_OWNER_ID cannot be removed; trying to remove owner replies "😎 BAAP SE PANGA NHI"
 - Unauthorized users see "❌ Buy premium from @random_0988"
"""

import os
import io
import re
import json
import shutil
import pathlib
from typing import List
from datetime import datetime

from telegram import (
    Update, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

# ---------------- CONFIG ----------------
TOKEN = os.getenv("BOT_TOKEN")  # MUST be set on host
MASTER_KEY = "Aryan9936"
BOT_OWNER_ID = 6497509361  # REPLACE with your telegram id (owner, permanent)
USERS_FILE = "allowed_users.json"
DOWNLOAD_DIR = "downloads"             # temporary store for uploads
OUT_DIR = "outputs"                    # temporary outputs
ALERT_ON_UNAUTHORIZED = "❌ Buy premium from @random_0988"
OWNER_REMOVE_MSG = "😎 BAAP SE PANGA NHI"

# ensure directories exist
pathlib.Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
pathlib.Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

# ---------------- UTIL: users ----------------
def load_users() -> List[int]:
    try:
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
            return list(map(int, data))
    except Exception:
        return []

def save_users(users: List[int]) -> None:
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)

ALLOWED_USERS = load_users()

def is_allowed(uid: int) -> bool:
    return uid == BOT_OWNER_ID or uid in ALLOWED_USERS

# ---------------- SESSION STORAGE (in-memory per chat) ----------------
sessions = {}  # chat_id -> dict

def get_session(chat_id: int):
    return sessions.setdefault(chat_id, {
        "mode": None,           # what flow user is in
        "step": None,           # step in flow
        "numbers": [],          # list of numbers for txt mode or admin/neavy
        "contacts_per_file": 100,
        "filename_input": None,
        "filename_gen": None,
        "contact_prefix": "Contact",
        "contact_start": 1,
        "vcf_files": [],        # for vcf->txt mode store file paths
        "tmp_files": []         # internal temporary files created
    })

# ---------------- ACCESS DECORATOR ----------------
def require_access(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if not is_allowed(uid):
            # If it's a command, reply to message
            await update.message.reply_text(ALERT_ON_UNAUTHORIZED)
            return
        return await handler(update, context)
    return wrapper

# ---------------- FILENAME INCREMENT LOGIC ----------------
def make_filename_generator(example: str):
    """
    Given 'HUH1OK' returns function gen(n) -> 'HUH1OK' (n=0), 'HUH2OK' (n=1), ...
    If no number present, append n before .vcf (or at end) -> example + n + .vcf
    """
    match = re.search(r'(\d+)', example)
    if not match:
        def gen(n):
            return f"{example}{n}.vcf"
        return gen
    num_str = match.group(1)
    start = int(num_str)
    pre = example[:match.start(1)]
    post = example[match.end(1):]
    def gen(n):
        return f"{pre}{start + n}{post}.vcf"
    return gen

# ---------------- VCF helpers ----------------
def create_vcard(fn: str, tel: str) -> str:
    # use vCard 3.0 format, with TEL;TYPE=CELL
    return f"BEGIN:VCARD\nVERSION:3.0\nFN:{fn}\nTEL;TYPE=CELL:{tel}\nEND:VCARD\n"

def extract_tels_from_vcf_text(text: str) -> List[str]:
    found = []
    for line in text.splitlines():
        m = re.search(r'TEL[^:]*:(.+)$', line, flags=re.IGNORECASE)
        if m:
            found.append(m.group(1).strip())
    return found

# ---------------- BATCH SENDER ----------------
async def send_files_in_batches(update: Update, files: List[InputFile], batch_size: int = 10):
    # send in groups of batch_size; if total<batch_size send all at once (telegram will still deliver files sequentially)
    batch = []
    for f in files:
        batch.append(f)
        if len(batch) == batch_size:
            for doc in batch:
                await update.message.reply_document(doc)
            batch = []
    if batch:
        for doc in batch:
            await update.message.reply_document(doc)

# ---------------- COMMANDS MENU ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    get_session(chat_id)  # init
    text = (
        "👋 *Velorse Contact Toolkit*\n\n"
        "Type /help to see commands list.\n"
        "Owner & admin controls: /admin <key>, /add <id>, /remove <id>, /list\n"
    )
    await update.message.reply_text(text)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu = (
"🔄 𝗙𝗶𝗹𝗲 𝗖𝗼𝗻𝘃𝗲𝗿𝘀𝗶𝗼𝗻\n"
"/rekapgroup - (placeholder) send group screenshots to extract name + members\n"
"/cv_txt_to_vcf - Convert TXT → VCF (split)\n"
"/cv_vcf_to_txt - Convert VCF → TXT (merge)\n"
"/cv_xlsx_to_vcf - Convert XLSX → VCF (first column)\n"
"/txt2vcf - Convert TXT auto-detect Admin/Neavy\n"
"/cvadminfile - Manage admin files (placeholder)\n\n"
"📁 𝗙𝗶𝗹𝗲 𝗠𝗮𝗻𝗮𝗴𝗲𝗺𝗲𝗻𝘁\n"
"/renamectc - Rename contact names inside a VCF\n"
"/renamefile - Rename an uploaded file (placeholder)\n"
"/joining - Merge multiple TXT files into one\n"
"/joinvcf - Merge multiple VCF files into one VCF\n"
"/graphfile - Split a VCF into parts (by size) (placeholder)\n"
"/gradctc - Split VCF into multiple files each having N contacts\n"
"/addctc - Add contact(s) into a VCF\n"
"/delctc - Delete contact(s) from a VCF\n"
"/calculatectc - Count contacts in VCF files\n"
"/totxt - Save a message into a TXT and return it\n"
"/listgc - Create a group list (placeholder)\n\n"
"⚙️ 𝗢𝘁𝗵𝗲𝗿\n"
"/reset_conversions - Reset session/temp files\n"
"/fixbug - Try auto fix common bug (placeholder)\n"
"/reportbug - Send a bug report to owner\n"
    )
    await update.message.reply_text(menu)

# ---------------- ADMIN PANEL ----------------
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /admin <key>")
        return
    key = context.args[0]
    if key == MASTER_KEY:
        uid = update.effective_user.id
        # add admin if not owner already
        if uid != BOT_OWNER_ID and uid not in ALLOWED_USERS:
            ALLOWED_USERS.append(uid)
            save_users(ALLOWED_USERS)
        await update.message.reply_text("✅ Admin key accepted. You can use commands.")
    else:
        await update.message.reply_text("❌ Wrong key.")

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /add <user_id>")
        return
    try:
        uid = int(context.args[0])
        if uid == BOT_OWNER_ID:
            await update.message.reply_text("Owner is always allowed.")
            return
        if uid not in ALLOWED_USERS:
            ALLOWED_USERS.append(uid)
            save_users(ALLOWED_USERS)
        await update.message.reply_text(f"✅ Added {uid}")
    except Exception:
        await update.message.reply_text("Invalid id.")

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove <user_id>")
        return
    try:
        uid = int(context.args[0])
        if uid == BOT_OWNER_ID:
            await update.message.reply_text(OWNER_REMOVE_MSG)
            return
        if uid in ALLOWED_USERS:
            ALLOWED_USERS.remove(uid)
            save_users(ALLOWED_USERS)
            await update.message.reply_text(f"✅ Removed {uid}")
        else:
            await update.message.reply_text("⚠️ Not found.")
    except Exception:
        await update.message.reply_text("Invalid id.")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    await update.message.reply_text("Allowed users:\n" + ("\n".join(map(str, ALLOWED_USERS)) or "None"))

# ---------------- Utility: cleanup session files ----------------
def cleanup_files(paths: List[str]):
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

# ---------------- CONVERSION COMMANDS ----------------

# 1) TXT -> VCF (split)
@require_access
async def cmd_cv_txt_to_vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Begins TXT->VCF flow. User will upload a .txt file; bot will ask for contacts-per-file, filename sample, contact prefix and start.
    """
    chat = update.effective_chat
    sess = get_session(chat.id)
    sess.update({
        "mode": "txt_to_vcf",
        "step": "await_txt",
        "numbers": []
    })
    await update.message.reply_text("📂 TXT→VCF mode started.\nSend a .txt file (one number per line).")

@require_access
async def cmd_cv_vcf_to_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts VCF->TXT flow. User uploads multiple .vcf files, then sends desired TXT filename.
    """
    chat = update.effective_chat
    sess = get_session(chat.id)
    sess.update({
        "mode": "vcf_to_txt",
        "vcf_files": [],
        "step": "await_vcf"
    })
    await update.message.reply_text("📜 VCF→TXT mode. Upload .vcf files (send multiple). When done, send the TXT filename (without .txt).")

@require_access
async def cmd_txt2vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Quick auto mode: paste numbers and bot will create individual VCFs (Admin/Neavy style) or split files automatically.
    We'll treat it as Admin-style by default (one number -> one VCF file per contact).
    """
    chat = update.effective_chat
    sess = get_session(chat.id)
    sess.update({
        "mode": "txt2vcf",
        "step": "await_numbers",
        "numbers": []
    })
    await update.message.reply_text("TXT→VCF quick mode. Paste numbers (one per line). Bot will create one VCF per number. Then send VCF filename sample with number (like H1OK).")

@require_access
async def cmd_cv_xlsx_to_vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    XLSX -> VCF: Ask user to upload .xlsx, then ask column index or assume first column.
    Implementation requires openpyxl installed (added to requirements).
    """
    chat = update.effective_chat
    sess = get_session(chat.id)
    sess.update({
        "mode": "xlsx_to_vcf",
        "step": "await_xlsx",
        "xlsx_files": []
    })
    await update.message.reply_text("📊 XLSX→VCF mode. Upload an .xlsx file. Bot will take first column (A) as numbers by default.")

@require_access
async def cmd_cvadminfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("cvadminfile: admin-file manager (placeholder). Use /help for other commands.")

# ---------------- File management commands (some implemented) ----------------

@require_access
async def cmd_joining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Upload multiple .txt files then send /joining_done <output_name> to combine them.
    We'll implement a simplified flow: user uploads multiple .txt files then sends '/joining_done filename'
    """
    chat = update.effective_chat
    sess = get_session(chat.id)
    sess.update({"mode": "joining", "step": "await_txts", "files": []})
    await update.message.reply_text("Joining TXT: upload .txt files you want to merge, then send command:\n/joining_done filename (without .txt)")

@require_access
async def cmd_joining_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /joining_done filename")
        return
    name = context.args[0]
    chat = update.effective_chat
    sess = get_session(chat.id)
    files = sess.get("files", [])
    if not files:
        await update.message.reply_text("No files uploaded. Upload .txt files first.")
        return
    combined = []
    for p in files:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                combined.extend([l.strip() for l in f.readlines() if l.strip()])
        except:
            pass
    out = os.path.join(OUT_DIR, f"{name}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(combined))
    await update.message.reply_document(document=InputFile(out, filename=f"{name}.txt"))
    # cleanup
    cleanup_files(files)
    sess["files"] = []

@require_access
async def cmd_joinvcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    sess = get_session(chat.id)
    sess.update({"mode": "joinvcf", "step": "await_vcfs", "files": []})
    await update.message.reply_text("Join VCF: upload .vcf files to merge, then send /joinvcf_done filename")

@require_access
async def cmd_joinvcf_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /joinvcf_done filename")
        return
    name = context.args[0]
    sess = get_session(update.effective_chat.id)
    files = sess.get("files", [])
    if not files:
        await update.message.reply_text("No vcf files uploaded.")
        return
    outpath = os.path.join(OUT_DIR, f"{name}.vcf")
    with open(outpath, "w", encoding="utf-8") as out:
        for p in files:
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    out.write(f.read())
                    out.write("\n")
            except:
                pass
    await update.message.reply_document(document=InputFile(outpath, filename=f"{name}.vcf"))
    cleanup_files(files)
    sess["files"] = []

@require_access
async def cmd_renamectc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Rename contact in VCF: upload vcf and then send /renamectc_do oldname newname (placeholder flow).")

@require_access
async def cmd_renamefile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Rename file: upload file and then use /renamefile_do oldname newname (placeholder).")

@require_access
async def cmd_graphfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("graphfile: splitting large VCF (placeholder)")

@require_access
async def cmd_gradctc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Split a given .vcf file into multiple files, each containing N contacts.
    Usage: upload vcf, then send /gradctc_do N basename
    We'll implement the core helper /gradctc_do to run on uploaded file in session.
    """
    sess = get_session(update.effective_chat.id)
    sess.update({"mode": "gradctc", "step": "await_vcf", "files": []})
    await update.message.reply_text("Upload .vcf file(s) to split, then use /gradctc_do N basename")

@require_access
async def cmd_gradctc_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /gradctc_do N basename
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /gradctc_do <contacts_per_file> <base_name>")
        return
    try:
        n = int(context.args[0])
        base = context.args[1]
    except:
        await update.message.reply_text("Invalid arguments.")
        return
    sess = get_session(update.effective_chat.id)
    files = sess.get("files", [])
    if not files:
        await update.message.reply_text("Upload a vcf first.")
        return
    # read all numbers from uploaded files
    phones = []
    for p in files:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                phones.extend(extract_tels_from_vcf_text(f.read()))
        except:
            pass
    # create chunks of n contacts per file
    chunks = [phones[i:i+n] for i in range(0, len(phones), n)]
    out_files = []
    for i, chunk in enumerate(chunks):
        vcfdata = ""
        for j, num in enumerate(chunk, start=1):
            vcfdata += create_vcard(f"Contact{j}", num if num.startswith("+") else "+" + num)
        fname = make_filename_generator(base)(i)
        outpath = os.path.join(OUT_DIR, fname)
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(vcfdata)
        out_files.append(InputFile(outpath, filename=fname))
    # send batched
    await send_files_in_batches(update, out_files, batch_size=10)
    cleanup_files(files)
    sess["files"] = []

@require_access
async def cmd_addctc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("addctc: Upload a VCF and send /addctc_do Name +number (placeholder)")

@require_access
async def cmd_delctc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("delctc: Upload a VCF and send /delctc_do name_or_number (placeholder)")

@require_access
async def cmd_calculatectc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("calculatectc: Upload .vcf file and use /calculatectc_do (placeholder)")

@require_access
async def cmd_totxt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ToTXT: reply to a message with /totxt to save that message text into a .txt file and receive it.")

@require_access
async def cmd_listgc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("listgc: (placeholder) create a group list - send group screenshots and we can parse later.")

# ---------------- Reset / misc ----------------
@require_access
async def cmd_reset_conversions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    sess = get_session(chat.id)
    # delete temp files listed in session
    cleanup_files(sess.get("files", []) + sess.get("vcf_files", []) + sess.get("tmp_files", []))
    sess.clear()
    sessions.pop(chat.id, None)
    await update.message.reply_text("✅ Session reset and temp files cleaned.")

@require_access
async def cmd_fixbug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fixbug executed (placeholder). If you have a specific error, use /reportbug with details.")

async def cmd_reportbug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # forward to owner
    msg = update.message.text or "No details"
    owner_text = f"[BUG REPORT] from {update.effective_user.id} - {msg}"
    # send to owner if possible (we have no direct bot to owner chat check here)
    await update.message.reply_text("Thanks — bug report received. Owner will be notified (if available).")
    # (Implementation: send to owner via bot if owner has started bot)
    try:
        app = context.application
        await app.bot.send_message(BOT_OWNER_ID, owner_text)
    except Exception:
        pass

# ---------------- FILE / MESSAGE HANDLING ----------------
# A single file handler that reacts depending on session 'mode' & 'step'
@require_access
async def handle_incoming_document(update: Update, context: C
