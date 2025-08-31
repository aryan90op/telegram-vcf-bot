# === Final Telegram Bot: VCF / TXT Toolkit (Feature-complete) ===
# Features:
# - TXT -> multiple VCFs (customizable each run)
# - Admin / Neavy single-contact VCF generation (customizable)
# - Smart filename increment: detects number in given name and increments it (HUH1OK -> HUH2OK ...)
# - Preview (shows first 5 contacts before generating)
# - VCF -> TXT: upload multiple .vcf files, get one TXT with all phone numbers (customizable filename)
# - Batching: sends VCFs in groups of up to 10 files (if total < 10, sends that many in one batch)
# - Admin panel: /admin <MASTER_KEY>, /add <id>, /remove <id>, /list
# - Persistent allowed users stored in allowed_users.json
# - BOT_OWNER_ID cannot be removed. Trying to remove owner replies "😎 BAAP SE PANGA NHI"
# - Unauthorized users see "❌ Buy premium from @random_0988"

import os
import io
import re
import json
import pathlib
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ====== CONFIG ======
TOKEN = os.getenv("BOT_TOKEN")  # set this in your hosting ENV
MASTER_KEY = "Aryan9936"        # admin panel key
BOT_OWNER_ID = 6497509361       # <- REPLACE with your Telegram ID (owner, permanent)
USERS_FILE = "allowed_users.json"
DOWNLOAD_DIR = "downloads"      # directory for temporarily storing uploaded VCFs

# ensure download dir exists
pathlib.Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

# ====== USER MANAGEMENT ======
def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

ALLOWED_USERS = load_users()

def is_allowed(uid):
    return uid == BOT_OWNER_ID or uid in ALLOWED_USERS

# ====== SESSION STORAGE ======
user_data = {}

def get_defaults():
    return {
        "mode": None,               # txt_upload / admin_mode / neavy_mode / vcf_to_txt
        "step": None,               # track which input to ask for
        "numbers": [],              # list of numbers (from TXT or pasted)
        "contacts_per_file": 100,
        "filename_input": None,     # user-provided example filename (with number)
        "filename_gen": None,       # generator function for filenames
        "contact_prefix": "Contact",
        "contact_start": 1,
        "vcf_files": []             # for vcf->txt mode store file paths
    }

# ====== ACCESS DECORATOR ======
def check_access(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        uid = user.id if user else None
        # allow admin commands (/admin) to be used for access control via key, but main UI should be locked
        if not is_allowed(uid):
            # Send the premium message to unauthorized users
            # For callback queries, reply to callback query
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.message.reply_text("❌ Buy premium from @random_0988")
            else:
                await update.message.reply_text("❌ Buy premium from @random_0988")
            return
        return await func(update, context)
    return wrapper

# ====== FILENAME GENERATOR ======
def increment_filename(base_name):
    # find first number in the base_name, keep prefix & suffix, increment the number
    match = re.search(r'(\d+)', base_name)
    if not match:
        # no number: append incremental number before extension
        def gen(n):
            return f"{base_name}{n}.vcf"
        return gen
    num_str = match.group(1)
    prefix = base_name[:match.start(1)]
    suffix = base_name[match.end(1):]
    start = int(num_str)
    def gen(n):
        return f"{prefix}{start+n}{suffix}.vcf"
    return gen

# ====== UTIL ======
def create_vcf(contact_name, number):
    # Proper vCard 3.0 format for broad compatibility
    # Ensure number starts with + if digits only - but don't force modification if already formatted
    return f"BEGIN:VCARD\nVERSION:3.0\nFN:{contact_name}\nTEL;TYPE=CELL:{number}\nEND:VCARD\n"

def extract_tel_from_vcf_text(text):
    # Find TEL lines and extract numbers robustly
    numbers = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # look for TEL: or TEL;TYPE=...:
        m = re.search(r'TEL[^:]*:(.+)$', line, flags=re.IGNORECASE)
        if m:
            num = m.group(1).strip()
            numbers.append(num)
    return numbers

# ====== UI MENU ======
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 TXT ➡️ VCF (Split)", callback_data="txt_mode")],
        [InlineKeyboardButton("🛡️ Admin VCF", callback_data="admin_mode"),
         InlineKeyboardButton("⚓ Neavy VCF", callback_data="neavy_mode")],
        [InlineKeyboardButton("📜 VCF ➡️ TXT", callback_data="vcf_to_txt_mode")]
    ])

