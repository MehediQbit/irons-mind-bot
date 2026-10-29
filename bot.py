import os
import logging
from datetime import datetime, timezone, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
from database import get_or_create_user, supabase

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@IronsMind")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://irons-mind-bot.onrender.com")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

HABIT_NAME, QUIT_DATE = range(2)
RESET_REASON = 10

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Iron Mind Bot is Running Live!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

def get_reply_keyboard():
    keyboard = [
        [KeyboardButton("📊 Dashboard"), KeyboardButton("➕ New Habit Goal")],
        [KeyboardButton("📜 Reset History"), KeyboardButton("🔥 Streaks & Trophies")],
        [KeyboardButton("💰 Savings Tracker"), KeyboardButton("⚙️ Settings & PIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

MENU_REGEX = "^(📊 Dashboard|➕ New Habit Goal|📜 Reset History|🔥 Streaks & Trophies|💰 Savings Tracker|⚙️ Settings & PIN)$"

def parse_user_date(text: str):
    text_clean = text.strip().lower()
    now = datetime.now(timezone.utc)
    
    if text_clean in ["today", "আজ", "এখন", "now"]: return now
    if text_clean in ["yesterday", "গতকাল"]: return now - timedelta(days=1)
    
    if "day" in text_clean or "দিন" in text_clean:
        try:
            num = int(''.join(filter(str.isdigit, text_clean)))
            return now - timedelta(days=num)
        except: pass

    for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
        try:
            dt = datetime.strptime(text_clean, fmt)
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

# --- Main Feature Functions ---
async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    habit = get_habit(user_id)
    
    if not habit:
        await update.message.reply_text(
            "⚠️ **কোনো তথ্য নেই!**\n\nআপনি এখনো কোনো হ্যাবিট সেটআপ করেননি। '➕ New Habit Goal' বাটনে চাপ দিয়ে শুরু করুন।",
            reply_markup=get_reply_keyboard(), parse_mode="Markdown"
        )
        return

    habit_name = habit.get("name", "Addiction")
    created_str = habit.get("created_at")
    
    try:
        start_time = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
    except Exception:
        start_time = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    diff = now - start_time if now > start_time else timedelta(seconds=0)
    
    days = diff.days
    hours, remainder = divmod(diff.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    msg = (
        f"📊 **IRON MIND DASHBOARD**\n\n"
        f"🎯 **Goal:** Quitting {habit_name}\n"
        f"📅 **Started:** {start_time.strftime('%Y-%m-%d')}\n"
        f"⏱️ **Abstinence Time:** {days} Days, {hours} Hours, {minutes} Mins\n\n"
        f"Every second counts! 💪"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Open Web App Dashboard", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("🔄 Reset Timer", callback_data="prompt_reset")]
    ])
    
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def show_reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    habit = get_habit(user_id)
    
    if not habit:
        await update.message.reply_text("⚠️ **কোনো তথ্য নেই!**\n\nআগে একটি হ্যাবিট গোল সেটআপ করুন।", reply_markup=get_reply_keyboard())
        return

    history = habit.get("reset_history", [])
    if history and len(history) > 0:
        msg = "📜 **YOUR RESET HISTORY:**\n\n"
        for idx, item in enumerate(history[-5:], 1):
            dt_str = item.get("date", "")[:10]
            rsn = item.get("reason", "No reason provided")
            msg += f"{idx}. **{dt_str}** - {rsn}\n"
        await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text("📜 **Reset History:** কোনো রিসেট হিস্ট্রি নেই! আপনার স্ট্রিক অক্ষুণ্ন রয়েছে। 🔥", reply_markup=get_reply_keyboard())

async def show_streaks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    habit = get_habit(user_id)
    
    if not habit:
        await update.message.reply_text("⚠️ **কোনো তথ্য নেই!**\n\nআগে একটি হ্যাবিট গোল সেটআপ করুন।", reply_markup=get_reply_keyboard())
        return

    start_time = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
    days = max(0, (datetime.now(timezone.utc) - start_time).days)
    msg = (
        f"🏆 **TROPHIES & MILESTONES (Streak: {days} Days)**\n\n"
        f"🛡️ **24 Hours Shield:** {'Achieved ✅' if days >= 1 else 'Locked 🔒'}\n"
        f"🛡️ **3 Days Shield:** {'Achieved ✅' if days >= 3 else 'Locked 🔒'}\n"
        f"🛡️ **1 Week Shield:** {'Achieved ✅' if days >= 7 else 'Locked 🔒'}\n"
        f"🛡️ **1 Month Shield:** {'Achieved ✅' if days >= 30 else 'Locked 🔒'}"
    )
    await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")

async def show_savings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    habit = get_habit(user_id)
    
    if not habit:
        await update.message.reply_text("⚠️ **কোনো তথ্য নেই!**\n\nআগে একটি হ্যাবিট গোল সেটআপ করুন।", reply_markup=get_reply_keyboard())
        return

    start_time = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
    days = max(0, (datetime.now(timezone.utc) - start_time).days)
    msg = (
        f"💰 **SAVINGS CALCULATOR**\n\n"
        f"💵 **Estimated Money Saved:** ৳{days * 100}\n"
        f"⏳ **Estimated Time Saved:** {days * 2} Hours\n\n"
        f"স্ট্রিক ধরে রাখুন এবং আরও সাশ্রয় করুন!"
    )
    await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = context.user_data.get("user_pin")
    if pin:
        msg = f"⚙️ **SETTINGS & SECURITY**\n\n🔒 **PIN Status:** Active (`{pin}`)\n\nপিন পরিবর্তন করতে নতুন ৪ ডিজিটের নম্বর পাঠান।"
    else:
        msg = "⚙️ **SETTINGS & SECURITY**\n\n🔒 **PIN Status:** কোনো পিন সেট করা নেই!\n\nসুরক্ষার জন্য আপনার অ্যাকাউন্টে ৪ ডিজিটের পিন সেট করতে এখানে নম্বর পাঠান।"

    await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")

async def handle_menu_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📊 Dashboard":
        await show_dashboard(update, context)
    elif text == "📜 Reset History":
        await show_reset_history(update, context)
    elif text == "🔥 Streaks & Trophies":
        await show_streaks(update, context)
    elif text == "💰 Savings Tracker":
        await show_savings(update, context)
    elif text == "⚙️ Settings & PIN":
        await show_settings(update, context)
    
    return ConversationHandler.END

# --- Onboarding Flows ---
async def start_new_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 **Step 1:** যে অভ্যাসটি আপনি ছাড়তে চান তার নাম লিখুন:\n"
        "*(যেমন: Smoking, Social Media, Sugar, Gambling)*",
        parse_mode="Markdown"
    )
    return HABIT_NAME

async def habit_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_habit_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"বুঝেছি! আপনি **{context.user_data['new_habit_name']}** ছাড়তে চান।\n\n"
        f"👉 **Step 2:** আপনি কবে থেকে এটি ছেড়েছেন?\n\n"
        f"• **'today'** লিখুন আজ থেকে শুরু করতে।\n"
        f"• **'5 days ago'** লিখুন (বা যত দিন আগে ছাড়েন)।\n"
        f"• অথবা তারিখ দিন: **YYYY-MM-DD** (যেমন: `2026-10-15`)",
        parse_mode="Markdown"
    )
    return QUIT_DATE

async def quit_date_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    dt = parse_user_date(text)
    
    if not dt:
        await update.message.reply_text("❌ **ভুল ফরম্যাট!** অনুগ্রহ করে 'today', '5 days ago', অথবা 'YYYY-MM-DD' ফরম্যাটে লিখুন।")
        return QUIT_DATE

    user_id = update.effective_user.id
    habit_name = context.user_data.get("new_habit_name")
    
    try:
        supabase.table("habits").delete().eq("user_id", user_id).execute()
        supabase.table("habits").insert({
            "user_id": user_id, 
            "name": habit_name, 
            "created_at": dt.isoformat(),
            "reset_history": []
        }).execute()
        
        await update.message.reply_text(
            f"🎉 **সেটআপ সফল হয়েছে!**\n\nলক্ষ্য: **Quitting {habit_name}**\nশুরুর তারিখ: **{dt.strftime('%Y-%m-%d')}**\n\nটাইমার লাইভ চালু হয়েছে! 🔥",
            reply_markup=get_reply_keyboard(), parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"DB Error: {e}")
        await update.message.reply_text("❌ ডাটাবেজে সেভ হতে সমস্যা হয়েছে।", reply_markup=get_reply_keyboard())
        
    return ConversationHandler.END

async def prompt_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "⚠️ **টাইমার রিসেট করতে চাচ্ছেন!**\n\n"
        "কেন আপনার স্ট্রিক ভেঙ্গে গেল তার **কারণ** সংক্ষেপে লিখে পাঠান।\n"
        "*(এটি আপনার Reset History-তে সেভ থাকবে)*",
        parse_mode="Markdown"
    )
    return RESET_REASON

