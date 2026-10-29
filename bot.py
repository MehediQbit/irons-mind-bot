import os
import logging
from datetime import datetime, timezone, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton, BotCommand, WebAppInfo
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from dotenv import load_dotenv
from database import get_or_create_user, supabase

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@IronsMind")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://irons-mind-bot.onrender.com")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Conversation States
HABIT_NAME, QUIT_DATE = range(2)
RESET_REASON, SET_PIN = 10, 11

MENU_REGEX = "^(📊 Dashboard|➕ New Habit Goal|📜 Reset History|🔥 Streaks & Trophies|💰 Savings Tracker|⚙️ Settings & PIN)$"

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

# --- Keyboard & Helpers ---
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

# --- PIN Lock Logic ---
async def is_locked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    pin = context.user_data.get("pin")
    unlocked = context.user_data.get("unlocked", False)
    
    if pin and not unlocked:
        text = update.message.text.strip() if update.message else ""
        if text == pin:
            context.user_data["unlocked"] = True
            await update.message.reply_text("✅ **সফলভাবে আনলক হয়েছে!**", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
            return False
        else:
            if update.message:
                await update.message.reply_text("🔒 **বট লক করা আছে!**\nঅনুগ্রহ করে আপনার ৪-ডিজিটের পিন নম্বরটি টাইপ করে পাঠান:", parse_mode="Markdown")
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
        msg = "⚠️ **কোনো তথ্য নেই!**\n\nআপনি এখনো কোনো হ্যাবিট সেটআপ করেননি। '➕ New Habit Goal' বাটনে চাপ দিয়ে শুরু করুন।"
        if update.message:
            await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        else:
            await update.callback_query.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")
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

    msg = (
        f"📊 **আপনার ড্যাশবোর্ড**\n\n"
        f"🎯 **লক্ষ্য:** Quitting {habit_name}\n"
        f"📅 **শুরুর তারিখ:** {start_time.strftime('%Y-%m-%d')}\n"
        f"⏱️ **সময় পার হয়েছে:** {days} দিন, {hours} ঘণ্টা, {minutes} মিনিট\n\n"
        f"এগিয়ে যান! আপনার ইচ্ছাশক্তি আরও দৃঢ় হচ্ছে। 💪"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Open Web App Dashboard", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("🔄 Reset Timer", callback_data="prompt_reset")]
    ])
    
    if update.message:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def show_reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    habit = get_habit(update.effective_user.id)
    if habit and habit.get("reset_history"):
        history = habit.get("reset_history")
        msg = "📜 **আপনার রিসেট হিস্ট্রি:**\n\n"
        for idx, item in enumerate(history[-5:], 1):
            msg += f"{idx}. **{item.get('date', '')[:10]}** - {item.get('reason', '')}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("📜 **কোনো রিসেট রেকর্ড নেই!** আপনার স্ট্রিক অক্ষুণ্ন আছে। 🔥")

async def show_streaks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    habit = get_habit(update.effective_user.id)
    if habit:
        st = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
        days = max(0, (datetime.now(timezone.utc) - st).days)
        msg = f"🏆 **আপনার ট্রফি ও ব্যাজ (বর্তমান স্ট্রিক: {days} দিন)**\n\n🛡️ **১ দিনের ব্যাজ:** {'অর্জিত ✅' if days>=1 else 'লক করা 🔒'}\n🛡️ **৩ দিনের ব্যাজ:** {'অর্জিত ✅' if days>=3 else 'লক করা 🔒'}\n🛡️ **৭ দিনের ব্যাজ:** {'অর্জিত ✅' if days>=7 else 'লক করা 🔒'}\n🛡️ **১ মাসের ব্যাজ:** {'অর্জিত ✅' if days>=30 else 'লক করা 🔒'}"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ **কোনো তথ্য নেই!** '➕ New Habit Goal' চাপুন।")

async def show_savings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    habit = get_habit(update.effective_user.id)
    if habit:
        st = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
        days = max(0, (datetime.now(timezone.utc) - st).days)
        msg = f"💰 **আপনার সাশ্রয় (Savings)**\n\n💵 **টাকা বেঁচেছে:** ৳{days * 100} (আনুমানিক)\n⏳ **সময় বেঁচেছে:** {days * 2} ঘণ্টা\n\nঅভ্যাস ধরে রাখুন এবং আরও সাশ্রয় করুন!"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ **কোনো তথ্য নেই!** '➕ New Habit Goal' চাপুন।")

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    pin = context.user_data.get("pin")
    status = f"সক্রিয় (`{pin}`)" if pin else "কোনো পিন সেট করা নেই"
    
    msg = f"⚙️ **সেটিংস ও নিরাপত্তা**\n\n🔒 **পিন লক স্ট্যাটাস:** {status}\n\nআপনার বটের চ্যাট সুরক্ষিত রাখতে চাইলে নিচের বাটন থেকে পিন সেট করতে পারেন।"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 নতুন পিন সেট করুন", callback_data="set_pin")],
        [InlineKeyboardButton("🗑️ পিন রিমুভ করুন", callback_data="remove_pin")]
    ])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

