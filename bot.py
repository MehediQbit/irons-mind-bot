import os
import logging
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from database import get_or_create_user

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

# ইনপুট বক্সের নিচের স্থায়ী কিবোর্ড
def get_reply_keyboard():
    keyboard = [
        [KeyboardButton("📊 Dashboard"), KeyboardButton("➕ Add Habit")],
        [KeyboardButton("📝 Log Habit"), KeyboardButton("🔥 View Streaks")],
        [KeyboardButton("⚙️ Settings"), KeyboardButton("❓ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ইনলাইন ড্যাশবোর্ড বাটন
def get_inline_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Open Web App Dashboard", callback_data="open_webapp")],
        [InlineKeyboardButton("⚙️ PIN & Biometric Lock", callback_data="settings")]
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

    await update.message.reply_text(
        f"🛡️ **Welcome to Iron Mind, {user.first_name}!**\n\n"
        f"Use the persistent menu buttons below without typing anything!",
        reply_markup=get_reply_keyboard(),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if query.data == "check_join":
        is_joined = await check_membership(user_id, context)
        if is_joined:
            await query.answer("✅ Verified successfully!", show_alert=True)
            await query.edit_message_text(
                f"🛡️ **Welcome to Iron Mind!**\n\nYour account is now active.",
                reply_markup=get_inline_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await query.answer("❌ You haven't joined @IronsMind yet!", show_alert=True)

    elif query.data == "open_webapp":
        await query.answer("📊 Web App Dashboard is loading...", show_alert=True)

    elif query.data == "settings":
        await query.answer("⚙️ Settings menu selected!", show_alert=True)

# কিবোর্ডের টেক্সট বাটনে ক্লিক হ্যান্ডেল করা
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📊 Dashboard":
        await update.message.reply_text("📊 **Opening Dashboard...**", reply_markup=get_inline_keyboard(), parse_mode="Markdown")
    elif text == "➕ Add Habit":
        await update.message.reply_text("➕ **Habit Manager:** Select or send habit name to track.", reply_markup=get_reply_keyboard())
    elif text == "📝 Log Habit":
        await update.message.reply_text("📝 **Habit Logged Successfully for today!** 🔥", reply_markup=get_reply_keyboard())
    elif text == "🔥 View Streaks":
        await update.message.reply_text("🔥 **Current Streak:** 7 Days Active!", reply_markup=get_reply_keyboard())
    elif text == "⚙️ Settings":
        await update.message.reply_text("⚙️ **Settings:** Manage PIN lock and notifications.", reply_markup=get_reply_keyboard())
    elif text == "❓ Help":
        await update.message.reply_text("❓ **Iron Mind Support:** Simply tap any button below to operate the bot.", reply_markup=get_reply_keyboard())

# নেটিভ 'Menu' বাটন সেট করা
async def post_init(application: Application):
    commands = [
        BotCommand("start", "Start or restart Iron Mind Bot"),
        BotCommand("dashboard", "Open Dashboard"),
        BotCommand("help", "Get support")
    ]
    await application.bot.set_my_commands(commands)

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN is missing!")
        return
        
    Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    print("Iron Mind Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
