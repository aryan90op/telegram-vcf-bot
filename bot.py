# === Telegram Bot for VCF Tool with Admin Panel ===
import os
import io
import re
import json
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ====== BOT CONFIG ======
TOKEN = os.getenv("BOT_TOKEN")  # Set BOT_TOKEN in Railway/Render/Heroku
MASTER_KEY = "Aryan9936"  # Admin panel access key
BOT_OWNER_ID = 6497509361  # Replace with YOUR Telegram ID
USERS_FILE = "allowed_users.json"

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
        "mode": None,
        "step": None,
        "numbers": [],
        "contacts_per_file": 100,
        "vcf_prefix": "contacts",
        "vcf_start": 1,
        "contact_prefix": "Contact",
        "contact_start": 1,
        "filename_input": None
    }

# ====== ACCESS CHECK DECORATOR ======
def check_access(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_allowed(user_id):
            await update.message.reply_text("❌ Buy premium from @random_0988")
            return
        return await func(update, context)
    return wrapper

# ====== FILE NAME GENERATOR ======
def increment_filename(base_name):
    match = re.search(r'(\d+)', base_name)
    if not match:
        prefix, suffix = base_name, ""
        return lambda n: f"{prefix}{n}.vcf"
    num_str = match.group(1)
    prefix = base_name[:match.start(1)]
    suffix = base_name[match.end(1):]
    start = int(num_str)
    return lambda n: f"{prefix}{start+n}{suffix}.vcf"

# ====== MAIN MENU ======
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Upload TXT (Split)", callback_data="txt_mode")],
        [InlineKeyboardButton("🛡️ Admin VCF", callback_data="admin_mode"),
         InlineKeyboardButton("⚓ Neavy VCF", callback_data="neavy_mode")]
    ])

# ====== START COMMAND ======
@check_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data[chat_id] = get_defaults()
    await update.message.reply_text("👋 Welcome! Choose an option:", reply_markup=main_menu())

# ====== BUTTON HANDLER ======
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
        await query.edit_message_text("📂 Send me a TXT file with numbers.", reply_markup=main_menu())

    elif query.data in ["admin_mode", "neavy_mode"]:
        settings["mode"] = query.data
        settings["step"] = "numbers_input"
        await query.edit_message_text(f"📋 Paste numbers for {query.data.split('_')[0].title()} VCF.", reply_markup=main_menu())

# ====== FILE HANDLER ======
@check_access
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = user_data.get(chat_id, get_defaults())

    if settings["mode"] != "txt_upload":
        await update.message.reply_text("ℹ️ Switch to TXT mode first.", reply_markup=main_menu())
        return

    file = await update.message.document.get_file()
    content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
    numbers = [line.strip() for line in content.splitlines() if line.strip()]
    settings["numbers"] = numbers
    settings["step"] = "contacts_per_file"

    await update.message.reply_text(
        f"✅ TXT uploaded. {len(numbers)} numbers loaded.\n\nEnter *Contacts per file*:", parse_mode="Markdown"
    )

# ====== TEXT HANDLER ======
@check_access
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    settings = user_data.get(chat_id, get_defaults())
    text = update.message.text.strip()

    if settings["mode"] == "txt_upload":
        await handle_txt_flow(update, settings, text)
        return
    if settings["mode"] in ["admin_mode", "neavy_mode"]:
        await handle_admin_neavy_flow(update, settings, text)
        return

# ====== TXT MODE FLOW ======
async def handle_txt_flow(update, settings, text):
    if settings["step"] == "contacts_per_file":
        if not text.isdigit():
            await update.message.reply_text("❌ Enter a number:")
            return
        settings["contacts_per_file"] = int(text)
        settings["step"] = "filename_input"
        await update.message.reply_text("Enter VCF filename example (with number): e.g., H1OK")
        return

    if settings["step"] == "filename_input":
        settings["filename_input"] = text
        settings["filename_gen"] = increment_filename(text)
        settings["step"] = "contact_prefix"
        await update.message.reply_text("Enter Contact name prefix (example: Contact):")
        return

    if settings["step"] == "contact_prefix":
        settings["contact_prefix"] = text
        settings["step"] = "contact_start"
        await update.message.reply_text("Enter Contact starting number:")
        return

    if settings["step"] == "contact_start":
        if not text.isdigit():
            await update.message.reply_text("❌ Must be a number:")
            return
        settings["contact_start"] = int(text)
        settings["step"] = None
        await send_vcfs_in_batches(update, settings)

