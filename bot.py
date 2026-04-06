import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import threading
import time
from datetime import datetime, timedelta

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== قاعدة البيانات ==========
conn = sqlite3.connect("reminder.db", check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    points INTEGER DEFAULT 10,
    total_shares INTEGER DEFAULT 0
)''')
c.execute('''CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    channel_id TEXT,
    duration_seconds INTEGER,
    duration_value INTEGER,
    duration_unit TEXT,
    message TEXT,
    media_type TEXT,
    media_file_id TEXT,
    is_active INTEGER DEFAULT 1
)''')
c.execute('''CREATE TABLE IF NOT EXISTS repeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    channel_id TEXT,
    interval_value INTEGER,
    interval_unit TEXT,
    interval_seconds INTEGER,
    end_value INTEGER,
    end_unit TEXT,
    end_time REAL,
    message TEXT,
    media_type TEXT,
    media_file_id TEXT,
    is_active INTEGER DEFAULT 1
)''')
c.execute('''CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER,
    referred_id INTEGER,
    date TEXT
)''')
conn.commit()

def get_user(user_id):
    c.execute("SELECT points, total_shares FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, points, total_shares) VALUES (?,?,?)", (user_id, 10, 0))
        conn.commit()
        return {"points": 10, "total_shares": 0}
    return {"points": row[0], "total_shares": row[1]}

def update_points(user_id, delta):
    c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (delta, user_id))
    conn.commit()

def add_share(user_id):
    c.execute("UPDATE users SET total_shares = total_shares + 1 WHERE user_id=?", (user_id,))
    c.execute("SELECT total_shares FROM users WHERE user_id=?", (user_id,))
    shares = c.fetchone()[0]
    if shares % 1 == 0:
        c.execute("UPDATE users SET points = points + 3 WHERE user_id=?", (user_id,))
    conn.commit()

def add_referral(referrer_id, referred_id):
    c.execute("SELECT * FROM referrals WHERE referred_id=?", (referred_id,))
    if c.fetchone():
        return False
    c.execute("INSERT INTO referrals (referrer_id, referred_id, date) VALUES (?,?,?)", 
              (referrer_id, referred_id, datetime.now().isoformat()))
    update_points(referrer_id, 3)
    conn.commit()
    return True

temp_data = {}

# ========== دالة تنسيق الوقت ==========
def format_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def convert_to_seconds(value, unit):
    if unit == "minutes":
        return value * 60
    elif unit == "hours":
        return value * 3600
    else:
        return value

def convert_unit_text(unit):
    if unit == "minutes":
        return "دقائق"
    elif unit == "hours":
        return "ساعات"
    else:
        return "ثواني"

# ========== المنبه مع الساعة التنازلية ==========
def run_reminder_timer(user_id, duration_seconds, reminder_id, channel_id, message, media_type, media_file_id):
    remaining = duration_seconds
    last_msg_id = None
    
    while remaining > 0:
        c.execute("SELECT is_active FROM reminders WHERE id=?", (reminder_id,))
        row = c.fetchone()
        if not row or row[0] == 0:
            return
        
        time_str = format_time(remaining)
        text = f"⏰ *الوقت المتبقي:*\n`{time_str}`"
        
        if last_msg_id:
            try:
                bot.edit_message_text(text, user_id, last_msg_id, parse_mode="Markdown")
            except:
                last_msg_id = bot.send_message(user_id, text, parse_mode="Markdown").message_id
        else:
            last_msg_id = bot.send_message(user_id, text, parse_mode="Markdown").message_id
        
        time.sleep(1)
        remaining -= 1
    
    if last_msg_id:
        try:
            bot.delete_message(user_id, last_msg_id)
        except:
            pass
    
    chat_id = channel_id if channel_id and channel_id != "None" else user_id
    
    try:
        if media_type == "photo":
            bot.send_photo(chat_id, media_file_id, caption=message if message else "⏰ انتهى وقت المنبه!")
        elif media_type == "document":
            bot.send_document(chat_id, media_file_id, caption=message if message else "⏰ انتهى وقت المنبه!")
        elif media_type == "video":
            bot.send_video(chat_id, media_file_id, caption=message if message else "⏰ انتهى وقت المنبه!")
        else:
            bot.send_message(chat_id, message if message else "⏰ انتهى وقت المنبه!")
    except Exception as e:
        bot.send_message(user_id, f"❌ فشل إرسال المنبه: {e}")
    
    c.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    conn.commit()
    bot.send_message(user_id, "✅ تم إرسال المنبه بنجاح!")

# ========== التكرار ==========
def run_repeat_timer(repeat_id, interval_seconds, user_id, channel_id, message, media_type, media_file_id, end_time):
    count = 1
    while True:
        time.sleep(interval_seconds)
        
        if time.time() >= end_time:
            c.execute("UPDATE repeats SET is_active=0 WHERE id=?", (repeat_id,))
            conn.commit()
            bot.send_message(user_id, f"✅ انتهى وقت التكرار المحدد. تم إرسال {count} رسالة.")
            break
        
        c.execute("SELECT is_active FROM repeats WHERE id=?", (repeat_id,))
        row = c.fetchone()
        if not row or row[0] == 0:
            break
        
        chat_id = channel_id if channel_id and channel_id != "None" else user_id
        
        try:
            if media_type == "photo":
                bot.send_photo(chat_id, media_file_id, caption=message if message else "🔄 رسالة مكررة")
            elif media_type == "document":
                bot.send_document(chat_id, media_file_id, caption=message if message else "🔄 ملف مكرر")
            elif media_type == "video":
                bot.send_video(chat_id, media_file_id, caption=message if message else "🔄 فيديو مكرر")
            else:
                bot.send_message(chat_id, message if message else "🔄 رسالة مكررة")
            count += 1
        except Exception as e:
            bot.send_message(user_id, f"❌ فشل إرسال التكرار: {e}")

# ========== أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    user = get_user(user_id)
    
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            if add_referral(int(ref), user_id):
                bot.send_message(user_id, "✅ تم تفعيل الإحالة! حصل الداعم على 3 نقاط.")
                bot.send_message(int(ref), "🎉 قام مستخدم جديد بالتسجيل عبر رابطك! تم إضافة 3 نقاط إلى رصيدك.")
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⏰ منبه جديد", callback_data="new_reminder"),
        InlineKeyboardButton("🔄 تكرار جديد", callback_data="new_repeat"),
        InlineKeyboardButton("📋 منبهاتي", callback_data="my_reminders"),
        InlineKeyboardButton("🔄 تكراراتي", callback_data="my_repeats"),
        InlineKeyboardButton("🎁 مشاركة الرابط", callback_data="share_link")
    )
    if user_id == OWNER_ID:
        markup.add(InlineKeyboardButton("🔧 لوحة التحكم", callback_data="admin_panel"))
    
    bot.send_message(user_id,
        f"🎯 *بوت المنبه والتكرار*\n\n"
        f"⭐ رصيدك: {user['points']} نقطة\n"
        f"• كل منبه أو تكرار يستهلك نقطة واحدة.\n"
        f"• احصل على نقاط عبر مشاركة الرابط (كل مشاركة = 3 نقاط).\n\n"
        f"🔗 رابط إحالتك:\n"
        f"https://t.me/{bot.get_me().username}?start={user_id}\n\n"
        f"📌 @ZeQuiz_Bot",
        parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "share_link")
def share_link(call):
    user_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, f"🎁 رابط إحالتك:\nhttps://t.me/{bot.get_me().username}?start={user_id}\n\nكل مشاركة = 3 نقاط!")

@bot.callback_query_handler(func=lambda call: call.data == "my_reminders")
def my_reminders(call):
    user_id = call.message.chat.id
    c.execute("SELECT id, duration_value, duration_unit, message FROM reminders WHERE user_id=? AND is_active=1", (user_id,))
    rows = c.fetchall()
    if not rows:
        bot.send_message(user_id, "📭 لا توجد منبهات نشطة حالياً.")
        return
    txt = "⏰ *المنبهات النشطة*\n\n"
    for rid, val, unit, msg in rows:
        unit_text = convert_unit_text(unit)
        txt += f"🆔 `{rid}` | {val} {unit_text}\n📝 {msg[:40] if msg else 'بدون نص'}\n\n"
    bot.send_message(user_id, txt, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "my_repeats")
def my_repeats(call):
    user_id = call.message.chat.id
    c.execute("SELECT id, interval_value, interval_unit, message FROM repeats WHERE user_id=? AND is_active=1", (user_id,))
    rows = c.fetchall()
    if not rows:
        bot.send_message(user_id, "📭 لا توجد تكرارات نشطة حالياً.")
        return
    txt = "🔄 *التكرارات النشطة*\n\n"
    for rid, val, unit, msg in rows:
        unit_text = convert_unit_text(unit)
        txt += f"🆔 `{rid}` | كل {val} {unit_text}\n📝 {msg[:40] if msg else 'بدون نص'}\n\n"
    bot.send_message(user_id, txt, parse_mode="Markdown")

# ========== إنشاء منبه ==========
@bot.callback_query_handler(func=lambda call: call.data == "new_reminder")
def new_reminder_start(call):
    user_id = call.message.chat.id
    user = get_user(user_id)
    if user["points"] < 1:
        bot.answer_callback_query(call.id, f"⚠️ ليس لديك نقاط كافية! رصيدك: {user['points']} نقطة", show_alert=True)
        return
    
    temp_data[user_id] = {"type": "reminder", "step": "unit"}
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("⏱️ ثواني", callback_data="reminder_unit_seconds"),
        InlineKeyboardButton("⏰ دقائق", callback_data="reminder_unit_minutes"),
        InlineKeyboardButton("🕐 ساعات", callback_data="reminder_unit_hours")
    )
    bot.edit_message_text("⏰ *اختر وحدة الوقت للمنبه*", user_id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("reminder_unit_"))
def process_reminder_unit(call):
    user_id = call.message.chat.id
    unit = call.data.split("_")[2]
    temp_data[user_id]["unit"] = unit
    temp_data[user_id]["step"] = "value"
    bot.edit_message_text(f"⌨️ *أرسل الرقم* (مثال: 30):", user_id, call.message.message_id, parse_mode="Markdown")
    bot.register_next_step_handler(call.message, process_reminder_value)

def process_reminder_value(message):
    user_id = message.chat.id
    try:
        value = int(message.text.strip())
        if value <= 0:
            raise ValueError
        temp_data[user_id]["value"] = value
        temp_data[user_id]["step"] = "channel"
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📱 البوت فقط", callback_data="reminder_channel_none"),
            InlineKeyboardButton("📢 قناة (أضف البوت أدمن)", callback_data="reminder_channel_add")
        )
        bot.send_message(user_id, "📍 *أين تريد إرسال المنبه؟*", parse_mode="Markdown", reply_markup=markup)
    except:
        bot.send_message(user_id, "❌ *خطأ:* أرسل رقماً صحيحاً أكبر من 0.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("reminder_channel_"))
def process_reminder_channel(call):
    user_id = call.message.chat.id
    if call.data == "reminder_channel_none":
        temp_data[user_id]["channel_id"] = None
        temp_data[user_id]["step"] = "message_type"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📝 نص", callback_data="reminder_msg_text"),
            InlineKeyboardButton("🖼️ صورة", callback_data="reminder_msg_photo"),
            InlineKeyboardButton("📄 ملف", callback_data="reminder_msg_document"),
            InlineKeyboardButton("🎥 فيديو", callback_data="reminder_msg_video")
        )
        bot.edit_message_text("📝 *اختر نوع المحتوى للمنبه*", user_id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
    else:
        temp_data[user_id]["step"] = "channel_id"
        bot.edit_message_text("📢 *أرسل معرف القناة* (مثال: @username):", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_reminder_channel_id)

def process_reminder_channel_id(message):
    user_id = message.chat.id
    channel_id = message.text.strip()
    temp_data[user_id]["channel_id"] = channel_id
    temp_data[user_id]["step"] = "message_type"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📝 نص", callback_data="reminder_msg_text"),
        InlineKeyboardButton("🖼️ صورة", callback_data="reminder_msg_photo"),
        InlineKeyboardButton("📄 ملف", callback_data="reminder_msg_document"),
        InlineKeyboardButton("🎥 فيديو", callback_data="reminder_msg_video")
    )
    bot.send_message(user_id, "📝 *اختر نوع المحتوى للمنبه*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("reminder_msg_"))
def process_reminder_msg_type(call):
    user_id = call.message.chat.id
    msg_type = call.data.split("_")[2]
    temp_data[user_id]["media_type"] = msg_type
    temp_data[user_id]["step"] = "content"
    
    if msg_type == "text":
        bot.edit_message_text("✏️ *أرسل النص الذي تريد إرساله عند انتهاء المنبه*", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_reminder_text)
    elif msg_type == "photo":
        bot.edit_message_text("🖼️ *أرسل الصورة*", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_reminder_media, "photo")
    elif msg_type == "document":
        bot.edit_message_text("📄 *أرسل الملف*", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_reminder_media, "document")
    elif msg_type == "video":
        bot.edit_message_text("🎥 *أرسل الفيديو*", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_reminder_media, "video")

def process_reminder_text(message):
    user_id = message.chat.id
    temp_data[user_id]["message"] = message.text
    temp_data[user_id]["media_file_id"] = None
    finalize_reminder(user_id)

def process_reminder_media(message, media_type):
    user_id = message.chat.id
    if media_type == "photo" and message.photo:
        file_id = message.photo[-1].file_id
        caption = message.caption
    elif media_type == "document" and message.document:
        file_id = message.document.file_id
        caption = message.caption
    elif media_type == "video" and message.video:
        file_id = message.video.file_id
        caption = message.caption
    else:
        bot.send_message(user_id, "❌ *نوع الملف غير صحيح* أعد المحاولة.", parse_mode="Markdown")
        return
    
    temp_data[user_id]["media_file_id"] = file_id
    temp_data[user_id]["message"] = caption or ""
    finalize_reminder(user_id)

def finalize_reminder(user_id):
    data = temp_data.pop(user_id)
    
    unit = data["unit"]
    value = data["value"]
    duration_seconds = convert_to_seconds(value, unit)
    
    update_points(user_id, -1)
    
    c.execute("INSERT INTO reminders (user_id, channel_id, duration_seconds, duration_value, duration_unit, message, media_type, media_file_id) VALUES (?,?,?,?,?,?,?,?)",
              (user_id, data.get("channel_id"), duration_seconds, value, unit, data.get("message"), data.get("media_type"), data.get("media_file_id")))
    reminder_id = c.lastrowid
    conn.commit()
    
    thread = threading.Thread(target=run_reminder_timer, args=(user_id, duration_seconds, reminder_id, data.get("channel_id"), data.get("message"), data.get("media_type"), data.get("media_file_id")))
    thread.daemon = True
    thread.start()
    
    new_user = get_user(user_id)
    unit_text = convert_unit_text(unit)
    bot.send_message(user_id, f"✅ *تم إنشاء المنبه بنجاح!*\n\n⏰ الوقت: {value} {unit_text}\n⭐ النقاط المتبقية: {new_user['points']}\n\n📢 سيظهر لك مؤقت تنازلي فوراً!", parse_mode="Markdown")

# ========== إنشاء تكرار ==========
@bot.callback_query_handler(func=lambda call: call.data == "new_repeat")
def new_repeat_start(call):
    user_id = call.message.chat.id
    user = get_user(user_id)
    if user["points"] < 1:
        bot.answer_callback_query(call.id, f"⚠️ ليس لديك نقاط كافية! رصيدك: {user['points']} نقطة", show_alert=True)
        return
    
    temp_data[user_id] = {"type": "repeat", "step": "interval_unit"}
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("⏱️ ثواني", callback_data="repeat_interval_unit_seconds"),
        InlineKeyboardButton("⏰ دقائق", callback_data="repeat_interval_unit_minutes"),
        InlineKeyboardButton("🕐 ساعات", callback_data="repeat_interval_unit_hours")
    )
    bot.edit_message_text("🔄 *اختر وحدة الوقت بين كل تكرار*", user_id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("repeat_interval_unit_"))
def process_repeat_interval_unit(call):
    user_id = call.message.chat.id
    unit = call.data.split("_")[3]
    temp_data[user_id]["interval_unit"] = unit
    temp_data[user_id]["step"] = "interval_value"
    bot.edit_message_text(f"⌨️ *أرسل الرقم* (مثال: 30):", user_id, call.message.message_id, parse_mode="Markdown")
    bot.register_next_step_handler(call.message, process_repeat_interval_value)

def process_repeat_interval_value(message):
    user_id = message.chat.id
    try:
        value = int(message.text.strip())
        if value <= 0:
            raise ValueError
        temp_data[user_id]["interval_value"] = value
        temp_data[user_id]["step"] = "end_unit"
        
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(
            InlineKeyboardButton("⏱️ ثواني", callback_data="repeat_end_unit_seconds"),
            InlineKeyboardButton("⏰ دقائق", callback_data="repeat_end_unit_minutes"),
            InlineKeyboardButton("🕐 ساعات", callback_data="repeat_end_unit_hours")
        )
        bot.send_message(user_id, "⏰ *اختر وحدة مدة انتهاء التكرار*", parse_mode="Markdown", reply_markup=markup)
    except:
        bot.send_message(user_id, "❌ *خطأ:* أرسل رقماً صحيحاً أكبر من 0.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("repeat_end_unit_"))
def process_repeat_end_unit(call):
    user_id = call.message.chat.id
    unit = call.data.split("_")[3]
    temp_data[user_id]["end_unit"] = unit
    temp_data[user_id]["step"] = "end_value"
    bot.edit_message_text(f"⌨️ *أرسل المدة* (مثال: 24):", user_id, call.message.message_id, parse_mode="Markdown")
    bot.register_next_step_handler(call.message, process_repeat_end_value)

def process_repeat_end_value(message):
    user_id = message.chat.id
    try:
        value = int(message.text.strip())
        if value <= 0:
            raise ValueError
        temp_data[user_id]["end_value"] = value
        temp_data[user_id]["step"] = "channel"
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📱 البوت فقط", callback_data="repeat_channel_none"),
            InlineKeyboardButton("📢 قناة (أضف البوت أدمن)", callback_data="repeat_channel_add")
        )
        bot.send_message(user_id, "📍 *أين تريد إرسال التكرارات؟*", parse_mode="Markdown", reply_markup=markup)
    except:
        bot.send_message(user_id, "❌ *خطأ:* أرسل رقماً صحيحاً أكبر من 0.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("repeat_channel_"))
def process_repeat_channel(call):
    user_id = call.message.chat.id
    if call.data == "repeat_channel_none":
        temp_data[user_id]["channel_id"] = None
        temp_data[user_id]["step"] = "message_type"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📝 نص", callback_data="repeat_msg_text"),
            InlineKeyboardButton("🖼️ صورة", callback_data="repeat_msg_photo"),
            InlineKeyboardButton("📄 ملف", callback_data="repeat_msg_document"),
            InlineKeyboardButton("🎥 فيديو", callback_data="repeat_msg_video")
        )
        bot.edit_message_text("📝 *اختر نوع المحتوى للتكرار*", user_id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
    else:
        temp_data[user_id]["step"] = "channel_id"
        bot.edit_message_text("📢 *أرسل معرف القناة* (مثال: @username):", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_repeat_channel_id)

def process_repeat_channel_id(message):
    user_id = message.chat.id
    channel_id = message.text.strip()
    temp_data[user_id]["channel_id"] = channel_id
    temp_data[user_id]["step"] = "message_type"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📝 نص", callback_data="repeat_msg_text"),
        InlineKeyboardButton("🖼️ صورة", callback_data="repeat_msg_photo"),
        InlineKeyboardButton("📄 ملف", callback_data="repeat_msg_document"),
        InlineKeyboardButton("🎥 فيديو", callback_data="repeat_msg_video")
    )
    bot.send_message(user_id, "📝 *اختر نوع المحتوى للتكرار*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("repeat_msg_"))
def process_repeat_msg_type(call):
    user_id = call.message.chat.id
    msg_type = call.data.split("_")[2]
    temp_data[user_id]["media_type"] = msg_type
    temp_data[user_id]["step"] = "content"
    
    if msg_type == "text":
        bot.edit_message_text("✏️ *أرسل النص الذي تريد تكراره*", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_repeat_text)
    elif msg_type == "photo":
        bot.edit_message_text("🖼️ *أرسل الصورة*", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_repeat_media, "photo")
    elif msg_type == "document":
        bot.edit_message_text("📄 *أرسل الملف*", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_repeat_media, "document")
    elif msg_type == "video":
        bot.edit_message_text("🎥 *أرسل الفيديو*", user_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_repeat_media, "video")

def process_repeat_text(message):
    user_id = message.chat.id
    temp_data[user_id]["message"] = message.text
    temp_data[user_id]["media_file_id"] = None
    finalize_repeat(user_id)

def process_repeat_media(message, media_type):
    user_id = message.chat.id
    if media_type == "photo" and message.photo:
        file_id = message.photo[-1].file_id
        caption = message.caption
    elif media_type == "document" and message.document:
        file_id = message.document.file_id
        caption = message.caption
    elif media_type == "video" and message.video:
        file_id = message.video.file_id
        caption = message.caption
    else:
        bot.send_message(user_id, "❌ *نوع الملف غير صحيح* أعد المحاولة.", parse_mode="Markdown")
        return
    
    temp_data[user_id]["media_file_id"] = file_id
    temp_data[user_id]["message"] = caption or ""
    finalize_repeat(user_id)

def finalize_repeat(user_id):
    data = temp_data.pop(user_id)
    
    interval_unit = data["interval_unit"]
    interval_value = data["interval_value"]
    interval_seconds = convert_to_seconds(interval_value, interval_unit)
    
    end_unit = data["end_unit"]
    end_value = data["end_value"]
    end_seconds = convert_to_seconds(end_value, end_unit)
    end_time = time.time() + end_seconds
    
    update_points(user_id, -1)
    
    c.execute("INSERT INTO repeats (user_id, channel_id, interval_value, interval_unit, interval_seconds, end_value, end_unit, end_time, message, media_type, media_file_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (user_id, data.get("channel_id"), interval_value, interval_unit, interval_seconds, end_value, end_unit, end_time, data.get("message"), data.get("media_type"), data.get("media_file_id")))
    repeat_id = c.lastrowid
    conn.commit()
    
    thread = threading.Thread(target=run_repeat_timer, args=(repeat_id, interval_seconds, user_id, data.get("channel_id"), data.get("message"), data.get("media_type"), data.get("media_file_id"), end_time))
    thread.daemon = True
    thread.start()
    
    new_user = get_user(user_id)
    interval_unit_text = convert_unit_text(interval_unit)
    end_unit_text = convert_unit_text(end_unit)
    bot.send_message(user_id, f"✅ *تم إنشاء التكرار بنجاح!*\n\n🔄 كل {interval_value} {interval_unit_text}\n⏰ ينتهي بعد {end_value} {end_unit_text}\n⭐ النقاط المتبقية: {new_user['points']}", parse_mode="Markdown")

# ========== لوحة تحكم المالك ==========
@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def admin_panel(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "🔒 غير مصرح", True)
        return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ إضافة نقاط", callback_data="admin_add_points"),
        InlineKeyboardButton("➖ خصم نقاط", callback_data="admin_remove_points"),
        InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats"),
        InlineKeyboardButton("📢 إذاعة", callback_data="admin_broadcast")
    )
    bot.send_message(OWNER_ID, "🔧 *لوحة تحكم المالك*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_points")
def admin_add_points(call):
    if call.message.chat.id != OWNER_ID:
        return
    msg = bot.send_message(OWNER_ID, "⌨️ *أرسل معرف المستخدم وعدد النقاط*\nمثال: `123456789 5`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, add_points_step)

def add_points_step(message):
    try:
        uid, pts = map(int, message.text.split())
        update_points(uid, pts)
        bot.send_message(OWNER_ID, f"✅ *تم إضافة {pts} نقطة للمستخدم {uid}*", parse_mode="Markdown")
    except:
        bot.send_message(OWNER_ID, "❌ *صيغة غير صحيحة*\nأرسل: `user_id points`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_points")
def admin_remove_points(call):
    if call.message.chat.id != OWNER_ID:
        return
    msg = bot.send_message(OWNER_ID, "⌨️ *أرسل معرف المستخدم وعدد النقاط*\nمثال: `123456789 3`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, remove_points_step)

def remove_points_step(message):
    try:
        uid, pts = map(int, message.text.split())
        update_points(uid, -pts)
        bot.send_message(OWNER_ID, f"✅ *تم خصم {pts} نقطة من المستخدم {uid}*", parse_mode="Markdown")
    except:
        bot.send_message(OWNER_ID, "❌ *صيغة غير صحيحة*", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if call.message.chat.id != OWNER_ID:
        return
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reminders WHERE is_active=1")
    reminders = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM repeats WHERE is_active=1")
    repeats = c.fetchone()[0]
    c.execute("SELECT SUM(points) FROM users")
    points = c.fetchone()[0] or 0
    bot.send_message(OWNER_ID, f"📊 *إحصائيات البوت*\n\n👥 المستخدمون: `{users}`\n⏰ المنبهات النشطة: `{reminders}`\n🔄 التكرارات النشطة: `{repeats}`\n⭐ مجموع النقاط: `{points}`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def admin_broadcast(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "🔒 غير مصرح", True)
        return
    msg = bot.send_message(OWNER_ID, "📢 *أرسل الرسالة التي تريد إذاعتها لجميع مستخدمي البوت*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(message):
    broadcast_text = message.text
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    success = 0
    for (uid,) in users:
        try:
            bot.send_message(uid, f"📢 *إذاعة من المالك*\n\n{broadcast_text}\n\n@ZeQuiz_Bot", parse_mode="Markdown")
            success += 1
        except:
            pass
        time.sleep(0.05)
    bot.send_message(OWNER_ID, f"✅ *تم إرسال الإذاعة إلى {success} مستخدم*", parse_mode="Markdown")

if __name__ == "__main__":
    print("✅ بوت المنبه والتكرار يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
