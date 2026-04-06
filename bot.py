import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
import json
import threading
import time
from datetime import datetime, timedelta
import tempfile

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== 1. قاعدة البيانات ==========
conn = sqlite3.connect("reminder_bot.db", check_same_thread=False)
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
    duration INTEGER,
    unit TEXT,
    end_time REAL,
    message TEXT,
    media_type TEXT,
    media_file_id TEXT,
    is_active INTEGER DEFAULT 1
)''')
c.execute('''CREATE TABLE IF NOT EXISTS repeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    channel_id TEXT,
    interval_duration INTEGER,
    interval_unit TEXT,
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
    if shares % 1 == 0:  # كل مشاركة = 3 نقاط
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

# تخزين مؤقت للبيانات أثناء إنشاء المنبه/التكرار
temp_data = {}

# ========== 2. دوال المؤقتات ==========
def run_reminder_timer(reminder_id, duration_seconds, user_id, channel_id, message, media_type, media_file_id):
    """تشغيل مؤقت المنبه"""
    time.sleep(duration_seconds)
    
    # التحقق من أن المنبه لا يزال نشطاً
    c.execute("SELECT is_active FROM reminders WHERE id=?", (reminder_id,))
    row = c.fetchone()
    if not row or row[0] == 0:
        return
    
    # إرسال الرسالة
    if channel_id and channel_id != "None":
        chat_id = channel_id
    else:
        chat_id = user_id
    
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
    
    # حذف المنبه من قاعدة البيانات
    c.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    conn.commit()
    
    bot.send_message(user_id, "✅ تم إرسال المنبه بنجاح!")

def run_repeat_timer(repeat_id, interval_seconds, user_id, channel_id, message, media_type, media_file_id, end_time):
    """تشغيل التكرار"""
    while True:
        time.sleep(interval_seconds)
        
        # التحقق من انتهاء الوقت
        if time.time() >= end_time:
            c.execute("UPDATE repeats SET is_active=0 WHERE id=?", (repeat_id,))
            conn.commit()
            bot.send_message(user_id, "✅ انتهى وقت التكرار المحدد.")
            break
        
        # التحقق من أن التكرار لا يزال نشطاً
        c.execute("SELECT is_active FROM repeats WHERE id=?", (repeat_id,))
        row = c.fetchone()
        if not row or row[0] == 0:
            break
        
        # إرسال الرسالة
        if channel_id and channel_id != "None":
            chat_id = channel_id
        else:
            chat_id = user_id
        
        try:
            if media_type == "photo":
                bot.send_photo(chat_id, media_file_id, caption=message)
            elif media_type == "document":
                bot.send_document(chat_id, media_file_id, caption=message)
            elif media_type == "video":
                bot.send_video(chat_id, media_file_id, caption=message)
            else:
                bot.send_message(chat_id, message)
        except Exception as e:
            bot.send_message(user_id, f"❌ فشل إرسال التكرار: {e}")

# ========== 3. أوامر البوت ==========
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
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⏰ منبه جديد", callback_data="new_reminder"))
    markup.add(InlineKeyboardButton("🔄 تكرار جديد", callback_data="new_repeat"))
    markup.add(InlineKeyboardButton("📋 قائمة المنبهات", callback_data="my_reminders"))
    markup.add(InlineKeyboardButton("🔄 قائمة التكرارات", callback_data="my_repeats"))
    markup.add(InlineKeyboardButton("🎁 مشاركة الرابط", callback_data="share_link"))
    if user_id == OWNER_ID:
        markup.add(InlineKeyboardButton("🔧 لوحة التحكم", callback_data="admin_panel"))
    
    bot.send_message(user_id,
        f"⏰ *بوت المنبه والتكرار*\n\n"
        f"• رصيدك: {user['points']} نقطة\n"
        f"• كل منبه أو تكرار يستهلك نقطة واحدة.\n"
        f"• احصل على نقاط عبر مشاركة الرابط (كل مشاركة = 3 نقاط).\n"
        f"رابط إحالتك:\nhttps://t.me/{bot.get_me().username}?start={user_id}\n\n"
        f"📌 @ZeQuiz_Bot",
        parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "share_link")
def share_link(call):
    user_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, f"🎁 رابط إحالتك:\nhttps://t.me/{bot.get_me().username}?start={user_id}\n\nكل مشاركة = 3 نقاط!")

