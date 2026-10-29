import os
import logging
import json
from datetime import datetime, timezone, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)
from dotenv import load_dotenv
from database import get_or_create_user, supabase

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@IronsMind")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://irons-mind-bot.onrender.com")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# States
HABIT_NAME, QUIT_DATE, RESET_REASON, SET_PIN = range(4)
MENU_REGEX = "^(📊 Dashboard|➕ New Habit Goal|📜 Reset History|🔥 Streaks & Trophies|💰 Savings Tracker|⚙️ Settings & PIN|bn|en)$"

# --- Web Server for Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Iron Mind Bot is Running Live!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- Helpers ---
def get_reply_keyboard():
    keyboard = [
        [KeyboardButton("📊 Dashboard"), KeyboardButton("➕ New Habit Goal")],
        [KeyboardButton("📜 Reset History"), KeyboardButton("🔥 Streaks & Trophies")],
        [KeyboardButton("💰 Savings Tracker"), KeyboardButton("⚙️ Settings & PIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def parse_user_date(text: str):
    t = text.strip().lower()
    now = datetime.now(timezone.utc)
    if t in ["today", "আজ", "এখন", "now"]: return now
    if t in ["yesterday", "গতকাল"]: return now - timedelta(days=1)
    
    if "day" in t or "দিন" in t:
        try:
            num = int(''.join(filter(str.isdigit, t)))
            return now - timedelta(days=num)
        except: pass

    for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
        try:
            dt = datetime.strptime(t, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError: continue
    return None

def get_habit(user_id):
    try:
        res = supabase.table("habits").select("*").eq("user_id", int(user_id)).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"DB Read Error: {e}")
        return None

# --- Localization & Text Output ---
def get_text(context: ContextTypes.DEFAULT_TYPE, key: str, **kwargs):
    lang = context.user_data.get("lang", "bn")
    texts = {
        "locked": {"en": "🔒 **Bot is Locked!**\nPlease enter your 4-digit PIN:", "bn": "🔒 **বট লক করা আছে!**\nদয়া করে আপনার ৪-ডিজিটের পিন দিন:"},
        "unlocked": {"en": "✅ **Unlocked Successfully!**", "bn": "✅ **সফলভাবে আনলক হয়েছে!**"},
        "wrong_pin": {"en": "❌ **Wrong PIN.** Try again:", "bn": "❌ **ভুল পিন!** আবার চেষ্টা করুন:"},
        "no_habit": {"en": "⚠️ **No active habit!** Tap '➕ New Habit Goal' to start.", "bn": "⚠️ **কোনো তথ্য নেই!** '➕ New Habit Goal' চাপুন।"},
        "db_error": {"en": "❌ Database save error.", "bn": "❌ ডাটাবেজে সেভ হতে সমস্যা হয়েছে।"},
        "settings": {"en": "⚙️ **Settings Menu:**", "bn": "⚙️ **সেটিংস মেনু:**"},
    }
    return texts.get(key, {}).get(lang, "Error").format(**kwargs)

# --- Check Lock Status ---
async def is_locked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    pin = context.user_data.get("pin")
    unlocked = context.user_data.get("unlocked", False)
    
    if pin and not unlocked:
        text = update.message.text.strip() if update.message else ""
        if text == pin:
            context.user_data["unlocked"] = True
            await update.message.reply_text(get_text(context, "unlocked"), reply_markup=get_reply_keyboard(), parse_mode="Markdown")
            return False
        else:
            if update.message:
                await update.message.reply_text(get_text(context, "locked"), parse_mode="Markdown")
            elif update.callback_query:
                await update.callback_query.answer("Bot is locked!", show_alert=True)
            return True
    return False

# --- Core Features ---
async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    
    user_id = update.effective_user.id
    habit = get_habit(user_id)
    
    if not habit:
        await update.message.reply_text(get_text(context, "no_habit"), reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        return

    habit_name = habit.get("name", "Addiction")
    created_str = habit.get("created_at")
    
    try:
        start_time = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
    except Exception:
        start_time = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    diff = max(timedelta(0), now - start_time)
    
    days = diff.days
    hours, remainder = divmod(diff.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    lang = context.user_data.get("lang", "bn")
    if lang == "bn":
        msg = f"📊 **ড্যাশবোর্ড**\n\n🎯 **লক্ষ্য:** Quitting {habit_name}\n📅 **শুরু:** {start_time.strftime('%Y-%m-%d')}\n⏱️ **সময়:** {days} দিন, {hours} ঘণ্টা, {minutes} মিনিট\n\nএগিয়ে যান! 💪"
    else:
        msg = f"📊 **DASHBOARD**\n\n🎯 **Goal:** Quitting {habit_name}\n📅 **Started:** {start_time.strftime('%Y-%m-%d')}\n⏱️ **Time:** {days}d, {hours}h, {minutes}m\n\nKeep going! 💪"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Web Dashboard", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("🔄 Reset Timer", callback_data="prompt_reset")]
    ])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

# --- Commands ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    msg = "❓ **Help / সাপোর্ট:**\n\n• `➕ New Habit Goal`: নতুন ট্র্যাকার সেট করতে।\n• `⚙️ Settings & PIN`: ভাষা ও পিন লক সেট করতে।\n• ডাটা রিসেট বা মুছে ফেলতে চাইলে নতুন করে হ্যাবিট সেট করুন।"
    await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")

# --- Menus ---
async def handle_menu_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    
    text = update.message.text
    user_id = update.effective_user.id
    lang = context.user_data.get("lang", "bn")

    if text == "📊 Dashboard":
        await show_dashboard(update, context)

    elif text == "📜 Reset History":
        habit = get_habit(user_id)
        if habit and habit.get("reset_history"):
            history = habit.get("reset_history")
            msg = "📜 **Reset History:**\n\n"
            for idx, item in enumerate(history[-5:], 1):
                msg += f"{idx}. **{item.get('date', '')[:10]}** - {item.get('reason', '')}\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("📜 কোনো রিসেট রেকর্ড নেই! স্ট্রিক অক্ষুণ্ন আছে। 🔥" if lang=="bn" else "No reset history! Perfect streak. 🔥")

    elif text == "🔥 Streaks & Trophies":
        habit = get_habit(user_id)
        if habit:
            st = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
            days = max(0, (datetime.now(timezone.utc) - st).days)
            msg = f"🏆 **Trophies (Streak: {days} Days)**\n\n🛡️ **1 Day:** {'✅' if days>=1 else '🔒'}\n🛡️ **3 Days:** {'✅' if days>=3 else '🔒'}\n🛡️ **7 Days:** {'✅' if days>=7 else '🔒'}"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(get_text(context, "no_habit"), parse_mode="Markdown")

    elif text == "💰 Savings Tracker":
        habit = get_habit(user_id)
        if habit:
            st = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
            days = max(0, (datetime.now(timezone.utc) - st).days)
            msg = f"💰 **Savings**\n\n💵 **Money:** ৳{days * 100}\n⏳ **Time:** {days * 2} Hours"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(get_text(context, "no_habit"), parse_mode="Markdown")

    elif text == "⚙️ Settings & PIN":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"), InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🔑 Set PIN", callback_data="set_pin"), InlineKeyboardButton("🗑️ Remove PIN", callback_data="remove_pin")]
        ])
        await update.message.reply_text(get_text(context, "settings"), reply_markup=kb, parse_mode="Markdown")
    
    return ConversationHandler.END