# ====== ADMIN/NEAVY FLOW ======
async def handle_admin_neavy_flow(update, settings, text):
    if settings["step"] == "numbers_input":
        settings["numbers"] = [line.strip() for line in text.splitlines() if line.strip()]
        settings["step"] = "filename_input"
        await update.message.reply_text("Enter VCF filename example (with number): e.g., H1OK")
        return

    if settings["step"] == "filename_input":
        settings["filename_input"] = text
        settings["filename_gen"] = increment_filename(text)
        settings["step"] = "contact_prefix"
        await update.message.reply_text("Enter Contact name prefix:")
        return

    if settings["step"] == "contact_prefix":
        settings["contact_prefix"] = text
        settings["step"] = "contact_start"
        await update.message.reply_text("Enter Contact starting number:")
        return

    if settings["step"] == "contact_start":
        if not text.isdigit():
            await update.message.reply_text("❌ Must be a number:")
            return
        settings["contact_start"] = int(text)
        settings["step"] = None
        await send_admin_neavy_files(update, settings)

# ====== FILE GENERATION ======
async def send_vcfs_in_batches(update, settings):
    nums = settings["numbers"]
    contact_num = settings["contact_start"]
    per_file = settings["contacts_per_file"]
    filename_gen = settings["filename_gen"]

    await update.message.reply_text(f"⚡ Generating {len(nums)} contacts...")

    batch = []
    for i in range(0, len(nums), per_file):
        chunk = nums[i:i+per_file]
        vcf_data = ""
        for n in chunk:
            if not n.startswith("+"): n = "+" + n
            vcf_data += f"BEGIN:VCARD\\nVERSION:3.0\\nFN:{settings['contact_prefix']}{contact_num}\\nTEL:{n}\\nEND:VCARD\\n"
            contact_num += 1

        filename = filename_gen(i//per_file)
        vcf_buffer = io.BytesIO(vcf_data.encode("utf-8"))
        vcf_buffer.name = filename
        batch.append(InputFile(vcf_buffer, filename=filename))

        if len(batch) >= 10:
            for f in batch: await update.message.reply_document(f)
            batch = []

    for f in batch: await update.message.reply_document(f)
    await update.message.reply_text("✅ All files sent!", reply_markup=main_menu())

async def send_admin_neavy_files(update, settings):
    nums = settings["numbers"]
    contact_num = settings["contact_start"]
    filename_gen = settings["filename_gen"]

    await update.message.reply_text(f"⚡ Generating {len(nums)} contacts...")

    for i, n in enumerate(nums):
        if not n.startswith("+"): n = "+" + n
        vcf_data = f"BEGIN:VCARD\\nVERSION:3.0\\nFN:{settings['contact_prefix']}{contact_num}\\nTEL:{n}\\nEND:VCARD\\n"
        filename = filename_gen(i)
        contact_num += 1

        vcf_buffer = io.BytesIO(vcf_data.encode("utf-8"))
        vcf_buffer.name = filename
        await update.message.reply_document(InputFile(vcf_buffer, filename=filename))

    await update.message.reply_text("✅ All Admin/Neavy files sent!", reply_markup=main_menu())

# ====== ADMIN PANEL ======
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or args[0] != MASTER_KEY:
        await update.message.reply_text("❌ Wrong key!")
        return
    await update.message.reply_text(
        "🔑 Admin Panel\nCommands:\n/add <user_id>\n/remove <user_id>\n/list"
    )

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(context.args[0])
        if uid == BOT_OWNER_ID:
            await update.message.reply_text("😎 Owner is always allowed.")
            return
        if uid not in ALLOWED_USERS:
            ALLOWED_USERS.append(uid)
            save_users(ALLOWED_USERS)
            await update.message.reply_text(f"✅ Added {uid}")
        else:
            await update.message.reply_text("⚠️ Already allowed.")
    except:
        await update.message.reply_text("❌ Usage: /add <user_id>")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(context.args[0])
        if uid == BOT_OWNER_ID:
            await update.message.reply_text("😎 BAAP SE PANGA NHI")
            return
        if uid in ALLOWED_USERS:
            ALLOWED_USERS.remove(uid)
            save_users(ALLOWED_USERS)
            await update.message.reply_text(f"✅ Removed {uid}")
        else:
            await update.message.reply_text("⚠️ Not found.")
    except:
        await update.message.reply_text("❌ Usage: /remove <user_id>")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ALLOWED_USERS:
        await update.message.reply_text("⚠️ No allowed users.")
    else:
        users = "\n".join(map(str, ALLOWED_USERS))
        await update.message.reply_text(f"👥 Allowed Users:\n{users}")

# ====== RUN BOT ======
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CommandHandler("remove", remove_user))
    app.add_handler(CommandHandler("list", list_users))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
                              