# ========== 4. إنشاء منبه جديد ==========
@bot.callback_query_handler(func=lambda call: call.data == "new_reminder")
def new_reminder_start(call):
    user_id = call.message.chat.id
    user = get_user(user_id)
    if user["points"] < 1:
        bot.answer_callback_query(call.id, f"ليس لديك نقاط كافية. رصيدك: {user['points']} نقطة. شارك الرابط!", show_alert=True)
        return
    
    temp_data[user_id] = {"type": "reminder", "step": "unit"}
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("ثواني", callback_data="unit_seconds"))
    markup.add(InlineKeyboardButton("دقائق", callback_data="unit_minutes"))
    markup.add(InlineKeyboardButton("ساعات", callback_data="unit_hours"))
    bot.send_message(user_id, "⏰ اختر وحدة الوقت للمنبه:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("unit_"))
def process_unit(call):
    user_id = call.message.chat.id
    unit = call.data.split("_")[1]
    temp_data[user_id]["unit"] = unit
    temp_data[user_id]["step"] = "duration"
    bot.edit_message_text(f"⏰ اخترت {unit}. أرسل الرقم (مثال: 30):", user_id, call.message.message_id)
    bot.register_next_step_handler(call.message, process_duration)

def process_duration(message):
    user_id = message.chat.id
    try:
        duration = int(message.text.strip())
        if duration <= 0:
            raise ValueError
        temp_data[user_id]["duration"] = duration
        temp_data[user_id]["step"] = "channel"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📱 في البوت فقط", callback_data="channel_none"))
        markup.add(InlineKeyboardButton("📢 في قناة (أضف البوت أدمن)", callback_data="channel_add"))
        bot.send_message(user_id, "📍 أين تريد إرسال المنبه؟", reply_markup=markup)
    except:
        bot.send_message(user_id, "❌ أرسل رقماً صحيحاً أكبر من 0.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("channel_"))
def process_channel(call):
    user_id = call.message.chat.id
    if call.data == "channel_none":
        temp_data[user_id]["channel_id"] = None
        temp_data[user_id]["step"] = "message_type"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📝 نص", callback_data="msg_text"))
        markup.add(InlineKeyboardButton("🖼️ صورة", callback_data="msg_photo"))
        markup.add(InlineKeyboardButton("📄 ملف", callback_data="msg_document"))
        markup.add(InlineKeyboardButton("🎥 فيديو", callback_data="msg_video"))
        bot.edit_message_text("📝 اختر نوع المحتوى للمنبه:", user_id, call.message.message_id, reply_markup=markup)
    else:
        temp_data[user_id]["step"] = "channel_id"
        bot.edit_message_text("📢 أرسل معرف القناة (مثال: @username):", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_channel_id)

def process_channel_id(message):
    user_id = message.chat.id
    channel_id = message.text.strip()
    temp_data[user_id]["channel_id"] = channel_id
    temp_data[user_id]["step"] = "message_type"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📝 نص", callback_data="msg_text"))
    markup.add(InlineKeyboardButton("🖼️ صورة", callback_data="msg_photo"))
    markup.add(InlineKeyboardButton("📄 ملف", callback_data="msg_document"))
    markup.add(InlineKeyboardButton("🎥 فيديو", callback_data="msg_video"))
    bot.send_message(user_id, "📝 اختر نوع المحتوى للمنبه:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("msg_"))
def process_message_type(call):
    user_id = call.message.chat.id
    msg_type = call.data.split("_")[1]
    temp_data[user_id]["media_type"] = msg_type
    temp_data[user_id]["step"] = "content"
    
    if msg_type == "text":
        bot.edit_message_text("✏️ أرسل النص الذي تريد إرساله عند انتهاء المنبه:", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_text_content)
    elif msg_type == "photo":
        bot.edit_message_text("🖼️ أرسل الصورة (كملف أو معرف):", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_media_content, "photo")
    elif msg_type == "document":
        bot.edit_message_text("📄 أرسل الملف:", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_media_content, "document")
    elif msg_type == "video":
        bot.edit_message_text("🎥 أرسل الفيديو:", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_media_content, "video")

def process_text_content(message):
    user_id = message.chat.id
    temp_data[user_id]["message"] = message.text
    temp_data[user_id]["media_file_id"] = None
    finalize_reminder(user_id)

def process_media_content(message, media_type):
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
        bot.send_message(user_id, "❌ نوع الملف غير صحيح. أعد المحاولة.")
        return
    
    temp_data[user_id]["media_file_id"] = file_id
    temp_data[user_id]["message"] = caption or ""
    finalize_reminder(user_id)

def finalize_reminder(user_id):
    data = temp_data.pop(user_id)
    
    # حساب الوقت بالثواني
    duration = data["duration"]
    unit = data["unit"]
    if unit == "minutes":
        duration_seconds = duration * 60
    elif unit == "hours":
        duration_seconds = duration * 3600
    else:
        duration_seconds = duration
    
    # استهلاك نقطة
    update_points(user_id, -1)
    
    # حفظ في قاعدة البيانات
    c.execute("INSERT INTO reminders (user_id, channel_id, duration, unit, end_time, message, media_type, media_file_id) VALUES (?,?,?,?,?,?,?,?)",
              (user_id, data.get("channel_id"), duration, unit, time.time() + duration_seconds, data.get("message"), data.get("media_type"), data.get("media_file_id")))
    reminder_id = c.lastrowid
    conn.commit()
    
    # تشغيل المؤقت
    thread = threading.Thread(target=run_reminder_timer, args=(reminder_id, duration_seconds, user_id, data.get("channel_id"), data.get("message"), data.get("media_type"), data.get("media_file_id")))
    thread.daemon = True
    thread.start()
    
    new_user = get_user(user_id)
    unit_text = {"seconds": "ثانية", "minutes": "دقيقة", "hours": "ساعة"}[unit]
    bot.send_message(user_id, f"✅ تم إنشاء المنبه بنجاح!\n⏰ الوقت: {duration} {unit_text}\n⭐ النقاط المتبقية: {new_user['points']}")

# ========== 5. إنشاء تكرار جديد ==========
@bot.callback_query_handler(func=lambda call: call.data == "new_repeat")
def new_repeat_start(call):
    user_id = call.message.chat.id
    user = get_user(user_id)
    if user["points"] < 1:
        bot.answer_callback_query(call.id, f"ليس لديك نقاط كافية. رصيدك: {user['points']} نقطة.", show_alert=True)
        return
    
    temp_data[user_id] = {"type": "repeat", "step": "unit"}
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("ثواني", callback_data="repeat_unit_seconds"))
    markup.add(InlineKeyboardButton("دقائق", callback_data="repeat_unit_minutes"))
    markup.add(InlineKeyboardButton("ساعات", callback_data="repeat_unit_hours"))
    bot.send_message(user_id, "🔄 اختر وحدة الوقت بين كل تكرار:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("repeat_unit_"))
def process_repeat_unit(call):
    user_id = call.message.chat.id
    unit = call.data.split("_")[2]
    temp_data[user_id]["unit"] = unit
    temp_data[user_id]["step"] = "interval"
    bot.edit_message_text(f"🔄 اخترت {unit}. أرسل الرقم (مثال: 30):", user_id, call.message.message_id)
    bot.register_next_step_handler(call.message, process_repeat_interval)

def process_repeat_interval(message):
    user_id = message.chat.id
    try:
        interval = int(message.text.strip())
        if interval <= 0:
            raise ValueError
        temp_data[user_id]["interval"] = interval
        temp_data[user_id]["step"] = "end_time"
        bot.send_message(user_id, "⏰ أرسل مدة التكرار (بالساعات)\nمثال: 24 (لمدة يوم)، أو 0 للتكرار غير المحدود:")
        bot.register_next_step_handler(message, process_repeat_end_time)
    except:
        bot.send_message(user_id, "❌ أرسل رقماً صحيحاً أكبر من 0.")

def process_repeat_end_time(message):
    user_id = message.chat.id
    try:
        end_hours = int(message.text.strip())
        if end_hours > 0:
            end_time = time.time() + (end_hours * 3600)
        else:
            end_time = float('inf')
        temp_data[user_id]["end_time"] = end_time
        temp_data[user_id]["step"] = "channel"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📱 في البوت فقط", callback_data="repeat_channel_none"))
        markup.add(InlineKeyboardButton("📢 في قناة (أضف البوت أدمن)", callback_data="repeat_channel_add"))
        bot.send_message(user_id, "📍 أين تريد إرسال التكرارات؟", reply_markup=markup)
    except:
        bot.send_message(user_id, "❌ أرسل رقماً صحيحاً.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("repeat_channel_"))
def process_repeat_channel(call):
    user_id = call.message.chat.id
    if call.data == "repeat_channel_none":
        temp_data[user_id]["channel_id"] = None
        temp_data[user_id]["step"] = "message_type"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📝 نص", callback_data="repeat_msg_text"))
        markup.add(InlineKeyboardButton("🖼️ صورة", callback_data="repeat_msg_photo"))
        markup.add(InlineKeyboardButton("📄 ملف", callback_data="repeat_msg_document"))
        markup.add(InlineKeyboardButton("🎥 فيديو", callback_data="repeat_msg_video"))
        bot.edit_message_text("📝 اختر نوع المحتوى للتكرار:", user_id, call.message.message_id, reply_markup=markup)
    else:
        temp_data[user_id]["step"] = "channel_id"
        bot.edit_message_text("📢 أرسل معرف القناة (مثال: @username):", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_repeat_channel_id)

def process_repeat_channel_id(message):
    user_id = message.chat.id
    channel_id = message.text.strip()
    temp_data[user_id]["channel_id"] = channel_id
    temp_data[user_id]["step"] = "message_type"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📝 نص", callback_data="repeat_msg_text"))
    markup.add(InlineKeyboardButton("🖼️ صورة", callback_data="repeat_msg_photo"))
    markup.add(InlineKeyboardButton("📄 ملف", callback_data="repeat_msg_document"))
    markup.add(InlineKeyboardButton("🎥 فيديو", callback_data="repeat_msg_video"))
    bot.send_message(user_id, "📝 اختر نوع المحتوى للتكرار:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("repeat_msg_"))
def process_repeat_message_type(call):
    user_id = call.message.chat.id
    msg_type = call.data.split("_")[2]
    temp_data[user_id]["media_type"] = msg_type
    temp_data[user_id]["step"] = "content"
    
    if msg_type == "text":
        bot.edit_message_text("✏️ أرسل النص الذي تريد تكراره:", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_repeat_text_content)
    elif msg_type == "photo":
        bot.edit_message_text("🖼️ أرسل الصورة (كملف أو معرف):", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_repeat_media_content, "photo")
    elif msg_type == "document":
        bot.edit_message_text("📄 أرسل الملف:", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_repeat_media_content, "document")
    elif msg_type == "video":
        bot.edit_message_text("🎥 أرسل الفيديو:", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, process_repeat_media_content, "video")

def process_repeat_text_content(message):
    user_id = message.chat.id
    temp_data[user_id]["message"] = message.text
    temp_data[user_id]["media_file_id"] = None
    finalize_repeat(user_id)

def process_repeat_media_content(message, media_type):
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
        bot.send_message(user_id, "❌ نوع الملف غير صحيح. أعد المحاولة.")
        return
    
    temp_data[user_id]["media_file_id"] = file_id
    temp_data[user_id]["message"] = caption or ""
    finalize_repeat(user_id)

def finalize_repeat(user_id):
    data = temp_data.pop(user_id)
    
    # حساب الفاصل الزمني بالثواني
    interval = data["interval"]
    unit = data["unit"]
    if unit == "minutes":
        interval_seconds = interval * 60
    elif unit == "hours":
        interval_seconds = interval * 3600
    else:
        interval_seconds = interval
    
    # استهلاك نقطة
    update_points(user_id, -1)
    
    # حفظ في قاعدة البيانات
    c.execute("INSERT INTO repeats (user_id, channel_id, interval_duration, interval_unit, end_time, message, media_type, media_file_id) VALUES (?,?,?,?,?,?,?,?)",
              (user_id, data.get("channel_id"), interval, unit, data.get("end_time"), data.get("message"), data.get("media_type"), data.get("media_file_id")))
    repeat_id = c.lastrowid
    conn.commit()
    
    # تشغيل التكرار
    thread = threading.Thread(target=run_repeat_timer, args=(repeat_id, interval_seconds, user_id, data.get("channel_id"), data.get("message"), data.get("media_type"), data.get("media_file_id"), data.get("end_time")))
    thread.daemon = True
    thread.start()
    
    new_user = get_user(user_id)
    unit_text = {"seconds": "ثانية", "minutes": "دقيقة", "hours": "ساعة"}[unit]
    end_text = "غير محدود" if data.get("end_time") == float('inf') else f"بعد {data['end_time']} ثانية"
    bot.send_message(user_id, f"✅ تم إنشاء التكرار بنجاح!\n🔄 كل {interval} {unit_text}\n⏰ ينتهي: {end_text}\n⭐ النقاط المتبقية: {new_user['points']}")

# ========== 6. قوائم المنبهات والتكرارات ==========
@bot.callback_query_handler(func=lambda call: call.data == "my_reminders")
def my_reminders(call):
    user_id = call.message.chat.id
    c.execute("SELECT id, duration, unit, message FROM reminders WHERE user_id=? AND is_active=1", (user_id,))
    reminders = c.fetchall()
    if not reminders:
        bot.send_message(user_id, "📭 لا توجد منبهات نشطة حالياً.")
        return
    txt = "⏰ *المنبهات النشطة:*\n\n"
    for rid, duration, unit, msg in reminders:
        unit_text = {"seconds": "ثانية", "minutes": "دقيقة", "hours": "ساعة"}[unit]
        txt += f"🆔 {rid} | {duration} {unit_text}\n📝 {msg[:30] if msg else 'بدون نص'}\n\n"
    bot.send_message(user_id, txt, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "my_repeats")
def my_repeats(call):
    user_id = call.message.chat.id
    c.execute("SELECT id, interval_duration, interval_unit, message FROM repeats WHERE user_id=? AND is_active=1", (user_id,))
    repeats = c.fetchall()
    if not repeats:
        bot.send_message(user_id, "📭 لا توجد تكرارات نشطة حالياً.")
        return
    txt = "🔄 *التكرارات النشطة:*\n\n"
    for rid, duration, unit, msg in repeats:
        unit_text = {"seconds": "ثانية", "minutes": "دقيقة", "hours": "ساعة"}[unit]
        txt += f"🆔 {rid} | كل {duration} {unit_text}\n📝 {msg[:30] if msg else 'بدون نص'}\n\n"
    bot.send_message(user_id, txt, parse_mode="Markdown")

# ========== 7. لوحة تحكم المالك ==========
@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def admin_panel(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة نقاط لمستخدم", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("➖ خصم نقاط من مستخدم", callback_data="admin_remove_points"))
    markup.add(InlineKeyboardButton("📊 إحصائيات البوت", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("📢 إذاعة للجميع", callback_data="admin_broadcast"))
    bot.send_message(OWNER_ID, "🔧 لوحة تحكم المالك", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_points")
def admin_add_points(call):
    if call.message.chat.id != OWNER_ID:
        return
    msg = bot.send_message(OWNER_ID, "أرسل معرف المستخدم وعدد النقاط (مثال: 123456789 5):")
    bot.register_next_step_handler(msg, add_points_step)

def add_points_step(message):
    try:
        parts = message.text.split()
        uid = int(parts[0])
        pts = int(parts[1])
        update_points(uid, pts)
        bot.send_message(OWNER_ID, f"✅ تم إضافة {pts} نقطة للمستخدم {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ صيغة غير صحيحة. أرسل: user_id points")

@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_points")
def admin_remove_points(call):
    if call.message.chat.id != OWNER_ID:
        return
    msg = bot.send_message(OWNER_ID, "أرسل معرف المستخدم وعدد النقاط (مثال: 123456789 3):")
    bot.register_next_step_handler(msg, remove_points_step)

def remove_points_step(message):
    try:
        parts = message.text.split()
        uid = int(parts[0])
        pts = int(parts[1])
        update_points(uid, -pts)
        bot.send_message(OWNER_ID, f"✅ تم خصم {pts} نقطة من المستخدم {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ صيغة غير صحيحة.")

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if call.message.chat.id != OWNER_ID:
        return
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reminders WHERE is_active=1")
    active_reminders = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM repeats WHERE is_active=1")
    active_repeats = c.fetchone()[0]
    c.execute("SELECT SUM(points) FROM users")
    total_points = c.fetchone()[0] or 0
    bot.send_message(OWNER_ID, f"📊 إحصائيات البوت\n👥 المستخدمون: {users}\n⏰ المنبهات النشطة: {active_reminders}\n🔄 التكرارات النشطة: {active_repeats}\n⭐ مجموع النقاط: {total_points}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def admin_broadcast(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    msg = bot.send_message(OWNER_ID, "📢 أرسل الرسالة التي تريد إذاعتها لجميع مستخدمي البوت:")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(message):
    broadcast_text = message.text
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    success = 0
    fail = 0
    for (uid,) in users:
        try:
            bot.send_message(uid, f"📢 *إذاعة من المالك:*\n\n{broadcast_text}\n\n📌 @ZeQuiz_Bot", parse_mode="Markdown")
            success += 1
        except:
            fail += 1
        time.sleep(0.05)
    bot.send_message(OWNER_ID, f"✅ تم إرسال الإذاعة إلى {success} مستخدم.\n❌ فشل الإرسال إلى {fail} مستخدم.")

if __name__ == "__main__":
    print("✅ بوت المنبه والتكرار يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
