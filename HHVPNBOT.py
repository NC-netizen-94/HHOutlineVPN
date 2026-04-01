import logging
import sqlite3
import uuid
import os
import asyncio
import re
import html 
from datetime import datetime, timedelta, time
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from outline_vpn.outline_vpn import OutlineVPN

# --- Flask Web Server for Render Health Check ---
app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is Alive!"

def run_web():
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
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# --- Reusable Keyboards & Helpers ---
BACK_TO_MAIN_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]])
BACK_TO_ADMIN_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]])

async def safe_delete_message(message):
    if message:
        try: await message.delete()
        except: pass

async def send_auto_backup(context: ContextTypes.DEFAULT_TYPE, target_id: int, target_uname: str, action_text: str):
    try:
        if os.path.exists('happyhive.db'):
            with open('happyhive.db', 'rb') as db_file:
                caption = f"📦 <b>Auto Backup</b>\n{get_mention(target_id, target_uname)} သို့ {action_text}ပြီးနောက် သိမ်းဆည်းထားသော အချက်အလက်များ။"
                await context.bot.send_document(ADMIN_ID, db_file, caption=caption, parse_mode='HTML')
    except Exception as e:
        logging.error(f"Backup failed: {e}")

# --- USERNAME & MENTION HELPERS ---
def get_user_display_name(user):
    if user.username: return f"@{user.username}"
    elif user.first_name: return user.first_name
    return "User"

def get_mention(user_id, name):
    if not name: name = "User"
    return f'<a href="tg://user?id={user_id}">{html.escape(str(name))}</a>'

def outline_safe_name(text):
    if not text: return "User"
    cleaned = re.sub(r'[^a-zA-Z0-9_]', '', str(text).replace(" ", "_"))
    return cleaned if cleaned else "User"

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
    # 🌟 ဖုန်းစခရင်တွင် စာလုံးအဆုံးထိပေါ်စေရန် တစ်တန်းလျှင် ခလုတ် (၁) ခုသာ ထားပါသည် 🌟
    for p_key, p_info in plans_dict.items():
        keyboard.append([InlineKeyboardButton(p_info['display'], callback_data=p_key)])
        
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
        c.execute("INSERT INTO users (telegram_id, unique_id, is_trial_used, username, referred_by, referral_reward_claimed) VALUES (?, ?, 0, ?, ?, 0)", (telegram_id, unique_id, username, referred_by))
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