async def execute_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    user_id = update.effective_user.id
    now_iso = datetime.now(timezone.utc).isoformat()
    
    habit = get_habit(user_id)
    if habit:
        history = habit.get("reset_history", []) if habit.get("reset_history") else []
        history.append({"date": now_iso, "reason": reason})
        
        try:
            supabase.table("habits").update({
                "created_at": now_iso,
                "reset_history": history
            }).eq("user_id", user_id).execute()
            
            await update.message.reply_text(
                f"🔄 **টাইমার সফলভাবে রিসেট হয়েছে!**\n\nকারণ: *\"{reason}\"*\nআবার নতুন স্ট্রিক শুরু করুন! 💪",
                reply_markup=get_reply_keyboard(), parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Reset DB Error: {e}")
            await update.message.reply_text("❌ সেভ হতে সমস্যা হয়েছে।", reply_markup=get_reply_keyboard())
    else:
        await update.message.reply_text("⚠️ রিসেট করার জন্য কোনো অভ্যাস পাওয়া যায়নি।", reply_markup=get_reply_keyboard())
        
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_or_create_user(user_id)
    
    commands = [BotCommand("start", "Restart Bot"), BotCommand("dashboard", "Open Dashboard")]
    await context.bot.set_my_commands(commands)
    
    await update.message.reply_text(
        f"🛡️ **Welcome to Iron Mind!**\n\nনিচের মেনু বাটনগুলো ব্যবহার করুন।",
        reply_markup=get_reply_keyboard(), parse_mode="Markdown"
    )

def main():
    if not BOT_TOKEN: return
    Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    onboarding_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ New Habit Goal$"), start_onboarding)],
        states={
            HABIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_REGEX), habit_name_received)],
            QUIT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_REGEX), quit_date_received)],
        },
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX), handle_menu_commands)],
    )

    reset_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(prompt_reset, pattern="^prompt_reset$")],
        states={
            RESET_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_REGEX), execute_reset)]
        },
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX), handle_menu_commands)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dashboard", show_dashboard))
    app.add_handler(onboarding_handler)
    app.add_handler(reset_handler)
    
    app.add_handler(MessageHandler(filters.Regex(MENU_REGEX), handle_menu_commands))
    
    print("Iron Mind Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
