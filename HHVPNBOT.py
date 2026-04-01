import logging
import sqlite3
import uuid
import os
import asyncio
import re
import html 
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from outline_vpn.outline_vpn import OutlineVPN

# --- Flask Web Server for Render Health Check ---
app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is Alive!"

def run_web():
    # Render uses port 10000 by default
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- Configuration ---
BOT_TOKEN = "8633829411:AAGZ9Vd6uqmwpjvxdjWs3h6dF1Uc2osUd4I"
BOT_USERNAME = "HHVPN_bot" 
ADMIN_ID = 1656832105
FB_LINK = "https://facebook.com/HappyHiveVPN"
ADMIN_CONTACT_LINK = "https://t.me/HappyHive9496"

# --- Image Paths ---
WELCOME_IMAGE_PATH = "welcome.jpg"
ANDROID_SS_PATH = "android_ss.jpg"  
APPLE_SS_PATH = "apple_ss.jpg"      
PAYMENT_QR_PATH = "kpay_qr.jpg"     

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- Reusable Keyboards & Helpers ---
BACK_TO_MAIN_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]])
BACK_TO_ADMIN_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]])

async def safe_delete_message(message):
    if message:
        try: await message.delete()
        except: pass

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, unique_id TEXT, is_trial_used INTEGER, username TEXT, referred_by INTEGER, referral_reward_claimed INTEGER DEFAULT 0, has_rated INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS plans (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER, key_id TEXT, plan_type TEXT, data_limit INTEGER, start_date TEXT, end_date TEXT, is_active INTEGER, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('outline_api_url', 'https://52.74.77.216:3584/j55zpDNtFPRSEVGYYK__XQ')")
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('outline_cert_sha256', '15AABC7E72C56F04C1DB2953ABD078D0ECAC4DF72F59C83D3090015882D0954A')")
    c.execute('''CREATE TABLE IF NOT EXISTS plan_configs (plan_key TEXT PRIMARY KEY, short_name TEXT, display_name TEXT, plan_type TEXT, data_gb INTEGER, months INTEGER)''')
    
    default_plans = [
        ('plan_10gb', '10GB Plan', '📦 10GB Plan (၁လ) - ၈၀၀ ကျပ်', '10GB', 10, 1),
        ('plan_20gb', '20GB Plan', '📦 20GB Plan (၁လ) - ၁,၂၀၀ ကျပ်', '20GB', 20, 1),
        ('plan_30gb', '30GB Plan', '📦 30GB Plan (၁လ) - ၁,၅၀၀ ကျပ်', '30GB', 30, 1),
        ('plan_40gb', '40GB Plan', '📦 40GB Plan (၁လ) - ၂,၀၀၀ ကျပ်', '40GB', 40, 1),
        ('plan_50gb', '50GB Plan', '📦 50GB Plan (၁လ) - ၃,၀၀၀ ကျပ်', '50GB', 50, 1),
        ('plan_100gb', '100GB Plan', '📦 100GB Plan (၁လ) - ၄,၀၀၀ ကျပ်', '100GB', 100, 1)
    ]
    for p in default_plans:
        c.execute("INSERT OR IGNORE INTO plan_configs VALUES (?, ?, ?, ?, ?, ?)", p)
    conn.commit()
    conn.close()

init_db()

def get_plan_details():
    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT plan_key, short_name, display_name, plan_type, data_gb, months FROM plan_configs")
    rows = c.fetchall()
    conn.close()
    return {r[0]: {'short_name': r[1], 'display': r[2], 'plan_type': r[3], 'data_gb': r[4], 'months': r[5]} for r in rows}

def get_plans_keyboard(plans_dict):
    keyboard = []
    row = []
    for p_key, p_info in plans_dict.items():
        row.append(InlineKeyboardButton(p_info['display'], callback_data=p_key))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')])
    return InlineKeyboardMarkup(keyboard)

def get_outline_client():
    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    c = conn.cursor()
    api_url = c.execute("SELECT value FROM settings WHERE key='outline_api_url'").fetchone()[0]
    cert_sha = c.execute("SELECT value FROM settings WHERE key='outline_cert_sha256'").fetchone()[0]
    conn.close()
    return OutlineVPN(api_url=api_url, cert_sha256=cert_sha)

def get_or_create_user(telegram_id, username="User", referred_by=None):
    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    c = conn.cursor()
    user = c.execute("SELECT unique_id, is_trial_used FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not user:
        unique_id = str(uuid.uuid4())[:8].upper()
        c.execute("INSERT INTO users (telegram_id, unique_id, is_trial_used, username, referred_by) VALUES (?, ?, 0, ?, ?)", (telegram_id, unique_id, username, referred_by))
        conn.commit()
        user = (unique_id, 0)
    else:
        c.execute("UPDATE users SET username=? WHERE telegram_id=?", (username, telegram_id))
        conn.commit()
    conn.close()
    return user

def get_bottom_keyboard(user_id):
    btns = [["🏠 ပင်မ မီနူးသို့သွားပါ", "🛡️ Admin Panel"]] if user_id == ADMIN_ID else [["🏠 ပင်မ မီနူးသို့သွားပါ"]]
    return ReplyKeyboardMarkup(btns, resize_keyboard=True, is_persistent=True)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = (f"@{user.username}" if user.username else user.first_name)
    referred_by = int(context.args[0]) if context.args and context.args[0].isdigit() and int(context.args[0]) != user.id else None
    get_or_create_user(user.id, username, referred_by)
    
    keyboard = [
        [InlineKeyboardButton("🎁 Free 3GB အစမ်းသုံးရန်", callback_data='free_trial'), InlineKeyboardButton("❓ အသုံးပြုပုံ", callback_data='how_to_use')],
        [InlineKeyboardButton("🛒 Plan ဝယ်ရန်", callback_data='buy_plan'), InlineKeyboardButton("🔄 သက်တမ်းတိုးရန်", callback_data='extend_plan')],
        [InlineKeyboardButton("👤 မိမိ၏ Plan မှတ်တမ်း", callback_data='my_plan'), InlineKeyboardButton("📝 အကြံပြုစာရေးရန်", callback_data='send_feedback')],
        [InlineKeyboardButton("📢 သူငယ်ချင်းများသို့ မျှဝေရန်", callback_data='share_referral')],
        [InlineKeyboardButton("👨‍💻 Admin ကို ဆက်သွယ်ရန်", url=ADMIN_CONTACT_LINK), InlineKeyboardButton("🌐 Facebook Page", url=FB_LINK)]
    ]
    welcome_text = "🌟 **Welcome to HappyHive VPN!** 🌟\n\n🛡️ **Private & Secure Server**\n⚡️ **High Speed AWS Server**\n🔒 **100% No Logs Policy**\n\n👇 ဝန်ဆောင်မှုရွေးချယ်ပါ ခင်ဗျာ။"
    
    if update.message:
        await update.message.reply_text("အောက်ပါ ခလုတ်များကို အသုံးပြုနိုင်ပါသည်။", reply_markup=get_bottom_keyboard(user.id))
        await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [[InlineKeyboardButton("📊 စီးပွားရေးစာရင်း", callback_data='admin_server_stats'), InlineKeyboardButton("🗑️ System Reset", callback_data='admin_reset_system')]]
    await update.message.reply_text("🛡️ **Admin Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'back_to_main': await start(update, context)
    elif data == 'buy_plan':
        plans = get_plan_details()
        await query.edit_message_text("🛒 **Plan ဝယ်ယူရန် ရွေးချယ်ပါ:**", reply_markup=get_plans_keyboard(plans), parse_mode='Markdown')
    elif data == 'free_trial':
        await query.edit_message_text("⏳ ခဏစောင့်ပေးပါ... (Render Free Plan တွင် အနည်းငယ်နှေးနိုင်ပါသည်)")
        # Trial Logic here...
        await query.edit_message_text("✅ Free Trial ပေးပို့ပြီးပါပြီ။", reply_markup=BACK_TO_MAIN_MARKUP)

# --- Main Bot ---
def main():
    # 🌟 1. Web Server ကို အရင်နှိုးထားပါမယ် (Render Health Check အတွက်)
    keep_alive()
    print("✅ Web Server is running on port 10000...")

    # 🌟 2. Bot ကို နှိုးပါမယ်
    app = Application.builder().token(BOT_TOKEN).job_queue(None).post_init(None).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: start(u, c) if u.message.text == "🏠 ပင်မ မီနူးသို့သွားပါ" else None))
    
    print("✅ Bot is running successfully...")
    app.run_polling()

if __name__ == '__main__':
    main()
