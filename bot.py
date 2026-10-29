import os
import logging
from datetime import datetime, timezone, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

HABIT_NAME, QUIT_DATE, RESET_REASON = range(3)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Iron Mind Bot is Running Live!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        logging.error(f"Membership check error: {e}")
        return False

def get_reply_keyboard():
    keyboard = [
        [KeyboardButton("📊 Dashboard"), KeyboardButton("➕ New Habit Goal")],
        [KeyboardButton("📜 Reset History"), KeyboardButton("🔥 Streaks & Trophies")],
        [KeyboardButton("💰 Savings Tracker"), KeyboardButton("⚙️ Settings & PIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_user_habit_data(user_id: int):
    try:
        res = supabase.table("habits").select("*").eq("user_id", user_id).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logging.error(f"DB Read Error: {e}")
        return None

def parse_user_date(text: str):
    text_clean = text.strip().lower()
    now = datetime.now(timezone.utc)
    
    if text_clean in ["today", "আজ", "এখন", "now"]:
        return now
    
    if "day" in text_clean or "দিন" in text_clean:
        try:
            num = int(''.join(filter(str.isdigit, text_clean)))
            return now - timedelta(days=num)
        except Exception:
            pass

    formats = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in formats:
        try:
            dt = datetime.strptime(text.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None

async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    habit = get_user_habit_data(user_id)
    
    if not habit:
        await update.message.reply_text(
            "⚠️ **No active habit setup yet!**\n\nTap '➕ New Habit Goal' to set up your habit step-by-step.",
            reply_markup=get_reply_keyboard(),
            parse_mode="Markdown"
        )
        return

    habit_name = habit.get("name", "Addiction")
    created_str = habit.get("created_at") or habit.get("quit_date")
    
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
        f"📊 **IRON MIND LIVE DASHBOARD**\n\n"
        f"🎯 **Target Goal:** Quitting {habit_name}\n"
        f"📅 **Started / Quit Date:** {start_time.strftime('%Y-%m-%d')}\n"
        f"⏱️ **Abstinence Time:** {days} Days, {hours} Hours, {minutes} Mins\n\n"
        f"Every second builds your willpower! 💪"
    )
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Reset Timer with Reason", callback_data="prompt_reset")]])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    get_or_create_user(user_id)
    is_joined = await check_membership(user_id, context)
    
    if not is_joined:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Official Channel", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}")],
            [InlineKeyboardButton("💡 Join Updates (Optional)", url="https://t.me/MehediQbit")],
            [InlineKeyboardButton("🔄 Verify Join", callback_data="check_join")]
        ])
        await update.message.reply_text(
            f"👋 Hello {user.first_name}!\n\n"
            f"⚠️ **Access Denied!**\n"
            f"You must join our official channel {REQUIRED_CHANNEL} to use Iron Mind.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"🛡️ **Welcome to Iron Mind, {user.first_name}!**\n\n"
        f"Use the buttons below to control your habits and dashboard.",
        reply_markup=get_reply_keyboard(),
        parse_mode="Markdown"
    )

# --- Onboarding Steps ---
async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 **Question 1:** What is the name of the habit or addiction you want to quit?\n"
        "*(Examples: Smoking, Gambling, Social Media, Sugar)*",
        parse_mode="Markdown"
    )
    return HABIT_NAME

async def habit_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("❌ Invalid name! Please send a valid habit name (e.g., Smoking).")
        return HABIT_NAME

    context.user_data["temp_habit_name"] = text
    await update.message.reply_text(
        f"Got it! Goal: **Quitting {text}**.\n\n"
        f"👉 **Question 2:** When did you quit or start this timer?\n\n"
        f"• Type **'today'** if starting today.\n"
        f"• Type **'10 days ago'** (or any number of days ago).\n"
        f"• Or send exact date: **YYYY-MM-DD** (Example: `2026-10-15`)",
        parse_mode="Markdown"
    )
    return QUIT_DATE

