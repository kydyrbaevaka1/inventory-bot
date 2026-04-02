import json
import logging
import os
import re
import traceback
from datetime import datetime

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("INVENTORY_TELEGRAM_TOKEN", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1wMmk_PLxhCjx6zljYl-bGcfDv_me-tKX-OWrzK1d0no")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HEADERS = ["Тауар аты", "Бастапқы қалдық", "Сатылды", "Қалдық", "Соңғы сату"]

HELP_TEXT = (
    "Инвентарь боты — пайдалану:\n\n"
    "Тауар сатуды жазу:\n"
    "  Розетка 5\n"
    "  Провод 2.5 = 3\n"
    "  Шам LED 20\n\n"
    "/list — Қалдықтар тізімі\n"
    "/help — Нұсқаулық"
)


def get_sheet():
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    try:
        sheet = spreadsheet.worksheet("Инвентарь")
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="Инвентарь", rows=1000, cols=5)
        sheet.append_row(HEADERS)
    return sheet


def read_inventory(sheet) -> dict:
    rows = sheet.get_all_records(expected_headers=HEADERS)
    inventory = {}
    for row in rows:
        name = row["Тауар аты"]
        if not name:
            continue
        inventory[name.lower()] = {
            "name": name,
            "initial": float(row["Бастапқы қалдық"] or 0),
            "sold": float(row["Сатылды"] or 0),
            "remaining": float(row["Қалдық"] or 0),
            "last_sale": row["Соңғы сату"],
            "row_index": rows.index(row) + 2,  # +2: header row + 1-indexed
        }
    return inventory


def add_sale(product: str, quantity: float) -> dict:
    sheet = get_sheet()
    inventory = read_inventory(sheet)
    key = product.lower()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    if key in inventory:
        item = inventory[key]
        new_sold = item["sold"] + quantity
        new_remaining = item["initial"] - new_sold
        row_idx = item["row_index"]
        # Update columns: C=sold, D=remaining, E=last_sale
        sheet.update_cell(row_idx, 3, new_sold)
        sheet.update_cell(row_idx, 4, new_remaining)
        sheet.update_cell(row_idx, 5, now)
        is_new = False
        return {
            "success": True,
            "product": product,
            "sold": quantity,
            "totalSold": new_sold,
            "remaining": new_remaining,
            "isNew": is_new,
        }
    else:
        new_row = [product, 0, quantity, -quantity, now]
        sheet.append_row(new_row)
        return {
            "success": True,
            "product": product,
            "sold": quantity,
            "totalSold": quantity,
            "remaining": -quantity,
            "isNew": True,
        }


def parse_message(text: str):
    text = text.strip()

    # "Провод 2.5 = 5" форматы
    match = re.match(r"^(.+?)\s*=\s*(\d+(?:\.\d+)?)$", text)
    if match:
        return match.group(1).strip(), float(match.group(2))

    # "Розетка 5" форматы
    match = re.match(r"^(.+?)\s+(\d+(?:\.\d+)?)$", text)
    if match:
        return match.group(1).strip(), float(match.group(2))

    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Инвентарь ботына қош келдіңіз!\n\n"
        "Тауар сатуды жазу:\n"
        "  Розетка 5\n"
        "  Провод 2.5 = 3\n\n"
        "/help — толық нұсқаулық"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        sheet = get_sheet()
        inventory = read_inventory(sheet)
    except Exception as e:
        logger.error("Sheets қатесі: %s\n%s", repr(e), traceback.format_exc())
        await update.message.reply_text("Google Sheets қосылу қатесі.")
        return

    if not inventory:
        await update.message.reply_text("Тізім бос.")
        return

    lines = ["Қалдықтар тізімі:\n"]
    for item in inventory.values():
        lines.append(
            f"{item['name']}: {item['remaining']} қалды "
            f"(сатылды: {item['sold']})"
        )

    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    logger.info("Message: %s", text)

    parsed = parse_message(text)
    if not parsed:
        await update.message.reply_text(
            "Форматты тексерініз:\n  Тауар аты саны\nМысалы: Розетка 5"
        )
        return

    product, quantity = parsed

    try:
        result = add_sale(product, quantity)
    except Exception as e:
        logger.error("Sheets жазу қатесі: %s\n%s", repr(e), traceback.format_exc())
        await update.message.reply_text("Google Sheets жазу қатесі. Кейін қайталаңыз.")
        return

    await update.message.reply_text(
        f"Жазылды: {result['product']}\n"
        f"Сатылды: {quantity}\n"
        f"Жалпы сатылды: {result['totalSold']}\n"
        f"Калдык: {result['remaining']}"
    )


def main() -> None:
    if not TELEGRAM_TOKEN:
        print("INVENTORY_TELEGRAM_TOKEN орнатылмаган!")
        return

    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        print("GOOGLE_SERVICE_ACCOUNT_JSON орнатылмаган!")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
