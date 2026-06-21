import logging
import uuid
import os
import asyncio
import re
import html
import urllib.parse
import json
import psycopg2
import sys
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta, time, timezone
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from outline_vpn.outline_vpn import OutlineVPN
import requests
import paramiko

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

DB_URL = os.environ.get('DATABASE_URL')

def get_db():
    if not DB_URL: raise ValueError("DATABASE_URL Environment Variable is missing! Please add it in Render.")
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn

# 🌟 မြန်မာစံတော်ချိန် (MMT) ရယူရန် 🌟
def get_mmt_now():
    return datetime.now(timezone.utc) + timedelta(hours=6, minutes=30)

app_web = Flask('')
@app_web.route('/')
def home(): return "Bot is Alive & Cloud DB is Active!"
def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host='0.0.0.0', port=port)
def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- CONFIGURATION ---
BOT_TOKEN = "8633829411:AAEdkGteDuDt4fjJABAIR7jIMLVIPQ1PPhA"
BOT_USERNAME = "HHVPN_bot" 
ADMIN_IDS = [1656832105] 
FB_LINK = "https://www.facebook.com/profile.php?id=100063992047331"
ADMIN_CONTACT_LINK = "https://t.me/HappyHive9496"

PROMO_MSG = "🎁 သတင်းကောင်း!\nTelegram ကနေ သူငယ်ချင်းကို Invite လုပ်ရင် 1GB Free ရမယ်နော်။\n\n👉 အသေးစိတ်ကို Admin ( https://t.me/HappyHive9496 ) ထံ ဆက်သွယ်မေးမြန်းနိုင်ပါတယ်။"
WELCOME_TEXT = ("🌟 **Welcome to HappyHive VPN!** 🌟\n\n🚀 **ဘာလို့ HappyHive ကို ရွေးချယ်သင့်တာလဲ?**\n🛡️ **Private & Secure:** လူထောင်ချီသုံးနေတဲ့ အခမဲ့ VPN တွေလို မဟုတ်ဘဲ၊ သီးသန့် Private Server ကို အသုံးပြုထားလို့ လိုင်းကျတာ၊ ချိတ်မရတာ လုံးဝရှိပါဘူး。\n⚡️ **High Speed:** ကမ္ဘာ့အကောင်းဆုံး AWS Server များဖြစ်လို့ ရုပ်ရှင်ကြည့်၊ ဂိမ်းဆော့၊ ဒေါင်းလုဒ်ဆွဲ... အထစ်အငေါ့မရှိ အမြန်နှုန်း အပြည့်ရပါမယ်。\n🔒 **100% Safe:** လူကြီးမင်း၏ ကိုယ်ရေးအချက်အလက်များကို လုံးဝ မှတ်သားထားခြင်း (No Logs) မရှိလို့ ယုံကြည်စိတ်ချစွာ အသုံးပြုနိုင်ပါတယ်။\n\n👇 အောက်ပါ Menu များမှတဆင့် မိမိအသုံးပြုလိုသော ဝန်ဆောင်မှုကို ရွေးချယ်ပါ ခင်ဗျာ©")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BACK_TO_MAIN_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]])
BACK_TO_ADMIN_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]])

async def safe_delete_message(message):
    if message:
        try: await message.delete()
        except: pass

