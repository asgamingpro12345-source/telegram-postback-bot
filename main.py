import logging
import asyncio
import random
import os

import requests
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ───── CONFIG ─────
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")

BASE_URL = "https://clipfun.fun/api/version_15"
API_KEY = "5cc8ff22bab10bd31294056f536e5598"

# ───── STATES KEYS IN user_data ─────
GMAIL_KEY = "gmail"
USER_ID_KEY = "clipfun_user_id"
COINS_KEY = "coins"

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ───── CLIPFUN HTTP HELPERS (SYNC, RUN IN THREAD) ─────
def post_form(path: str, data: dict):
    url = f"{BASE_URL}/{path}"
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "okhttp/4.10.0",
    }
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=20)
        print(f"[{path}] -> {data} | Status: {resp.status_code}")
    except Exception as e:
        return {"error": str(e)}

    try:
        result = resp.json()
        print(f"[{path}] Response: {result}")
        return result
    except ValueError:
        return {"http_status": resp.status_code, "raw": resp.text}


async def post_form_async(path: str, data: dict):
    # Run blocking requests.post in a separate thread so it does not block the bot loop.[web:81][web:85]
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, post_form, path, data)


async def clipfun_login_get_user_id(email: str) -> str | None:
    """
    Call login_with_google exactly like your Flask /login.
    Returns user_id string or None.[web:85]
    """
    login_data = {
        "google_id": "MpLauhNqECMbcu6r7QKCYxe53P22",
        "name": email.split("@")[0],
        "email": email,
        "image": "https://lh3.googleusercontent.com/a/ACg8ocJM9xjfpA69tYJccsiLSvUblSyuwfc5HU99l-z-8bpAx9cYUA=s96-c",
        "firebase_token": "eRhj98w6QP-6s724QwpbVw:APA91bGMuyElFpHLe8IgwB5lls-GozNQfoy_dijpJyKZ682GbjMbGhCKVPxTfXDaJ3SPyVEvs7dg95R-VCX9xe17h528zXlq_5mJ2ddgtj9vtaHr5XUHros",
        "referrer_url": "utm_source=google-play&utm_medium=organic",
    }
    login_res = await post_form_async("login_with_google", login_data)
    user_id = None
    if isinstance(login_res, dict) and login_res.get("statuscode") == 1 and login_res.get("user_id"):
        user_id = str(login_res["user_id"])
        # same as Flask: call setting after login
        settings_data = {"android_id": "e66820c13ec20987", "user_id": user_id}
        await post_form_async("setting", settings_data)
    return user_id


async def clipfun_add_coin(user_id: str, video_id: str):
    """
    Same as Flask /add-coins loop but for ONE request:
    POST Add_Coin {user_id, video_id}.
    """
    data = {"user_id": user_id, "video_id": video_id}
    return await post_form_async("Add_Coin", data)


# ───── TELEGRAM UI HELPERS ─────
def main_menu_keyboard():
    buttons = [
        [InlineKeyboardButton("Show Info / Menu", callback_data="menu")],
        [InlineKeyboardButton("Set / Change Gmail", callback_data="set_gmail")],
        [InlineKeyboardButton("Start Video Watch", callback_data="start_watch")],
    ]
    return InlineKeyboardMarkup(buttons)


# ───── HANDLERS ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Welcome to ClipFun Auto Watch Bot.\n\n"
        "Before using, please join these channels:\n"
        "- Apple Cash Earning: https://t.me/applecashearning\n"
        "- Cash Feed: https://t.me/cash_feed\n\n"
        "Then use /menu."
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_menu(update.effective_chat.id, context)


