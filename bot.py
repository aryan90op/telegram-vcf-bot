
import os
import io
import zipfile
import tempfile
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN")

# User-specific settings and state
user_data = {}

def get_defaults():
    return {
        "contacts_per_file": 100,
        "vcf_prefix": "contacts",
        "vcf_start": 1,
        "contact_prefix": "Contact",
        "contact_start": 1,
        "mode": None,
        "waiting_for": None,
        "numbers": []
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data[chat_id] = get_defaults()
    await update.message.reply_text(
        "👋 Welcome! I can convert TXT → VCF.\nChoose an option:",
        reply_markup=main_menu()
    )

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Upload TXT (Split)", callback_data="txt_mode")],
        [InlineKeyboardButton("🛡️ Admin VCF", callback_data="admin_mode"),
         InlineKeyboardButton("⚓ Neavy VCF", callback_data="neavy_mode")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ])

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

    elif data == "settings":
        await query.edit_message_text(settings_text(settings), reply_markup=settings_menu())

    elif data.startswith("set_"):
        key = data.replace("set_", "")
        settings["waiting_for"] = key
        await query.edit_message_text(f"✏️ Send me new value for `{key}`", parse_mode="Markdown")

    elif data == "preview_vcf":
        await preview_vcf(chat_id, update)

    elif data == "generate_vcf":
        await generate_vcfs(chat_id, update)

def settings_text(s):
    return (
        f"⚙️ Current Settings:\n"
        f"- Contacts per file: {s['contacts_per_file']}\n"
        f"- VCF prefix: {s['vcf_prefix']}\n"
        f"- VCF start: {s['vcf_start']}\n"
        f"- Contact prefix: {s['contact_prefix']}\n"
        f"- Contact start: {s['contact_start']}\n"
        "\nTap a button below to change:"
    )

def settings_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Contacts per File", callback_data="set_contacts_per_file")],
        [InlineKeyboardButton("VCF Prefix", callback_data="set_vcf_prefix")],
        [InlineKeyboardButton("VCF Start", callback_data="set_vcf_start")],
        [InlineKeyboardButton("Contact Prefix", callback_data="set_contact_prefix")],
        [InlineKeyboardButton("Contact Start", callback_data="set_contact_start")],
        [InlineKeyboardButton("⬅️ Back", callback_data="txt_mode")]
    ])

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

    preview = "\n".join(numbers[:50])
    await update.message.reply_text(
        f"✅ TXT uploaded. {len(numbers)} numbers loaded.\n\nPreview:\n```\n{preview}\n```",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👁 Preview VCF", callback_data="preview_vcf")],
            [InlineKeyboardButton("⚡ Generate VCFs", callback_data="generate_vcf")],
            [InlineKeyboardButton("⬅️ Back", callback_data="txt_mode")]
        ])
    )

async def preview_vcf(chat_id, update):
    settings = user_data[chat_id]
    nums = settings["numbers"][:min(10, len(settings["numbers"]))]
    vcf_preview = ""
    cnum = settings["contact_start"]
    for n in nums:
        if not n.startswith("+"): n = "+"+n
        vcf_preview += f"BEGIN:VCARD\nVERSION:3.0\nFN:{settings['contact_prefix']}{cnum}\nTEL:{n}\nEND:VCARD\n"
        cnum += 1
    await update.callback_query.edit_message_text(
        f"👁 VCF Preview:\n```\n{vcf_preview}\n```",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Generate VCFs", callback_data="generate_vcf")],
            [InlineKeyboardButton("⬅️ Back", callback_data="txt_mode")]
        ])
    )

async def generate_vcfs(chat_id, update):
    settings = user_data[chat_id]
    nums = settings["numbers"]
    if not nums:
        await update.callback_query.edit_message_text("❌ No numbers loaded. Upload TXT first.")
        return

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        contact_num = settings["contact_start"]
        file_num = settings["vcf_start"]
        for i in range(0, len(nums), settings["contacts_per_file"]):
            chunk = nums[i:i+settings["contacts_per_file"]]
            vcf_data = ""
            for n in chunk:
                if not n.startswith("+"): n = "+"+n
                vcf_data += f"BEGIN:VCARD\nVERSION:3.0\nFN:{settings['contact_prefix']}{contact_num}\nTEL:{n}\nEND:VCARD\n"
                contact_num += 1
            fname = f"{settings['vcf_prefix']}{file_num}.vcf"
            zf.writestr(fname, vcf_data)
            file_num += 1

    zip_buffer.seek(0)
    await update.callback_query.message.reply_document(
        InputFile(zip_buffer, filename=f"{settings['vcf_prefix']}_all.zip"),
        caption="✅ All VCF files ready!"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_data:
        user_data[chat_id] = get_defaults()
    settings = user_data[chat_id]

    if settings["waiting_for"]:
        key = settings["waiting_for"]
        value = update.message.text.strip()
        if key in ["contacts_per_file","vcf_start","contact_start"] and not value.isdigit():
            await update.message.reply_text("❌ Must be a number.")
        else:
            settings[key] = int(value) if value.isdigit() else value
            await update.message.reply_text(f"✅ {key} set to {value}", reply_markup=main_menu())
        settings["waiting_for"] = None
        return

    if settings["mode"] not in ["admin", "neavy"]:
        return

    prefix = "Admin" if settings["mode"]=="admin" else "Neavy"
    numbers = [line.strip() for line in update.message.text.splitlines() if line.strip()]

    txt_buffer = io.BytesIO("\n".join(numbers).encode("utf-8"))
    vcf_data = ""
    for idx, n in enumerate(numbers, start=1):
        if not n.startswith("+"): n = "+"+n
        vcf_data += f"BEGIN:VCARD\nVERSION:3.0\nFN:{prefix}-{idx}\nTEL:{n}\nEND:VCARD\n"
    vcf_buffer = io.BytesIO(vcf_data.encode("utf-8"))

    await update.message.reply_document(InputFile(txt_buffer, filename=f"{prefix}.txt"))
    await update.message.reply_document(InputFile(vcf_buffer, filename=f"{prefix}.vcf"))

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