# --- Onboarding Flows ---
async def start_new_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    await update.message.reply_text("🎯 **ধাপ ১:** যে অভ্যাসটি আপনি ছাড়তে চান তার নাম লিখুন:\n*(যেমন: Smoking, Social Media, Sugar, Gambling)*", parse_mode="Markdown")
    return HABIT_NAME

async def habit_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["📊 Dashboard", "📜 Reset History", "🔥 Streaks & Trophies", "💰 Savings Tracker", "⚙️ Settings & PIN", "➕ New Habit Goal"]:
        return await handle_menu_commands(update, context)

    context.user_data["new_habit_name"] = text
    await update.message.reply_text(
        f"বুঝেছি! আপনার লক্ষ্য: **Quitting {text}**.\n\n"
        f"👉 **ধাপ ২:** আপনি কবে থেকে এটি ছেড়েছেন?\n\n"
        f"• **'today'** বা **'আজ'** লিখুন।\n"
        f"• **'5 days ago'** লিখুন (বা যত দিন আগে)।\n"
        f"• অথবা নির্দিষ্ট তারিখ দিন: **YYYY-MM-DD** (যেমন: `2026-10-15`)",
        parse_mode="Markdown"
    )
    return QUIT_DATE

async def quit_date_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["📊 Dashboard", "📜 Reset History", "🔥 Streaks & Trophies", "💰 Savings Tracker", "⚙️ Settings & PIN", "➕ New Habit Goal"]:
        return await handle_menu_commands(update, context)

    dt = parse_user_date(text)
    if not dt:
        await update.message.reply_text("❌ **ভুল তারিখ ফরম্যাট!** অনুগ্রহ করে 'today', '5 days ago', অথবা 'YYYY-MM-DD' ফরম্যাটে সঠিক তথ্য দিন।")
        return QUIT_DATE

    user_id = update.effective_user.id
    habit_name = context.user_data.get("new_habit_name", "Addiction")
    
    try:
        get_or_create_user(user_id) # Ensure user exists
        supabase.table("habits").delete().eq("user_id", int(user_id)).execute()
        
        # শুধুমাত্র ৩টি বেসিক কলাম পুশ করছি যাতে কোনো স্কিমা এরর না আসে
        db_data = {
            "user_id": int(user_id), 
            "name": habit_name, 
            "created_at": dt.strftime("%Y-%m-%d %H:%M:%S")
        }
        supabase.table("habits").insert(db_data).execute()
        
        await update.message.reply_text("🎉 **সেটআপ সফলভাবে সম্পন্ন হয়েছে!**\nআপনার রিয়েল-টাইম টাইমার শুরু হয়ে গেছে! 🔥", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        await show_dashboard(update, context)
        
    except Exception as e:
        logging.error(f"DB Error: {e}")
        err_msg = str(e).replace('"', "'")[:200]
        await update.message.reply_text(f"❌ **ডাটাবেজে সেভ হতে সমস্যা হয়েছে।**\n`{err_msg}`\nঅনুগ্রহ করে আবার চেষ্টা করুন।", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        
    return ConversationHandler.END

# --- Reset Flow ---
async def prompt_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "⚠️ **আপনি টাইমার রিসেট করতে চাচ্ছেন!**\n\n"
        "কেন আপনার স্ট্রিক ভেঙ্গে গেল তার **কারণ** সংক্ষেপে চ্যাটে লিখে পাঠান।\n"
        "*(এটি আপনার Reset History-তে সেভ থাকবে)*",
        parse_mode="Markdown"
    )
    return RESET_REASON

async def execute_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    if reason in ["📊 Dashboard", "📜 Reset History", "🔥 Streaks & Trophies", "💰 Savings Tracker", "⚙️ Settings & PIN", "➕ New Habit Goal"]:
        return await handle_menu_commands(update, context)

    user_id = update.effective_user.id
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        # Update Time
        supabase.table("habits").update({"created_at": now_str}).eq("user_id", int(user_id)).execute()
        
        # Try updating history (Will silently pass if column doesn't exist)
        try:
            habit = get_habit(user_id)
            history = habit.get("reset_history", []) if habit and habit.get("reset_history") else []
            history.append({"date": now_str, "reason": reason})
            supabase.table("habits").update({"reset_history": history}).eq("user_id", int(user_id)).execute()
        except: pass
        
        await update.message.reply_text(f"🔄 **টাইমার সফলভাবে রিসেট হয়েছে!**\n\nকারণ: *\"{reason}\"*\nআবার নতুন স্ট্রিক শুরু করুন! 💪", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Reset Error: {e}")
        await update.message.reply_text("❌ রিসেট সেভ হতে সমস্যা হয়েছে।", reply_markup=get_reply_keyboard())
        
    return ConversationHandler.END

# --- Settings & PIN Flow ---
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "set_pin":
        await query.message.reply_text("🔑 **পিন সেটআপ:**\nঅনুগ্রহ করে একটি ৪-ডিজিটের পিন নম্বর চ্যাটে লিখে পাঠান:", parse_mode="Markdown")
        return SET_PIN
    elif query.data == "remove_pin":
        context.user_data["pin"] = None
        context.user_data["unlocked"] = True
        await query.message.reply_text("🗑️ **আপনার পিন সফলভাবে মুছে ফেলা হয়েছে।**", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
    return ConversationHandler.END

async def receive_new_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if pin.isdigit() and len(pin) >= 4:
        context.user_data["pin"] = pin
        context.user_data["unlocked"] = True
        await update.message.reply_text("✅ **পিন সফলভাবে সেভ হয়েছে!** আপনার বট এখন সুরক্ষিত।", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ পিনটি সঠিক নয়। অনুগ্রহ করে কমপক্ষে ৪-ডিজিটের একটি নম্বর দিন:")
        return SET_PIN
    return ConversationHandler.END

# --- Main Menu & Commands ---
async def handle_menu_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_locked(update, context): return
    
    text = update.message.text if update.message else ""
    if text == "📊 Dashboard" or text.startswith("/dashboard"):
        await show_dashboard(update, context)
    elif text == "📜 Reset History":
        await show_reset_history(update, context)
    elif text == "🔥 Streaks & Trophies":
        await show_streaks(update, context)
    elif text == "💰 Savings Tracker":
        await show_savings(update, context)
    elif text == "⚙️ Settings & PIN" or text.startswith("/settings"):
        await show_settings(update, context)
    elif text == "➕ New Habit Goal" or text.startswith("/new"):
        return await start_new_habit(update, context)
    elif text.startswith("/help"):
        await update.message.reply_text("❓ **সাহায্য ও সাপোর্ট:**\n\n• `➕ New Habit Goal`: নতুন অভ্যাস সেট করতে।\n• `⚙️ Settings & PIN`: বটের পিন লক চালু বা বন্ধ করতে।\n• মেনুবারের /dashboard চাপলে সরাসরি ড্যাশবোর্ড আসবে।")
    
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_or_create_user(user_id)
    
    if context.user_data.get("pin"): context.user_data["unlocked"] = False
    
    if await is_locked(update, context): return
    await update.message.reply_text("🛡️ **Iron Mind-এ স্বাগতম!**\n\nনিচের বাটনগুলো ব্যবহার করে আপনার অভ্যাস নিয়ন্ত্রণ করুন।", reply_markup=get_reply_keyboard(), parse_mode="Markdown")

async def post_init(application: Application):
    commands = [
        BotCommand("start", "বট রিস্টার্ট করুন"),
        BotCommand("dashboard", "আপনার ড্যাশবোর্ড দেখুন"),
        BotCommand("new", "নতুন অভ্যাস সেট করুন"),
        BotCommand("help", "সাহায্য ও সাপোর্ট")
    ]
    await application.bot.set_my_commands(commands)

def main():
    if not BOT_TOKEN: return
    Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    onboarding_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ New Habit Goal$"), start_new_habit),
            CommandHandler("new", start_new_habit)
        ],
        states={
            HABIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, habit_name_received)],
            QUIT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, quit_date_received)]
        },
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX) | filters.COMMAND, handle_menu_commands)]
    )

    reset_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(prompt_reset, pattern="^prompt_reset$")],
        states={RESET_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, execute_reset)]},
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX) | filters.COMMAND, handle_menu_commands)]
    )

    pin_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(settings_callback, pattern="^set_pin$")],
        states={SET_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_pin)]},
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX) | filters.COMMAND, handle_menu_commands)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(onboarding_handler)
    app.add_handler(reset_handler)
    app.add_handler(pin_handler)
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^remove_pin$"))
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, handle_menu_commands))
    
    print("Iron Mind Bot is running beautifully...")
    app.run_polling()

if __name__ == "__main__":
    main()