async def send_auto_backup(context: ContextTypes.DEFAULT_TYPE, target_id: int, target_uname: str, action_text: str):
    try:
        caption = f"☁️ <b>Cloud Sync Successful</b>\n{get_mention(target_id, target_uname)} သို့ {action_text}ပြီးနောက် အချက်အလက်များကို လုံခြုံစွာ Cloud တွင် သိမ်းဆည်းလိုက်ပါပြီ。"
        for admin in ADMIN_IDS:
            try: await context.bot.send_message(admin, text=caption, parse_mode='HTML')
            except: pass
    except Exception as e: logging.error(f"Backup alert failed: {e}")

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

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (telegram_id BIGINT PRIMARY KEY, unique_id TEXT, is_trial_used INT, username TEXT, referred_by BIGINT, referral_reward_claimed INT DEFAULT 0, has_rated INT DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS plans (id SERIAL PRIMARY KEY, telegram_id BIGINT, key_id TEXT, plan_type TEXT, data_limit BIGINT, start_date TEXT, end_date TEXT, is_active INT, username TEXT)''')
    
    try: c.execute("ALTER TABLE plans ADD COLUMN current_used_bytes BIGINT DEFAULT 0")
    except psycopg2.Error: pass
    try: c.execute("ALTER TABLE plans ADD COLUMN expired_at TEXT")
    except psycopg2.Error: pass
    try: c.execute("ALTER TABLE plans ADD COLUMN previous_used_bytes BIGINT DEFAULT 0")
    except psycopg2.Error: pass
    try: c.execute("ALTER TABLE plans ADD COLUMN external_key TEXT") 
    except psycopg2.Error: pass

    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    upsert_query = "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    
    # API & CERT
    NEW_API_URL = 'https://194.36.88.172:11236/jAycy_SJSIk2zYta6jSWNA'
    NEW_CERT = '360A41E53BD63C2E143362F2D1AF255A690BA7958D17504389898D4938AED744'

    c.execute(upsert_query, ('outline_api_url', NEW_API_URL))
    c.execute(upsert_query, ('outline_cert_sha256', NEW_CERT))
    
    ignore_query = "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING"
    c.execute(ignore_query, ('total_server_gb', '2000'))
    c.execute(ignore_query, ('monthly_cost', '25000'))
    
    c.execute('''CREATE TABLE IF NOT EXISTS plan_configs (plan_key TEXT PRIMARY KEY, short_name TEXT, display_name TEXT, plan_type TEXT, data_gb INT, months INT)''')
    c.execute("DELETE FROM plan_configs")
    default_plans = [
        ('unlim_1m_1d', '1M (1 Device)', 'Unlimited - 1 month (1 device) - 6000ks', 'Unlimited', None, 1),
        ('unlim_1m_2d', '1M (2 Devices)', 'Unlimited - 1 month (2 devices) - 7000ks', 'Unlimited', None, 1),
        ('unlim_1m_4d', '1M (4 Devices)', 'Unlimited - 1 month (4 devices) - 9000ks', 'Unlimited', None, 1),
        ('unlim_3m_1d', '3M (1 Device)', 'Unlimited - 3 months (1 device) - 16000ks', 'Unlimited', None, 3),
        ('unlim_3m_2d', '3M (2 Devices)', 'Unlimited - 3 months (2 devices) - 19000ks', 'Unlimited', None, 3),
        ('unlim_3m_4d', '3M (4 Devices)', 'Unlimited - 3 months (4 devices) - 25000ks', 'Unlimited', None, 3)
    ]
    for p in default_plans:
        c.execute("INSERT INTO plan_configs VALUES (%s, %s, %s, %s, %s, %s)", p)
    conn.commit()
    conn.close()

init_db()

def get_kamatera_traffic(ip, password):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=22, username='root', password=password, timeout=5)
        
        cmd = "awk '/eth0|ens/{rx+=$2; tx+=$10} END{print rx\":\"tx}' /proc/net/dev"
        stdin, stdout, stderr = client.exec_command(cmd)
        result = stdout.read().decode().strip().split(':')
        client.close()
        
        inbound_bytes = int(result[0])
        outbound_bytes = int(result[1])
        
        inbound_gb = inbound_bytes / (1024**3)
        outbound_gb = outbound_bytes / (1024**3)
        
        return inbound_gb, outbound_gb
    except Exception as e:
        logging.error(f"Kamatera SSH Error: {e}")
        return None, None

def calculate_and_sync_usage(all_keys):
    conn = get_db()
    c = conn.cursor()
    usage_dict = {}
    for k in all_keys:
        kid = str(k.key_id)
        curr_b = int(getattr(k, 'used_bytes', 0) or 0)
        c.execute("UPDATE plans SET current_used_bytes=%s WHERE key_id=%s AND is_active=1", (curr_b, kid))
        usage_dict[kid] = curr_b
    conn.commit()
    conn.close()
    return usage_dict

def get_plan_details():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT plan_key, short_name, display_name, plan_type, data_gb, months FROM plan_configs")
    rows = c.fetchall()
    conn.close()
    return {r[0]: {'short_name': r[1], 'display': r[2], 'plan_type': r[3], 'data_gb': r[4], 'months': r[5]} for r in rows}

def get_plans_keyboard(plans_dict):
    keyboard = []
    for p_key, p_info in plans_dict.items(): keyboard.append([InlineKeyboardButton(p_info['display'], callback_data=p_key)])
    keyboard.append([InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')])
    return InlineKeyboardMarkup(keyboard)

def get_outline_client():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='outline_api_url'")
    api_url = c.fetchone()[0]
    c.execute("SELECT value FROM settings WHERE key='outline_cert_sha256'")
    cert_sha = c.fetchone()[0]
    conn.close()
    return OutlineVPN(api_url=api_url, cert_sha256=cert_sha)

def get_or_create_user(telegram_id, username="User", referred_by=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT unique_id, is_trial_used FROM users WHERE telegram_id=%s", (telegram_id,))
    user = c.fetchone()
    if not user:
        unique_id = str(uuid.uuid4())[:8].upper()
        c.execute("INSERT INTO users (telegram_id, unique_id, is_trial_used, username, referred_by, referral_reward_claimed) VALUES (%s, %s, 0, %s, %s, 0)", (telegram_id, unique_id, username, referred_by))
        user = (unique_id, 0)
    else:
        c.execute("UPDATE users SET username=%s WHERE telegram_id=%s", (username, telegram_id))
    conn.close()
    return user

def get_bottom_keyboard(user_id):
    btns = [["🏠 ပင်မ မီနူးသို့သွားပါ", "🛡️ Admin Panel"]] if user_id in ADMIN_IDS else [["🏠 ပင်မ မီနူးသို့သွားပါ"]]
    return ReplyKeyboardMarkup(btns, resize_keyboard=True, is_persistent=True)

def generate_vpn_key(telegram_id, plan_type, data_gb=None, months=None):
    client = get_outline_client()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT unique_id, username FROM users WHERE telegram_id=%s", (telegram_id,))
    row = c.fetchone()
    unique_id, raw_username = row[0], row[1] if row[1] else "User"
    
    new_key = client.create_key()
    start_date = get_mmt_now()
    db_start_date = start_date.strftime("%Y-%m-%d %H:%M:%S")
    end_date = start_date + timedelta(days=5) if plan_type == "FreeTrial" else (start_date + timedelta(days=30 * months) if months else None)
    db_end_date = end_date.strftime("%Y-%m-%d %H:%M:%S") if end_date else None
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d') if end_date else "NoExp"
    suffix = f"{plan_type}_{start_str}_{end_str}_{telegram_id}_Key{new_key.key_id}"
    
    client.rename_key(new_key.key_id, suffix)
    data_bytes = data_gb * 1e9 if data_gb else None
    
    if data_bytes:
        try: client.add_data_limit(new_key.key_id, int(data_bytes))
        except Exception as e: logging.error(f"Failed to set data limit on outline server: {e}")

    c.execute('''INSERT INTO plans (telegram_id, key_id, plan_type, data_limit, start_date, end_date, is_active, username, current_used_bytes, previous_used_bytes) VALUES (%s, %s, %s, %s, %s, %s, 1, %s, 0, 0)''', (telegram_id, new_key.key_id, plan_type, data_bytes, db_start_date, db_end_date, raw_username))
    conn.close()
    final_url = f"{new_key.access_url.split('#')[0]}#{urllib.parse.quote(suffix)}"
    return final_url, suffix

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
        [InlineKeyboardButton("🛒 Plan ဝယ်ရန်", callback_data='buy_plan')],
        [InlineKeyboardButton("👤 Plan/Data စစ်ရန်", callback_data='my_plan'), InlineKeyboardButton("❓ အသုံးပြုပုံ", callback_data='how_to_use')],
        [InlineKeyboardButton("📢 သူငယ်ချင်းများသို့ မျှဝေရန်", callback_data='share_referral')],
        [InlineKeyboardButton("📝 အကြံပြုစာရေးရန်", callback_data='send_feedback'), InlineKeyboardButton("🌐 Facebook Page", url=FB_LINK)],
        [InlineKeyboardButton("👨‍💻 Admin ကို ဆက်သွယ်ရန်", url=ADMIN_CONTACT_LINK)]
    ]
    chat_id = update.effective_chat.id
    markup = InlineKeyboardMarkup(keyboard)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='welcome_image_id'")
    row = c.fetchone()
    conn.close()

    if update.message and update.message.text.startswith('/start'):
        await update.message.reply_text("👇 အောက်ပါ ခလုတ်များကိုလည်း အလွယ်တကူ အသုံးပြုနိုင်ပါသည်။", reply_markup=get_bottom_keyboard(user.id))
        if row:
            try: await context.bot.send_photo(chat_id=chat_id, photo=row[0])
            except Exception as e: logging.error(e)
        await context.bot.send_message(chat_id=chat_id, text=WELCOME_TEXT, reply_markup=markup, parse_mode='Markdown')
    else:
        if update.callback_query and not update.callback_query.message.photo:
            try: await update.callback_query.edit_message_text(text=WELCOME_TEXT, reply_markup=markup, parse_mode='Markdown')
            except: await context.bot.send_message(chat_id=chat_id, text=WELCOME_TEXT, reply_markup=markup, parse_mode='Markdown')
        else:
            await safe_delete_message(update.callback_query.message if update.callback_query else None)
            await context.bot.send_message(chat_id=chat_id, text=WELCOME_TEXT, reply_markup=markup, parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    keyboard = [
        [InlineKeyboardButton("👥 View Users Plans", callback_data='admin_view_users'), InlineKeyboardButton("⚠️ Expiring Soon", callback_data='admin_expiring')],
        [InlineKeyboardButton("➕ Manual Key ထုတ်ရန်", callback_data='admin_manual_key'), InlineKeyboardButton("📝 Plan အမည်များ ပြင်ရန်", callback_data='admin_edit_plans')],
        [InlineKeyboardButton("🔄 User Key ပြောင်းရန်", callback_data='admin_change_key'), InlineKeyboardButton("📂 ဖိုင်နှင့် ပုံများ တင်ရန်", callback_data='admin_uploads_menu')],
        [InlineKeyboardButton("📊 စီးပွားရေး/Server Stats", callback_data='admin_server_stats'), InlineKeyboardButton("💽 Server Storage ပြင်ရန်", callback_data='admin_change_storage')],
        [InlineKeyboardButton("💰 လစဉ်အရင်း ပြင်ရန်", callback_data='admin_change_cost'), InlineKeyboardButton("💾 Database Backup ယူရန်", callback_data='admin_manual_backup')],
        [InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast'), InlineKeyboardButton("🗑️ စနစ်တစ်ခုလုံး Reset ချရန်", callback_data='admin_reset_system')]
    ]
    msg = "🛡️ **Admin Panel ရောက်ပါပြီ။**\n👇 လုပ်ဆောင်လိုသော မီနူးကို ရွေးချယ်ပါ။"
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
        for admin in ADMIN_IDS:
            try: await context.bot.send_message(chat_id=admin, text=f"💌 <b>New Anonymous Feedback</b> 💌\n\n💬 Message:\n{html.escape(text)}", parse_mode='HTML')
            except: pass
        del context.user_data['state']
        await update.message.reply_text("✅ ကျေးဇူးတင်ပါသည်။ လူကြီးမင်း၏ အကြံပြုစာကို Admin ထံသို့ လျှို့ဝှက်ပေးပို့ပြီးပါပြီ©", reply_markup=BACK_TO_MAIN_MARKUP)

    elif state == 'waiting_for_manual_key' and update.effective_user.id in ADMIN_IDS:
        if "|" not in text or len(text.split("|")) != 3: return await update.message.reply_text("❌ Format မှားယွင်းနေပါသည်။ `ID | Name | Plan` ပုံစံဖြင့် ရိုက်ထည့်ပါ။", parse_mode='Markdown')
        tid_str, uname, pkey = map(str.strip, text.split('|', 2))
        try: target_id = int(tid_str)
        except ValueError: return await update.message.reply_text("❌ Telegram ID (သို့) ဖုန်းနံပါတ်သည် ဂဏန်းသက်သက်သာ ဖြစ်ရပါမည်©")
        plan_info = get_plan_details().get(pkey)
        if not plan_info: return await update.message.reply_text("❌ Plan အမည် မှားယွင်းနေပါသည်။", parse_mode='Markdown')
        del context.user_data['state']
        await update.message.reply_text("⏳ Manual Key ဖန်တီးနေပါသည်... ခဏစောင့်ပါ။")
        get_or_create_user(target_id, uname)
        try:
            access_url, key_name = generate_vpn_key(target_id, plan_info['plan_type'], plan_info['data_gb'], plan_info['months'])
            await update.message.reply_text(f"✅ **Manual Key အောင်မြင်စွာ ထုတ်ပေးလိုက်ပါပြီ©**\n\n👤 Name: `{key_name}`\n🔑 Access Key:\n`{access_url}`", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')
            try:
                await context.bot.send_message(chat_id=target_id, text=f"🎉 **Admin မှ လူကြီးမင်း၏ VPN Plan ကို အတည်ပြုပေးလိုက်ပါပြီ©**\n\n👤 **Name:** `{key_name}`\n\n👇 **အောက်ပါ Key ကို Copy ကူးပြီး Outline VPN တွင် ထည့်သွင်းအသုံးပြုနိုင်ပါပြီ©**", parse_mode='Markdown')
                await context.bot.send_message(chat_id=target_id, text=f"`{access_url}`", parse_mode='Markdown')
            except: pass
            await send_auto_backup(context, target_id, uname, "Plan (Manual) ချပေး")
        except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

    elif state == 'waiting_for_change_key' and update.effective_user.id in ADMIN_IDS:
        if "|" not in text or len(text.split("|")) != 2:
            return await update.message.reply_text("❌ Format မှားယွင်းနေပါသည်။ `Telegram ID | Access URL` ပုံစံဖြင့် မှန်ကန်စွာ ရိုက်ထည့်ပါ။\n\n📌 ဥပမာ - `123456789 | ss://ey...`", parse_mode='Markdown')
            
        tid_str, new_access_url = map(str.strip, text.split('|', 1))
        try: target_id = int(tid_str)
        except ValueError: return await update.message.reply_text("❌ Telegram ID သည် ဂဏန်းသာ ဖြစ်ရပါမည်။", reply_markup=BACK_TO_ADMIN_MARKUP)
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, key_id, plan_type, data_limit, current_used_bytes, previous_used_bytes, username, start_date, end_date FROM plans WHERE telegram_id=%s AND is_active=1", (target_id,))
        plan = c.fetchone()
        
        if not plan:
            conn.close()
            return await update.message.reply_text("❌ ဤ User တွင် Active ဖြစ်နေသော Plan မရှိပါ။", reply_markup=BACK_TO_ADMIN_MARKUP)
        
        pid, old_kid, ptype, dlimit, c_bytes, prev_bytes, uname, sdate, edate = plan
        
        try:
            client = get_outline_client()
            all_keys = client.get_keys()
            matched_old_key = next((k for k in all_keys if str(k.key_id) == str(old_kid)), None)
            real_c_bytes = int(getattr(matched_old_key, 'used_bytes', 0) or 0) if matched_old_key else c_bytes
            
            clean_new_url = new_access_url.split('#')[0]
            matched_new_key = next((k for k in all_keys if k.access_url.split('#')[0] == clean_new_url), None)
            
            if not matched_new_key:
                conn.close()
                return await update.message.reply_text(f"❌ Outline Server ပေါ်တွင် ထို Access URL ကို မတွေ့ပါ။ Manager တွင် အရင်ဖန်တီးထားပါ။", reply_markup=BACK_TO_ADMIN_MARKUP)
                
            new_kid_str = str(matched_new_key.key_id)
        except Exception as e:
            conn.close()
            return await update.message.reply_text(f"❌ Outline Server Error: {e}", reply_markup=BACK_TO_ADMIN_MARKUP)
            
        total_used_so_far = (prev_bytes or 0) + real_c_bytes
        try: client.delete_key(old_kid)
        except: pass
        
        suffix = f"{ptype}_{sdate[:10]}_{edate[:10] if edate else 'NoExp'}_{target_id}_Key{new_kid_str}"
        try: client.rename_key(new_kid_str, suffix)
        except: pass
        
        if dlimit:
            rem_bytes = max(0, dlimit - total_used_so_far)
            try: client.add_data_limit(new_kid_str, int(rem_bytes))
            except: pass
            
        c.execute("UPDATE plans SET key_id=%s, previous_used_bytes=%s, current_used_bytes=0 WHERE id=%s", (new_kid_str, total_used_so_far, pid))
        conn.commit()
        conn.close()
        
        final_url = f"{clean_new_url}#{urllib.parse.quote(suffix)}"
        del context.user_data['state']
        await update.message.reply_text(f"✅ Key ပြောင်းလဲခြင်း အောင်မြင်ပါပြီ။\n\nNew Key: `{final_url}`", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')
        
        try:
            user_msg = f"⚠️ **အသိပေးချက် (Server Update)**\n\nဆာဗာပြုပြင်မှုကြောင့် လူကြီးမင်း၏ Key အား အသစ်ပြောင်းလဲပေးလိုက်ပါသည်။ (Data မှတ်တမ်းများ ပျောက်ပျက်သွားမည် မဟုတ်ပါ။)\n\n👇 **အောက်ပါ Key အသစ်ကို အသုံးပြုပေးပါခင်ဗျာ။**\n\n`{final_url}`"
            await context.bot.send_message(chat_id=target_id, text=user_msg, parse_mode='Markdown')
        except: pass

    elif state == 'waiting_for_storage_gb' and update.effective_user.id in ADMIN_IDS:
        try:
            new_gb = int(text.strip())
            conn = get_db()
            c = conn.cursor()
            upsert_gb = "INSERT INTO settings (key, value) VALUES ('total_server_gb', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            c.execute(upsert_gb, (str(new_gb),))
            conn.close()
            del context.user_data['state']
            await update.message.reply_text(f"✅ Server ၏ Storage ကို **{new_gb} GB** အဖြစ် အောင်မြင်စွာ ပြောင်းလဲသတ်မှတ်လိုက်ပါပြီ©", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')
        except ValueError: await update.message.reply_text("❌ ကျေးဇူးပြု၍ Storage ပမာဏကို ဂဏန်းသက်သက်သာ ရိုက်ထည့်ပါ။ (ဥပမာ - 1000, 2000)", parse_mode='Markdown')

    elif state == 'waiting_for_cost' and update.effective_user.id in ADMIN_IDS:
        try:
            new_cost = int(text.strip())
            conn = get_db()
            c = conn.cursor()
            upsert_cost = "INSERT INTO settings (key, value) VALUES ('monthly_cost', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            c.execute(upsert_cost, (str(new_cost),))
            conn.close()
            del context.user_data['state']
            await update.message.reply_text(f"✅ လစဉ် အရင်းပမာဏကို **{new_cost:,} ကျပ်** အဖြစ် အောင်မြင်စွာ ပြောင်းလဲသတ်မှတ်လိုက်ပါပြီ©", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ ကျေးဇူးပြု၍ ပမာဏကို ဂဏန်းသက်သက်သာ ရိုက်ထည့်ပါ။ (ဥပမာ - 25000, 30000)", parse_mode='Markdown')

    elif state and state.startswith('waiting_for_plan_name_') and update.effective_user.id in ADMIN_IDS:
        plan_key = state.replace('waiting_for_plan_name_', '')
        if "|" not in text: return await update.message.reply_text("❌ Format မှားယွင်းနေပါသည်။ `Short Name | Display Name` ပုံစံဖြင့် ရိုက်ထည့်ပါ။", parse_mode='Markdown')
        short_name, display_name = map(str.strip, text.split('|', 1))
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE plan_configs SET short_name=%s, display_name=%s WHERE plan_key=%s", (short_name, display_name, plan_key))
        conn.close()
        del context.user_data['state']
        await update.message.reply_text(f"✅ Plan အမည်ကို အောင်မြင်စွာ ပြောင်းလဲလိုက်ပါပြီ©\n\n🔹 **Short:** `{short_name}`\n🔹 **Display:** `{display_name}`", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif state == 'waiting_for_broadcast' and update.effective_user.id in ADMIN_IDS:
        await update.message.reply_text("⏳ Broadcast စတင်ပေးပို့နေပါသည်... ခဏစောင့်ပါ။")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT DISTINCT telegram_id FROM users")
        all_users = c.fetchall()
        conn.close()
        success, failed = 0, 0
        for uid in all_users:
            try:
                await context.bot.send_message(chat_id=uid[0], text=f"📢 **Admin မှ အသိပေးချက်**\n\n{text}", parse_mode='Markdown')
                success += 1
                await asyncio.sleep(0.05) 
            except: failed += 1
        del context.user_data['state']
        await context.bot.send_message(chat_id=update.effective_user.id, text=f"✅ **Broadcast ပေးပို့ခြင်း ပြီးဆုံးပါပြီ©**\n\n🟢 အောင်မြင်: `{success}` ဦး\n🔴 မအောင်မြင်: `{failed}` ဦး", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif state and state.startswith('wait_ext_key_') and update.effective_user.id in ADMIN_IDS:
        payment_id = state.replace('wait_ext_key_', '')
        payment_info = context.bot_data.get('payments', {}).get(payment_id)
        
        if not payment_info:
            del context.user_data['state']
            return await update.message.reply_text("❌ Payment အချက်အလက် ရှာမတွေ့တော့ပါ။")

        target_user_id, plan_key, target_uname, msgs_to_edit = payment_info['user_id'], payment_info['plan_key'], payment_info['user_name'], payment_info['msgs']
        provided_key = text.strip()

        del context.user_data['state']
        del context.bot_data['payments'][payment_id]

        for adm_id, msg_id in msgs_to_edit:
            try: await context.bot.edit_message_caption(chat_id=adm_id, message_id=msg_id, caption=f"✅ <b>Approved & Key Sent:</b>\n<code>{html.escape(provided_key)}</code>", parse_mode='HTML')
            except: pass

        try:
            await context.bot.send_message(target_user_id, f"🎉 **ငွေသွင်းမှု အတည်ပြုပြီးပါပြီ©**\n\n👇 **အောက်ပါ Key ကို Copy ကူးပြီး Outline VPN တွင် ထည့်သွင်းအသုံးပြုနိုင်ပါပြီ©**", parse_mode='Markdown')
            await context.bot.send_message(target_user_id, f"`{provided_key}`", parse_mode='Markdown')
        except: pass

        conn = get_db()
        c = conn.cursor()
        plan_info = get_plan_details().get(plan_key)
        if plan_info:
            start_date = get_mmt_now()
            db_start_date = start_date.strftime("%Y-%m-%d %H:%M:%S")
            months = plan_info['months']
            end_date = start_date + timedelta(days=30 * months) if months else None
            db_end_date = end_date.strftime("%Y-%m-%d %H:%M:%S") if end_date else None
            data_bytes = plan_info['data_gb'] * 1e9 if plan_info['data_gb'] else None
            fake_key_id = f"ext_{uuid.uuid4().hex[:8]}" 

            c.execute('''INSERT INTO plans (telegram_id, key_id, plan_type, data_limit, start_date, end_date, is_active, username, current_used_bytes, previous_used_bytes, external_key) VALUES (%s, %s, %s, %s, %s, %s, 1, %s, 0, 0, %s)''', (target_user_id, fake_key_id, plan_info['plan_type'], data_bytes, db_start_date, db_end_date, target_uname, provided_key))

        conn.commit()
        conn.close()
        await send_auto_backup(context, target_user_id, target_uname, "Plan (External Key) ချပေး")
        await update.message.reply_text("✅ User ထံသို့ Key အောင်မြင်စွာ ပေးပို့ပြီး မှတ်တမ်းတင်လိုက်ပါပြီ။", reply_markup=BACK_TO_ADMIN_MARKUP)

async def delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(context.args) != 1: return await update.message.reply_text("❌ အသုံးပြုပုံ မှားယွင်းနေပါသည်။\nဥပမာ - `/deluser 123456789`", parse_mode='Markdown')
    try: target_id = int(context.args[0])
    except ValueError: return await update.message.reply_text("❌ User ID သည် ဂဏန်းသာ ဖြစ်ရပါမည်©")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT key_id FROM plans WHERE telegram_id=%s", (target_id,))
    user_plans = c.fetchall()
    if user_plans:
        try:
            client = get_outline_client()
            for p in user_plans:
                if not str(p[0]).startswith('ext_'):
                    try: client.delete_key(p[0])
                    except: pass
        except: pass
    c.execute("DELETE FROM plans WHERE telegram_id=%s", (target_id,))
    deleted_plans = c.rowcount
    c.execute("DELETE FROM users WHERE telegram_id=%s", (target_id,))
    deleted_users = c.rowcount
    conn.close()
    if deleted_plans > 0 or deleted_users > 0: await update.message.reply_text(f"✅ User ID `{target_id}` အား ဖျက်ပစ်လိုက်ပါပြီ©", parse_mode='Markdown')
    else: await update.message.reply_text(f"⚠️ User ID `{target_id}` ကို မတွေ့ပါ။", parse_mode='Markdown')

async def restore_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    await update.message.reply_text("⏳ Data များ ပြန်လည်သွင်းနေပါသည်...")
    
    users_data = [
        {"id": 1648867714, "name": "@CamelliaBlossom123", "plan": "30GB", "key_id": "3", "start": "2026-05-02 07:13:12", "exp": "2026-06-01 07:13:12"},
        {"id": 7545066157, "name": "Myat Thuzar", "plan": "30GB", "key_id": "6", "start": "2026-05-12 06:25:58", "exp": "2026-06-11 06:25:58"},
        {"id": 1652674399, "name": "@mingochen", "plan": "30GB", "key_id": "4", "start": "2026-05-09 08:31:41", "exp": "2026-06-08 08:31:41"},
        {"id": 1656832105, "name": "@HappyHive9496", "plan": "30GB", "key_id": "8", "start": "2026-05-02 05:56:48", "exp": "2026-06-01 05:56:48"}
    ]
    
    try:
        conn = get_db()
        c = conn.cursor()
        data_limit_bytes = int(30 * 1e9)
        
        for u in users_data:
            uid = str(uuid.uuid4())[:8].upper()
            c.execute("INSERT INTO users (telegram_id, unique_id, is_trial_used, username, referral_reward_claimed, has_rated) VALUES (%s, %s, 0, %s, 0, 0) ON CONFLICT (telegram_id) DO NOTHING", (u["id"], uid, u["name"]))
            c.execute("DELETE FROM plans WHERE key_id=%s", (u["key_id"],))
            c.execute('''INSERT INTO plans (telegram_id, key_id, plan_type, data_limit, start_date, end_date, is_active, username, current_used_bytes, previous_used_bytes) 
                         VALUES (%s, %s, %s, %s, %s, %s, 1, %s, 0, 0)''', 
                      (u["id"], u["key_id"], u["plan"], data_limit_bytes, u["start"], u["exp"], u["name"]))
            
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ User (၄) ဦး၏ မှတ်တမ်းများကို Database သို့ ပြန်ထည့်ပြီးပါပြီ။\nData Usage များကို Outline Server မှ တိုက်ရိုက်ဆွဲယူပါမည်။")
    except Exception as e:
        await update.message.reply_text(f"❌ Error restoring data: {e}")

async def send_rating_request(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    kb = [[InlineKeyboardButton("⭐", callback_data='rate_1'), InlineKeyboardButton("⭐⭐", callback_data='rate_2'), InlineKeyboardButton("⭐⭐⭐", callback_data='rate_3')],
          [InlineKeyboardButton("⭐⭐⭐⭐", callback_data='rate_4'), InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data='rate_5')]]
    try: await context.bot.send_message(chat_id=user_id, text="🌟 **HappyHive VPN ကို အသုံးပြုရတာ အဆင်ပြေရဲ့လား ခင်ဗျာ?**\n\nလူကြီးမင်း၏ အတွေ့အကြုံကို အောက်ပါ ကြယ်လေးတွေနှိပ်ပြီး အမှတ်ပေး အကဲဖြတ်ပေးပါဦး ခင်ဗျာ©", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    except: pass

async def send_htu_guide(query, context, os_type):
    user_id = query.from_user.id
    await safe_delete_message(query.message)
    conn = get_db()
    c = conn.cursor()
    
    if os_type == 'android': 
        c.execute("SELECT value FROM settings WHERE key='android_guide_file_id'")
        row = c.fetchone()
        file_id = row[0] if row else None
        text = "🤖 **Android ဖုန်းများအတွက် အသုံးပြုပုံ**\n\nအောက်ပါပုံတွင် ကြည့်ရှုနိုင်ပါသည်။"
        url = "https://play.google.com/store/apps/details?id=org.outline.android.client&hl=en_SG"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Outline App Download ဆွဲရန်", url=url)], [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]])
        if file_id: await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=text, reply_markup=markup, parse_mode='Markdown')
        else: await context.bot.send_message(chat_id=user_id, text=text + "\n*(⚠️ ပုံမရှိသေးပါ။ Admin တင်ပေးရန် လိုပါသည်။)*", reply_markup=markup, parse_mode='Markdown')
        
    elif os_type == 'apple': 
        c.execute("SELECT value FROM settings WHERE key='ios_guide_file_id'")
        row = c.fetchone()
        file_id = row[0] if row else None
        text = "🍎 **Apple (iOS) ဖုန်းများအတွက် အသုံးပြုပုံ**\n\nအောက်ပါပုံတွင် ကြည့်ရှုနိုင်ပါသည်။"
        url = "https://apps.apple.com/us/app/outline-app/id1356177741"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Outline App Download ဆွဲရန်", url=url)], [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]])
        if file_id: await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=text, reply_markup=markup, parse_mode='Markdown')
        else: await context.bot.send_message(chat_id=user_id, text=text + "\n*(⚠️ ပုံမရှိသေးပါ။ Admin တင်ပေးရန် လိုပါသည်။)*", reply_markup=markup, parse_mode='Markdown')
        
    elif os_type == 'pc':
        c.execute("SELECT value FROM settings WHERE key='pc_installer_file_id'")
        row = c.fetchone()
        file_id = row[0] if row else None
        text = "💻 **PC (Windows) အတွက် အသုံးပြုပုံ**\n\nအောက်ပါဖိုင်ကို Download ဆွဲပြီး Install လုပ်ပါ။ ပြီးလျှင် Admin ပေးသော Key ကို ထည့်သွင်းအသုံးပြုနိုင်ပါသည်။"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]])
        if file_id:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
            await context.bot.send_document(chat_id=user_id, document=file_id, caption="📥 PC Outline Client (Windows)", reply_markup=markup)
        else: await context.bot.send_message(chat_id=user_id, text="*(⚠️ Installer ဖိုင် မရှိသေးပါ။ Admin တင်ပေးရန် လိုပါသည်။)*", reply_markup=markup, parse_mode='Markdown')
    conn.close()

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

    elif data == 'admin_uploads_menu':
        kb = [
            [InlineKeyboardButton("🖼️ Android ပုံတင်ရန်", callback_data='up_android'), InlineKeyboardButton("🖼️ iOS ပုံတင်ရန်", callback_data='up_ios')],
            [InlineKeyboardButton("💻 PC Installer တင်ရန်", callback_data='up_pc'), InlineKeyboardButton("🌟 Welcome ပုံတင်ရန်", callback_data='up_welcome')],
            [InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]
        ]
        await query.edit_message_text("📂 **တင်လိုသော ဖိုင် သို့မဟုတ် ပုံ ကိုရွေးချယ်ပါ:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data in ['up_android', 'up_ios', 'up_welcome', 'up_pc']:
        context.user_data['state'] = f'wait_{data}'
        msg = "📸 ယခု ပုံကို Bot ထဲသို့ တိုက်ရိုက် လှမ်းပို့ပေးပါ။" if data != 'up_pc' else "📁 ယခု PC Installer (.exe) ဖိုင်ကို Bot ထဲသို့ တိုက်ရိုက် လှမ်းပို့ပေးပါ။"
        await query.edit_message_text(msg, reply_markup=BACK_TO_ADMIN_MARKUP)

    elif data == 'admin_change_key':
        context.user_data['state'] = 'waiting_for_change_key'
        msg = "🔄 **User Key ပြောင်းရန်**\n\nAdmin ကိုယ်တိုင် Outline တွင် ဖန်တီးထားသော Key ၏ Access URL ကို အောက်ပါအတိုင်း `|` ခံ၍ ရိုက်ထည့်ပါ:\n`Telegram ID | Access URL`\n\n📌 ဥပမာ - `123456789 | ss://ey...`"
        await query.edit_message_text(msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data.startswith('adm_delkey_'):
        key_id_to_del = data.replace('adm_delkey_', '')
        await query.edit_message_text(f"⏳ ဖျက်နေပါသည်...")
        try:
            if not key_id_to_del.startswith('ext_'):
                client = get_outline_client()
                try: client.delete_key(key_id_to_del)
                except: pass
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM plans WHERE key_id = %s", (key_id_to_del,))
            conn.commit()
            conn.close()
            await query.edit_message_text(f"✅ ဤ Key အား အောင်မြင်စွာ ဖျက်လိုက်ပါပြီ။")
        except Exception as e: await query.edit_message_text(f"❌ Error: {e}")

    elif data == 'admin_change_cost':
        context.user_data['state'] = 'waiting_for_cost'
        conn = get_db(); c = conn.cursor(); c.execute("SELECT value FROM settings WHERE key='monthly_cost'"); row = c.fetchone(); conn.close()
        current_cost = int(row[0]) if row else 25000
        msg = f"💰 **လစဉ်အရင်း ပြင်ရန်**\nလက်ရှိမှာ **{current_cost:,} ကျပ်** ဖြစ်ပါသည်။ ပမာဏအသစ်ကို ရိုက်ထည့်ပါ:"
        await query.edit_message_text(text=msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'admin_manual_backup':
        await query.edit_message_text("⏳ Backup ယူနေပါသည်...")
        try:
            conn = get_db(); c = conn.cursor(cursor_factory=psycopg2.extras.DictCursor); backup_data = {}
            for t in ['users', 'plans', 'settings', 'plan_configs']:
                c.execute(f"SELECT * FROM {t}"); rows = c.fetchall(); backup_data[t] = [dict(r) for r in rows]
            conn.close()
            filename = f"HHVPN_Backup_{get_mmt_now().strftime('%Y%m%d_%H%M')}.json"
            with open(filename, 'w', encoding='utf-8') as f: json.dump(backup_data, f, ensure_ascii=False, indent=4)
            with open(filename, 'rb') as f: await context.bot.send_document(chat_id=user_id, document=f, caption="📦 Cloud Backup")
            os.remove(filename)
            await query.edit_message_text("✅ Backup ပေးပို့ပြီးပါပြီ©", reply_markup=BACK_TO_ADMIN_MARKUP)
        except Exception as e: await query.edit_message_text(f"❌ Error: {e}", reply_markup=BACK_TO_ADMIN_MARKUP)

    elif data == 'share_referral':
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        share_url = f"https://t.me/share/url?url={ref_link}&text=🌟 HappyHive VPN ကို အသုံးပြုကြည့်ဖို့ ဖိတ်ခေါ်ပါတယ် ခင်ဗျာ။ 👇"
        msg = ("🎁 **Referral အစီအစဉ်**\n\nမိမိ၏ လင့်ခ်မှတဆင့် ဖိတ်ခေါ်ပါ။\n⚠️ *(သူငယ်ချင်းမှ Plan ဝယ်ယူမှသာ Data 1GB ရရှိပါမည်)*")
        kb = [[InlineKeyboardButton("📤 ယခုပဲ မျှဝေရန်", url=share_url)], [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == 'admin_change_storage':
        context.user_data['state'] = 'waiting_for_storage_gb'
        conn = get_db(); c = conn.cursor(); c.execute("SELECT value FROM settings WHERE key='total_server_gb'"); row = c.fetchone(); conn.close()
        current_gb = row[0] if row else "2000"
        msg = f"💽 **Server Storage ပြင်ရန်**\nလက်ရှိ: **{current_gb} GB**\n\nပမာဏအသစ် ရိုက်ထည့်ပါ:"
        await query.edit_message_text(text=msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'admin_server_stats':
        await query.edit_message_text(text="⏳ တွက်ချက်နေပါသည်...")
        try:
            conn = get_db(); c = conn.cursor()
            c.execute("SELECT plan_type, start_date FROM plans WHERE plan_type != 'FreeTrial'")
            all_plans = c.fetchall()
            c.execute("SELECT data_limit FROM plans WHERE is_active=1 AND plan_type != 'FreeTrial'")
            active_plans = c.fetchall()
            c.execute("SELECT value FROM settings WHERE key='total_server_gb'"); row_gb = c.fetchone(); total_server_gb = int(row_gb[0]) if row_gb else 2000
            c.execute("SELECT value FROM settings WHERE key='monthly_cost'"); row_cost = c.fetchone(); monthly_cost = int(row_cost[0]) if row_cost else 25000
            c.execute("SELECT current_used_bytes, previous_used_bytes FROM plans WHERE is_active=1")
            usage_rows = c.fetchall(); conn.close()
            
            total_used_gb = sum((r[0] or 0) + (r[1] or 0) for r in usage_rows) / 1e9
            PLAN_PRICES = {'30GB': 2000, '50GB': 3000, '100GB': 4000}
            now = get_mmt_now(); current_m, current_y, current_m_num = now.strftime("%Y-%m"), now.strftime("%Y"), now.month
            monthly_rev = sum(PLAN_PRICES.get(p[0], 0) for p in all_plans if p[1][:7] == current_m)
            yearly_rev = sum(PLAN_PRICES.get(p[0], 0) for p in all_plans if p[1][:4] == current_y)
            monthly_profit = monthly_rev - monthly_cost
            yearly_profit = yearly_rev - (monthly_cost * current_m_num)
            def get_status(p): return f"🟢 မြတ် (<b>+{p:,}</b>)" if p > 0 else (f"⚪️ အရင်းကြေ (<b>0</b>)" if p == 0 else f"🔴 ရှုံး (<b>{p:,}</b>)")
            
            try: client = get_outline_client(); active_keys_count = len(client.get_keys())
            except: active_keys_count = "Error"
            
            total_allocated_gb = sum(d[0]/1e9 for d in active_plans if d[0])
            KAMATERA_IP, KAMATERA_PASS = "194.36.88.172", "HHoutlinevpn@123"
            in_gb, out_gb = get_kamatera_traffic(KAMATERA_IP, KAMATERA_PASS)
            kt_text = f"☁️ <b>Traffic:</b> In: <code>{in_gb:.2f}GB</code> | Out: <code>{out_gb:.2f}GB</code>" if in_gb is not None else "☁️ SSH Failed."

            msg = (
                f"📊 <b>Server Stats</b>\n\n"
                f"📅 <b>{now.strftime('%B')}:</b> အရင်း: <code>{monthly_cost:,}</code> | ဝင်ငွေ: <code>{monthly_rev:,}</code> | {get_status(monthly_profit)}\n"
                f"📆 <b>YTD:</b> အရင်း: <code>{monthly_cost*current_m_num:,}</code> | ဝင်ငွေ: <code>{yearly_rev:,}</code> | {get_status(yearly_profit)}\n\n"
                f"💽 <b>Data:</b> Allocated: <code>{total_allocated_gb:.2f}GB</code> | Usage: <code>{total_used_gb:.2f}GB</code> / <b>{total_server_gb}GB</b>\n"
                f"{kt_text}\n"
            )
            await query.edit_message_text(text=msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='HTML')
        except Exception as e: await query.edit_message_text(text=f"❌ Error: {e}", reply_markup=BACK_TO_ADMIN_MARKUP)

    elif data == 'admin_view_users':
        await query.edit_message_text("⏳ Data ဆွဲယူနေပါသည်...")
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT u.telegram_id, u.username, p.plan_type, p.end_date, p.key_id, p.data_limit, p.current_used_bytes, p.previous_used_bytes, p.external_key FROM plans p JOIN users u ON p.telegram_id = u.telegram_id WHERE p.is_active=1")
        users_data = c.fetchall(); conn.close()
        if not users_data: return await query.edit_message_text("Active User မရှိပါ။", reply_markup=BACK_TO_ADMIN_MARKUP)
        try: client = get_outline_client(); all_keys = client.get_keys()
        except Exception as e: return await query.edit_message_text(f"❌ Server Error: {e}", reply_markup=BACK_TO_ADMIN_MARKUP)
        
        await safe_delete_message(query.message)
        await context.bot.send_message(chat_id=update.effective_chat.id, text="👥 <b>Active Users List (Real-time)</b>", parse_mode='HTML')
        for tid, uname, ptype, edate, kid, dlimit, current_bytes, prev_bytes, ext_key in users_data:
            if str(kid).startswith('ext_'):
                final_url = ext_key if ext_key else "Key မမှတ်မိသေးပါ (Record အဟောင်း)"
                total_used_bytes = current_bytes + (prev_bytes or 0)
            else:
                matched_key = next((k for k in all_keys if str(k.key_id) == str(kid)), None)
                final_url = f"{matched_key.access_url.split('#')[0]}#{urllib.parse.quote(matched_key.name or f'Key_{kid}')}" if matched_key else "Key Not Found"
                total_used_bytes = (int(getattr(matched_key, 'used_bytes', 0) or 0) if matched_key else current_bytes) + (prev_bytes or 0)
                
            data_info = f"📊 Data: <code>{total_used_bytes/1e9:.2f}GB / {dlimit/1e9:.2f}GB</code>" if dlimit else f"📊 Data: <code>{total_used_bytes/1e9:.2f}GB</code>"
            user_msg = f"👤 {get_mention(tid, uname)} (ID: <code>{tid}</code>)\n📦 Plan: <code>{ptype}</code>\n⏳ Exp: <code>{edate or 'No Exp'}</code>\n{data_info}\n🔑 Key: <code>{final_url}</code>"
            await context.bot.send_message(chat_id=update.effective_chat.id, text=user_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🗑 ဤ Key အား ဖျက်မည်", callback_data=f"adm_delkey_{kid}")]]), parse_mode='HTML')
            await asyncio.sleep(0.05)
        await context.bot.send_message(chat_id=update.effective_chat.id, text="👇 အခြားလုပ်ဆောင်ရန်", reply_markup=BACK_TO_ADMIN_MARKUP)

    elif data == 'admin_broadcast':
        context.user_data['state'] = 'waiting_for_broadcast'
        await query.edit_message_text("📢 **Broadcast စာတိုပေးပို့ရန်**\n\nUser များအားလုံးထံသို့ ပေးပို့လိုသော စာသားကို ရိုက်ထည့်ပါ:", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'admin_reset_system':
        msg = "⚠️ **သတိပေးချက် (System Reset)** ⚠️\n\nယခုလုပ်ဆောင်ချက်သည် စမ်းသပ်ထားသော User များ၊ Plan များ၊ ငွေကြေးမှတ်တမ်းများအားလုံးကို Database မှ အပြီးတိုင် ဖျက်ပစ်မည်ဖြစ်ပြီး၊ Outline Server ပေါ်ရှိ သက်ဆိုင်ရာ Key များကိုပါ ဖျက်ပစ်မည် ဖြစ်ပါသည်။\n\n**တကယ် Reset ချမှာ သေချာပြီလား?**"
        kb = [[InlineKeyboardButton("✅ သေချာပါသည် (Reset All)", callback_data='confirm_reset_all')], [InlineKeyboardButton("❌ မလုပ်တော့ပါ (Cancel)", callback_data='back_to_admin')]]
        await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == 'confirm_reset_all':
        await query.edit_message_text("⏳ စနစ်တစ်ခုလုံးကို ရှင်းလင်းနေပါသည်... ခဏစောင့်ပါ။")
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT key_id FROM plans")
            all_keys = c.fetchall()
            if all_keys:
                client = get_outline_client()
                for kid in all_keys:
                    try: client.delete_key(kid[0])
                    except: pass
            c.execute("TRUNCATE TABLE plans, users RESTART IDENTITY CASCADE")
            conn.close()
            await query.edit_message_text("✅ **စနစ်တစ်ခုလုံးကို အောင်မြင်စွာ Reset ချလိုက်ပါပြီ©**", reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')
        except Exception as e: await query.edit_message_text(f"❌ Error ဖြစ်နေပါသည်: {e}", reply_markup=BACK_TO_ADMIN_MARKUP)

    elif data == 'admin_manual_key':
        context.user_data['state'] = 'waiting_for_manual_key'
        plan_list = "\n".join([f"▪️ `{k}` - {v['short_name']}" for k, v in plans_dict.items()])
        msg = f"🔑 **Manual Key ထုတ်ရန်**\n\nအောက်ပါအတိုင်း `|` ခံ၍ ရိုက်ထည့်ပါ။\n`Telegram ID | User Name | Plan Key`\n\n📌 ဥပမာ - `09123456789 | Kyaw Kyaw | plan_50gb`\n\n📋 **ရရှိနိုင်သော Plans:**\n{plan_list}"
        await query.edit_message_text(text=msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'admin_edit_plans':
        kb = [[InlineKeyboardButton(p_info['short_name'], callback_data=f"editplan_{p_key}")] for p_key, p_info in plans_dict.items()]
        kb.append([InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')])
        await query.edit_message_text("📝 **နာမည်ပြောင်းလိုသော Plan ကို ရွေးချယ်ပါ:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith('editplan_'):
        plan_key = data.replace('editplan_', '')
        context.user_data['state'] = f'waiting_for_plan_name_{plan_key}'
        msg = f"✏️ ရွေးချယ်ထားသော Plan: `{plans_dict.get(plan_key, {}).get('short_name', plan_key)}`\n\n**Plan အမည်သစ်ကို | ခံ၍ ရိုက်ထည့်ပါ။**\n`Short Name | Display Name`"
        await query.edit_message_text(msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')

    elif data == 'send_feedback':
        context.user_data['state'] = 'waiting_for_feedback'
        await safe_delete_message(query.message)
        await context.bot.send_message(user_id, "📝 **အကြံပြုစာရေးရန်**\n\nအကြံပြုချက်များကို အောက်တွင် စာရိုက်၍ ပေးပို့နိုင်ပါသည်။", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')

    elif data == 'how_to_use':
        kb = [[InlineKeyboardButton("🤖 Android", callback_data='htu_android'), InlineKeyboardButton("🍎 Apple (iOS)", callback_data='htu_apple')], [InlineKeyboardButton("💻 PC (Windows)", callback_data='htu_pc')], [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        await query.edit_message_text("📱 **မိမိအသုံးပြုမည့် Device ကို ရွေးချယ်ပါ:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data in ('htu_android', 'htu_apple', 'htu_pc'): await send_htu_guide(query, context, data.replace('htu_', ''))

    elif data == 'buy_plan':
        await query.edit_message_text(text="🛒 **ဝယ်ယူလိုသော Plan ကို ရွေးချယ်ပါ:**", reply_markup=get_plans_keyboard(plans_dict), parse_mode='Markdown')
        
    elif data == 'my_plan':
        await query.edit_message_text("⏳ ရှာဖွေနေပါသည်...")
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT plan_type, data_limit, start_date, end_date, current_used_bytes, is_active, expired_at, key_id, previous_used_bytes, external_key FROM plans WHERE telegram_id=%s AND is_active IN (0, 1)", (user_id,))
        user_plans = c.fetchall(); conn.close()
        if not user_plans: return await query.edit_message_text("မှတ်တမ်း မရှိသေးပါ။", reply_markup=BACK_TO_MAIN_MARKUP)
        try: client = get_outline_client(); all_keys = client.get_keys()
        except: return await query.edit_message_text(f"❌ Server Error.", reply_markup=BACK_TO_MAIN_MARKUP)
        msg = "👤 **လက်ရှိ Plan နှင့် မှတ်တမ်းများ**\n\n"
        for ptype, dlimit, sdate, edate, current_bytes, is_active, exp_at, kid, prev_bytes, ext_key in user_plans:
            if str(kid).startswith('ext_'):
                total_used_bytes = current_bytes + (prev_bytes or 0)
                status_text = "🟢 **Active**" if is_active == 1 else "🔴 **Expired**"
                msg += f"🔹 **Plan:** `{ptype}`\n📌 **Status:** {status_text}\n📅 **စဝယ်သည့်ရက်:** `{sdate[:10]}`\n⏳ **Exp:** `{edate[:10] if edate else 'No Exp'}`\n"
                if dlimit: msg += f"📊 **Usage:** `{total_used_bytes/1e9:.2f} GB` / `{dlimit/1e9:.2f} GB`\n"
                msg += f"🔑 **Key:** `{ext_key if ext_key else 'Key Not Found'}`"
                msg += f"\n🛑 **ရပ်စဲသည့်အချိန်:** `{exp_at}`\n---\n" if is_active == 0 and exp_at else "\n---\n"
            else:
                matched_key = next((k for k in all_keys if str(k.key_id) == str(kid)), None) if is_active == 1 else None
                total_used_bytes = (int(getattr(matched_key, 'used_bytes', 0) or 0) if matched_key else current_bytes) + (prev_bytes or 0)
                status_text = "🟢 **Active**" if is_active == 1 else "🔴 **Expired**"
                msg += f"🔹 **Plan:** `{ptype}`\n📌 **Status:** {status_text}\n📅 **စဝယ်သည့်ရက်:** `{sdate[:10]}`\n⏳ **Exp:** `{edate[:10] if edate else 'No Exp'}`\n📊 **Usage:** `{total_used_bytes/1e9:.2f} GB` / `{dlimit/1e9:.2f} GB`" if dlimit else f"📊 **Usage:** `{total_used_bytes/1e9:.2f} GB`"
                msg += f"\n🛑 **ရပ်စဲသည့်အချိန်:** `{exp_at}`\n---\n" if is_active == 0 and exp_at else "\n---\n"
        await query.edit_message_text(text=msg, reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')

    elif data in plans_dict:
        context.user_data['pending_plan'] = data
        context.user_data['action_type'] = 'buy'
        await safe_delete_message(query.message)
        await context.bot.send_message(user_id, "💰 **KPay သို့ ငွေလွှဲပါ**\n👤 Name: `U Aung Pyae`\n📞 `09952130817`\n📝 Note: `shopping`\n\n📸 **ငွေလွှဲပြေစာ (Screenshot)** ကို ပို့ပေးပါ။", parse_mode='Markdown')

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    doc = update.message.document; state = context.user_data.get('state')
    
    if state == 'wait_up_pc':
        conn = get_db(); c = conn.cursor(); c.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ('pc_installer_file_id', doc.file_id)); conn.commit(); conn.close()
        await update.message.reply_text(f"✅ PC Installer သိမ်းပြီးပါပြီ©", reply_markup=BACK_TO_ADMIN_MARKUP)
    else: await update.message.reply_text("❌ လုပ်ဆောင်ချက် မှားယွင်းနေပါသည်။")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS and 'pending_plan' not in context.user_data: return
    user_id = update.effective_user.id; state = context.user_data.get('state'); photo_id = update.message.photo[-1].file_id
    
    if state in ['wait_up_android', 'wait_up_ios', 'wait_up_welcome']:
        db_key = 'android_guide_file_id' if state == 'wait_up_android' else ('ios_guide_file_id' if state == 'wait_up_ios' else 'welcome_image_id')
        conn = get_db(); c = conn.cursor(); c.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (db_key, photo_id)); conn.commit(); conn.close()
        del context.user_data['state']; await update.message.reply_text("✅ ပုံသိမ်းပြီးပါပြီ©", reply_markup=BACK_TO_ADMIN_MARKUP)
    elif 'pending_plan' in context.user_data:
        plan = context.user_data.pop('pending_plan')
        action_type = context.user_data.pop('action_type', 'buy')
        user_name = get_user_display_name(update.effective_user)
        disp = get_plan_details().get(plan, {}).get('short_name', plan)
        
        payment_id = str(uuid.uuid4())[:8]
        if 'payments' not in context.bot_data: context.bot_data['payments'] = {}
        context.bot_data['payments'][payment_id] = {'user_id': user_id, 'plan_key': plan, 'action_type': action_type, 'user_name': user_name, 'msgs': []}
        kb = [[InlineKeyboardButton("✅ Approve & Send Key", callback_data=f"pay_app_{payment_id}")], [InlineKeyboardButton("❌ Reject", callback_data=f"pay_rej_{payment_id}")]]
        
        for admin in ADMIN_IDS:
            try: 
                msg = await context.bot.send_photo(admin, photo=photo_id, caption=f"🔔 <b>New Payment!</b>\n\n👤 User: {get_mention(user_id, user_name)}\n📦 Plan: <code>{disp}</code>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                context.bot_data['payments'][payment_id]['msgs'].append((admin, msg.message_id))
            except: pass
        await update.message.reply_text("✅ ငွေလွှဲပြေစာကို Admin ထံ ပို့ဆောင်ပြီးပါပြီ©")
    else:
        await update.message.reply_text("⚠️ ကျေးဇူးပြု၍ Plan အရင်ရွေးချယ်ပြီးမှ Screenshot ပို့ပေးပါ။")

async def admin_approval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("pay_"): return
    parts = query.data.split("_")
    action_code, payment_id = parts[1], parts[2]
    payment_info = context.bot_data.get('payments', {}).get(payment_id)
    
    if not payment_info:
        try: await query.edit_message_caption(caption=f"{query.message.caption_html}\n\n⚠️ <b>ဤပြေစာကို လုပ်ဆောင်ပြီးဖြစ်ပါသည်။</b>", parse_mode='HTML')
        except: pass
        return
        
    target_user_id, plan_key, target_uname, msgs_to_edit = payment_info['user_id'], payment_info['plan_key'], payment_info['user_name'], payment_info['msgs']
    
    if action_code == "app":
        context.user_data['state'] = f"wait_ext_key_{payment_id}"
        for adm_id, msg_id in msgs_to_edit:
            try: await context.bot.edit_message_caption(chat_id=adm_id, message_id=msg_id, caption=f"{query.message.caption_html}\n\n⏳ <b>Key ရိုက်ထည့်ရန် စောင့်ဆိုင်းနေပါသည်...</b>\n👇 ယခု User အတွက် ပေးလိုသော External Access URL (Key) ကို အောက်တွင် စာရိုက်၍ ပို့ပေးပါ။", parse_mode='HTML')
            except: pass
        return 
        
    elif action_code == "rej":
        del context.bot_data['payments'][payment_id]
        for adm_id, msg_id in msgs_to_edit:
            try: await context.bot.edit_message_caption(chat_id=adm_id, message_id=msg_id, caption=f"{query.message.caption_html}\n\n--- <b>❌ Rejected</b> ---", parse_mode='HTML')
            except: pass
        await context.bot.send_message(target_user_id, "❌ **ငွေသွင်းမှု မအောင်မြင်ပါ။**\n\nငွေသွင်းပြေစာ မှားယွင်းနေပါသည်။", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')

async def fb_approval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("fbapp_"):
        try:
            rest = data[6:]; parts = rest.rsplit("_", 1); plan_code, fb_psid = parts[0], parts[1]
            get_or_create_user(int(fb_psid), username=f"FB_{fb_psid}")
            plan_info = get_plan_details().get(plan_code)
            access_url, key_name = generate_vpn_key(int(fb_psid), plan_info['plan_type'], plan_info['data_gb'], plan_info['months'])
            fb_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
            url = f"https://graph.facebook.com/v18.0/me/messages?access_token={fb_token}"
            requests.post(url, json={"recipient": {"id": fb_psid}, "message": {"text": f"🎉 အတည်ပြုပြီးပါပြီ©\nName: {key_name}\nKey: {access_url}"}})
            await query.edit_message_caption(caption=f"✅ Approved for FB User!")
        except Exception as e: await query.edit_message_caption(caption=f"❌ Error: {e}")

async def check_expired_keys(context: ContextTypes.DEFAULT_TYPE):
    conn = get_db(); c = conn.cursor(); now_str = get_mmt_now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT p.key_id, p.telegram_id, p.plan_type, u.username, p.end_date, p.data_limit, p.previous_used_bytes FROM plans p JOIN users u ON p.telegram_id = u.telegram_id WHERE p.is_active = 1")
    active_plans = c.fetchall()
    if active_plans:
        try: client = get_outline_client(); all_keys = client.get_keys(); usage_dict = calculate_and_sync_usage(all_keys)
        except: conn.close(); return
        for kid, tid, ptype, uname, end_date, dlimit, prev_bytes in active_plans:
            total_used = usage_dict.get(str(kid), 0) + (prev_bytes or 0)
            if (end_date and end_date <= now_str) or (dlimit and total_used >= dlimit):
                try: client.delete_key(kid)
                except: pass
                c.execute("UPDATE plans SET is_active = 0, expired_at = %s WHERE key_id = %s", (now_str, kid))
                await context.bot.send_message(tid, "⚠️ **သက်တမ်းကုန်ဆုံးပါပြီ©**", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
    c.execute("DELETE FROM plans WHERE is_active = 0 AND expired_at <= %s", ((get_mmt_now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),))
    conn.commit(); conn.close()

async def post_init(application: Application):
    await application.bot.set_my_commands([BotCommand("start", "Main Menu")], scope=BotCommandScopeDefault())
    for admin in ADMIN_IDS:
        try: await application.bot.set_my_commands([BotCommand("start", "Main Menu"), BotCommand("admin", "Admin Panel")], scope=BotCommandScopeChat(chat_id=admin))
        except: pass

def main():
    keep_alive(); app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    if app.job_queue:
        app.job_queue.run_repeating(check_expired_keys, interval=60, first=10)
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("restore", restore_data_command)) 
    app.add_handler(CommandHandler("deluser", delete_user_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(fb_approval_handler, pattern="^fb(app|rej)_"))
    app.add_handler(CallbackQueryHandler(admin_approval_handler, pattern="^pay_(app|rej)_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    print("✅ Bot is running successfully...")
    app.run_polling()

if __name__ == '__main__': main()
