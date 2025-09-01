import os
import logging
import re
import pandas as pd
from tinydb import TinyDB, Query
from telegram import Update, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)

# ================== CONFIG ==================
BOT_TOKEN = "8421126137:AAE3lsRd6DS4lRZ_bqGGGi3uvEDq9vUwkvw"   # << REPLACE THIS
OWNER_ID = 6497509361               # << REPLACE WITH YOUR TELEGRAM ID
ADMIN_KEY = "000000"                # admin entry key
DB_FILE = "db.json"
# ============================================

db = TinyDB(DB_FILE)
Users = Query()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== AUTH ==================
def is_authorized(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    return bool(db.search(Users.id == user_id))

def add_user(user_id: int):
    if not db.search(Users.id == user_id):
        db.insert({"id": user_id})

def remove_user(user_id: int):
    db.remove(Users.id == user_id)

# ================== HELPERS ==================
def sequence_name(prefix: str, start: int, count: int, suffix: str = ""):
    names = []
    for i in range(count):
        names.append(f"{prefix}{start+i}{suffix}")
    return names

def txt_to_vcf(txt_file, prefix="Contact", start_num=1, vcf_prefix="VCF", batch_size=100):
    with open(txt_file, "r", encoding="utf-8") as f:
        numbers = [line.strip() for line in f if line.strip()]
    files = []
    total = len(numbers)
    idx = 0
    file_count = 1
    while idx < total:
        batch = numbers[idx: idx+batch_size]
        vcf_name = f"{vcf_prefix}{file_count}.vcf"
        with open(vcf_name, "w", encoding="utf-8") as vcf:
            for j, num in enumerate(batch, start=0):
                name = f"{prefix}{start_num+j}"
                vcf.write("BEGIN:VCARD\nVERSION:3.0\n")
                vcf.write(f"N:{name};;;\nFN:{name}\n")
                vcf.write(f"TEL;TYPE=CELL:{num}\nEND:VCARD\n")
        files.append(vcf_name)
        idx += batch_size
        file_count += 1
    return files

def vcf_to_txt(vcf_file, out_file="out.txt"):
    with open(vcf_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    numbers = []
    for line in lines:
        if line.startswith("TEL"):
            numbers.append(line.split(":")[-1].strip())
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(numbers))
    return out_file

def merge_files(files, out_file="merged.txt"):
    with open(out_file, "w", encoding="utf-8") as out:
        for file in files:
            with open(file, "r", encoding="utf-8") as f:
                out.write(f.read() + "\n")
    return out_file

def split_file(file_path, lines_per_file=100, prefix="split"):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    files = []
    for i in range(0, len(lines), lines_per_file):
        part = lines[i:i+lines_per_file]
        out_name = f"{prefix}_{i//lines_per_file+1}.txt"
        with open(out_name, "w", encoding="utf-8") as out:
            out.write("\n".join(part))
        files.append(out_name)
    return files

def xlsx_to_vcf(xlsx_file, prefix="XLSContact", start_num=1, vcf_name="out.xlsx.vcf"):
    df = pd.read_excel(xlsx_file)
    numbers = df.iloc[:, 0].dropna().astype(str).tolist()
    with open(vcf_name, "w", encoding="utf-8") as vcf:
        for i, num in enumerate(numbers, start=start_num):
            name = f"{prefix}{i}"
            vcf.write("BEGIN:VCARD\nVERSION:3.0\n")
            vcf.write(f"N:{name};;;\nFN:{name}\n")
            vcf.write(f"TEL;TYPE=CELL:{num}\nEND:VCARD\n")
    return vcf_name

# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /help to see commands.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
📌 Commands:
/admin <key> – Enter admin mode
/adduser <id> – Authorize user
/removeuser <id> – Remove user
/convert_txt – Upload TXT → get VCF
/vcf_to_txt – Upload VCF → get TXT
/merge_txt – Upload multiple TXT → merged
/split_txt – Upload TXT → multiple parts
/merge_vcf – Upload multiple VCF → merged
/split_vcf – Upload VCF → multiple parts
/xlsx_to_vcf – Upload XLSX → VCF
/admin_neavy – Special admin+neavy mode
"""
    await update.message.reply_text(msg)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1 or context.args[0] != ADMIN_KEY:
        return await update.message.reply_text("❌ Invalid admin key.")
    add_user(update.effective_user.id)
    await update.message.reply_text("✅ You are now an admin.")

async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("BAAP SE PANGA NHI 😁")
    if len(context.args) != 1:
        return await update.message.reply_text("Usage: /adduser <id>")
    add_user(int(context.args[0]))
    await update.message.reply_text("✅ User added.")

async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == OWNER_ID:
        if len(context.args) != 1:
            return await update.message.reply_text("Usage: /removeuser <id>")
        remove_user(int(context.args[0]))
        await update.message.reply_text("✅ User removed.")
    else:
        await update.message.reply_text("BAAP SE PANGA NHI 😁")

# ================== FILE HANDLERS ==================
async def handle_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return await update.message.reply_text("🚫 Purchase access from @random_0988")
    doc = await update.message.document.get_file()
    local_file = "input.txt"
    await doc.download_to_drive(local_file)
    vcf_files = txt_to_vcf(local_file, prefix="C", start_num=1, vcf_prefix="OUT", batch_size=50)
    for vf in vcf_files:
        await update.message.reply_document(InputFile(vf))
        os.remove(vf)

async def handle_vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return await update.message.reply_text("🚫 Purchase access from @random_0988")
    doc = await update.message.document.get_file()
    local_file = "input.vcf"
    await doc.download_to_drive(local_file)
    out = vcf_to_txt(local_file)
    await update.message.reply_document(InputFile(out))
    os.remove(out)

async def handle_xlsx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return await update.message.reply_text("🚫 Purchase access from @random_0988")
    doc = await update.message.document.get_file()
    local_file = "input.xlsx"
    await doc.download_to_drive(local_file)
    out = xlsx_to_vcf(local_file)
    await update.message.reply_document(InputFile(out))
    os.remove(out)

async def admin_neavy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔑 Admin+Neavy mode activated (demo).")

# ================== MAIN ==================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("adduser", adduser))
    app.add_handler(CommandHandler("removeuser", removeuser))
    app.add_handler(CommandHandler("admin_neavy", admin_neavy))

    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_txt))
    app.add_handler(MessageHandler(filters.Document.FileExtension("vcf"), handle_vcf))
    app.add_handler(MessageHandler(filters.Document.FileExtension("xlsx"), handle_xlsx))

    app.run_polling()

if __name__ == "__main__":
    main()
         
