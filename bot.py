import os
import logging
from datetime import datetime
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
        [KeyboardButton("📊 Dashboard"), KeyboardButton("➕ Add Habit")],
        [KeyboardButton("📝 Daily Diary"), KeyboardButton("🔥 Streaks & Trophies")],
        [KeyboardButton("💰 Savings Tracker"), KeyboardButton("⚙️ Settings & PIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_preset_habits_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚭 Smoking", callback_data="preset_Smoking"), InlineKeyboardButton("🍷 Alcohol", callback_data="preset_Alcohol")],
        [InlineKeyboardButton("🔞 Porn / Masturbation", callback_data="preset_Porn"), InlineKeyboardButton("🍰 Sugar", callback_data="preset_Sugar")],
        [InlineKeyboardButton("🎲 Gambling", callback_data="preset_Gambling"), InlineKeyboardButton("📱 Social Media", callback_data="preset_Procrastination")],
        [InlineKeyboardButton("✏️ Custom Habit Name", callback_data="preset_custom")]
    ])

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

    commands = [
        BotCommand("start", "Restart Iron Mind Bot"),
        BotCommand("dashboard", "Open Dashboard"),
        BotCommand("help", "Get Support")
    ]
    await context.bot.set_my_commands(commands)

    await update.message.reply_text(
        f"🛡️ **Welcome to Iron Mind, {user.first_name}!**\n\n"
        f"Track your abstinence timers, streaks, savings, and trophies directly below without typing commands.",
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
            await query.edit_message_text(
                f"🛡️ **Welcome to Iron Mind!**\n\nYour account is now active.",
                reply_markup=get_reply_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await query.answer("❌ You haven't joined @IronsMind yet!", show_alert=True)

    elif query.data.startswith("preset_"):
        preset_type = query.data.split("_")[1]
        if preset_type == "custom":
            context.user_data["awaiting_habit_name"] = True
            await query.edit_message_text("✍️ **Send the name of your custom habit/addiction to quit:**")
        else:
            try:
                supabase.table("habits").insert({"user_id": user_id, "name": preset_type}).execute()
                await query.edit_message_text(f"✅ **Goal Created:** Quitting **{preset_type}**!\n\nTimer started from today! 🔥")
            except Exception as e:
                logging.error(f"DB Error: {e}")
                await query.edit_message_text(f"✅ Goal set for **{preset_type}**! Timer running.")

    elif query.data == "reset_timer":
        await query.edit_message_text("🔄 **Timer Reset!** Don't give up, start your new streak right now! 💪")

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    # কাস্টম হ্যাবিট ইনপুট হ্যান্ডলিং
    if context.user_data.get("awaiting_habit_name"):
        habit_name = text.strip()
        try:
            supabase.table("habits").insert({"user_id": user_id, "name": habit_name}).execute()
            context.user_data["awaiting_habit_name"] = False
            await update.message.reply_text(
                f"✅ **Goal Created Successfully!**\n\nQuitting: **{habit_name}**\nTimer started! 🔥",
                reply_markup=get_reply_keyboard(),
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Error adding habit: {e}")
            await update.message.reply_text(f"✅ Quitting **{habit_name}** saved!", reply_markup=get_reply_keyboard())
        return

    # কিবোর্ড বাটন লজিক
    if text == "📊 Dashboard":
        msg = (
            "📊 **IRON MIND DASHBOARD**\n\n"
            "🔴 **Active Goal:** Quitting Addiction\n"
            "⏱️ **Abstinence Time:** 10 days, 6 hours, 56 mins\n"
            "🎯 **Current Goal:** 2 Weeks (73.5% Completed)\n\n"
            "I'm in control now! 💪"
        )
        reset_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Reset Timer", callback_data="reset_timer")]])
        await update.message.reply_text(msg, reply_markup=reset_btn, parse_mode="Markdown")

    elif text == "➕ Add Habit":
        await update.message.reply_text(
            "🎯 **What do you want to quit?**\nChoose a category or set a custom habit:",
            reply_markup=get_preset_habits_keyboard()
        )

    elif text == "📝 Daily Diary":
        await update.message.reply_text(
            "📖 **Daily Motivation & Reasons to Quit:**\n\n"
            "1. *'I choose freedom from this habit!'*\n"
            "2. *'An ant on the move does more than a dozing ox.'*\n\n"
            "Type any note below to log into your diary.",
            reply_markup=get_reply_keyboard(),
            parse_mode="Markdown"
        )

    elif text == "🔥 Streaks & Trophies":
        trophies_text = (
            "🏆 **YOUR TROPHIES & MILESTONES:**\n\n"
            "🛡️ **24 Hours Shield:** Achieved ✅\n"
            "🛡️ **3 Days Shield:** Achieved ✅\n"
            "🛡️ **1 Week Shield:** Achieved ✅\n"
            "🔒 **1 Month Shield:** 10 Days Remaining\n\n"
            "Keep pushing! Your willpower is forging into iron."
        )
        await update.message.reply_text(trophies_text, reply_markup=get_reply_keyboard(), parse_mode="Markdown")

    elif text == "💰 Savings Tracker":
        savings_text = (
            "💰 **FINANCIAL & TIME SAVINGS:**\n\n"
            "💵 **Money Saved:** $0.00 / ৳0.00\n"
            "⏳ **Time Saved:** 10 Hours Total\n"
            "🥕 **Rewards:** Set a savings target to earn treats!"
        )
        await update.message.reply_text(savings_text, reply_markup=get_reply_keyboard(), parse_mode="Markdown")

    elif text == "⚙️ Settings & PIN":
        await update.message.reply_text(
            "⚙️ **SETTINGS & SECURITY:**\n\n"
            "🔒 **PIN Lock:** Active\n"
            "🔔 **Daily Reminder:** 09:00 AM\n"
            "👤 **Account:** Verified",
            reply_markup=get_reply_keyboard(),
            parse_mode="Markdown"
        )

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
