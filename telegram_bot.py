import csv
import logging
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("INVENTORY_TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
CSV_FILE = os.path.join(os.path.dirname(__file__), "inventory.csv")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Инвентарь боты — пайдалану:\n\n"
    "Тауар сатуды жазу:\n"
    "  Розетка 5\n"
    "  Провод 2.5 = 3\n"
    "  Шам LED 20\n\n"
    "/list — Қалдықтар тізімі\n"
    "/help — Нұсқаулық"
)


def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Тауар аты", "Бастапқы қалдық", "Сатылды", "Қалдық", "Соңғы сату"])


def read_inventory() -> dict:
    ensure_csv()
    inventory = {}
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Тауар аты"]
            inventory[name.lower()] = {
                "name": name,
                "initial": float(row["Бастапқы қалдық"] or 0),
                "sold": float(row["Сатылды"] or 0),
                "remaining": float(row["Қалдық"] or 0),
                "last_sale": row["Соңғы сату"],
            }
    return inventory


def write_inventory(inventory: dict):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Тауар аты", "Бастапқы қалдық", "Сатылды", "Қалдық", "Соңғы сату"])
        for item in inventory.values():
            writer.writerow([
                item["name"],
                item["initial"],
                item["sold"],
                item["remaining"],
                item["last_sale"],
            ])


def add_sale(product: str, quantity: float) -> dict:
    inventory = read_inventory()
    key = product.lower()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    if key in inventory:
        item = inventory[key]
        item["sold"] += quantity
        item["remaining"] = item["initial"] - item["sold"]
        item["last_sale"] = now
        is_new = False
    else:
        inventory[key] = {
            "name": product,
            "initial": 0,
            "sold": quantity,
            "remaining": -quantity,
            "last_sale": now,
        }
        is_new = True

    write_inventory(inventory)
    item = inventory[key]
    return {
        "success": True,
        "product": product,
        "sold": quantity,
        "totalSold": item["sold"],
        "remaining": item["remaining"],
        "isNew": is_new,
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
    inventory = read_inventory()

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
    result = add_sale(product, quantity)

    await update.message.reply_text(
        f"Жазылды: {result['product']}\n"
        f"Сатылды: {quantity}\n"
        f"Жалпы сатылды: {result['totalSold']}\n"
        f"Калдык: {result['remaining']}"
    )


def main() -> None:
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("TELEGRAM_TOKEN орнатылмаган!")
        return

    ensure_csv()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
