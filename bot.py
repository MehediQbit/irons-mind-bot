import os
import logging
from datetime import datetime, timezone
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from database import get_or_create_user, supabase

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@IronsMind")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

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

async def show_dashboard(update_or_query, user_id: int, is_callback=False):
    habit = get_user_habit_data(user_id)
    if not habit:
        text = "⚠️ **No active habit setup yet!**\n\nTap '➕ New Habit Goal' to set up your habit details step-by-step."
        if is_callback:
            await update_or_query.edit_message_text(text, parse_mode="Markdown")
        else:
            await update_or_query.message.reply_text(text, reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        return

    habit_name = habit.get("name", "Addiction")
    quit_date_str = habit.get("quit_date") or habit.get("created_at")
    
    try:
        quit_time = datetime.fromisoformat(quit_date_str.replace("Z", "+00:00"))
    except Exception:
        quit_time = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    diff = now - quit_time
    
    days = diff.days
    hours, remainder = divmod(diff.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    msg = (
        f"📊 **IRON MIND LIVE DASHBOARD**\n\n"
        f"🎯 **Target Goal:** Quitting {habit_name}\n"
        f"⏳ **Previously Doing For:** {habit.get('duration_years', 'N/A')}\n"
        f"🔄 **Daily Frequency:** {habit.get('daily_frequency', 'N/A')}\n"
        f"⏱️ **Abstinence Time:** {days} Days, {hours} Hours, {minutes} Mins\n\n"
        f"Stay strong! Every second builds your iron willpower. 💪"
    )
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Reset Timer with Reason", callback_data="prompt_reset")]])

    if is_callback:
        await update_or_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update_or_query.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

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
            f"You must join our official channel {REQUIRED_CHANNEL} to use Iron Mind.\n\n"
            f"Please join and click 'Verify Join' below.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    habit = get_user_habit_data(user_id)
    if not habit:
        context.user_data["onboarding_step"] = "habit_name"
        await update.message.reply_text(
            f"🛡️ **Welcome to Iron Mind, {user.first_name}!**\n\n"
            f"Let's configure your tracker first.\n"
            f"👉 **Question 1:** What is the name of the habit or addiction you want to quit?\n"
            f"*(Example: Smoking, Alcohol, Porn, Gambling, Gaming)*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"🛡️ **Welcome back to Iron Mind, {user.first_name}!**\n\n"
            f"Use the buttons below to check your dashboard and stats.",
            reply_markup=get_reply_keyboard(),
            parse_mode="Markdown"
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "check_join":
        is_joined = await check_membership(user_id, context)
        if is_joined:
            await query.edit_message_text("✅ Verified! Send /start to begin setup.")
        else:
            await query.answer("❌ You haven't joined @IronsMind yet!", show_alert=True)

    elif query.data == "prompt_reset":
        context.user_data["awaiting_reset_reason"] = True
        await query.edit_message_text(
            "⚠️ **Resetting Timer:**\n\n"
            "Please send the **reason** for resetting your timer.\n"
            "*(This will be saved in your Reset History to analyze your triggers)*"
        )

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # অনবোর্ডিং ফ্লো (Onboarding Steps)
    step = context.user_data.get("onboarding_step")
    
    if step == "habit_name":
        context.user_data["temp_habit_name"] = text
        context.user_data["onboarding_step"] = "duration"
        await update.message.reply_text(
            f"Got it! Quitting **{text}**.\n\n"
            f"👉 **Question 2:** How long have you had this habit?\n"
            f"*(Example: 2 Years, 6 Months, 5 Years)*",
            parse_mode="Markdown"
        )
        return

    elif step == "duration":
        context.user_data["temp_duration"] = text
        context.user_data["onboarding_step"] = "frequency"
        await update.message.reply_text(
            f"👉 **Question 3:** How often did you do this habit per day/week?\n"
            f"*(Example: 5 times a day, 2 times a week)*",
            parse_mode="Markdown"
        )
        return

    elif step == "frequency":
        context.user_data["temp_frequency"] = text
        now_iso = datetime.now(timezone.utc).isoformat()
        
        habit_data = {
            "user_id": user_id,
            "name": context.user_data.get("temp_habit_name"),
            "duration_years": context.user_data.get("temp_duration"),
            "daily_frequency": text,
            "quit_date": now_iso
        }
        
        try:
            supabase.table("habits").delete().eq("user_id", user_id).execute()
            supabase.table("habits").insert(habit_data).execute()
        except Exception as e:
            logging.error(f"DB Insert Error: {e}")

        context.user_data["onboarding_step"] = None
        await update.message.reply_text(
            "🎉 **Setup Complete!**\n\nYour abstinence timer has started right now! 🔥",
            reply_markup=get_reply_keyboard(),
            parse_mode="Markdown"
        )
        await show_dashboard(update, user_id, is_callback=False)
        return

    # রিসেট রিজন সেভ করা
    if context.user_data.get("awaiting_reset_reason"):
        reason = text
        now_iso = datetime.now(timezone.utc).isoformat()
        
        habit = get_user_habit_data(user_id)
        if habit:
            history = habit.get("reset_history") or []
            history.append({"reset_at": now_iso, "reason": reason})
            
            try:
                supabase.table("habits").update({
                    "quit_date": now_iso,
                    "reset_history": history
                }).eq("user_id", user_id).execute()
            except Exception as e:
                logging.error(f"Reset Save Error: {e}")

        context.user_data["awaiting_reset_reason"] = False
        await update.message.reply_text(f"🔄 **Timer Reset Recorded!**\n\nReason: *\"{reason}\"*\nYour new streak starts now!", reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        return

    # মেনু বাটন হ্যান্ডলার
    if text == "📊 Dashboard":
        await show_dashboard(update, user_id, is_callback=False)

    elif text == "➕ New Habit Goal":
        context.user_data["onboarding_step"] = "habit_name"
        await update.message.reply_text("👉 **Question 1:** What is the name of the new habit/addiction you want to quit?")

    elif text == "📜 Reset History":
        habit = get_user_habit_data(user_id)
        if habit and habit.get("reset_history"):
            history_list = habit.get("reset_history")
            msg = "📜 **YOUR RESET HISTORY & REASONS:**\n\n"
            for idx, item in enumerate(history_list[-5:], 1): # সর্বশেষ ৫টি
                msg += f"{idx}. **Date:** {item['reset_at'][:10]}\n   **Reason:** {item['reason']}\n\n"
            await update.message.reply_text(msg, reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        else:
            await update.message.reply_text("📜 **Reset History:** No resets logged yet! Perfect streak! 🔥", reply_markup=get_reply_keyboard())

    elif text in ["🔥 Streaks & Trophies", "💰 Savings Tracker", "⚙️ Settings & PIN"]:
        await update.message.reply_text(f"📌 **{text}** configuration active.", reply_markup=get_reply_keyboard())

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN is missing!")
        return
        
    Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    print("Iron Mind Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
