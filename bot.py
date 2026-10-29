import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv
from database import get_or_create_user

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@IronsMind")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """ইউজার বাধ্যতামূলক চ্যানেলে সদস্য কি না তা যাচাই করে।"""
    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
        return False
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """স্টার্ট কমান্ড এবং চ্যানেল সাবস্ক্রিপশন চেক করে।"""
    user = update.effective_user
    user_id = user.id
    
    # ডাটাবেজে ইউজার এন্ট্রি
    get_or_create_user(user_id)
    
    # চ্যানেল সাবস্ক্রিপশন যাচাই
    is_joined = await check_membership(user_id, context)
    
    if not is_joined:
        keyboard = [
            [InlineKeyboardButton("📢 Join Official Channel", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}")],
            [InlineKeyboardButton("💡 Join Updates (Optional)", url="https://t.me/MehediQbit")],
            [InlineKeyboardButton("🔄 Verify Join", callback_data="check_join")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"👋 Hello {user.first_name}!\n\n"
            f"⚠️ **Access Denied!**\n"
            f"You must join our official channel {REQUIRED_CHANNEL} to use Iron Mind.\n\n"
            f"Please join and click 'Verify Join' below.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    # মূল ওয়েলকাম বোতাম
    keyboard = [
        [InlineKeyboardButton("📊 Open Web App Dashboard", callback_data="open_webapp")],
        [InlineKeyboardButton("⚙️ Settings & PIN", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🛡️ **Welcome to Iron Mind, {user.first_name}!**\n\n"
        f"Your private habit and streak tracker is ready.\n"
        f"Use the dashboard to track your habits and build willpower securely.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ইনলাইন বাটনের রেসপন্স হ্যান্ডল করে।"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "check_join":
        is_joined = await check_membership(query.from_user.id, context)
        if is_joined:
            await query.edit_message_text(
                "✅ **Verification Successful!**\n\nSend /start to open your Iron Mind dashboard.",
                parse_mode="Markdown"
            )
        else:
            await query.answer("❌ You haven't joined @IronsMind yet!", show_alert=True)

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN environment variable is missing!")
        return
        
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("Iron Mind Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
              
