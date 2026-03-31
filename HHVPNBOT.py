import logging
import sqlite3
import uuid
import os
import asyncio
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from outline_vpn.outline_vpn import OutlineVPN

# --- Configuration (မိမိအချက်အလက်များ) ---
BOT_TOKEN = "8633829411:AAGZ9Vd6uqmwpjvxdjWs3h6dF1Uc2osUd4I"
ADMIN_ID = 1656832105
FB_LINK = "https://facebook.com/HappyHiveVPN"
ADMIN_CONTACT_LINK = "https://t.me/HappyHive9496"

# ⚠️ အောက်ပါ YOUR_BOT_USERNAME နေရာတွင် မိမိ Bot ၏ Username (ဥပမာ - HappyHiveVPN_bot) ကို အစားထိုးပါ ⚠️
BOT_SHARE_LINK = "https://t.me/share/url?url=https://t.me/HHVPN_bot&text=🌟 မြန်နှုန်းမြင့်ပြီး လုံခြုံစိတ်ချရတဲ့ HappyHive VPN ကို အသုံးပြုကြည့်ဖို့ ဖိတ်ခေါ်ပါတယ် ခင်ဗျာ။ 👇"

# ⚠️ ပုံဖိုင်အမည်များ သတ်မှတ်ခြင်း ⚠️
WELCOME_IMAGE_PATH = "welcome.jpg"
ANDROID_SS_PATH = "android_ss.jpg"  # Android အသုံးပြုပုံ Screenshot
APPLE_SS_PATH = "apple_ss.jpg"      # Apple အသုံးပြုပုံ Screenshot
PAYMENT_QR_PATH = "kpay_qr.jpg"     # ⚠️ ငွေပေးချေရန် KPay QR Code ပုံ ⚠️

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (telegram_id INTEGER PRIMARY KEY, unique_id TEXT, is_trial_used INTEGER)''')
    
    try:
        c.execute("ALTER TABLE users ADD COLUMN username TEXT")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE users ADD COLUMN has_rated INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS plans
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER, key_id TEXT, 
                  plan_type TEXT, data_limit INTEGER, start_date TEXT, end_date TEXT, is_active INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('outline_api_url', 'https://52.74.77.216:3584/j55zpDNtFPRSEVGYYK__XQ')")
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('outline_cert_sha256', '15AABC7E72C56F04C1DB2953ABD078D0ECAC4DF72F59C83D3090015882D0954A')")
    
    conn.commit()
    conn.close()

init_db()

# --- ⚠️ Markdown Error ဖြေရှင်းရန် အဆင့်မြှင့်ထားသော Helper Function ⚠️ ---
def safe_name(text):
    """User ၏ နာမည်တွင် Markdown Error ဖြစ်စေမည့် သင်္ကေတများအားလုံးကို အပြီးတိုင် ဖယ်ရှားမည်"""
    if not text:
        return "User"
    # ဖယ်ရှားမည့် သင်္ကေတများ (() ဂွင်းများပါ အပါအဝင်)
    cleaned_text = re.sub(r'[*_\[\]()~`>#+\-=|{}.!]', '', str(text))
    if not cleaned_text.strip():
        return "User"
    return cleaned_text.strip()

# --- Outline Client ခေါ်ယူသည့်အပိုင်း ---
def get_outline_client():
    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='outline_api_url'")
    api_url = c.fetchone()[0]
    
    c.execute("SELECT value FROM settings WHERE key='outline_cert_sha256'")
    cert_sha256 = c.fetchone()[0]
    conn.close()
    
    return OutlineVPN(api_url=api_url, cert_sha256=cert_sha256)

def get_or_create_user(telegram_id, username="User"):
    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()
    c.execute("SELECT unique_id, is_trial_used FROM users WHERE telegram_id=?", (telegram_id,))
    user = c.fetchone()
    if not user:
        unique_id = str(uuid.uuid4())[:8].upper()
        c.execute("INSERT INTO users (telegram_id, unique_id, is_trial_used, username) VALUES (?, ?, 0, ?)", (telegram_id, unique_id, username))
        conn.commit()
        user = (unique_id, 0)
    else:
        c.execute("UPDATE users SET username=? WHERE telegram_id=?", (username, telegram_id))
        conn.commit()
    conn.close()
    return user

# --- Bottom Keyboard (Reply Keyboard) ဖန်တီးသည့်အပိုင်း ---
def get_bottom_keyboard(user_id):
    if user_id == ADMIN_ID:
        return ReplyKeyboardMarkup([["🏠 ပင်မ မီနူးသို့သွားပါ", "🛡️ Admin Panel"]], resize_keyboard=True, is_persistent=True)
    else:
        return ReplyKeyboardMarkup([["🏠 ပင်မ မီနူးသို့သွားပါ"]], resize_keyboard=True, is_persistent=True)

# --- Core Functions (Key ဖန်တီးသည့်အပိုင်း) ---
def generate_vpn_key(telegram_id, plan_type, data_gb=None, months=None):
    client = get_outline_client()
    
    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()
    c.execute("SELECT unique_id, username FROM users WHERE telegram_id=?", (telegram_id,))
    row = c.fetchone()
    unique_id = row[0]
    raw_username = row[1] if row[1] else "User"
    
    safe_username = safe_name(raw_username).replace(" ", "_")

    new_key = client.create_key()
    
    start_date = datetime.now()
    start_date_str = start_date.strftime("%Y-%m-%d")
    db_start_date = start_date.strftime("%Y-%m-%d %H:%M:%S")
    db_end_date = None
    end_date = None
    
    if plan_type == "FreeTrial":
        end_date = start_date + timedelta(days=5)
        db_end_date = end_date.strftime("%Y-%m-%d %H:%M:%S")
    elif months:
        end_date = start_date + timedelta(days=30 * months)
        db_end_date = end_date.strftime("%Y-%m-%d %H:%M:%S")
    
    if months and end_date:
        end_date_str = end_date.strftime('%Y-%m-%d')
        suffix = f"HHVPN_{telegram_id}_{safe_username}_{unique_id}_{plan_type}_{start_date_str}_{end_date_str}"
    else:
        suffix = f"HHVPN_{telegram_id}_{safe_username}_{unique_id}_{plan_type}_{start_date_str}"

    client.rename_key(new_key.key_id, suffix)
    
    data_bytes = None
    if data_gb:
        data_bytes = data_gb * 1000 * 1000 * 1000
        client.add_data_limit(new_key.key_id, data_bytes)
        
    c.execute('''INSERT INTO plans (telegram_id, key_id, plan_type, data_limit, start_date, end_date, is_active)
                 VALUES (?, ?, ?, ?, ?, ?, 1)''', 
              (telegram_id, new_key.key_id, plan_type, data_bytes, db_start_date, db_end_date))
    conn.commit()
    conn.close()
    
    base_url = new_key.access_url.split('#')[0]
    final_access_url = f"{base_url}#{suffix}"
    
    return final_access_url, suffix

# --- Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'state' in context.user_data:
        del context.user_data['state']
        
    user = update.effective_user
    username = user.username or user.first_name
    get_or_create_user(user.id, username)
    
    keyboard = [
        [InlineKeyboardButton("🎁 Free အစမ်းသုံးရန်", callback_data='free_trial')],
        [InlineKeyboardButton("🛒 Plan ဝယ်ရန်", callback_data='buy_plan')],
        [InlineKeyboardButton("👤 မိမိ၏ Plan/ Data သုံးစွဲမှုမှတ်တမ်း", callback_data='my_plan')],
        [InlineKeyboardButton("🔄 သက်တမ်းတိုးရန်", callback_data='extend_plan')],
        [InlineKeyboardButton("❓ အသုံးပြုပုံ", callback_data='how_to_use')],
        [InlineKeyboardButton("📝 အကြံပြုစာရေးရန် (သင့်ID ကိုမဖော်ပြပါ)", callback_data='send_feedback')],
        [InlineKeyboardButton("📢 သူငယ်ချင်းများသို့ မျှဝေရန်", url=BOT_SHARE_LINK)],
        [InlineKeyboardButton("👨‍💻 Admin ကို ဆက်သွယ်ရန်", url=ADMIN_CONTACT_LINK)],
        [InlineKeyboardButton("🌐 Facebook Page သို့သွားရန်", url=FB_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "🌟 **Welcome to HappyHive VPN!** 🌟\n\n"
        "မြန်နှုန်းမြင့်ပြီး လုံခြုံစိတ်ချရသော VPN ဝန်ဆောင်မှုမှ ကြိုဆိုပါတယ်။\n"
        "အောက်ပါ Menu များမှတဆင့် မိမိအသုံးပြုလိုသော ဝန်ဆောင်မှုကို ရွေးချယ်နိုင်ပါသည်။ 👇"
    )
    
    if update.message:
        if update.message.text == '/start':
            await update.message.reply_text("👇 အောက်ပါ ခလုတ်များကိုလည်း အလွယ်တကူ အသုံးပြုနိုင်ပါသည်။", reply_markup=get_bottom_keyboard(user.id))
            
            if os.path.exists(WELCOME_IMAGE_PATH):
                try:
                    with open(WELCOME_IMAGE_PATH, 'rb') as photo_file:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo_file,
                            read_timeout=20,
                            write_timeout=20
                        )
                except Exception as e:
                    logging.error(f"Error sending photo: {e}")
                    
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=welcome_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=welcome_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
    elif update.callback_query:
        message = update.callback_query.message
        if message.photo:
            try:
                await message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=welcome_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            try:
                await update.callback_query.edit_message_text(
                    text=welcome_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=welcome_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    keyboard = [
        [InlineKeyboardButton("👥 View Users Plans", callback_data='admin_view_users')],
        [InlineKeyboardButton("⚠️ Expiring Soon Users", callback_data='admin_expiring')],
        [InlineKeyboardButton("⚙️ Change Outline API", callback_data='admin_change_api')],
        [InlineKeyboardButton("📢 အသိပေးစာပေးပို့ရန် (Broadcast)", callback_data='admin_broadcast')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text('🛡️ **Admin Panel ရောက်ပါပြီ။**', reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        try:
            await update.callback_query.message.delete()
        except:
            pass
        await context.bot.send_message(chat_id=update.effective_chat.id, text='🛡️ **Admin Panel ရောက်ပါပြီ။**', reply_markup=reply_markup, parse_mode='Markdown')

# --- Text Message Handler (Bottom Keyboard, Feedback နှင့် Broadcast အတွက်) ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🏠 ပင်မ မီနူးသို့သွားပါ":
        if 'state' in context.user_data:
            del context.user_data['state']
        await start(update, context)
        return
    elif text == "🛡️ Admin Panel":
        if 'state' in context.user_data:
            del context.user_data['state']
        await admin_panel(update, context)
        return
        
    # --- Feedback အတွက် ---
    if context.user_data.get('state') == 'waiting_for_feedback':
        admin_msg = f"💌 **New Anonymous Feedback** 💌\n\n💬 Message:\n{text}"
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode='Markdown')
        
        del context.user_data['state']
        
        keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("✅ ကျေးဇူးတင်ပါသည်။ လူကြီးမင်း၏ အကြံပြုစာကို Admin ထံသို့ လျှို့ဝှက်ပေးပို့ပြီးပါပြီ။", reply_markup=reply_markup)

    # --- Broadcast (Admin သီးသန့်) အတွက် ---
    elif context.user_data.get('state') == 'waiting_for_broadcast' and update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("⏳ Broadcast စတင်ပေးပို့နေပါသည်... ခဏစောင့်ပါ။")
        
        conn = sqlite3.connect('happyhive.db')
        c = conn.cursor()
        c.execute("SELECT DISTINCT telegram_id FROM users")
        all_users = c.fetchall()
        conn.close()
        
        success_count = 0
        failed_count = 0
        broadcast_msg = f"📢 **Admin မှ အသိပေးချက်**\n\n{text}"
        
        for user_row in all_users:
            uid = user_row[0]
            try:
                await context.bot.send_message(chat_id=uid, text=broadcast_msg, parse_mode='Markdown')
                success_count += 1
                await asyncio.sleep(0.05) 
            except Exception:
                failed_count += 1
                
        del context.user_data['state']
        
        summary_msg = (
            f"✅ **Broadcast ပေးပို့ခြင်း ပြီးဆုံးပါပြီ။**\n\n"
            f"🟢 အောင်မြင်: `{success_count}` ဦး\n"
            f"🔴 မအောင်မြင်: `{failed_count}` ဦး (Bot ကို Block ထားသူများ)"
        )
        keyboard = [[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]]
        await context.bot.send_message(chat_id=ADMIN_ID, text=summary_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# --- Admin Delete User Command ---
async def delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
        
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("❌ အသုံးပြုပုံ မှားယွင်းနေပါသည်။\nဥပမာ - `/deluser 123456789`", parse_mode='Markdown')
        return
        
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID သည် ဂဏန်းသာ ဖြစ်ရပါမည်။")
        return

    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()

    c.execute("SELECT key_id FROM plans WHERE telegram_id=?", (target_id,))
    user_plans = c.fetchall()

    if user_plans:
        try:
            client = get_outline_client()
            for plan in user_plans:
                key_id = plan[0]
                try:
                    client.delete_key(key_id)
                except Exception as e:
                    logging.error(f"Error deleting key {key_id} from Outline Server: {e}")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Outline Server နှင့် ချိတ်ဆက်၍မရသဖြင့် Key ကိုဖျက်၍မရပါ။ သို့သော် Database မှ ဆက်ဖျက်ပါမည်။\nError: {e}")

    c.execute("DELETE FROM plans WHERE telegram_id=?", (target_id,))
    c.execute("DELETE FROM users WHERE telegram_id=?", (target_id,))
    
    changes = conn.total_changes
    conn.commit()
    conn.close()

    if changes > 0:
        await update.message.reply_text(f"✅ User ID `{target_id}` ၏ အကောင့်နှင့် VPN Key များအားလုံးကို အောင်မြင်စွာ ဖျက်ပစ်လိုက်ပါပြီ။", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"⚠️ User ID `{target_id}` ကို Database တွင် မတွေ့ပါ။", parse_mode='Markdown')

# --- Admin API Change Command ---
async def set_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
        
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ အသုံးပြုပုံ မှားယွင်းနေပါသည်။ ဥပမာ - `/setapi API_URL CERT_SHA256` ဟု ရိုက်ထည့်ပါ။", parse_mode='Markdown')
        return
        
    api_url = args[0]
    cert_sha256 = args[1]
    
    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('outline_api_url', ?)", (api_url,))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('outline_cert_sha256', ?)", (cert_sha256,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("✅ Outline API နှင့် Cert SHA256 အသစ် ပြောင်းလဲခြင်း အောင်မြင်ပါသည်။")

# --- Rating Request Function ---
async def send_rating_request(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    keyboard = [
        [
            InlineKeyboardButton("⭐", callback_data='rate_1'),
            InlineKeyboardButton("⭐⭐", callback_data='rate_2'),
            InlineKeyboardButton("⭐⭐⭐", callback_data='rate_3')
        ],
        [
            InlineKeyboardButton("⭐⭐⭐⭐", callback_data='rate_4'),
            InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data='rate_5')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "🌟 **HappyHive VPN ကို အသုံးပြုရတာ အဆင်ပြေရဲ့လား ခင်ဗျာ?**\n\n"
        "လူကြီးမင်း၏ အတွေ့အကြုံကို အောက်ပါ ကြယ်လေးတွေနှိပ်ပြီး အမှတ်ပေး အကဲဖြတ်ပေးပါဦး ခင်ဗျာ။ "
        "လူကြီးမင်း၏ အကဲဖြတ်မှုက ကျွန်တော်တို့ ဝန်ဆောင်မှုကို ပိုမိုကောင်းမွန်လာစေရန် အများကြီး အထောက်အကူပြုပါတယ်။ 🙏"
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Failed to send rating request to {user_id}: {e}")

# --- Button Clicks ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    username = user.username or user.first_name
    get_or_create_user(user_id, username)
    data = query.data

    # --- ADMIN BUTTON HANDLERS ---
    if data == 'back_to_admin':
        if 'state' in context.user_data:
            del context.user_data['state']
        try:
            await query.message.delete()
        except Exception:
            pass
        await admin_panel(update, context)
        return

    elif data == 'admin_view_users':
        await query.edit_message_text(text="⏳ Data နှင့် VPN Keys များကို ဆွဲယူနေပါသည်... ခဏစောင့်ပါ။")
        
        conn = sqlite3.connect('happyhive.db')
        c = conn.cursor()
        c.execute("""SELECT u.telegram_id, u.username, p.plan_type, p.end_date, p.key_id 
                     FROM plans p JOIN users u ON p.telegram_id = u.telegram_id WHERE p.is_active=1""")
        users_data = c.fetchall()
        conn.close()
        
        if not users_data:
            await query.edit_message_text(text="လက်ရှိ Active ဖြစ်နေသော User မရှိသေးပါ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]]))
            return
            
        try:
            client = get_outline_client()
            all_keys = client.get_keys()
        except Exception as e:
            await query.edit_message_text(text=f"❌ Server နှင့် ချိတ်ဆက်ရာတွင် အခက်အခဲရှိနေပါသည်။\nError: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]]))
            return
            
        msg = "👥 **Active Users List**\n\n"
        for row in users_data:
            tid, uname, ptype, edate, kid = row
            uname = safe_name(uname)
            
            final_url = "Key Not Found in Server"
            for k in all_keys:
                if str(k.key_id) == str(kid):
                    base_url = k.access_url.split('#')[0]
                    name = k.name if k.name else f"Key_{kid}"
                    final_url = f"{base_url}#{name}"
                    break
            
            msg += f"👤 [{uname}](tg://user?id={tid}) (`{tid}`)\n📦 Plan: `{ptype}`\n⏳ Exp: `{edate or 'No Expiry'}`\n🔑 Key: `{final_url}`\n---\n"
            
        if len(msg) > 4000:
            msg = msg[:4000] + "\n... (စာရင်းများလွန်းသဖြင့် အချို့ကို ဖြတ်ထားပါသည်)"
            
        await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]]), parse_mode='Markdown')

    elif data == 'admin_expiring':
        conn = sqlite3.connect('happyhive.db')
        c = conn.cursor()
        today = datetime.now()
        warning_date = (today + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("""SELECT u.telegram_id, u.username, p.plan_type, p.end_date 
                     FROM plans p JOIN users u ON p.telegram_id = u.telegram_id 
                     WHERE p.is_active=1 AND p.end_date IS NOT NULL AND p.end_date <= ?""", (warning_date,))
        exp_data = c.fetchall()
        conn.close()
        
        if not exp_data:
            await query.edit_message_text(text="✅ သုံးရက်အတွင်း သက်တမ်းကုန်မည့် User မရှိပါ။", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]]))
            return
            
        msg = "⚠️ **၃ ရက်အတွင်း သက်တမ်းကုန်မည့် Users များ**\n\n"
        for row in exp_data:
            tid, uname, ptype, edate = row
            uname = safe_name(uname)
            msg += f"👤 [{uname}](tg://user?id={tid}) (`{tid}`)\n📦 Plan: `{ptype}`\n⏳ Exp: `{edate}`\n---\n"
            
        await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]]), parse_mode='Markdown')

    elif data == 'admin_change_api':
        msg = (
            "⚙️ **Outline API အသစ် ပြောင်းလဲရန်**\n\n"
            "API URL နှင့် Cert SHA256 အသစ်ကို ပြောင်းလဲလိုပါက အောက်ပါ Command ကို Copy ကူးပြီး Edit လုပ်ကာ Chat ထဲသို့ ပို့ပေးပါ။\n\n"
            "`/setapi YOUR_API_URL YOUR_CERT_SHA256`\n\n"
            "**ဥပမာ:**\n"
            "`/setapi https://1.2.3.4:1234/xyz 15AABC7E72...`"
        )
        await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]]), parse_mode='Markdown')

    elif data == 'admin_broadcast':
        context.user_data['state'] = 'waiting_for_broadcast'
        keyboard = [[InlineKeyboardButton("🔙 Admin Panel သို့ ပြန်သွားရန်", callback_data='back_to_admin')]]
        await query.edit_message_text(
            text="📢 **အသိပေးစာ (Broadcast) ပေးပို့ရန်**\n\nBot ကို အသုံးပြုထားသူများအားလုံးထံ ပေးပို့လိုသော စာသားကို အောက်တွင် ရိုက်ထည့်ပါ။\n\n*(အောက်ခြေ Menu မှ ခလုတ်တစ်ခုခုကို နှိပ်ပါက Broadcast အစီအစဉ် ပယ်ဖျက်သွားပါမည်။)*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    # --- HOW TO USE HANDLERS ---
    elif data == 'how_to_use':
        keyboard = [
            [InlineKeyboardButton("🤖 Android", callback_data='htu_android'),
             InlineKeyboardButton("🍎 Apple (iOS)", callback_data='htu_apple')],
            [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]
        ]
        await query.edit_message_text(text="📱 **မိမိအသုံးပြုမည့် ဖုန်းအမျိုးအစားကို ရွေးချယ်ပါ:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data == 'htu_android':
        keyboard = [
            [InlineKeyboardButton("📥 Outline App Download ဆွဲရန်", url="https://play.google.com/store/apps/details?id=org.outline.android.client&hl=en_SG")],
            [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.message.delete()
        except Exception:
            pass
        
        await context.bot.send_message(
            chat_id=user_id, 
            text="🤖 **Android ဖုန်းများအတွက် အသုံးပြုပုံ**\n\nအောက်ပါပုံတွင် ကြည့်ရှုနိုင်ပါသည်။", 
            parse_mode='Markdown'
        )
        
        if os.path.exists(ANDROID_SS_PATH):
            with open(ANDROID_SS_PATH, 'rb') as photo_file:
                await context.bot.send_photo(
                    chat_id=user_id, 
                    photo=photo_file, 
                    caption="App ကို Download ဆွဲယူရန် အောက်ပါ Menu ကိုနှိပ်ပါ။ 👇", 
                    reply_markup=reply_markup, 
                    parse_mode='Markdown'
                )
        else:
            await context.bot.send_message(
                chat_id=user_id, 
                text="App ကို Download ဆွဲယူရန် အောက်ပါ Menu ကိုနှိပ်ပါ။ 👇\n\n*(⚠️ ပုံဖိုင်ကို Folder ထဲတွင် မတွေ့ပါ။)*", 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )

    elif data == 'htu_apple':
        keyboard = [
            [InlineKeyboardButton("📥 Outline App Download ဆွဲရန်", url="https://apps.apple.com/us/app/outline-app/id1356177741")],
            [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.message.delete()
        except Exception:
            pass
        
        await context.bot.send_message(
            chat_id=user_id, 
            text="🍎 **Apple (iOS) ဖုန်းများအတွက် အသုံးပြုပုံ**\n\nအောက်ပါပုံတွင် ကြည့်ရှုနိုင်ပါသည်။", 
            parse_mode='Markdown'
        )
        
        if os.path.exists(APPLE_SS_PATH):
            with open(APPLE_SS_PATH, 'rb') as photo_file:
                await context.bot.send_photo(
                    chat_id=user_id, 
                    photo=photo_file, 
                    caption="App ကို Download ဆွဲယူရန် အောက်ပါ Menu ကိုနှိပ်ပါ။ 👇", 
                    reply_markup=reply_markup, 
                    parse_mode='Markdown'
                )
        else:
            await context.bot.send_message(
                chat_id=user_id, 
                text="App ကို Download ဆွဲယူရန် အောက်ပါ Menu ကိုနှိပ်ပါ။ 👇\n\n*(⚠️ ပုံဖိုင်ကို Folder ထဲတွင် မတွေ့ပါ။)*", 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )

    # --- FEEDBACK HANDLER ---
    elif data == 'send_feedback':
        context.user_data['state'] = 'waiting_for_feedback'
        
        keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.message.delete()
        except Exception:
            pass
            
        await context.bot.send_message(
            chat_id=user_id,
            text="📝 **အကြံပြုစာရေးရန်**\n\nလူကြီးမင်း၏ အကြံပြုချက်၊ ဝေဖန်ချက် သို့မဟုတ် အခက်အခဲများကို အောက်တွင် စာရိုက်၍ ပေးပို့နိုင်ပါသည်။\n\n*(မှတ်ချက် - ဤစာလွှာသည် Admin ထံသို့ အမည်မဖော်ပြဘဲ လျှို့ဝှက်ပေးပို့မည် ဖြစ်ပါသည်။)*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    # --- RATING HANDLER ---
    elif data.startswith('rate_'):
        rating = data.split('_')[1]
        
        await query.edit_message_text(
            text=f"💖 ကြယ် ({rating}) ပွင့် ပေးတဲ့အတွက် အထူးကျေးဇူးတင်ပါတယ် ခင်ဗျာ!\n\nနောက်ထပ် အခက်အခဲများရှိပါက Admin ထံ အချိန်မရွေး ဆက်သွယ်နိုင်ပါသည်။", 
            parse_mode='Markdown'
        )
        
        safe_uname = safe_name(username)
        await context.bot.send_message(
            chat_id=ADMIN_ID, 
            text=f"🌟 **New Rating Received!**\n\n👤 User: [{safe_uname}](tg://user?id={user_id})\n⭐️ Rating: **{rating} Stars**", 
            parse_mode='Markdown'
        )

    # --- USER BUTTON HANDLERS ---
    elif data == 'free_trial':
        conn = sqlite3.connect('happyhive.db')
        c = conn.cursor()
        c.execute("SELECT is_trial_used FROM users WHERE telegram_id=?", (user_id,))
        is_used = c.fetchone()[0]
        
        if is_used == 1:
            keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text="⚠️ လူကြီးမင်းသည် Free Trial ကို အသုံးပြုပြီးဖြစ်ပါသည်။ ကျေးဇူးပြု၍ Plan ဝယ်ယူပါ။", reply_markup=reply_markup)
        else:
            await query.edit_message_text(text="⏳ Free Trial 3GB Key ကို ဖန်တီးနေပါသည်... ခဏစောင့်ပါ။")
            try:
                access_url, key_name = generate_vpn_key(user_id, "FreeTrial", data_gb=3)
                c.execute("UPDATE users SET is_trial_used=1 WHERE telegram_id=?", (user_id,))
                conn.commit()
                
                info_msg = f"✅ **လူကြီးမင်း၏ Free Trial ရရှိပါပြီ။**\n⏱ **(၅) ရက်တိတိ အသုံးပြုနိုင်ပါသည်။**\n\n👤 **Name:** `{key_name}`\n\n*(အောက်ပါ Key ကို တစ်ချက်နှိပ်၍ Copy ကူးကာ Outline App တွင် ထည့်သွင်းအသုံးပြုနိုင်ပါသည်။)* 👇"
                keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await query.message.delete()
                except Exception:
                    pass
                
                await context.bot.send_message(chat_id=user_id, text=info_msg, reply_markup=reply_markup, parse_mode='Markdown')
                await context.bot.send_message(chat_id=user_id, text=f"`{access_url}`", parse_mode='Markdown')
            except Exception as e:
                await query.edit_message_text(text=f"❌ Server နှင့် ချိတ်ဆက်ရာတွင် အခက်အခဲရှိနေပါသည်။ Error: {e}")
        conn.close()

    elif data == 'buy_plan':
        keyboard = [
            [InlineKeyboardButton("📦 50GB Plan (သက်တမ်းကုန်ဆုံးရက်မရှိ)", callback_data='plan_50gb')],
            [InlineKeyboardButton("📦 100GB Plan (သက်တမ်းကုန်ဆုံးရက်မရှိ)", callback_data='plan_100gb')],
            [InlineKeyboardButton("📆 ၁လ Plan", callback_data='plan_1mo')],
            [InlineKeyboardButton("📆 ၂လ Plan", callback_data='plan_2mo')],
            [InlineKeyboardButton("📆 ၃လ Plan", callback_data='plan_3mo')],
            [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="🛒 **ဝယ်ယူလိုသော Plan ကို ရွေးချယ်ပါ:**", reply_markup=reply_markup, parse_mode='Markdown')
        
    elif data == 'my_plan':
        await query.edit_message_text(text="⏳ အချက်အလက်များ ရှာဖွေနေပါသည်... ခဏစောင့်ပါ။")
        
        conn = sqlite3.connect('happyhive.db')
        c = conn.cursor()
        c.execute("SELECT key_id, plan_type, data_limit, start_date, end_date FROM plans WHERE telegram_id=? AND is_active=1", (user_id,))
        active_plans = c.fetchall()
        
        if not active_plans:
            keyboard = [
                [InlineKeyboardButton("🛒 Plan ဝယ်ရန်", callback_data='buy_plan')],
                [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]
            ]
            await query.edit_message_text(text="❌ လူကြီးမင်းတွင် လက်ရှိ အသုံးပြုနေသော Plan မရှိသေးပါ။ ကျေးဇူးပြု၍ Plan အသစ်ဝယ်ယူပါ။", reply_markup=InlineKeyboardMarkup(keyboard))
            conn.close()
            return
            
        try:
            client = get_outline_client()
            all_keys = client.get_keys()
        except Exception as e:
            await query.edit_message_text(text="❌ Server နှင့် ချိတ်ဆက်ရာတွင် အခက်အခဲရှိနေပါသည်။ ပြန်လည်ကြိုးစားကြည့်ပါ။")
            conn.close()
            return

        msg = "👤 **လူကြီးမင်း၏ လက်ရှိ Plan အချက်အလက်များ**\n\n"
        for plan in active_plans:
            db_key_id, plan_type, data_limit, start_date, end_date = plan
            
            used_bytes = 0
            for k in all_keys:
                if str(k.key_id) == str(db_key_id):
                    used_bytes = k.used_bytes if k.used_bytes else 0
                    break
            
            used_gb = used_bytes / (1000 * 1000 * 1000)
            
            display_plan_type = plan_type
            if plan_type == "50GB": display_plan_type = "50GB Plan (သက်တမ်းကုန်ဆုံးရက်မရှိ)"
            elif plan_type == "100GB": display_plan_type = "100GB Plan (သက်တမ်းကုန်ဆုံးရက်မရှိ)"
            elif plan_type == "1Month": display_plan_type = "၁လ Plan"
            elif plan_type == "2Months": display_plan_type = "၂လ Plan"
            elif plan_type == "3Months": display_plan_type = "၃လ Plan"

            msg += f"🔹 **Plan:** `{display_plan_type}`\n"
            msg += f"📅 **စဝယ်သည့်ရက်:** `{start_date}`\n"
            if end_date:
                msg += f"⏳ **ကုန်ဆုံးမည့်ရက်:** `{end_date}`\n"
            
            if data_limit:
                limit_gb = data_limit / (1000 * 1000 * 1000)
                msg += f"📊 **Data Limit:** `{limit_gb:.2f} GB`\n"
            
            msg += f"📈 **အသုံးပြုပြီး Data:** `{used_gb:.2f} GB`\n"
            msg += "------------------------\n"
            
        keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        conn.close()

    elif data == 'extend_plan':
        keyboard = [
            [InlineKeyboardButton("📦 50GB Plan (သက်တမ်းကုန်ဆုံးရက်မရှိ)", callback_data='plan_50gb')],
            [InlineKeyboardButton("📦 100GB Plan (သက်တမ်းကုန်ဆုံးရက်မရှိ)", callback_data='plan_100gb')],
            [InlineKeyboardButton("📆 ၁လ Plan", callback_data='plan_1mo')],
            [InlineKeyboardButton("📆 ၂လ Plan", callback_data='plan_2mo')],
            [InlineKeyboardButton("📆 ၃လ Plan", callback_data='plan_3mo')],
            [InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="🔄 **သက်တမ်းတိုးရန် (သို့) Data ထပ်ဝယ်ရန် အောက်ပါ Plan များကို ရွေးချယ်ပါ:**\n\n*(မှတ်ချက် - ဝယ်ယူမှု အောင်မြင်ပါက VPN Key အသစ်တစ်ခု ထပ်မံရရှိမည် ဖြစ်ပါသည်။)*", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith('plan_'):
        plan_selected = data
        context.user_data['pending_plan'] = plan_selected
        
        try:
            await query.message.delete()
        except Exception:
            pass

        payment_msg = (
            "💰 **ငွေပေးချေရန် အချက်အလက်များ**\n\n"
            "လူကြီးမင်းရွေးချယ်ထားသော Plan အတွက် အောက်ပါ KPay အကောင့်သို့ ငွေလွှဲပေးပါ။\n"
            "📝 **Note မှာ shopping လို့ရေးပေးပါ**\n\n"
            "👤 Name: `Nyein Chan`\n\n"
            "📸 ငွေလွှဲပြီးပါက **ငွေလွှဲပြေစာ (Screenshot)** ကို ဤ Bot အတွင်းသို့ တိုက်ရိုက် ပို့ပေးပါ။"
        )
        await context.bot.send_message(chat_id=user_id, text=payment_msg, parse_mode='Markdown')
        
        await context.bot.send_message(chat_id=user_id, text="`09799844344`", parse_mode='Markdown')
        
        keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if os.path.exists(PAYMENT_QR_PATH):
            with open(PAYMENT_QR_PATH, 'rb') as photo_file:
                await context.bot.send_photo(
                    chat_id=user_id, 
                    photo=photo_file, 
                    reply_markup=reply_markup
                )
        else:
            await context.bot.send_message(
                chat_id=user_id, 
                text="*(⚠️ QR Code ပုံ ထည့်သွင်းထားခြင်း မရှိပါ။)*", 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
        
    elif data == 'back_to_main':
        if 'state' in context.user_data:
            del context.user_data['state']
        try:
            await query.message.delete()
        except:
            pass
        await start(update, context)

# --- Photo/Payment Upload Handling ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = safe_name(update.effective_user.first_name)
    
    if 'pending_plan' in context.user_data:
        plan = context.user_data['pending_plan']
        photo_file_id = update.message.photo[-1].file_id
        
        display_plan_type = plan
        if plan == 'plan_50gb': display_plan_type = "50GB Plan"
        elif plan == 'plan_100gb': display_plan_type = "100GB Plan"
        elif plan == 'plan_1mo': display_plan_type = "၁လ Plan"
        elif plan == 'plan_2mo': display_plan_type = "၂လ Plan"
        elif plan == 'plan_3mo': display_plan_type = "၃လ Plan"

        keyboard = [
            [InlineKeyboardButton("✅ Approve & Send Key", callback_data=f"approve_{user_id}_{plan}")],
            [InlineKeyboardButton("❌ Reject Payment", callback_data=f"reject_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_photo(
            chat_id=ADMIN_ID, 
            photo=photo_file_id, 
            # ⚠️ Plan ကို Backticks ဖြင့် ထုပ်ထားပါသည် ⚠️
            caption=f"🔔 **New Payment Received!**\n\n👤 User: [{user_name}](tg://user?id={user_id})\n📦 Plan: `{display_plan_type}`", 
            reply_markup=reply_markup, 
            parse_mode='Markdown'
        )
        
        await update.message.reply_text("✅ ငွေလွှဲပြေစာကို Admin ထံ ပို့ဆောင်ပြီးပါပြီ။ အတည်ပြုပြီးပါက VPN Key ကျလာပါမည်။ ခဏစောင့်ပေးပါ။")
        del context.user_data['pending_plan']
    else:
        await update.message.reply_text("⚠️ ကျေးဇူးပြု၍ 'Plan ဝယ်ရန်' သို့မဟုတ် 'သက်တမ်းတိုးရန်' မှတဆင့် မိမိဝယ်ယူမည့် Plan ကို အရင်ရွေးချယ်ပြီးမှ Screenshot ပို့ပေးပါ။")

# --- Admin Approval Actions ---
async def admin_approval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    parts = data.split("_", 2)
    target_user_id = int(parts[1])
    
    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()
    c.execute("SELECT username, has_rated FROM users WHERE telegram_id=?", (target_user_id,))
    row = c.fetchone()
    target_uname = safe_name(row[0] if row and row[0] else "User")
    has_rated = row[1] if row and len(row) > 1 else 0
    
    if data.startswith("approve_"):
        plan = parts[2]
        
        display_plan_type = plan
        if plan == 'plan_50gb': display_plan_type = "50GB Plan"
        elif plan == 'plan_100gb': display_plan_type = "100GB Plan"
        elif plan == 'plan_1mo': display_plan_type = "၁လ Plan"
        elif plan == 'plan_2mo': display_plan_type = "၂လ Plan"
        elif plan == 'plan_3mo': display_plan_type = "၃လ Plan"
        
        # ⚠️ Plan အား Backticks ` ` ဖြင့် သေချာ ထုပ်ပေးထားပါသည် ⚠️
        await query.edit_message_caption(caption=f"✅ Approved [{target_uname}](tg://user?id={target_user_id}) for `{display_plan_type}`. Generating Key...", parse_mode='Markdown')
        
        try:
            access_url, key_name = None, None
            
            if plan == 'plan_50gb':
                access_url, key_name = generate_vpn_key(target_user_id, "50GB", data_gb=50)
            elif plan == 'plan_100gb':
                access_url, key_name = generate_vpn_key(target_user_id, "100GB", data_gb=100)
            elif plan == 'plan_1mo':
                access_url, key_name = generate_vpn_key(target_user_id, "1Month", months=1)
            elif plan == 'plan_2mo':
                access_url, key_name = generate_vpn_key(target_user_id, "2Months", months=2)
            elif plan == 'plan_3mo':
                access_url, key_name = generate_vpn_key(target_user_id, "3Months", months=3)
            else:
                raise Exception("Plan အမည် မှားယွင်းနေပါသည်။")
            
            info_msg = (
                f"🎉 **ငွေသွင်းမှု အတည်ပြုပြီးပါပြီ။**\n\n"
                f"လူကြီးမင်း၏ VPN Key ကို အောက်တွင် ရယူနိုင်ပါသည်။\n\n"
                f"👤 **Name:** `{key_name}`\n\n"
                f"*(အောက်ပါ Key ကို တစ်ချက်နှိပ်၍ Copy ကူးကာ Outline App တွင် ထည့်သွင်းအသုံးပြုနိုင်ပါသည်။)* 👇"
            )
            keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
            await context.bot.send_message(chat_id=target_user_id, text=info_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
            await context.bot.send_message(chat_id=target_user_id, text=f"`{access_url}`", parse_mode='Markdown')
            
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"✅ Key Successfully sent to [{target_uname}](tg://user?id={target_user_id}).", parse_mode='Markdown')
            
            if has_rated == 0:
                context.job_queue.run_once(send_rating_request, 3600, data=target_user_id, name=f"rating_{target_user_id}")
                c.execute("UPDATE users SET has_rated=1 WHERE telegram_id=?", (target_user_id,))
                conn.commit()
            
        except Exception as e:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Error generating key: {str(e)}")

    elif data.startswith("reject_"):
        await query.edit_message_caption(caption=f"❌ Rejected Payment for [{target_uname}](tg://user?id={target_user_id}).", parse_mode='Markdown')
        
        keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
        await context.bot.send_message(chat_id=target_user_id, text="❌ **ငွေသွင်းမှု မအောင်မြင်ပါ။**\n\nလူကြီးမင်း၏ ငွေသွင်းပြေစာမှာ မှားယွင်းနေသဖြင့် ငြင်းပယ်လိုက်ပါသည်။ လိုအပ်ပါက Admin သို့ ဆက်သွယ်ပါ။", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        
    conn.close()

# --- Auto Background Checker (Every 60 Seconds) ---
async def check_expired_keys(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('happyhive.db')
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute("""SELECT p.key_id, p.telegram_id, p.plan_type, u.username 
                 FROM plans p JOIN users u ON p.telegram_id = u.telegram_id 
                 WHERE p.end_date IS NOT NULL AND p.end_date <= ? AND p.is_active = 1""", (now_str,))
    expired_plans = c.fetchall()
    
    if expired_plans:
        client = get_outline_client()
        for plan in expired_plans:
            key_id, telegram_id, plan_type, uname = plan
            uname = safe_name(uname)
            try:
                client.delete_key(key_id)
                c.execute("UPDATE plans SET is_active = 0 WHERE key_id = ?", (key_id,))
                
                keyboard = [[InlineKeyboardButton("🔙 Menu သို့ပြန်သွားရန်", callback_data='back_to_main')]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                if plan_type == "FreeTrial":
                    alert_msg = "⚠️ လူကြီးမင်း၏ **(၅) ရက် Free Trial** သက်တမ်း ကုန်ဆုံးသွားပါပြီ။ ဆက်လက်အသုံးပြုလိုပါက Plan ဝယ်ယူနိုင်ပါသည်။"
                else:
                    alert_msg = "⚠️ လူကြီးမင်း၏ **VPN သက်တမ်း** ကုန်ဆုံးသွားပါပြီ။ ဆက်လက်အသုံးပြုလိုပါက သက်တမ်းတိုး (Extend) ပြုလုပ်နိုင်ပါသည်။"
                    
                await context.bot.send_message(chat_id=telegram_id, text=alert_msg, reply_markup=reply_markup, parse_mode='Markdown')
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"♻️ Auto-deleted expired key ID `{key_id}` for [{uname}](tg://user?id={telegram_id}) (Plan: `{plan_type}`).", parse_mode='Markdown')
            except Exception as e:
                logging.error(f"Failed to delete key {key_id}: {e}")
            
    conn.commit()
    conn.close()

# --- Post Init Setup (Menu Commands Scope) ---
async def post_init(application: Application):
    await application.bot.set_my_commands(
        [BotCommand("start", "ပင်မ မီနူးသို့ သွားရန် (Main Menu)")],
        scope=BotCommandScopeDefault()
    )
    
    try:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "ပင်မ မီနူးသို့ သွားရန် (Main Menu)"),
                BotCommand("admin", "Admin Panel သို့ သွားရန်"),
                BotCommand("setapi", "Outline API အသစ်ပြောင်းရန်"),
                BotCommand("deluser", "User ကို အပြီးဖျက်ရန်")
            ],
            scope=BotCommandScopeChat(chat_id=ADMIN_ID)
        )
    except Exception as e:
        logging.warning(f"Admin commands set up skipped: {e}")

# --- Main App Execution ---
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("setapi", set_api_command))
    app.add_handler(CommandHandler("deluser", delete_user_command)) 
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    app.add_handler(CallbackQueryHandler(admin_approval_handler, pattern="^(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    app.job_queue.run_repeating(check_expired_keys, interval=60, first=10)

    print("✅ Bot is running successfully... (Press Ctrl+C to stop)")
    app.run_polling()

if __name__ == '__main__':
    main()