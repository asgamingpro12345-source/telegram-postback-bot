import logging
import httpx
import json
import os
from urllib.parse import urlparse, parse_qs
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import asyncio
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set. Please add your Telegram bot token to the Secrets.")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

IST = timezone(timedelta(hours=5, minutes=30))
batch_counter = 0

def get_ist_time():
    return datetime.now(IST).strftime("%H:%M:%S")

def build_postback_url(click_id):
    return (
        f"https://unstop.gotrackier.io/pixel?"
        f"av=685bf90ea7dc8107e3090882"
        f"&utmd=Affiliates"
        f"&utmc=trackier_11"
        f"&__v=6.3&s=websdk"
        f"&click_id={click_id}"
    )

async def fire_single_postback(chat_id, context, click_id, delay_minutes, mode_info=""):
    await asyncio.sleep(delay_minutes * 60)
    
    postback_url = build_postback_url(click_id)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(postback_url, timeout=30.0)
        
        if response.status_code == 200:
            fire_time = get_ist_time()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Success! {mode_info}\nFired: {fire_time} IST\nClick_id: {click_id}"
            )
    except Exception as e:
        logging.error(f"Postback failed for click_id {click_id}: {str(e)}")

async def process_single_id_queue(chat_id, context, links):
    for index, (click_id, receive_time) in enumerate(links):
        delay = (index + 1) * 5
        asyncio.create_task(fire_single_postback(chat_id, context, click_id, delay, f"(Link {index + 1})"))

async def process_batch_queue(chat_id, context, batch_num, links, submit_time):
    for index, click_id in enumerate(links):
        delay = (index + 1) * 5
        asyncio.create_task(fire_single_postback(chat_id, context, click_id, delay, f"(Batch {batch_num}, Link {index + 1})"))

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("single id"), KeyboardButton("submit")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Welcome to Postback Bot!\n\nChoose a mode:\n"
        "🔵 single id - Sequential firing (5, 10, 15 min...)\n"
        "📦 submit - Batch mode (collect & submit)\n"
        "Or just send links for instant 5-min postbacks!",
        reply_markup=reply_markup
    )

async def command1_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['mode'] = 'single_id'
    context.user_data['single_id_links'] = []
    context.user_data['single_id_start_time'] = None
    await update.message.reply_text("🔵 Single ID mode activated!\nSend links one by one. They will fire at 5-min intervals:\n1st link: 5 min\n2nd link: 10 min\n3rd link: 15 min\n...")

async def command2_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global batch_counter
    
    if context.user_data.get('mode') == 'batch' and context.user_data.get('current_batch_links'):
        links = context.user_data['current_batch_links']
        batch_counter += 1
        batch_num = batch_counter
        submit_time = get_ist_time()
        
        asyncio.create_task(process_batch_queue(update.effective_chat.id, context, batch_num, links, submit_time))
        
        await update.message.reply_text(
            f"📦 Batch {batch_num} submitted at {submit_time} IST!\n"
            f"Total links: {len(links)}\n"
            f"Postbacks will fire at 5-min intervals starting in 5 minutes."
        )
        
        context.user_data['current_batch_links'] = []
    else:
        context.user_data['mode'] = 'batch'
        context.user_data['current_batch_links'] = []
        await update.message.reply_text("📦 Batch mode activated!\nSend links, then use /command2 again to submit the batch.")

async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "single id":
        await command1_handler(update, context)
        return
    elif text == "submit":
        await command2_handler(update, context)
        return
    
    receive_time = get_ist_time()
    current_timestamp = datetime.now(IST)

    try:
        parsed_url = urlparse(text)
        query = parse_qs(parsed_url.query)
        click_ids = query.get("click_id", [])
        if not click_ids:
            await update.message.reply_text("No click_id found in your link.")
            return
        click_id = click_ids[0]
    except Exception as e:
        await update.message.reply_text(f"Error parsing link: {str(e)}")
        return

    mode = context.user_data.get('mode', 'default')
    
    if mode == 'single_id':
        if context.user_data.get('single_id_start_time') is None:
            context.user_data['single_id_start_time'] = current_timestamp
        
        context.user_data['single_id_links'].append((click_id, receive_time))
        link_num = len(context.user_data['single_id_links'])
        
        start_time = context.user_data['single_id_start_time']
        target_fire_time = start_time + timedelta(minutes=link_num * 5)
        delay_seconds = (target_fire_time - current_timestamp).total_seconds()
        delay_minutes = max(delay_seconds / 60, 0)
        
        await update.message.reply_text(
            f"✅ Link {link_num} received at {receive_time} IST\n"
            f"Will fire in {int(delay_minutes)} minutes"
        )
        
        asyncio.create_task(fire_single_postback(update.effective_chat.id, context, click_id, delay_minutes, f"(Link {link_num})"))
        
    elif mode == 'batch':
        context.user_data['current_batch_links'].append(click_id)
        link_num = len(context.user_data['current_batch_links'])
        
        await update.message.reply_text(
            f"📦 Link {link_num} added to current batch\n"
            f"Click_id: {click_id}\n"
            f"Use 'submit' button to submit batch"
        )
    
    else:
        await update.message.reply_text(
            f"✅ Link received at {receive_time} IST!\nWill fire postback in 5 minutes.\nTracking click_id: {click_id}"
        )
        asyncio.create_task(fire_single_postback(update.effective_chat.id, context, click_id, 5, ""))

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("command1", command1_handler))
    app.add_handler(CommandHandler("command2", command2_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link_handler))
    print("Bot running...")
    app.run_polling()