async def quit_date_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    dt = parse_user_date(text)
    
    if not dt:
        await update.message.reply_text(
            "❌ **Invalid Date Format!**\n\n"
            "Please send in one of these formats:\n"
            "1. Type `today`\n"
            "2. Type `5 days ago` (or any number)\n"
            "3. Send Date: `YYYY-MM-DD` (e.g. `2026-10-01`)",
            parse_mode="Markdown"
        )
        return QUIT_DATE

    user_id = update.effective_user.id
    now_iso = dt.isoformat()
    habit_name = context.user_data.get("temp_habit_name")
    
    habit_data = {
        "user_id": user_id,
        "name": habit_name,
        "created_at": now_iso
    }
    
    try:
        supabase.table("habits").delete().eq("user_id", user_id).execute()
        supabase.table("habits").insert(habit_data).execute()
    except Exception as e:
        logging.error(f"DB Insert Error: {e}")

    await update.message.reply_text(
        f"🎉 **Habit Goal Saved Successfully!**\n\n"
        f"Goal: **Quitting {habit_name}**\n"
        f"Start Date: **{dt.strftime('%Y-%m-%d')}**\n\n"
        f"Your real-time abstinence timer is active! 🔥",
        reply_markup=get_reply_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Process cancelled.", reply_markup=get_reply_keyboard())
    return ConversationHandler.END

# --- Reset Flow ---
async def prompt_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚠️ **Resetting Timer:**\n\n"
        "Please type and send the **reason** for resetting your timer.\n"
        "*(This will be logged in your Reset History)*"
    )
    return RESET_REASON

async def save_reset_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    user_id = update.effective_user.id
    now_iso = datetime.now(timezone.utc).isoformat()
    
    try:
        supabase.table("habits").update({"created_at": now_iso}).eq("user_id", user_id).execute()
    except Exception as e:
        logging.error(f"Reset Error: {e}")

    await update.message.reply_text(
        f"🔄 **Timer Reset Recorded!**\n\nReason: *\"{reason}\"*\nNew streak starts now! 💪",
        reply_markup=get_reply_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# --- Main Message Handler ---
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📊 Dashboard":
        await show_dashboard(update, context)
    elif text == "📜 Reset History":
        await update.message.reply_text("📜 **Reset History:** History logs active.", reply_markup=get_reply_keyboard())
    elif text in ["🔥 Streaks & Trophies", "💰 Savings Tracker", "⚙️ Settings & PIN"]:
        await update.message.reply_text(f"📌 **{text}** configuration active.", reply_markup=get_reply_keyboard())

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "check_join":
        is_joined = await check_membership(user_id, context)
        if is_joined:
            await query.edit_message_text("✅ Verified! Send /start to open menu.")
        else:
            await query.answer("❌ You haven't joined @IronsMind yet!", show_alert=True)

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN is missing!")
        return
        
    Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    menu_buttons_regex = "^(📊 Dashboard|➕ New Habit Goal|📜 Reset History|🔥 Streaks & Trophies|💰 Savings Tracker|⚙️ Settings & PIN)$"

    onboarding_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ New Habit Goal$"), start_onboarding)],
        states={
            HABIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(menu_buttons_regex), habit_name_step)],
            QUIT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(menu_buttons_regex), quit_date_step)],
        },
        fallbacks=[MessageHandler(filters.Regex(menu_buttons_regex), cancel_conversation)],
    )

    reset_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(prompt_reset_callback, pattern="^prompt_reset$")],
        states={
            RESET_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reset_reason)]
        },
        fallbacks=[MessageHandler(filters.Regex(menu_buttons_regex), cancel_conversation)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dashboard", lambda u, c: show_dashboard(u, c)))
    app.add_handler(onboarding_conv)
    app.add_handler(reset_conv)
    app.add_handler(CallbackQueryHandler(button_callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    print("Iron Mind Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
