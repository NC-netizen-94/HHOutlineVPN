import logging
import sqlite3
import uuid
import os
import asyncio
import re
import html 
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from outline_vpn.outline_vpn import OutlineVPN

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
        except Exception: pass

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
    conn = sqlite3.connect('happyhive.db')
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
    conn = sqlite3.connect('happyhive.db')
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
    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()
    api_url = c.execute("SELECT value FROM settings WHERE key='outline_api_url'").fetchone()[0]
    cert_sha = c.execute("SELECT value FROM settings WHERE key='outline_cert_sha256'").fetchone()[0]
    conn.close()
    return OutlineVPN(api_url=api_url, cert_sha256=cert_sha)

def get_or_create_user(telegram_id, username="User", referred_by=None):
    conn = sqlite3.connect('happyhive.db')
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
    conn = sqlite3.connect('happyhive.db')
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

# --- Core Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('state', None)
    user = update.effective_user
    username = get_user_display_name(user)
    referred_by = int(context.args[0]) if context.args and context.args[0].isdigit() and int(context.args[0]) != user.id else None
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
        "🛡️ **Private & Secure:** သီးသန့် Private Server ကို အသုံးပြုထားလို့ လိုင်းကျတာ လုံးဝမရှိပါဘူး။\n"
        "⚡️ **High Speed:** ကမ္ဘာ့အကောင်းဆုံး AWS Server များဖြစ်လို့ အမြန်နှုန်း အပြည့်ရပါမယ်။\n"
        "🔒 **100% Safe:** ကိုယ်ရေးအချက်အလက်များကို လုံးဝ မှတ်သားထားခြင်း မရှိပါ။\n\n"
        "👇 အောက်ပါ Menu များမှတဆင့် ရွေးချယ်ပါ ခင်ဗျာ။"
    )
    if update.message:
        await update.message.reply_text("👇 အောက်ပါ ခလုတ်များကိုလည်း အလွယ်တကူ အသုံးပြုနိုင်ပါသည်။", reply_markup=get_bottom_keyboard(user.id))
        if os.path.exists(WELCOME_IMAGE_PATH):
            with open(WELCOME_IMAGE_PATH, 'rb') as f: await context.bot.send_photo(chat_id=update.effective_chat.id, photo=f)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await safe_delete_message(update.callback_query.message)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [
        [InlineKeyboardButton("👥 View Users Plans", callback_data='admin_view_users'), InlineKeyboardButton("⚠️ Expiring Soon", callback_data='admin_expiring')],
        [InlineKeyboardButton("➕ Manual Key ထုတ်ရန်", callback_data='admin_manual_key'), InlineKeyboardButton("📝 Plan အမည်များ ပြင်ရန်", callback_data='admin_edit_plans')],
        [InlineKeyboardButton("📊 စီးပွားရေးနှင့် Server အခြေအနေ", callback_data='admin_server_stats'), InlineKeyboardButton("🗑️ System Reset", callback_data='admin_reset_system')],
        [InlineKeyboardButton("⚙️ Change API", callback_data='admin_change_api'), InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast')]
    ]
    msg = "🛡️ **Admin Panel ရောက်ပါပြီ။**"
    if update.message: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id, data = query.from_user.id, query.data
    plans_dict = get_plan_details()

    if data == 'back_to_main': await start(update, context)
    elif data == 'back_to_admin': await admin_panel(update, context)
    elif data == 'share_referral':
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        share_url = f"https://t.me/share/url?url={ref_link}&text=🌟 HappyHive VPN ကို စမ်းသုံးကြည့်ဖို့ ဖိတ်ခေါ်ပါတယ် ခင်ဗျာ။"
        msg = "🎁 **Referral အစီအစဉ် (1GB လက်ဆောင်ယူရန်)**\n\nသူငယ်ချင်းကို ဖိတ်ခေါ်ပါ။ သူငယ်ချင်းမှ Plan ဝယ်ယူပြီးစီးမှသာ လူကြီးမင်းအတွက် **Data 1GB** ကို အလိုအလျောက် ပေါင်းထည့်ပေးပါမည်။"
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 ယခုပဲ မျှဝေရန်", url=share_url)], [InlineKeyboardButton("🔙 Menu", callback_data='back_to_main')]]), parse_mode='Markdown')
    
    elif data in ('buy_plan', 'extend_plan'):
        context.user_data['action_type'] = 'extend' if data == 'extend_plan' else 'buy'
        msg = "🛒 **ဝယ်ယူလိုသော Plan ကို ရွေးချယ်ပါ:**" if data == 'buy_plan' else "🔄 **သက်တမ်းတိုးရန် (သို့) Data ထပ်ဝယ်ရန် Plan ရွေးပါ:**"
        await query.edit_message_text(msg, reply_markup=get_plans_keyboard(plans_dict), parse_mode='Markdown')
        
    elif data == 'my_plan':
        conn = sqlite3.connect('happyhive.db')
        active_plans = conn.cursor().execute("SELECT key_id, plan_type, data_limit, start_date, end_date FROM plans WHERE telegram_id=? AND is_active=1", (user_id,)).fetchall()
        conn.close()
        if not active_plans: return await query.edit_message_text("❌ လက်ရှိ Plan မရှိသေးပါ။", reply_markup=BACK_TO_MAIN_MARKUP)
        client = get_outline_client()
        keys = client.get_keys()
        msg = "👤 **လက်ရှိ Plan အချက်အလက်များ**\n\n"
        for kid, ptype, dlimit, sdate, edate in active_plans:
            used_gb = next(((getattr(k, 'used_bytes', 0) or 0) / 1e9 for k in keys if str(k.key_id) == str(kid)), 0)
            msg += f"🔹 **Plan:** `{ptype}`\n📅 **ဝယ်ယူရက်:** `{sdate[:10]}`\n⏳ **ကုန်ဆုံးရက်:** `{edate[:10] if edate else 'No Expiry'}`\n📊 **သတ်မှတ် Data:** `{dlimit/1e9 if dlimit else 0:.2f} GB`\n📈 **အသုံးပြုပြီး Data:** `{used_gb:.2f} GB`\n---\n"
        await query.edit_message_text(msg, reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')

    elif data == 'free_trial':
        conn = sqlite3.connect('happyhive.db')
        used = conn.cursor().execute("SELECT is_trial_used FROM users WHERE telegram_id=?", (user_id,)).fetchone()[0]
        if used: await query.edit_message_text("⚠️ အစမ်းသုံးခြင်းကို အသုံးပြုပြီးဖြစ်ပါသည်။", reply_markup=BACK_TO_MAIN_MARKUP)
        else:
            try:
                url, name = generate_vpn_key(user_id, "FreeTrial", data_gb=3)
                conn.cursor().execute("UPDATE users SET is_trial_used=1 WHERE telegram_id=?", (user_id,))
                conn.commit()
                await query.edit_message_text(f"✅ **Free Trial 3GB ရရှိပါပြီ။ (၅) ရက် အသုံးပြုနိုင်ပါသည်။**\n\n`{url}`", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
            except Exception as e: await query.edit_message_text(f"❌ Error: {e}")
        conn.close()

    elif data == 'admin_server_stats':
        try:
            conn = sqlite3.connect('happyhive.db')
            now = datetime.now()
            current_m, current_y = now.strftime("%Y-%m"), now.strftime("%Y")
            PLAN_PRICES = {'10GB': 800, '20GB': 1200, '30GB': 1500, '40GB': 2000, '50GB': 3000, '100GB': 4000}
            all_plans = conn.cursor().execute("SELECT plan_type, start_date FROM plans WHERE plan_type != 'FreeTrial'").fetchall()
            monthly_rev = sum(PLAN_PRICES.get(p[0], 0) for p in all_plans if p[1].startswith(current_m))
            yearly_rev = sum(PLAN_PRICES.get(p[0], 0) for p in all_plans if p[1].startswith(current_y))
            client = get_outline_client()
            keys = client.get_keys()
            total_used_gb = sum((getattr(k, 'used_bytes', 0) or 0) for k in keys) / 1e9
            msg = (f"📊 **Financial Report**\n\n📅 **ယခုလဝင်ငွေ:** `{monthly_rev:,} ကျပ်`\n📆 **ယခုနှစ်ဝင်ငွေ:** `{yearly_rev:,} ကျပ်`\n\n"
                   f"💽 **Server Stats**\n▪️ Keys: `{len(keys)}` ခု\n▪️ Data Used: `{total_used_gb:.2f} GB` / 1000 GB")
            await query.edit_message_text(msg, reply_markup=BACK_TO_ADMIN_MARKUP, parse_mode='Markdown')
        except Exception as e: await query.edit_message_text(f"❌ Error: {e}")

    elif data in plans_dict:
        context.user_data['pending_plan'] = data
        await safe_delete_message(query.message)
        msg = f"💰 **ငွေပေးချေရန်**\nKPay: `09799844344` (Nyein Chan)\n📝 Note: `shopping` ဟုရေးပါ\n\nပြီးလျှင် ပြေစာ (Screenshot) ပို့ပေးပါ။"
        await context.bot.send_message(user_id, msg, parse_mode='Markdown')
        if os.path.exists(PAYMENT_QR_PATH):
            with open(PAYMENT_QR_PATH, 'rb') as f: await context.bot.send_photo(user_id, f, reply_markup=BACK_TO_MAIN_MARKUP)

    elif data == 'how_to_use':
        kb = [[InlineKeyboardButton("🤖 Android", callback_data='htu_android'), InlineKeyboardButton("🍎 iOS", callback_data='htu_apple')], [InlineKeyboardButton("🔙 Menu", callback_data='back_to_main')]]
        await query.edit_message_text("📱 **ဖုန်းအမျိုးအစား ရွေးချယ်ပါ:**", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data in ('htu_android', 'htu_apple'):
        path = ANDROID_SS_PATH if data == 'htu_android' else APPLE_SS_PATH
        if os.path.exists(path):
            with open(path, 'rb') as f: await context.bot.send_photo(user_id, f, caption="အသုံးပြုပုံလမ်းညွှန်", reply_markup=BACK_TO_MAIN_MARKUP)
        else: await query.edit_message_text("ပုံမရှိသေးပါ။", reply_markup=BACK_TO_MAIN_MARKUP)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, user_name = update.effective_user.id, get_user_display_name(update.effective_user)
    if 'pending_plan' in context.user_data:
        plan, action = context.user_data.pop('pending_plan'), context.user_data.pop('action_type', 'buy')
        kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{plan}_{action}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]]
        await context.bot.send_photo(ADMIN_ID, update.message.photo[-1].file_id, caption=f"🔔 <b>New Payment</b>\nUser: {get_mention(user_id, user_name)}\nPlan: {plan}\nAction: {action}", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
        await update.message.reply_text("✅ ပြေစာပို့ပြီးပါပြီ။ Admin အတည်ပြုသည်အထိ ခဏစောင့်ပေးပါ။")

async def admin_approval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p = query.data.split("_")
    action, tid = p[0], int(p[1])
    if action == "approve":
        plan_key, req_action = f"{p[2]}_{p[3]}", p[4]
        plan_info = get_plan_details().get(plan_key)
        try:
            client = get_outline_client()
            conn = sqlite3.connect('happyhive.db')
            if req_action == 'extend':
                active = conn.cursor().execute("SELECT key_id, data_limit, end_date FROM plans WHERE telegram_id=? AND is_active=1 ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
                if active:
                    kid, old_limit, old_end = active
                    new_limit = (old_limit or 0) + (plan_info['data_gb'] * 1e9)
                    curr_end = max(datetime.now(), datetime.strptime(old_end, "%Y-%m-%d %H:%M:%S")) if old_end else datetime.now()
                    new_end = curr_end + timedelta(days=30)
                    client.add_data_limit(kid, int(new_limit))
                    conn.cursor().execute("UPDATE plans SET data_limit=?, end_date=? WHERE key_id=?", (new_limit, new_end.strftime("%Y-%m-%d %H:%M:%S"), kid))
                    conn.commit()
                    await context.bot.send_message(tid, f"✅ သက်တမ်းတိုးပြီးပါပြီ။ အသုံးပြုနိုင်ပါပြီ။", reply_markup=BACK_TO_MAIN_MARKUP)
                else: req_action = 'buy'
            if req_action == 'buy':
                url, name = generate_vpn_key(tid, plan_info['plan_type'], plan_info['data_gb'], plan_info['months'])
                await context.bot.send_message(tid, f"✅ ဝယ်ယူမှုအောင်မြင်ပါသည်။ 👇\n\n`{url}`", reply_markup=BACK_TO_MAIN_MARKUP, parse_mode='Markdown')
            
            # Referral Bonus
            ref_data = conn.cursor().execute("SELECT referred_by, referral_reward_claimed FROM users WHERE telegram_id=?", (tid,)).fetchone()
            if ref_data and ref_data[0] and ref_data[1] == 0:
                referrer_id = ref_data[0]
                ref_plan = conn.cursor().execute("SELECT key_id, data_limit FROM plans WHERE telegram_id=? AND is_active=1 ORDER BY id DESC LIMIT 1", (referrer_id,)).fetchone()
                if ref_plan:
                    new_ref_limit = ref_plan[1] + 1e9
                    client.add_data_limit(ref_plan[0], int(new_ref_limit))
                    conn.cursor().execute("UPDATE plans SET data_limit=? WHERE key_id=?", (new_ref_limit, ref_plan[0]))
                    conn.cursor().execute("UPDATE users SET referral_reward_claimed=1 WHERE telegram_id=?", (tid,))
                    conn.commit()
                    await context.bot.send_message(referrer_id, "🎁 သူငယ်ချင်းဝယ်ယူမှုကြောင့် Bonus 1GB ရရှိပါသည်။")
            
            await send_auto_backup(context, tid, "User", "Process Finish")
            await query.edit_message_caption("✅ Approved")
            conn.close()
        except Exception as e: await context.bot.send_message(ADMIN_ID, f"❌ Error: {e}")
    elif action == "reject":
        await context.bot.send_message(tid, "❌ ငွေသွင်းမှု မအောင်မြင်ပါ။ ပြေစာမှားယွင်းနေပါသည်။")
        await query.edit_message_caption("❌ Rejected")

async def check_expired_keys(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('happyhive.db')
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expired = conn.cursor().execute("SELECT key_id, telegram_id FROM plans WHERE end_date <= ? AND is_active=1", (now,)).fetchall()
    if expired:
        client = get_outline_client()
        for kid, tid in expired:
            try:
                client.delete_key(kid)
                conn.cursor().execute("UPDATE plans SET is_active=0 WHERE key_id=?", (kid,))
                await context.bot.send_message(tid, "⚠️ သက်တမ်းကုန်ဆုံးသွားပါပြီ။")
            except: pass
        conn.commit()
    conn.close()

async def post_init(application: Application):
    await application.bot.set_my_commands([BotCommand("start", "Main Menu")], scope=BotCommandScopeDefault())

def main():
    # 🌟 JobQueue Activate လုပ်ထားပါသည် 🌟
    app = Application.builder().token(BOT_TOKEN).job_queue(None).post_init(post_init).build()
    if app.job_queue:
        app.job_queue.run_repeating(check_expired_keys, interval=60, first=10)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(admin_approval_handler, pattern="^(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: start(u, c) if u.message.text == "🏠 ပင်မ မီနူးသို့သွားပါ" else (admin_panel(u, c) if u.message.text == "🛡️ Admin Panel" else None)))
    
    print("✅ Bot is running successfully...")
    app.run_polling()

if __name__ == '__main__':
    main()