# --- Settings Callbacks ---
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("lang_"):
        context.user_data["lang"] = data.split("_")[1]
        await query.edit_message_text(f"✅ Language updated!")
    elif data == "set_pin":
        await query.edit_message_text("🔑 **PIN Setup:**\nPlease send a 4-digit PIN in the chat:", parse_mode="Markdown")
        return SET_PIN
    elif data == "remove_pin":
        context.user_data["pin"] = None
        context.user_data["unlocked"] = True
        await query.edit_message_text("🗑️ **PIN removed securely.**", parse_mode="Markdown")
    return ConversationHandler.END

async def receive_new_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if pin.isdigit() and len(pin) >= 4:
        context.user_data["pin"] = pin
        context.user_data["unlocked"] = True
        await update.message.reply_text("✅ **PIN Saved!** Your bot is now secure.", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Please enter a valid numeric PIN (at least 4 digits):")
        return SET_PIN
    return ConversationHandler.END

# --- Onboarding Flows ---
async def start_new_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    lang = context.user_data.get("lang", "bn")
    msg = "🎯 **Step 1:** যে অভ্যাসটি ছাড়তে চান তার নাম লিখুন (যেমন: Smoking):" if lang=="bn" else "🎯 **Step 1:** Habit name to quit (e.g., Smoking):"
    await update.message.reply_text(msg, parse_mode="Markdown")
    return HABIT_NAME

async def habit_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_habit_name"] = update.message.text.strip()
    lang = context.user_data.get("lang", "bn")
    msg = f"👉 **Step 2:** কবে থেকে এটি ছেড়েছেন?\n\n• **'today'** লিখুন।\n• **'5 days ago'** লিখুন।\n• অথবা তারিখ: **YYYY-MM-DD**" if lang=="bn" else f"👉 **Step 2:** When did you start?\n\n• Type **'today'**\n• Type **'5 days ago'**\n• Or Date: **YYYY-MM-DD**"
    await update.message.reply_text(msg, parse_mode="Markdown")
    return QUIT_DATE

async def quit_date_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    dt = parse_user_date(text)
    
    if not dt:
        await update.message.reply_text("❌ **Invalid format.** Please type 'today', '5 days ago', or 'YYYY-MM-DD'.")
        return QUIT_DATE

    user_id = update.effective_user.id
    habit_name = context.user_data.get("new_habit_name")
    
    try:
        supabase.table("habits").delete().eq("user_id", int(user_id)).execute()
        # FIX: Removed empty list insertion to prevent JSONB error
        supabase.table("habits").insert({
            "user_id": int(user_id), 
            "name": habit_name, 
            "created_at": dt.isoformat()
        }).execute()
        
        await update.message.reply_text("🎉 **Setup Complete! / সেটআপ সফল!**\nTimer is live! 🔥", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        await show_dashboard(update, context)
    except Exception as e:
        logging.error(f"DB Error: {e}")
        await update.message.reply_text(get_text(context, "db_error"), reply_markup=get_reply_keyboard())
        
    return ConversationHandler.END

# --- Main Setup ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_or_create_user(user_id)
    
    if context.user_data.get("pin"): context.user_data["unlocked"] = False
    
    commands = [BotCommand("start", "Restart Bot"), BotCommand("dashboard", "Open Dashboard"), BotCommand("help", "Support")]
    await context.bot.set_my_commands(commands)
    
    if await is_locked(update, context): return
    await update.message.reply_text("🛡️ **Welcome to Iron Mind!**", reply_markup=get_reply_keyboard(), parse_mode="Markdown")

def main():
    if not BOT_TOKEN: return
    Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Conversations
    onboarding_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ New Habit Goal$"), start_new_habit)],
        states={HABIT_NAME: [MessageHandler(filters.TEXT & ~filters.Regex(MENU_REGEX), habit_name_received)], QUIT_DATE: [MessageHandler(filters.TEXT & ~filters.Regex(MENU_REGEX), quit_date_received)]},
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX), handle_menu_commands)]
    )

    pin_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(settings_callback, pattern="^set_pin$")],
        states={SET_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_pin)]},
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX), handle_menu_commands)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(onboarding_handler)
    app.add_handler(pin_handler)
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^(lang_bn|lang_en|remove_pin)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_commands))
    
    print("Iron Mind Bot is running flawlessly...")
    app.run_polling()

if __name__ == "__main__":
    main()