# ====== HANDLERS ======
@check_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data[chat_id] = get_defaults()
    await update.message.reply_text("👋 Welcome! Choose an option:", reply_markup=main_menu())

@check_access
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    if chat_id not in user_data:
        user_data[chat_id] = get_defaults()
    settings = user_data[chat_id]

    if query.data == "txt_mode":
        settings["mode"] = "txt_upload"
        settings["step"] = None
        await query.edit_message_text("📂 Send me a TXT file with numbers (one per line).", reply_markup=main_menu())

    elif query.data in ["admin_mode", "neavy_mode"]:
        settings["mode"] = query.data
        settings["step"] = "numbers_input"
        await query.edit_message_text(f"📋 Paste numbers (one per line) for {query.data.split('_')[0].title()} VCF.", reply_markup=main_menu())

    elif query.data == "vcf_to_txt_mode":
        settings["mode"] = "vcf_to_txt"
        settings["vcf_files"] = []
        settings["step"] = "vcf_uploading"
        await query.edit_message_text("📜 Send multiple VCF files now. When done, send the desired TXT filename (without .txt).", reply_markup=main_menu())

@check_access
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = user_data.get(chat_id, get_defaults())

    # TXT -> VCF upload
    if settings.get("mode") == "txt_upload":
        doc = update.message.document
        if not doc or not doc.file_name.lower().endswith(".txt"):
            await update.message.reply_text("Please upload a .txt file.")
            return
        file = await doc.get_file()
        content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
        numbers = [line.strip() for line in content.splitlines() if line.strip()]
        settings["numbers"] = numbers
        settings["step"] = "contacts_per_file"
        await update.message.reply_text(f"✅ TXT uploaded. {len(numbers)} numbers loaded.\n\nEnter Contacts per file (example: 100).")
        return

    # VCF -> TXT mode upload
    if settings.get("mode") == "vcf_to_txt":
        doc = update.message.document
        if not doc or not doc.file_name.lower().endswith(".vcf"):
            await update.message.reply_text("Please upload a .vcf file in VCF->TXT mode.")
            return
        file = await doc.get_file()
        safe_name = f"{chat_id}_{doc.file_name}"
        dest = os.path.join(DOWNLOAD_DIR, safe_name)
        await file.download_to_drive(dest)
        settings["vcf_files"].append(dest)
        await update.message.reply_text(f"✅ Added {doc.file_name}. Send more or send the TXT filename to finalize.")
        return

    await update.message.reply_text("ℹ️ Wrong mode or file type. Choose an option from the menu.", reply_markup=main_menu())

@check_access
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = user_data.get(chat_id, get_defaults())
    text = update.message.text.strip()

    # TXT -> VCF flow steps
    if settings.get("mode") == "txt_upload":
        await handle_txt_flow(update, settings, text)
        return

    # Admin / Neavy flows (paste numbers then provide filename and contact options)
    if settings.get("mode") in ("admin_mode", "neavy_mode"):
        await handle_admin_neavy_flow(update, settings, text)
        return

    # VCF -> TXT finalization: user sends desired TXT name
    if settings.get("mode") == "vcf_to_txt" and settings.get("vcf_files") is not None:
        # text is the desired filename (without .txt)
        await finalize_vcf_to_txt(update, settings, text)
        return

    await update.message.reply_text("ℹ️ Choose an option from the menu:", reply_markup=main_menu())

# ====== TXT FLOW ======
``` (file truncated — see next message for remaining part) :contentReference[oaicite:0]{index=0}