def generate_vpn_key(telegram_id, plan_type, data_gb=None, months=None):
    client = get_outline_client()
    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    c = conn.cursor()
    row = c.execute("SELECT unique_id, username FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    unique_id, raw_username = row[0], row[1] if row[1] else "User"
    
    safe_username = outline_safe_name(raw_username)
    new_key = client.create_key()
    
    start_date = datetime.now()
    db_start_date = start_date.strftime("%Y-%m-%d %H:%M:%S")
    end_date = start_date + timedelta(days=5) if plan_type == "FreeTrial" else (start_date + timedelta(days=30 * months) if months else None)
    db_end_date = end_date.strftime("%Y-%m-%d %H:%M:%S") if end_date else None
    
    suffix = f"HHVPN_{telegram_id}_{safe_username}_{unique_id}_{plan_type}_{start_date.strftime('%Y-%m-%d')}" + (f"_{end_date.strftime('%Y-%m-%d')}" if end_date else "")
    client.rename_key(new_key.key_id, suffix)
    
    data_bytes = data_gb * 1e9 if data_gb else None
    if data_bytes: client.add_data_limit(new_key.key_id, int(data_bytes))
    
    c.execute('''INSERT INTO plans (telegram_id, key_id, plan_type, data_limit, start_date, end_date, is_active, username) VALUES (?, ?, ?, ?, ?, ?, 1, ?)''', (telegram_id, new_key.key_id, plan_type, data_bytes, db_start_date, db_end_date, raw_username))
    conn.commit()
    conn.close()
    
    return f"{new_key.access_url.split('#')[0]}#{suffix}", suffix

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('state', None)
    user = update.effective_user
    username = get_user_display_name(user)
    
    referred_by = None
    if getattr(context, 'args', None):
        try:
            referred_by = int(context.args[0])
            if referred_by == user.id: referred_by = None
        except ValueError: pass
        
    get_or_create_user(user.id, username, referred_by)
    
    keyboard = [
        [InlineKeyboardButton("🎁 Free 3GB အစမ်းသုံးရန်", callback_data='free_trial'), InlineKeyboardButton("❓ အသုံးပြုပုံ", callback_data='how_to_use')],
        [InlineKeyboardButton("🛒 Plan ဝယ်ရန်", callback_data='buy_plan'), InlineKeyboardButton("🔄 သက်တမ်းတိုးရန်", callback_data='extend_plan')],
        [InlineKeyboardButton("👤 မိမိ၏ Plan/ Data မှတ်တမ်း", callback_data='my_plan'), InlineKeyboardButton("📝 အကြံပြုစာရေးရန်", callback_data='send_feedback')],
        [InlineKeyboardButton("📢 သူငယ်ချင်းများသို့ မျှဝေရန်", callback_data='share_referral')],
        [InlineKeyboardButton("👨‍💻 Admin ကို ဆက်သွယ်ရန်", url=ADMIN_CONTACT_LINK), InlineKeyboardButton("🌐 Facebook Page", url=FB_LINK)]
    ]
    
    welcome_text = (
        "🌟 **Welcome to HappyHive VPN!** 🌟\n\n"
        "🚀 **ဘာလို့ HappyHive ကို ရွေးချယ်သင့်တာလဲ?**\n"
        "🛡️ **Private & Secure:** လူထောင်ချီသုံးနေတဲ့ အခမဲ့ VPN တွေလို မဟုတ်ဘဲ၊ သီးသန့် Private Server ကို အသုံးပြုထားလို့ လိုင်းကျတာ၊ ချိတ်မရတာ လုံးဝမရှိပါဘူး။\n"
        "⚡️ **High Speed:** ကမ္ဘာ့အကောင်းဆုံး AWS Server များဖြစ်လို့ ရုပ်ရှင်ကြည့်၊ ဂိမ်းဆော့၊ ဒေါင်းလုဒ်ဆွဲ... အထစ်အငေါ့မရှိ အမြန်နှုန်း အပြည့်ရပါမယ်။\n"
        "🔒 **100% Safe:** လူကြီးမင်း၏ ကိုယ်ရေးအချက်အလက်များကို လုံးဝ မှတ်သားထားခြင်း (No Logs) မရှိလို့ ယုံကြည်စိတ်ချစွာ အသုံးပြုနိုင်ပါတယ်။\n\n"
        "👇 အောက်ပါ Menu များမှတဆင့် မိမိအသုံးပြုလိုသော ဝန်ဆောင်မှုကို ရွေးချယ်ပါ ခင်ဗျာ。"
    )
    
    chat_id = update.effective_chat.id
    if update.message and update.message.text.startswith('/start'):
        await update.message.reply_text("👇 အောက်ပါ ခလုတ်များကိုလည်း အလွယ်တကူ အသုံးပြုနိုင်ပါသည်။", reply_markup=get_bottom_keyboard(user.id))
        if os.path.exists(WELCOME_IMAGE_PATH):
            try:
                with open(WELCOME_IMAGE_PATH, 'rb') as f: await context.bot.send_photo(chat_id=chat_id, photo=f)
            except Exception as e: logging.error(e)
        await context.bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        if update.callback_query and update.callback_query.message.photo:
            await safe_delete_message(update.callback_query.message)
            await context.bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        elif update.callback_query:
            try: await update.callback_query.edit_message_text(text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            except: await context.bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [
        [InlineKeyboardButton("👥 View Users Plans", callback_data='admin_view_users'), InlineKeyboardButton("⚠️ Expiring Soon", callback_data='admin_expiring')],
        [InlineKeyboardButton("➕ Manual Key ထုတ်ရန်", callback_data='admin_manual_key'), InlineKeyboardButton("📝 Plan အမည်များ ပြင်ရန်", callback_data='admin_edit_plans')],
        [InlineKeyboardButton("📊 စီးပွားရေးနှင့် Server အခြေအနေ", callback_data='admin_server_stats'), InlineKeyboardButton("🗑️ စနစ်တစ်ခုလုံး Reset ချရန်", callback_data='admin_reset_system')],
        [InlineKeyboardButton("⚙️ Change API", callback_data='admin_change_api'), InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast')]
    ]
    msg = "🛡️ **Admin Panel ရောက်ပါပြီ။**"
    if update.message: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    elif update.callback_query:
        await safe_delete_message(update.callback_query.message)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    state = context.user_data.get('state')
    
    if text == "🏠 ပင်မ မီနူးသို့သွားပါ":
        context.user_data.pop('state', None)
        return await start(update, context)
    elif text == "🛡️ Admin Panel":
        context.user_data.pop('state', None)
        return await admin_panel(update, context)
        
    if state == 'waiting_for_feedback':
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"💌 <b>New Anonymous Feedback</b> 💌\n\n💬 Message:\n{html.escape(text)}", parse_mode='HTML')
        del context.user_data['state']
        await update.message.reply_text("✅ ကျေးဇူးတင်ပါသည်။ လူကြီးမင်း၏ အကြံပြုစာကို Admin ထံသို့ လျှို့ဝှက်ပေးပို့ပြီးပါပြီ။", reply_markup=BACK_TO_MAIN_MARKUP)

    elif state == 'waiting_for_manual_key' and update.effective_user.id == ADMIN_ID:
        if "|" not in text or len(text.split("|")) != 3: return await update.message.reply_text("❌ Format မှားယွင်းနေပါသည်။ `ID | Name | Plan` ပုံစံဖြင့် ရိုက်ထည့်ပါ။", parse_mode='Markdown')
        tid_str, uname, pkey = map(str.strip, text.split('|', 2))
        try: target_id = int(tid_str)
        except ValueError: return await update.message.reply_text("❌ Telegram ID (သို့) ဖုန်းနံပါတ်သည် ဂဏန်းသက်သက်သာ ဖြစ်ရပါမည်။")
            
        plan_info = get_plan_details().get(pkey)
        if not plan_info: return await update.message.reply_text("❌ Plan အမည် မှားယွင်းနေပါသည်။", parse_mode='Markdown')
            
        del context.user_data['state']
        await update.message.reply_text("⏳ Manual Key ဖန်တီးနေပါသည်... ခဏစောင့်ပါ။")
        get_or_create_user(target_id, uname)
        
        try:
            access_url, key_name = generate_vpn_key(target_id, plan_info['plan_type'], plan_info['data_gb'], plan_info['months'])
            await update.message.reply_text(f"✅ **Manual Key အောင်မြင်စွာ ထုတ်ပေးလိုက်ပါပြီ။**\n\n👤 Name: `{key_name}`\n🔑 Access Key:\n`{access_url}`", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')
            try:
                await context.bot.send_message(chat_id=target_id, text=f"🎉 **Admin မှ လူကြီးမင်း၏ VPN Plan ကို အတည်ပြုပေးလိုက်ပါပြီ။**\n\n👤 **Name:** `{key_name}`\n\n👇", parse_mode='Markdown')
                await context.bot.send_message(chat_id=target_id, text=f"`{access_url}`", parse_mode='Markdown')
            except: pass
            await send_auto_backup(context, target_id, uname, "Plan (Manual) ချပေး")
        except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

    elif state and state.startswith('waiting_for_plan_name_') and update.effective_user.id == ADMIN_ID:
        plan_key = state.replace('waiting_for_plan_name_', '')
        if "|" not in text: return await update.message.reply_text("❌ Format မှားယွင်းနေပါသည်။ `Short Name | Display Name` ပုံစံဖြင့် ရိုက်ထည့်ပါ။", parse_mode='Markdown')
        short_name, display_name = map(str.strip, text.split('|', 1))
        
        conn = sqlite3.connect('happyhive.db', check_same_thread=False)
        conn.cursor().execute("UPDATE plan_configs SET short_name=?, display_name=? WHERE plan_key=?", (short_name, display_name, plan_key))
        conn.commit()
        conn.close()
        
        del context.user_data['state']
        await update.message.reply_text(f"✅ Plan အမည်ကို အောင်မြင်စွာ ပြောင်းလဲလိုက်ပါပြီ။\n\n🔹 **Short:** `{short_name}`\n🔹 **Display:** `{display_name}`", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif state == 'waiting_for_broadcast' and update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("⏳ Broadcast စတင်ပေးပို့နေပါသည်... ခဏစောင့်ပါ။")
        conn = sqlite3.connect('happyhive.db', check_same_thread=False)
        all_users = conn.cursor().execute("SELECT DISTINCT telegram_id FROM users").fetchall()
        conn.close()
        
        success, failed = 0, 0
        for uid in all_users:
            try:
                await context.bot.send_message(chat_id=uid[0], text=f"📢 **Admin မှ အသိပေးချက်**\n\n{text}", parse_mode='Markdown')
                success += 1
                await asyncio.sleep(0.05) 
            except: failed += 1
                
        del context.user_data['state']
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"✅ **Broadcast ပေးပို့ခြင်း ပြီးဆုံးပါပြီ။**\n\n🟢 အောင်မြင်: `{success}` ဦး\n🔴 မအောင်မြင်: `{failed}` ဦး", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

async def delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 1: return await update.message.reply_text("❌ အသုံးပြုပုံ မှားယွင်းနေပါသည်။\nဥပမာ - `/deluser 123456789`", parse_mode='Markdown')
    try: target_id = int(context.args[0])
    except ValueError: return await update.message.reply_text("❌ User ID သည် ဂဏန်းသာ ဖြစ်ရပါမည်။")

    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    c = conn.cursor()
    user_plans = c.execute("SELECT key_id FROM plans WHERE telegram_id=?", (target_id,)).fetchall()

    if user_plans:
        try:
            client = get_outline_client()
            for p in user_plans:
                try: client.delete_key(p[0])
                except: pass
        except: pass

    c.execute("DELETE FROM plans WHERE telegram_id=?", (target_id,))
    c.execute("DELETE FROM users WHERE telegram_id=?", (target_id,))
    changes = conn.total_changes
    conn.commit()
    conn.close()

    if changes > 0: await update.message.reply_text(f"✅ User ID `{target_id}` အား ဖျက်ပစ်လိုက်ပါပြီ။", parse_mode='Markdown')
    else: await update.message.reply_text(f"⚠️ User ID `{target_id}` ကို မတွေ့ပါ။", parse_mode='Markdown')

async def set_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 2: return await update.message.reply_text("❌ အသုံးပြုပုံ မှားယွင်းနေပါသည်။ ဥပမာ - `/setapi API_URL CERT_SHA256`", parse_mode='Markdown')
    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    conn.cursor().execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('outline_api_url', ?)", (context.args[0],))
    conn.cursor().execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('outline_cert_sha256', ?)", (context.args[1],))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Outline API ပြောင်းလဲခြင်း အောင်မြင်ပါသည်။")

async def send_rating_request(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    kb = [[InlineKeyboardButton("⭐", callback_data='rate_1'), InlineKeyboardButton("⭐⭐", callback_data='rate_2'), InlineKeyboardButton("⭐⭐⭐", callback_data='rate_3')],
          [InlineKeyboardButton("⭐⭐⭐⭐", callback_data='rate_4'), InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data='rate_5')]]
    try: await context.bot.send_message(chat_id=user_id, text="🌟 **HappyHive VPN ကို အသုံးပြုရတာ အဆင်ပြေရဲ့လား ခင်ဗျာ?**\n\nလူကြီးမင်း၏ အတွေ့အကြုံကို အောက်ပါ ကြယ်လေးတွေနှိပ်ပြီး အမှတ်ပေး အကဲဖြတ်ပေးပါဦး ခင်ဗျာ。", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    except: pass

async def send_htu_guide(query, context, os_type):
    user_id = query.from_user.id
    await safe_delete_message(query.message)
    if os_type == 'android': text, img_path, url = "🤖 **Android ဖုန်းများအတွက် အသုံးပြုပုံ**\n\nအောက်ပါပုံတွင် ကြည့်ရှုနိုင်ပါသည်။", ANDROID_SS_PATH, "https://play.google.com/store/apps/details?id=org.outline.android.client&hl=en_SG"
    else: text, img_path, url = "🍎 **Apple (iOS) ဖုန်းများအတွက် အသုံးပြုပုံ**\n\nအောက်ပါပုံတွင် ကြည့်ရှုနိုင်ပါသည်။", APPLE_SS_PATH, "https://apps.apple.com/us/app/outline-app/id1356177741"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Outline App Download ဆွဲရန်", url=url)], [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]])
    await context.bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
    if os.path.exists(img_path):
        with open(img_path, 'rb') as f: await context.bot.send_photo(chat_id=user_id, photo=f, caption="App ကို Download ဆွဲယူရန် အောက်ပါ Menu ကိုနှိပ်ပါ။ 👇", reply_markup=markup, parse_mode='Markdown')
    else: await context.bot.send_message(chat_id=user_id, text="App ကို Download ဆွဲယူရန် အောက်ပါ Menu ကိုနှိပ်ပါ။ 👇", reply_markup=markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = get_user_display_name(query.from_user)
    get_or_create_user(user_id, username)
    data = query.data
    plans_dict = get_plan_details()

    if data == 'back_to_admin':
        context.user_data.pop('state', None)
        await safe_delete_message(query.message)
        return await admin_panel(update, context)
        
    elif data == 'back_to_main':
        context.user_data.pop('state', None)
        await safe_delete_message(query.message)
        return await start(update, context)

    elif data == 'share_referral':
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        share_url = f"https://t.me/share/url?url={ref_link}&text=🌟 မြန်နှုန်းမြင့်ပြီး လုံခြုံစိတ်ချရတဲ့ HappyHive VPN ကို အသုံးပြုကြည့်ဖို့ ဖိတ်ခေါ်ပါတယ် ခင်ဗျာ။ အောက်ပါလင့်ခ်မှတဆင့် ဝင်ရောက်ပါ 👇"
        msg = (
            "🎁 **Referral အစီအစဉ် (1GB လက်ဆောင်ယူရန်)**\n\n"
            "မိမိ၏ မျှဝေရန်လင့်ခ်မှတဆင့် သူငယ်ချင်းများကို ဖိတ်ခေါ်ပါ။\n\n"
            "⚠️ *(သတိပြုရန်: ဖိတ်ခေါ်ခံရသော သူငယ်ချင်းမှ VPN Plan တစ်ခုခုကို အမှန်တကယ် ဝယ်ယူပြီးစီးမှသာလျှင် လူကြီးမင်းအတွက် Data 1GB ကို အလိုအလျောက် ပေါင်းထည့်ပေးမည် ဖြစ်ပါသည်။)*"
        )
        kb = [[InlineKeyboardButton("📤 ယခုပဲ မျှဝေရန်", url=share_url)], [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == 'admin_reset_system':
        msg = "⚠️ **သတိပေးချက် (System Reset)** ⚠️\n\nယခုလုပ်ဆောင်ချက်သည် စမ်းသပ်ထားသော User များ၊ Plan များ၊ ငွေကြေးမှတ်တမ်းများအားလုံးကို Database မှ အပြီးတိုင် ဖျက်ပစ်မည်ဖြစ်ပြီး၊ Outline Server ပေါ်ရှိ သက်ဆိုင်ရာ Key များကိုပါ ဖျက်ပစ်မည် ဖြစ်ပါသည်။\n\n**တကယ် Reset ချမှာ သေချာပြီလား?**"
        kb = [[InlineKeyboardButton("✅ သေချာပါသည် (Reset All)", callback_data='confirm_reset_all')], [InlineKeyboardButton("❌ မလုပ်တော့ပါ (Cancel)", callback_data='back_to_admin')]]
        await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == 'confirm_reset_all':
        await query.edit_message_text("⏳ စနစ်တစ်ခုလုံးကို ရှင်းလင်းနေပါသည်... ခဏစောင့်ပါ။")
        try:
            conn = sqlite3.connect('happyhive.db', check_same_thread=False)
            c = conn.cursor()
            all_keys = c.execute("SELECT key_id FROM plans").fetchall()
            if all_keys:
                client = get_outline_client()
                for kid in all_keys:
                    try: client.delete_key(kid[0])
                    except: pass
            c.execute("DELETE FROM plans")
            c.execute("DELETE FROM users")
            try: c.execute("DELETE FROM sqlite_sequence WHERE name IN ('plans', 'users')")
            except: pass
            conn.commit()
            conn.close()
            await query.edit_message_text("✅ **စနစ်တစ်ခုလုံးကို အောင်မြင်စွာ Reset ချလိုက်ပါပြီ။**", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')
        except Exception as e: await query.edit_message_text(f"❌ Error ဖြစ်နေပါသည်: {e}", reply_markup=BACK_TO_ADMIN_MARKUP)

    elif data == 'admin_manual_key':
        context.user_data['state'] = 'waiting_for_manual_key'
        plan_list = "\n".join([f"▪️ `{k}` - {v['short_name']}" for k, v in plans_dict.items()])
        msg = f"🔑 **Manual Key ထုတ်ရန်**\n\nအောက်ပါအတိုင်း `|` ခံ၍ ရိုက်ထည့်ပါ။\n`Telegram ID | User Name | Plan Key`\n\n📌 ဥပမာ - `09123456789 | Kyaw Kyaw | plan_50gb`\n\n📋 **ရရှိနိုင်သော Plans:**\n{plan_list}"
        await query.edit_message_text(text=msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'admin_server_stats':
        await query.edit_message_text(text="⏳ ငွေကြေးနှင့် Server Data များကို တွက်ချက်နေပါသည်...")
        try:
            conn = sqlite3.connect('happyhive.db', check_same_thread=False)
            all_plans = conn.cursor().execute("SELECT plan_type, start_date FROM plans WHERE start_date IS NOT NULL AND plan_type != 'FreeTrial'").fetchall()
            active_plans = conn.cursor().execute("SELECT data_limit FROM plans WHERE is_active=1 AND plan_type != 'FreeTrial'").fetchall()
            conn.close()
            
            PLAN_PRICES = {'10GB': 800, '20GB': 1200, '30GB': 1500, '40GB': 2000, '50GB': 3000, '100GB': 4000}
            now = datetime.now()
            current_m, current_y, current_m_num = now.strftime("%Y-%m"), now.strftime("%Y"), now.month
            
            monthly_rev = sum(PLAN_PRICES.get(p[0], 0) for p in all_plans if p[1].startswith(current_m))
            yearly_rev = sum(PLAN_PRICES.get(p[0], 0) for p in all_plans if p[1].startswith(current_y))
            monthly_profit, yearly_profit = monthly_rev - 25000, yearly_rev - (25000 * current_m_num)
            
            def get_status(p): return f"🟢 မြတ် (<b>+{p:,}</b>)" if p > 0 else (f"⚪️ အရင်းကြေ (<b>0</b>)" if p == 0 else f"🔴 ရှုံး (<b>{p:,}</b>)")
            
            client = get_outline_client()
            keys = client.get_keys()
            total_used_gb = sum((getattr(k, 'used_bytes', 0) or 0) for k in keys) / 1e9
            total_allocated_gb = sum(d[0]/1e9 for d in active_plans if d[0])
            
            srv_status = "🔴 <b>DANGER:</b> Server အသစ် အမြန်ဝယ်ရန် လိုအပ်နေပါပြီ။" if total_used_gb >= 900 else ("🟡 <b>WARNING:</b> မကြာမီ Server အသစ်ဝယ်ရန် ပြင်ဆင်ထားပါ။" if total_allocated_gb >= 1500 and total_used_gb >= 700 else "🟢 <b>NORMAL:</b> Server အခြေအနေ ကောင်းမွန်ပါသေးသည်။")
            
            msg = (
                f"📊 <b>စီးပွားရေးနှင့် Server အခြေအနေ (Stats)</b>\n\n"
                f"📅 <b>ယခုလစာရင်း ({now.strftime('%B')}):</b>\n▪️ လစဉ် အရင်း: <code>25,000 ကျပ်</code>\n▪️ ယခုလ ဝင်ငွေ: <code>{monthly_rev:,} ကျပ်</code>\n▪️ အခြေအနေ: {get_status(monthly_profit)} ကျပ်\n\n"
                f"📆 <b>ယခုနှစ်စာရင်း (YTD):</b>\n▪️ နှစ်စဉ် အရင်း: <code>{25000 * current_m_num:,} ကျပ်</code>\n▪️ ယခုနှစ် ဝင်ငွေ: <code>{yearly_rev:,} ကျပ်</code>\n▪️ အခြေအနေ: {get_status(yearly_profit)} ကျပ်\n\n"
                f"💽 <b>Server Data အခြေအနေ:</b>\n▪️ Active Keys: <code>{len(keys)} ခု</code>\n▪️ ရောင်းချထားသော Data: <code>{total_allocated_gb:.2f} GB</code>\n▪️ အမှန်တကယ် သုံးစွဲမှု: <code>{total_used_gb:.2f} GB</code> / 1000 GB\n\n💡 <b>အကြံပြုချက်:</b>\n{srv_status}"
            )
            await query.edit_message_text(text=msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='HTML')
        except Exception as e: await query.edit_message_text(text=f"❌ Error: {e}", reply_markup=BACK_TO_ADMIN_MARKUP)

    elif data == 'admin_edit_plans':
        kb = [[InlineKeyboardButton(p_info['short_name'], callback_data=f"editplan_{p_key}")] for p_key, p_info in plans_dict.items()]
        kb.append([InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')])
        await query.edit_message_text("📝 **နာမည်ပြောင်းလိုသော Plan ကို ရွေးချယ်ပါ:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        
    elif data.startswith('editplan_'):
        plan_key = data.replace('editplan_', '')
        context.user_data['state'] = f'waiting_for_plan_name_{plan_key}'
        msg = f"✏️ ရွေးချယ်ထားသော Plan: `{plans_dict.get(plan_key, {}).get('short_name', plan_key)}`\n\n**Plan အမည်သစ်ကို | ခံ၍ ရိုက်ထည့်ပါ။**\n`Short Name | Display Name`"
        await query.edit_message_text(msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'admin_view_users':
        await query.edit_message_text("⏳ Data များကို ဆွဲယူနေပါသည်...")
        conn = sqlite3.connect('happyhive.db', check_same_thread=False)
        users_data = conn.cursor().execute("SELECT u.telegram_id, u.username, p.plan_type, p.end_date, p.key_id, p.data_limit FROM plans p JOIN users u ON p.telegram_id = u.telegram_id WHERE p.is_active=1").fetchall()
        conn.close()
        if not users_data: return await query.edit_message_text("လက်ရှိ Active ဖြစ်နေသော User မရှိသေးပါ။", reply_markup=BACK_TO_ADMIN_MARKUP)
        try: all_keys = get_outline_client().get_keys()
        except Exception as e: return await query.edit_message_text(f"❌ Server Error: {e}", reply_markup=BACK_TO_ADMIN_MARKUP)
            
        msg = "👥 <b>Active Users List</b>\n\n"
        for tid, uname, ptype, edate, kid, dlimit in users_data:
            matched_key = next((k for k in all_keys if str(k.key_id) == str(kid)), None)
            final_url = f"{matched_key.access_url.split('#')[0]}#{matched_key.name or f'Key_{kid}'}" if matched_key else "Not Found"
            used_gb = ((getattr(matched_key, 'used_bytes', 0) or 0) / 1e9) if matched_key else 0
            if dlimit:
                limit_gb = dlimit / 1e9
                rem_gb = max(0, limit_gb - used_gb)
                data_info = f"📊 Data: <code>{used_gb:.2f}GB / {limit_gb:.2f}GB</code> (လက်ကျန်: <code>{rem_gb:.2f}GB</code>)"
            else:
                data_info = f"📊 သုံးထားသော Data: <code>{used_gb:.2f}GB</code> (အကန့်အသတ်မရှိ)"
            msg += f"👤 {get_mention(tid, uname)} (<code>{tid}</code>)\n📦 Plan: <code>{ptype}</code>\n⏳ Exp: <code>{edate or 'No Expiry'}</code>\n{data_info}\n🔑 Key: <code>{final_url}</code>\n---\n"
        if len(msg) > 4000: msg = msg[:4000] + "\n... (စာရင်းများလွန်းသဖြင့် အချို့ကို ဖြတ်ထားပါသည်)"
        await query.edit_message_text(text=msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='HTML')

    elif data == 'admin_expiring':
        conn = sqlite3.connect('happyhive.db', check_same_thread=False)
        warn_dt = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        exp_data = conn.cursor().execute("SELECT u.telegram_id, u.username, p.plan_type, p.end_date FROM plans p JOIN users u ON p.telegram_id = u.telegram_id WHERE p.is_active=1 AND p.end_date IS NOT NULL AND p.end_date <= ?", (warn_dt,)).fetchall()
        conn.close()
        if not exp_data: return await query.edit_message_text("✅ သုံးရက်အတွင်း သက်တမ်းကုန်မည့် User မရှိပါ။", reply_markup=BACK_TO_ADMIN_MARKUP)
        msg = "⚠️ <b>၃ ရက်အတွင်း သက်တမ်းကုန်မည့် Users များ</b>\n\n"
        for tid, uname, ptype, edate in exp_data: msg += f"👤 {get_mention(tid, uname)} (<code>{tid}</code>)\n📦 Plan: <code>{ptype}</code>\n⏳ Exp: <code>{edate}</code>\n---\n"
        await query.edit_message_text(text=msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='HTML')

    elif data == 'admin_change_api':
        await query.edit_message_text("⚙️ **Outline API အသစ် ပြောင်းလဲရန်**\n\n`/setapi YOUR_API_URL YOUR_CERT_SHA256` ဟု ရိုက်ထည့်ပါ။", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'admin_broadcast':
        context.user_data['state'] = 'waiting_for_broadcast'
        await query.edit_message_text("📢 **အသိပေးစာ (Broadcast) ပေးပို့ရန်**\n\nပေးပို့လိုသော စာသားကို အောက်တွင် ရိုက်ထည့်ပါ။", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'how_to_use':
        kb = [[InlineKeyboardButton("🤖 Android", callback_data='htu_android'), InlineKeyboardButton("🍎 Apple (iOS)", callback_data='htu_apple')], [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        await query.edit_message_text("📱 **မိမိအသုံးပြုမည့် ဖုန်းအမျိုးအစားကို ရွေးချယ်ပါ:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data in ('htu_android', 'htu_apple'): await send_htu_guide(query, context, 'android' if data == 'htu_android' else 'apple')

    elif data == 'send_feedback':
        context.user_data['state'] = 'waiting_for_feedback'
        await safe_delete_message(query.message)
        await context.bot.send_message(user_id, "📝 **အကြံပြုစာရေးရန်**\n\nအကြံပြုချက်များကို အောက်တွင် စာရိုက်၍ ပေးပို့နိုင်ပါသည်။", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
        
    elif data.startswith('rate_'):
        rating = data.split('_')[1]
        await query.edit_message_text(f"💖 ကြယ် ({rating}) ပွင့် ပေးတဲ့အတွက် အထူးကျေးဇူးတင်ပါတယ် ခင်ဗျာ!", parse_mode='Markdown')
        await context.bot.send_message(ADMIN_ID, f"🌟 <b>New Rating!</b>\n\n👤 User: {get_mention(user_id, username)}\n⭐️ Rating: <b>{rating} Stars</b>", parse_mode='HTML')

    elif data == 'free_trial':
        conn = sqlite3.connect('happyhive.db', check_same_thread=False)
        is_used = conn.cursor().execute("SELECT is_trial_used FROM users WHERE telegram_id=?", (user_id,)).fetchone()[0]
        if is_used == 1: await query.edit_message_text("⚠️ Free Trial ကို အသုံးပြုပြီးဖြစ်ပါသည်။ Plan ဝယ်ယူရန်အတွက် Menuသို့ပြန်သွားပါ", reply_markup=BACK_TO_MAIN_MARKUP)
        else:
            await query.edit_message_text("⏳ Free Trial Key ကို ဖန်တီးနေပါသည်...")
            try:
                url, name = generate_vpn_key(user_id, "FreeTrial", data_gb=3)
                conn.cursor().execute("UPDATE users SET is_trial_used=1 WHERE telegram_id=?", (user_id,))
                conn.commit()
                await safe_delete_message(query.message)
                await context.bot.send_message(user_id, f"✅ **Free Trial 3GB ရရှိပါပြီ။**\n⏱ **(၅) ရက်တိတိ အသုံးပြုနိုင်ပါသည်။**\n\n👤 **Name:** `{name}` 👇", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
                await context.bot.send_message(user_id, f"`{url}`", parse_mode='Markdown')
            except Exception as e: await query.edit_message_text(f"❌ Error: {e}")
        conn.close()

    elif data in ('buy_plan', 'extend_plan'):
        action_type = 'extend' if data == 'extend_plan' else 'buy'
        context.user_data['action_type'] = action_type
        
        # 🌟 Plan ဈေးနှုန်းများကို Message Text တွင် ရှင်းလင်းစွာ ဖော်ပြရန် 🌟
        price_list_text = ""
        for k, v in plans_dict.items():
            price_list_text += f"▪️ {v['display']}\n"
            
        if action_type == 'buy':
            msg = f"🛒 **ဝယ်ယူလိုသော Plan ကို ရွေးချယ်ပါ:**\n\n{price_list_text}\n✅ **100% Full Speed:** ဝယ်ယူထားသော Data မကုန်မချင်း အမြန်နှုန်း အပြည့်ဖြင့် အသုံးပြုနိုင်ပါသည်။\n✅ **Smart Top-up:** သက်တမ်းမကုန်ခင် ထပ်ဝယ်ပါက Data အဟောင်းများ မပျောက်ဘဲ အလိုအလျောက် ထပ်ပေါင်းပေးမည် ဖြစ်ပါသည်။"
        else: 
            msg = f"🔄 **သက်တမ်းတိုးရန် (သို့) Data ထပ်ဝယ်ရန် Plan ရွေးပါ:**\n\n{price_list_text}\n*(မှတ်ချက် - ယခုအသုံးပြုနေသော Key ထဲသို့သာ Data နှင့် သက်တမ်း ပေါင်းထည့်ပေးမည်ဖြစ်ပါသည်။)*"
            
        await query.edit_message_text(text=msg, reply_markup=get_plans_keyboard(plans_dict), parse_mode='Markdown')
        
    elif data == 'my_plan':
        await query.edit_message_text("⏳ အချက်အလက်များ ရှာဖွေနေပါသည်...")
        conn = sqlite3.connect('happyhive.db', check_same_thread=False)
        active_plans = conn.cursor().execute("SELECT key_id, plan_type, data_limit, start_date, end_date FROM plans WHERE telegram_id=? AND is_active=1", (user_id,)).fetchall()
        conn.close()
        if not active_plans: return await query.edit_message_text("❌ လက်ရှိ Plan မရှိသေးပါ။", reply_markup=BACK_TO_MAIN_MARKUP)
        try: all_keys = get_outline_client().get_keys()
        except: return await query.edit_message_text("❌ Server Error", reply_markup=BACK_TO_MAIN_MARKUP)

        msg = "👤 **လက်ရှိ Plan အချက်အလက်များ**\n\n"
        for db_kid, ptype, dlimit, sdate, edate in active_plans:
            used_gb = next((((getattr(k, 'used_bytes', 0) or 0) / 1e9) for k in all_keys if str(k.key_id) == str(db_kid)), 0)
            disp_plan = next((details['display'] for key, details in plans_dict.items() if details['plan_type'] == ptype), ptype)
            msg += f"🔹 **Plan:** `{disp_plan}`\n📅 **စဝယ်သည့်ရက်:** `{sdate[:10]}`\n"
            msg += f"⏳ **ကုန်ဆုံးရက်:** `{edate[:10]}`\n" if edate else ""
            msg += f"📊 **သတ်မှတ် Data:** `{dlimit/1e9:.2f} GB`\n" if dlimit else ""
            msg += f"📈 **အသုံးပြုပီး Data:** `{used_gb:.2f} GB`\n---\n"
        await query.edit_message_text(text=msg, reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')

    elif data in plans_dict:
        context.user_data['pending_plan'] = data
        if 'action_type' not in context.user_data: context.user_data['action_type'] = 'buy'
        await safe_delete_message(query.message)
        await context.bot.send_message(user_id, "💰 **ငွေပေးချေရန် အချက်အလက်များ**\n\nအောက်ပါ KPay သို့ ငွေလွှဲပါ။\n📝 **Note မှာ shopping လို့ရေးပေးပါ**\n\n👤 Name: `Nyein Chan`\n\n📸 **ငွေလွှဲပြေစာ (Screenshot)** ကို ပို့ပေးပါ။", parse_mode='Markdown')
        await context.bot.send_message(user_id, "`09799844344`", parse_mode='Markdown')
        if os.path.exists(PAYMENT_QR_PATH):
            with open(PAYMENT_QR_PATH, 'rb') as f: await context.bot.send_photo(user_id, f, reply_markup=BACK_TO_MAIN_MARKUP)
        else: await context.bot.send_message(user_id, "*(⚠️ QR Code မရှိပါ)*", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = get_user_display_name(update.effective_user)
    if 'pending_plan' in context.user_data:
        plan = context.user_data.pop('pending_plan')
        action_type = context.user_data.pop('action_type', 'buy')
        photo_id = update.message.photo[-1].file_id
        disp = get_plan_details().get(plan, {}).get('short_name', plan)
        action_str = "Extend Plan (သက်တမ်းတိုး)" if action_type == 'extend' else "Buy New Plan (ဝယ်ယူမှုအသစ်)"
        kb = [[InlineKeyboardButton("✅ Approve & Send Key", callback_data=f"approve_{user_id}_{plan}_{action_type}")], [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}_{action_type}")]]
        await context.bot.send_photo(ADMIN_ID, photo=photo_id, caption=f"🔔 <b>New Payment!</b>\n\n👤 User: {get_mention(user_id, user_name)}\n📦 Plan: <code>{disp}</code>\n⚡ Action: <b>{action_str}</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
        await update.message.reply_text("✅ ငွေလွှဲပြေစာကို Admin ထံ ပို့ဆောင်ပြီးပါပြီ။")
    else: await update.message.reply_text("⚠️ ကျေးဇူးပြု၍ Plan အရင်ရွေးချယ်ပြီးမှ Screenshot ပို့ပေးပါ။")

async def admin_approval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action, target_user_id = parts[0], int(parts[1])
    
    if len(parts) >= 5: plan_key, req_action = f"{parts[2]}_{parts[3]}", parts[4]
    elif len(parts) >= 4 and action == "approve": plan_key, req_action = f"{parts[2]}_{parts[3]}", 'buy'
    else: plan_key, req_action = "", 'buy'
    
    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    c = conn.cursor()
    row = c.execute("SELECT username, has_rated FROM users WHERE telegram_id=?", (target_user_id,)).fetchone()
    target_uname = str(row[0]) if row and row[0] else "User"
    has_rated = row[1] if row and len(row) > 1 else 0
    
    if action == "approve":
        plan_info = get_plan_details().get(plan_key)
        if not plan_info:
            await query.edit_message_caption("❌ Plan Error!")
            return conn.close()
            
        await query.edit_message_caption(caption=f"✅ Approved {get_mention(target_user_id, target_uname)} for <code>{plan_info['short_name']}</code>. Processing...", parse_mode='HTML')
        
        try:
            client = get_outline_client()
            if req_action == 'extend':
                active_plan = c.execute("SELECT key_id, data_limit, end_date FROM plans WHERE telegram_id=? AND is_active=1 ORDER BY id DESC LIMIT 1", (target_user_id,)).fetchone()
                if active_plan:
                    old_key_id, old_limit, old_end_date = active_plan
                    new_data_bytes = (plan_info['data_gb'] * 1e9) if plan_info['data_gb'] else 0
                    total_new_limit = (old_limit or 0) + new_data_bytes
                    current_end = datetime.now()
                    if old_end_date:
                        old_end_dt = datetime.strptime(old_end_date, "%Y-%m-%d %H:%M:%S")
                        if old_end_dt > datetime.now(): current_end = old_end_dt
                    new_end = current_end + timedelta(days=30 * plan_info['months'])
                    new_end_str = new_end.strftime("%Y-%m-%d %H:%M:%S")
                    
                    if total_new_limit > 0: client.add_data_limit(old_key_id, int(total_new_limit))
                    c.execute("UPDATE plans SET data_limit=?, end_date=? WHERE key_id=?", (int(total_new_limit), new_end_str, old_key_id))
                    conn.commit()
                    
                    matched_key = next((k for k in client.get_keys() if str(k.key_id) == str(old_key_id)), None)
                    access_url = matched_key.access_url if matched_key else "Not Found"
                    
                    user_msg = f"🎉 **သက်တမ်းတိုးခြင်း အောင်မြင်ပါသည်။**\n\nလူကြီးမင်း၏ လက်ရှိ VPN Key ထဲသို့ Data နှင့် သက်တမ်း ပေါင်းထည့်ပေးလိုက်ပါပြီ။ **App ထဲတွင် Key အသစ်ထပ်ထည့်ရန် မလိုအပ်ပါ။**\n\n⏳ **ကုန်ဆုံးမည့်ရက်အသစ်:** `{new_end.strftime('%Y-%m-%d')}`\n👇 (အကယ်၍ Key ပျောက်သွားပါက ပြန်သုံးနိုင်ပါသည်)"
                    await context.bot.send_message(target_user_id, user_msg, reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
                    await context.bot.send_message(target_user_id, f"`{access_url}`", parse_mode='Markdown')
                    await context.bot.send_message(ADMIN_ID, f"✅ Extended Plan for {get_mention(target_user_id, target_uname)}.", parse_mode='HTML')
                    await send_auto_backup(context, target_user_id, target_uname, "Plan သက်တမ်းတိုးပေး")
                else: req_action = 'buy'
            
            if req_action == 'buy':
                access_url, key_name = generate_vpn_key(target_user_id, plan_info['plan_type'], plan_info['data_gb'], plan_info['months'])
                await context.bot.send_message(target_user_id, f"🎉 **ငွေသွင်းမှု အတည်ပြုပြီးပါပြီ။**\n\n👤 **Name:** `{key_name}`\n\n👇", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
                await context.bot.send_message(target_user_id, f"`{access_url}`", parse_mode='Markdown')
                await context.bot.send_message(ADMIN_ID, f"✅ Key sent to {get_mention(target_user_id, target_uname)}.", parse_mode='HTML')
                if has_rated == 0:
                    if context.job_queue: context.job_queue.run_once(send_rating_request, 3600, data=target_user_id)
                    c.execute("UPDATE users SET has_rated=1 WHERE telegram_id=?", (target_user_id,))
                    conn.commit()
                await send_auto_backup(context, target_user_id, target_uname, "Plan အသစ် ချပေး")

            ref_data = c.execute("SELECT referred_by, referral_reward_claimed FROM users WHERE telegram_id=?", (target_user_id,)).fetchone()
            if ref_data and ref_data[0] and ref_data[1] == 0:
                referrer_id = ref_data[0]
                ref_plan = c.execute("SELECT key_id, data_limit FROM plans WHERE telegram_id=? AND is_active=1 ORDER BY id DESC LIMIT 1", (referrer_id,)).fetchone()
                if ref_plan and ref_plan[1]:
                    new_limit = ref_plan[1] + int(1e9)
                    try:
                        client.add_data_limit(ref_plan[0], new_limit)
                        c.execute("UPDATE plans SET data_limit=? WHERE key_id=?", (new_limit, ref_plan[0]))
                        c.execute("UPDATE users SET referral_reward_claimed=1 WHERE telegram_id=?", (target_user_id,))
                        conn.commit()
                        await context.bot.send_message(referrer_id, "🎁 **Referral Bonus ရရှိပါသည်!**\n\nလူကြီးမင်း ဖိတ်ခေါ်ထားသော သူငယ်ချင်းမှ VPN ဝယ်ယူသွားသောကြောင့် လက်ရှိ Plan ထဲသို့ **Data 1GB** ကို လက်ဆောင်ထည့်သွင်းပေးလိုက်ပါပြီ။", parse_mode='Markdown')
                    except Exception as e: logging.error(f"Failed to give referral reward: {e}")
        except Exception as e: await context.bot.send_message(ADMIN_ID, f"❌ Error: {e}")
    elif action == "reject":
        await query.edit_message_caption(caption=f"❌ Rejected Payment for {get_mention(target_user_id, target_uname)}.", parse_mode='HTML')
        await context.bot.send_message(target_user_id, "❌ **ငွေသွင်းမှု မအောင်မြင်ပါ။**\n\nငွေသွင်းပြေစာ မှားယွင်းနေပါသည်။", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
    conn.close()

async def check_expired_keys(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('happyhive.db', check_same_thread=False)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expired = conn.cursor().execute("SELECT p.key_id, p.telegram_id, p.plan_type, u.username FROM plans p JOIN users u ON p.telegram_id = u.telegram_id WHERE p.end_date IS NOT NULL AND p.end_date <= ? AND p.is_active = 1", (now_str,)).fetchall()
    if expired:
        client = get_outline_client()
        for kid, tid, ptype, uname in expired:
            try:
                client.delete_key(kid)
                conn.cursor().execute("UPDATE plans SET is_active = 0 WHERE key_id = ?", (kid,))
                msg = "⚠️ **Free Trial** ကုန်ဆုံးပါပြီ။" if ptype == "FreeTrial" else "⚠️ **VPN သက်တမ်း** ကုန်ဆုံးသွားပါပြီ။"
                await context.bot.send_message(tid, msg, reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
                await context.bot.send_message(ADMIN_ID, f"♻️ Auto-deleted <code>{kid}</code> for {get_mention(tid, uname)} (<code>{ptype}</code>).", parse_mode='HTML')
            except: pass
        conn.commit()
    conn.close()

# --- Daily Admin Report Handler ---
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID, 
            text="✅ **Daily Status Report**\n\nBot is running perfectly. Have a great day!", 
            parse_mode='Markdown'
        )
    except Exception as e:
        logging.error(f"Failed to send daily report: {e}")

# --- Global Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling an update:", exc_info=context.error)
    print(f"🚨 BOT ERROR: {context.error}")

async def post_init(application: Application):
    await application.bot.set_my_commands([BotCommand("start", "Main Menu")], scope=BotCommandScopeDefault())
    try: await application.bot.set_my_commands([BotCommand("start", "Main Menu"), BotCommand("admin", "Admin Panel"), BotCommand("setapi", "API ပြောင်းရန်"), BotCommand("deluser", "User ဖျက်ရန်")], scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    except: pass

def main():
    # 🌟 Web Server (Render အတွက်)
    keep_alive()
    print("✅ Web Server is running on port 10000...")

    # 🌟 Telegram Bot Initialization
    app = Application.builder().token(BOT_TOKEN).job_queue(None).post_init(post_init).build()
    
    if app.job_queue:
        app.job_queue.run_repeating(check_expired_keys, interval=60, first=10)
        # UTC 02:00 = မြန်မာစံတော်ချိန် 08:30 AM 
        report_time = time(hour=2, minute=0, second=0)
        app.job_queue.run_daily(send_daily_report, time=report_time)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("setapi", set_api_command))
    app.add_handler(CommandHandler("deluser", delete_user_command)) 
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(admin_approval_handler, pattern="^(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Error ဖမ်းပေးမည့် နေရာ
    app.add_error_handler(error_handler)
    
    print("✅ Bot is running successfully...")
    app.run_polling()

if __name__ == '__main__':
    main()
