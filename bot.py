# Let's create a clean full bot.py, requirements.txt, and allowed_users.json
# We'll write simplified but feature-complete code with all required features in one go.

bot_code = r"""
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

# CONFIG
TOKEN = os.getenv("BOT_TOKEN")
MASTER_KEY = "Aryan9936"
BOT_OWNER_ID = 6497509361  # Replace with your Telegram ID
USERS_FILE = "allowed_users.json"
DOWNLOAD_DIR = "downloads"
pathlib.Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

# USER MANAGEMENT
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

# SESSION STORAGE
user_data = {}

def get_defaults():
    return {
        "mode": None,
        "step": None,
        "numbers": [],
        "contacts_per_file": 100,
        "filename_input": None,
        "filename_gen": None,
        "contact_prefix": "Contact",
        "contact_start": 1,
        "vcf_files": []
    }

# ACCESS DECORATOR
def check_access(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if not is_allowed(uid):
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.message.reply_text("❌ Buy premium from @random_0988")
            else:
                await update.message.reply_text("❌ Buy premium from @random_0988")
            return
        return await func(update, context)
    return wrapper

# UTIL
def increment_filename(base_name):
    match = re.search(r'(\d+)', base_name)
    if not match:
        def gen(n): return f"{base_name}{n}.vcf"
        return gen
    num_str = match.group(1)
    prefix = base_name[:match.start(1)]
    suffix = base_name[match.end(1):]
    start = int(num_str)
    def gen(n):
        return f"{prefix}{start+n}{suffix}.vcf"
    return gen

def create_vcf(contact_name, number):
    return f"BEGIN:VCARD\nVERSION:3.0\nFN:{contact_name}\nTEL;TYPE=CELL:{number}\nEND:VCARD\n"

def extract_tel_from_vcf_text(text):
    numbers = []
    for line in text.splitlines():
        m = re.search(r'TEL[^:]*:(.+)$', line, re.IGNORECASE)
        if m:
            numbers.append(m.group(1).strip())
    return numbers

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 TXT ➡️ VCF (Split)", callback_data="txt_mode")],
        [InlineKeyboardButton("🛡️ Admin VCF", callback_data="admin_mode"),
         InlineKeyboardButton("⚓ Neavy VCF", callback_data="neavy_mode")],
        [InlineKeyboardButton("📜 VCF ➡️ TXT", callback_data="vcf_to_txt_mode")]
    ])

# HANDLERS
@check_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data[chat_id] = get_defaults()
    await update.message.reply_text("👋 Welcome! Choose an option:", reply_markup=main_menu())

@check_access
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    settings = user_data.setdefault(chat_id, get_defaults())

    if q.data == "txt_mode":
        settings["mode"] = "txt_upload"
        await q.edit_message_text("📂 Send me a TXT file with numbers.", reply_markup=main_menu())

    elif q.data in ["admin_mode", "neavy_mode"]:
        settings["mode"] = q.data
        settings["step"] = "numbers_input"
        await q.edit_message_text(f"📋 Paste numbers (one per line) for {q.data.split('_')[0].title()} VCF.", reply_markup=main_menu())

    elif q.data == "vcf_to_txt_mode":
        settings["mode"] = "vcf_to_txt"
        settings["vcf_files"] = []
        settings["step"] = "vcf_uploading"
        await q.edit_message_text("📜 Send multiple VCF files now, then send TXT filename (without .txt).", reply_markup=main_menu())

@check_access
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = user_data.setdefault(chat_id, get_defaults())

    if settings["mode"] == "txt_upload":
        doc = update.message.document
        if not doc.file_name.lower().endswith(".txt"):
            await update.message.reply_text("Upload a .txt file.")
            return
        f = await doc.get_file()
        content = (await f.download_as_bytearray()).decode("utf-8", errors="ignore")
        nums = [l.strip() for l in content.splitlines() if l.strip()]
        settings["numbers"] = nums
        settings["step"] = "contacts_per_file"
        await update.message.reply_text(f"✅ Loaded {len(nums)} numbers. Enter contacts per file.")
        return

    if settings["mode"] == "vcf_to_txt":
        doc = update.message.document
        if not doc.file_name.lower().endswith(".vcf"):
            await update.message.reply_text("Upload only .vcf files.")
            return
        f = await doc.get_file()
        path = os.path.join(DOWNLOAD_DIR, doc.file_name)
        await f.download_to_drive(path)
        settings["vcf_files"].append(path)
        await update.message.reply_text(f"✅ Added {doc.file_name}. Send more or send TXT filename.")
        return

    await update.message.reply_text("Choose a mode first.", reply_markup=main_menu())

async def send_vcfs_in_batches(update, settings):
    nums = settings["numbers"]
    contact_num = settings["contact_start"]
    per_file = settings["contacts_per_file"]
    gen = settings["filename_gen"]
    batch = []
    for i in range(0, len(nums), per_file):
        chunk = nums[i:i+per_file]
        vcf_data = "".join(create_vcf(f"{settings['contact_prefix']}{contact_num+j}", n if n.startswith("+") else "+"+n) for j, n in enumerate(chunk))
        filename = gen(i//per_file)
        buf = io.BytesIO(vcf_data.encode("utf-8"))
        buf.name = filename
        batch.append(InputFile(buf, filename=filename))
        contact_num += len(chunk)
        if len(batch) == 10:
            for file in batch: await update.message.reply_document(file)
            batch = []
    if batch:
        for file in batch: await update.message.reply_document(file)
    await update.message.reply_text("✅ Done!", reply_markup=main_menu())

async def finalize_vcf_to_txt(update, settings, filename):
    txt_name = filename + ".txt"
    numbers = []
    for vcf in settings["vcf_files"]:
        with open(vcf, "r", encoding="utf-8") as f:
            numbers.extend(extract_tel_from_vcf_text(f.read()))
    with open(txt_name, "w", encoding="utf-8") as out:
        out.write("\n".join(numbers))
    await update.message.reply_document(document=open(txt_name, "rb"), filename=txt_name)
    settings["vcf_files"] = []

# TEXT HANDLER
@check_access
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = user_data.setdefault(chat_id, get_defaults())
    text = update.message.text.strip()

    if settings["mode"] == "txt_upload":
        if settings["step"] == "contacts_per_file":
            try:
                settings["contacts_per_file"] = int(text)
                settings["step"] = "filename_input"
                await update.message.reply_text("Enter base VCF filename (e.g., H1OK):")
            except:
                await update.message.reply_text("Enter a valid number.")
        elif settings["step"] == "filename_input":
            settings["filename_gen"] = increment_filename(text)
            settings["step"] = "contact_prefix"
            await update.message.reply_text("Enter contact prefix (default Contact):")
        elif settings["step"] == "contact_prefix":
            settings["contact_prefix"] = text or "Contact"
            settings["step"] = "contact_start"
            await update.message.reply_text("Enter starting number for contacts:")
        elif settings["step"] == "contact_start":
            try:
                settings["contact_start"] = int(text)
            except: pass
            preview = "\n".join(settings["numbers"][:5])
            await update.message.reply_text(f"Preview of numbers:\n{preview}")
            await send_vcfs_in_batches(update, settings)

    elif settings["mode"] == "vcf_to_txt" and settings["vcf_files"]:
        await finalize_vcf_to_txt(update, settings, text)

# ADMIN COMMANDS
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /admin <key>")
        return
    if context.args[0] == MASTER_KEY:
        uid = update.effective_user.id
        if uid not in ALLOWED_USERS and uid != BOT_OWNER_ID:
            ALLOWED_USERS.append(uid)
            save_users(ALLOWED_USERS)
        await update.message.reply_text("✅ You are admin now.")
    else:
        await update.message.reply_text("❌ Wrong key.")

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    try:
        uid = int(context.args[0])
        if uid not in ALLOWED_USERS: ALLOWED_USERS.append(uid)
        save_users(ALLOWED_USERS)
        await update.message.reply_text(f"Added {uid}")
    except:
        await update.message.reply_text("Usage: /add <id>")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    try:
        uid = int(context.args[0])
        if uid == BOT_OWNER_ID:
            await update.message.reply_text("😎 BAAP SE PANGA NHI")
            return
        if uid in ALLOWED_USERS:
            ALLOWED_USERS.remove(uid)
            save_users(ALLOWED_USERS)
            await update.message.reply_text(f"Removed {uid}")
        else:
            await update.message.reply_text("Not found.")
    except:
        await update.message.reply_text("Usage: /remove <id>")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    await update.message.reply_text(f"Users: {ALLOWED_USERS}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CommandHandler("remove", remove_user))
    app.add_handler(CommandHandler("list", list_users))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
"""

requirements_txt = "python-telegram-bot==20.3\n"
allowed_users = "[]\n"

# Save files
with open("/mnt/data/bot.py", "w") as f:
    f.write(bot_code)

with open("/mnt/data/requirements.txt", "w") as f:
    f.write(requirements_txt)

with open("/mnt/data/allowed_users.json", "w") as f:
    f.write(allowed_users)

"/mnt/data/bot.py, requirements.txt, allowed_users.json created successfully."

