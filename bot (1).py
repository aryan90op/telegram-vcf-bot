
import os
import io
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN")

# Store per-user data
user_data = {}

def get_defaults():
    return {
        "mode": None,       # txt_upload / admin / neavy
        "step": None,       # current step in flow
        "numbers": [],
        "contacts_per_file": 100,
        "vcf_prefix": "contacts",
        "vcf_start": 1,
        "contact_prefix": "Contact",
        "contact_start": 1,
    }

# ---------------- UI MENUS ----------------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Upload TXT (Split)", callback_data="txt_mode")],
        [InlineKeyboardButton("🛡️ Admin VCF", callback_data="admin_mode"),
         InlineKeyboardButton("⚓ Neavy VCF", callback_data="neavy_mode")]
    ])

# ---------------- COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data[chat_id] = get_defaults()
    await update.message.reply_text(
        "👋 Welcome! I can convert TXT → VCF.\nChoose an option:",
        reply_markup=main_menu()
    )

# ---------------- BUTTONS ----------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    if chat_id not in user_data:
        user_data[chat_id] = get_defaults()
    data = query.data
    settings = user_data[chat_id]

    if data == "txt_mode":
        settings["mode"] = "txt_upload"
        await query.edit_message_text("📂 Send me a TXT file with numbers.", reply_markup=main_menu())

    elif data == "admin_mode":
        settings["mode"] = "admin"
        await query.edit_message_text("🛡️ Paste numbers (one per line) for Admin VCF.", reply_markup=main_menu())

    elif data == "neavy_mode":
        settings["mode"] = "neavy"
        await query.edit_message_text("⚓ Paste numbers (one per line) for Neavy VCF.", reply_markup=main_menu())

# ---------------- HANDLE TXT FILE ----------------
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_data:
        user_data[chat_id] = get_defaults()
    settings = user_data[chat_id]

    if settings["mode"] != "txt_upload":
        await update.message.reply_text("ℹ️ Switch to TXT mode first.", reply_markup=main_menu())
        return

    file = await update.message.document.get_file()
    content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
    numbers = [line.strip() for line in content.splitlines() if line.strip()]
    settings["numbers"] = numbers
    settings["step"] = "contacts_per_file"

    await update.message.reply_text(
        f"✅ TXT uploaded. {len(numbers)} numbers loaded.\n\n"
        "Enter *Contacts per file* (example: 100):",
        parse_mode="Markdown"
    )

# ---------------- HANDLE TEXT INPUT ----------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_data:
        user_data[chat_id] = get_defaults()
    settings = user_data[chat_id]
    text = update.message.text.strip()

    # Flow for TXT Upload
    if settings["mode"] == "txt_upload":
        if settings["step"] == "contacts_per_file":
            if not text.isdigit():
                await update.message.reply_text("❌ Must be a number. Enter Contacts per file:")
                return
            settings["contacts_per_file"] = int(text)
            settings["step"] = "vcf_prefix"
            await update.message.reply_text("Enter VCF file prefix (example: contacts):")
            return

        if settings["step"] == "vcf_prefix":
            settings["vcf_prefix"] = text
            settings["step"] = "vcf_start"
            await update.message.reply_text("Enter VCF starting number (example: 1):")
            return

        if settings["step"] == "vcf_start":
            if not text.isdigit():
                await update.message.reply_text("❌ Must be a number. Enter VCF starting number:")
                return
            settings["vcf_start"] = int(text)
            settings["step"] = "contact_prefix"
            await update.message.reply_text("Enter Contact name prefix (example: Contact):")
            return

        if settings["step"] == "contact_prefix":
            settings["contact_prefix"] = text
            settings["step"] = "contact_start"
            await update.message.reply_text("Enter Contact starting number (example: 1):")
            return

        if settings["step"] == "contact_start":
            if not text.isdigit():
                await update.message.reply_text("❌ Must be a number. Enter Contact starting number:")
                return
            settings["contact_start"] = int(text)
            settings["step"] = None
            await send_vcfs_in_batches(update, settings)
            return

    # Flow for Admin / Neavy
    elif settings["mode"] in ["admin", "neavy"]:
        prefix = "Admin" if settings["mode"] == "admin" else "Neavy"
        numbers = [line.strip() for line in text.splitlines() if line.strip()]
        await send_admin_neavy_files(update, numbers, prefix)
        return

# ---------------- SEND VCF FILES IN BATCHES ----------------
async def send_vcfs_in_batches(update, settings):
    nums = settings["numbers"]
    if not nums:
        await update.message.reply_text("❌ No numbers loaded.")
        return

    contact_num = settings["contact_start"]
    file_num = settings["vcf_start"]
    per_file = settings["contacts_per_file"]
    prefix = settings["vcf_prefix"]

    await update.message.reply_text(f"⚡ Generating {len(nums)} contacts into multiple VCF files...")

    batch = []
    for i in range(0, len(nums), per_file):
        chunk = nums[i:i+per_file]
        vcf_data = ""
        for n in chunk:
            if not n.startswith("+"): n = "+" + n
            vcf_data += f"BEGIN:VCARD\nVERSION:3.0\nFN:{settings['contact_prefix']}{contact_num}\nTEL:{n}\nEND:VCARD\n"
            contact_num += 1

        vcf_buffer = io.BytesIO(vcf_data.encode("utf-8"))
        filename = f"{prefix}{file_num}.vcf"
        vcf_buffer.name = filename
        batch.append(InputFile(vcf_buffer, filename=filename))
        file_num += 1

        # Send batch of 10 files
        if len(batch) >= 10:
            for f in batch:
                await update.message.reply_document(f)
            batch = []

    # Send remaining files
    for f in batch:
        await update.message.reply_document(f)

    await update.message.reply_text("✅ All VCF files sent!", reply_markup=main_menu())

# ---------------- SEND ADMIN/NEAVY FILES ----------------
async def send_admin_neavy_files(update, numbers, prefix):
    txt_buffer = io.BytesIO("\n".join(numbers).encode("utf-8"))
    txt_buffer.name = f"{prefix}.txt"

    vcf_data = ""
    for idx, n in enumerate(numbers, start=1):
        if not n.startswith("+"): n = "+" + n
        vcf_data += f"BEGIN:VCARD\nVERSION:3.0\nFN:{prefix}-{idx}\nTEL:{n}\nEND:VCARD\n"
    vcf_buffer = io.BytesIO(vcf_data.encode("utf-8"))
    vcf_buffer.name = f"{prefix}.vcf"

    await update.message.reply_document(txt_buffer)
    await update.message.reply_document(vcf_buffer)
    await update.message.reply_text(f"✅ {prefix} files ready!", reply_markup=main_menu())

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