async def send_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    gmail = user_data.get(GMAIL_KEY, "Not set")
    coins = user_data.get(COINS_KEY, 0)

    text = (
        "Your Panel\n\n"
        f"Gmail: {gmail}\n"
        f"Coins (local counter): {coins}\n\n"
        "Use the buttons below:"
    )
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=main_menu_keyboard())


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "menu":
        await send_menu(chat_id, context)

    elif data == "set_gmail":
        context.user_data["awaiting_gmail"] = True
        await query.message.reply_text(
            "Send your Gmail address (example: yourname@gmail.com)."
        )

    elif data == "start_watch":
        gmail = context.user_data.get(GMAIL_KEY)
        if not gmail:
            await query.message.reply_text(
                "You have not set any Gmail yet.\nClick \"Set / Change Gmail\" first."
            )
            return
        context.user_data["awaiting_video_count"] = True
        await query.message.reply_text(
            "How many videos to watch? (example: 100)\n"
            "Bot will call Add_Coin that many times."
        )


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user_data = context.user_data
    chat_id = update.effective_chat.id

    # Step 1: expecting Gmail
    if user_data.get("awaiting_gmail"):
        if "@gmail.com" not in text:
            await update.message.reply_text(
                "Please send a valid Gmail address (must contain @gmail.com)."
            )
            return

        user_data[GMAIL_KEY] = text
        user_data["awaiting_gmail"] = False
        user_data[COINS_KEY] = user_data.get(COINS_KEY, 0)
        user_data[USER_ID_KEY] = None  # reset ClipFun user id

        await update.message.reply_text(
            f"Gmail saved: {text}\nUse the menu to start watching videos.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Step 2: expecting video count (Times)
    if user_data.get("awaiting_video_count"):
        if not text.isdigit():
            await update.message.reply_text("Send only a number (e.g. 100).")
            return
        total_videos = int(text)
        if total_videos <= 0:
            await update.message.reply_text("Number must be greater than 0.")
            return

        user_data["awaiting_video_count"] = False
        await update.message.reply_text(
            f"Starting Add_Coin for {total_videos} times.\n"
            "You will receive updates at 20%, 40%, 60%, 80% and 100%."
        )

        # start background task
        asyncio.create_task(
            video_watch_job(
                chat_id=chat_id,
                context=context,
                total_videos=total_videos,
            )
        )
        return

    # If no special state, show menu
    await send_menu(chat_id, context)


async def video_watch_job(chat_id: int, context: ContextTypes.DEFAULT_TYPE, total_videos: int):
    user_data = context.user_data
    gmail = user_data.get(GMAIL_KEY)
    if not gmail:
        await context.bot.send_message(chat_id, "No Gmail set. Please set Gmail first.")
        return

    # 1) Login to ClipFun and get real user_id (like Flask /login)
    if not user_data.get(USER_ID_KEY):
        await context.bot.send_message(chat_id, "Logging in to ClipFun with your Gmail...")
        user_id = await clipfun_login_get_user_id(gmail)
        if not user_id:
            await context.bot.send_message(
                chat_id,
                "Login failed. Please check Gmail or try again later.",
            )
            return
        user_data[USER_ID_KEY] = user_id
    else:
        user_id = user_data[USER_ID_KEY]

    # same as Flask add-coins form: user_id + video_id + times
    video_id = "15028"  # same default as your HTML form
    done = 0
    coins_per_video = 1  # local counter only
    milestones = [0.2, 0.4, 0.6, 0.8, 1.0]
    sent_milestones = set()

    await context.bot.send_message(
        chat_id,
        f"Started Add_Coin for {total_videos} times for Gmail: {gmail} (user_id: {user_id}).",
    )

    for i in range(total_videos):
        try:
            result = await clipfun_add_coin(user_id, video_id)
            # if API returns error, stop early
            if isinstance(result, dict) and result.get("statuscode") not in (None, 1):
                await context.bot.send_message(
                    chat_id,
                    f"Server returned error on Add_Coin: {result}\nStopped at {done}/{total_videos}.",
                )
                return
        except Exception as e:
            logger.exception("Error calling Add_Coin: %s", e)
            await context.bot.send_message(
                chat_id,
                f"Error while calling Add_Coin: {e}\nStopped at {done}/{total_videos}.",
            )
            return

        done += 1
        user_data[COINS_KEY] = user_data.get(COINS_KEY, 0) + coins_per_video

        progress = done / total_videos
        for m in milestones:
            if progress >= m and m not in sent_milestones:
                sent_milestones.add(m)
                percent = int(m * 100)
                await context.bot.send_message(
                    chat_id,
                    f"{percent}% completed ({done}/{total_videos} Add_Coin calls).",
                )

        # mimic Flask: small delay between requests
        await asyncio.sleep(1.0)  # similar to time.sleep(1) in your Flask loop

    await context.bot.send_message(
        chat_id,
        f"All done! 100% completed ({done}/{total_videos} Add_Coin calls).",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Usage:\n"
        "1) Use /start or /menu.\n"
        "2) Set / Change Gmail (same as ClipFun email).\n"
        "3) Click \"Start Video Watch\" and enter how many videos.\n"
        "Bot logs in to ClipFun and calls Add_Coin that many times."
    )
    await update.message.reply_text(text)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
