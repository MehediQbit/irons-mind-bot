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

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@IronsMind")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://irons-mind-bot.onrender.com")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Conversation States
HABIT_NAME, QUIT_DATE = range(2)
RESET_REASON = 10

# --- Health Check Server for Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Iron Mind Bot is Running Live!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- Helpers & Keyboards ---
def get_reply_keyboard():
    keyboard = [
        [KeyboardButton("📊 Dashboard"), KeyboardButton("➕ New Habit Goal")],
        [KeyboardButton("📜 Reset History"), KeyboardButton("🔥 Streaks & Trophies")],
        [KeyboardButton("💰 Savings Tracker"), KeyboardButton("⚙️ Settings")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

MENU_REGEX = "^(📊 Dashboard|➕ New Habit Goal|📜 Reset History|🔥 Streaks & Trophies|💰 Savings Tracker|⚙️ Settings)$"

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

# --- Feature Modules ---
async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    habit = get_habit(user_id)
    
    if not habit:
        await update.message.reply_text(
            "⚠️ **No active habit found!**\n\nPlease tap '➕ New Habit Goal' to set up your tracker first.",
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
        f"⏱️ **Abstinence Time:** {days}d, {hours}h, {minutes}m\n\n"
        f"Every second counts! 💪"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Open Web App Dashboard", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("🔄 Reset Timer", callback_data="prompt_reset")]
    ])
    
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def handle_menu_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "📊 Dashboard":
        await show_dashboard(update, context)

    elif text == "📜 Reset History":
        habit = get_habit(user_id)
        if habit and habit.get("reset_history"):
            history = habit.get("reset_history")
            msg = "📜 **YOUR RESET HISTORY:**\n\n"
            for idx, item in enumerate(history[-5:], 1):
                dt_str = item.get("date", "")[:10]
                rsn = item.get("reason", "No reason provided")
                msg += f"{idx}. **{dt_str}** - {rsn}\n"
            await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        else:
            await update.message.reply_text("📜 **Reset History:** No resets logged. You are on a perfect streak! 🔥", reply_markup=get_reply_keyboard())

    elif text == "🔥 Streaks & Trophies":
        habit = get_habit(user_id)
        if habit:
            start_time = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
            days = max(0, (datetime.now(timezone.utc) - start_time).days)
            msg = (
                f"🏆 **TROPHIES & MILESTONES (Current: {days} Days)**\n\n"
                f"🛡️ **24 Hours Shield:** {'Achieved ✅' if days >= 1 else 'Locked 🔒'}\n"
                f"🛡️ **3 Days Shield:** {'Achieved ✅' if days >= 3 else 'Locked 🔒'}\n"
                f"🛡️ **1 Week Shield:** {'Achieved ✅' if days >= 7 else 'Locked 🔒'}\n"
                f"🛡️ **1 Month Shield:** {'Achieved ✅' if days >= 30 else 'Locked 🔒'}"
            )
            await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ Setup a habit first to see trophies.", reply_markup=get_reply_keyboard())

    elif text == "💰 Savings Tracker":
        habit = get_habit(user_id)
        if habit:
            start_time = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
            days = max(0, (datetime.now(timezone.utc) - start_time).days)
            msg = (
                f"💰 **SAVINGS CALCULATOR**\n\n"
                f"💵 **Estimated Money Saved:** ৳{days * 100}\n"
                f"⏳ **Estimated Time Saved:** {days * 2} Hours\n\n"
                f"Keep up the streak to save more!"
            )
            await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ Setup a habit first to see savings.", reply_markup=get_reply_keyboard())

    elif text == "⚙️ Settings":
        await update.message.reply_text("⚙️ **Settings & Security:** Feature active.", reply_markup=get_reply_keyboard())
    
    return ConversationHandler.END

# --- Onboarding Conversation (New Habit) ---
async def start_new_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 **Step 1:** What is the name of the habit or addiction you want to quit?\n"
        "*(Example: Smoking, Social Media, Sugar, Gambling)*",
        parse_mode="Markdown"
    )
    return HABIT_NAME

async def habit_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_habit_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"Got it! You want to quit **{context.user_data['new_habit_name']}**.\n\n"
        f"👉 **Step 2:** When did you start your timer?\n\n"
        f"• Type **'today'** if starting today.\n"
        f"• Type **'5 days ago'** (or any number).\n"
        f"• Or send Date: **YYYY-MM-DD** (e.g. `2026-10-15`)",
        parse_mode="Markdown"
    )
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
        supabase.table("habits").delete().eq("user_id", user_id).execute()
        supabase.table("habits").insert({
            "user_id": user_id, 
            "name": habit_name, 
            "created_at": dt.isoformat(),
            "reset_history": []
        }).execute()
        
        await update.message.reply_text(
            f"🎉 **Setup Complete!**\n\nQuitting: **{habit_name}**\nStarted: **{dt.strftime('%Y-%m-%d')}**\n\nTimer is live! 🔥",
            reply_markup=get_reply_keyboard(), parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"DB Error: {e}")
        await update.message.reply_text("❌ Database error occurred.", reply_markup=get_reply_keyboard())
        
    return ConversationHandler.END

# --- Reset Conversation ---
async def prompt_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "⚠️ **You are about to Reset your Timer!**\n\n"
        "Please type and send the **reason** why you relapsed or broke the streak.\n"
        "*(This helps you analyze triggers later in Reset History)*",
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
                f"🔄 **Timer Reset Successful!**\n\nReason: *\"{reason}\"*\nDon't give up! A new streak begins right now. 💪",
                reply_markup=get_reply_keyboard(), parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Reset DB Error: {e}")
            await update.message.reply_text("❌ Failed to save reset.", reply_markup=get_reply_keyboard())
    else:
        await update.message.reply_text("⚠️ No habit found to reset.", reply_markup=get_reply_keyboard())
        
    return ConversationHandler.END

# --- Start & Core Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_or_create_user(user_id)
    
    commands = [BotCommand("start", "Restart Bot"), BotCommand("help", "Get Support")]
    await context.bot.set_my_commands(commands)
    
    await update.message.reply_text(
        f"🛡️ **Welcome to Iron Mind!**\n\nUse the menu buttons below.",
        reply_markup=get_reply_keyboard(), parse_mode="Markdown"
    )

def main():
    if not BOT_TOKEN: return
    Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 1. Onboarding Conversation
    onboarding_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ New Habit Goal$"), start_new_habit)],
        states={
            HABIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_REGEX), habit_name_received)],
            QUIT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_REGEX), quit_date_received)],
        },
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX), handle_menu_commands)],
    )

    # 2. Reset Timer Conversation
    reset_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(prompt_reset, pattern="^prompt_reset$")],
        states={
            RESET_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_REGEX), execute_reset)]
        },
        fallbacks=[MessageHandler(filters.Regex(MENU_REGEX), handle_menu_commands)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(onboarding_handler)
    app.add_handler(reset_handler)
    
    # General Menu Handler for any button tap outside a conversation
    app.add_handler(MessageHandler(filters.Regex(MENU_REGEX), handle_menu_commands))
    
    print("Iron Mind Bot is running flawlessly...")
    app.run_polling()

if __name__ == "__main__":
    main()
