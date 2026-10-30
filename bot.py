import os
import logging
from datetime import datetime, timezone, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from database import supabase

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://irons-mind-bot.onrender.com")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- Render Health Check ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Iron Mind Live!")

def run_health_server():
    try:
        server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), HealthCheckHandler)
        server.serve_forever()
    except Exception as e:
        logging.error(f"Health Server Error: {e}")

# --- Database Helpers ---
def get_or_create_profile(user_id):
    try:
        res = supabase.table("users").select("*").eq("id", user_id).execute()
        if res.data: return res.data[0]
        default_data = {"id": user_id, "lang": "bn", "pin": None, "recovery_phrase": None}
        supabase.table("users").insert(default_data).execute()
        return default_data
    except Exception as e:
        logging.error(f"Profile Error: {e}")
        return {"id": user_id, "lang": "bn", "pin": None, "recovery_phrase": None}

def update_user_db(user_id, data):
    supabase.table("users").update(data).eq("id", user_id).execute()

def get_habit(user_id):
    try:
        res = supabase.table("habits").select("*").eq("user_id", user_id).execute()
        return res.data[0] if res.data else None
    except: return None

# --- UI Helpers ---
def get_keyboard(lang):
    if lang == "en":
        return ReplyKeyboardMarkup([
            ["📊 Dashboard", "➕ New Habit Goal"],
            ["📜 Reset History", "🔥 Streaks & Trophies"],
            ["💰 Savings Tracker", "⚙️ Settings & PIN"]
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup([
        ["📊 ড্যাশবোর্ড", "➕ নতুন লক্ষ্য"],
        ["📜 রিসেট হিস্ট্রি", "🔥 ট্রফি ও স্ট্রিক"],
        ["💰 সাশ্রয় ট্র্যাকার", "⚙️ সেটিংস ও পিন"]
    ], resize_keyboard=True)

def parse_date(text: str):
    t = text.strip().lower()
    now = datetime.now(timezone.utc)
    if t in ["today", "আজ", "এখন", "now"]: return now
    if t in ["yesterday", "গতকাল"]: return now - timedelta(days=1)
    if "day" in t or "দিন" in t:
        try: return now - timedelta(days=int(''.join(filter(str.isdigit, t))))
        except: pass
    for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]:
        try: return datetime.strptime(t, fmt).replace(tzinfo=timezone.utc)
        except ValueError: continue
    return None

# --- Core Security Check ---
async def check_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if "profile" not in context.user_data:
        context.user_data["profile"] = get_or_create_profile(user_id)
        
    profile = context.user_data["profile"]
    lang = profile.get("lang", "bn")
    
    if profile.get("pin") and not context.user_data.get("unlocked"):
        msg = "🔒 **বট লক করা আছে!**\n৪-ডিজিটের পিন দিন। (ভুলে গেলে লিখুন: `reset`)" if lang=="bn" else "🔒 **Bot Locked!**\nEnter 4-digit PIN. (Forgot? type: `reset`)"
        if update.message: await update.message.reply_text(msg, parse_mode="Markdown")
        elif update.callback_query: await update.callback_query.answer("Locked!", show_alert=True)
        return True
    return False

# --- Command Functions ---
async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_lock(update, context): return
    context.user_data["state"] = None
    
    user_id = update.effective_user.id
    lang = context.user_data.get("profile", {}).get("lang", "bn")
    habit = get_habit(user_id)
    
    if not habit:
        msg = "⚠️ কোনো তথ্য নেই! '➕ নতুন লক্ষ্য' বাটন থেকে হ্যাবিট সেট করুন।" if lang=="bn" else "⚠️ No data! Tap '➕ New Habit Goal'."
        await update.message.reply_text(msg, reply_markup=get_keyboard(lang))
        return

    st = datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))
    diff = max(timedelta(0), datetime.now(timezone.utc) - st)
    
    if lang == "bn":
        msg = f"📊 **ড্যাশবোর্ড**\n\n🎯 **লক্ষ্য:** {habit.get('name')} ছাড়া\n📅 **শুরু:** {st.strftime('%Y-%m-%d')}\n⏱️ **সময় পার হয়েছে:** {diff.days} দিন, {diff.seconds//3600} ঘণ্টা, {(diff.seconds//60)%60} মিনিট\n\nএগিয়ে যান! 💪"
    else:
        msg = f"📊 **DASHBOARD**\n\n🎯 **Goal:** Quitting {habit.get('name')}\n📅 **Started:** {st.strftime('%Y-%m-%d')}\n⏱️ **Time:** {diff.days}d, {diff.seconds//3600}h, {(diff.seconds//60)%60}m\n\nKeep going! 💪"
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Web Dashboard", web_app=WebAppInfo(url=WEBAPP_URL))], [InlineKeyboardButton("🔄 Reset Timer", callback_data="do_reset")]])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def cmd_new_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_lock(update, context): return
    context.user_data["state"] = "WAITING_HABIT_NAME"
    lang = context.user_data.get("profile", {}).get("lang", "bn")
    msg = "🎯 যে অভ্যাসটি ছাড়তে চান তার নাম লিখুন (যেমন: Sugar, Smoking):" if lang=="bn" else "🎯 Habit name to quit (e.g., Sugar):"
    await update.message.reply_text(msg)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data["profile"] = get_or_create_profile(user_id)
    if context.user_data["profile"].get("pin"): context.user_data["unlocked"] = False
    
    if await check_lock(update, context): return
    lang = context.user_data["profile"].get("lang", "bn")
    await update.message.reply_text("🛡️ **Iron Mind-এ স্বাগতম!**" if lang=="bn" else "🛡️ **Welcome to Iron Mind!**", reply_markup=get_keyboard(lang), parse_mode="Markdown")

# --- Message Handler ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if "profile" not in context.user_data: context.user_data["profile"] = get_or_create_profile(user_id)
    profile = context.user_data["profile"]
    lang = profile.get("lang", "bn")
    state = context.user_data.get("state")

    # 1. PIN Lock Processing
    if profile.get("pin") and not context.user_data.get("unlocked"):
        if text == profile.get("pin"):
            context.user_data["unlocked"] = True
            await update.message.reply_text("✅ আনলক হয়েছে!" if lang=="bn" else "✅ Unlocked!", reply_markup=get_keyboard(lang))
        elif text.lower() == "reset":
            context.user_data["state"] = "WAITING_RECOVERY"
            await update.message.reply_text("🆘 আপনার রিকভারি ফ্রেজ লিখুন:" if lang=="bn" else "🆘 Enter recovery phrase:")
        elif state == "WAITING_RECOVERY":
            if text == profile.get("recovery_phrase"):
                update_user_db(user_id, {"pin": None})
                context.user_data["profile"]["pin"] = None
                context.user_data["unlocked"] = True
                context.user_data["state"] = None
                await update.message.reply_text("✅ পিন সফলভাবে রিসেট হয়েছে!" if lang=="bn" else "✅ PIN reset successful!", reply_markup=get_keyboard(lang))
            else:
                await update.message.reply_text("❌ ভুল ফ্রেজ!" if lang=="bn" else "❌ Wrong phrase!")
        else:
            await update.message.reply_text("❌ ভুল পিন!" if lang=="bn" else "❌ Wrong PIN!")
        return

    # 2. Main Menus
    if text.startswith("📊"): return await cmd_dashboard(update, context)
    elif text.startswith("➕"): return await cmd_new_habit(update, context)
    elif text.startswith("📜"):
        context.user_data["state"] = None
        habit = get_habit(user_id)
        history = habit.get("reset_history", []) if habit else []
        if history:
            msg = "📜 **রিসেট হিস্ট্রি:**\n\n" if lang=="bn" else "📜 **Reset History:**\n\n"
            for i, item in enumerate(history[-5:], 1): msg += f"{i}. **{item.get('date', '')[:10]}** - {item.get('reason', '')}\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("📜 কোনো রেকর্ড নেই!" if lang=="bn" else "📜 No records!")
        return

    elif text.startswith("🔥"):
        context.user_data["state"] = None
        habit = get_habit(user_id)
        if not habit: return await update.message.reply_text("⚠️ ডাটা নেই!" if lang=="bn" else "⚠️ No data!")
        d = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))).days)
        msg = f"🏆 **Trophies (Streak: {d} Days)**\n\n🛡️ **1 Day:** {'✅' if d>=1 else '🔒'}\n🛡️ **3 Days:** {'✅' if d>=3 else '🔒'}\n🛡️ **7 Days:** {'✅' if d>=7 else '🔒'}"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    elif text.startswith("💰"):
        context.user_data["state"] = None
        habit = get_habit(user_id)
        if not habit: return await update.message.reply_text("⚠️ ডাটা নেই!" if lang=="bn" else "⚠️ No data!")
        d = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(habit.get("created_at").replace("Z", "+00:00"))).days)
        msg = f"💰 **সাশ্রয় (Savings)**\n\n💵 টাকা: ৳{d * 100}\n⏳ সময়: {d * 2} ঘণ্টা" if lang=="bn" else f"💰 **Savings**\n\n💵 Money: ${d * 2}\n⏳ Time: {d * 2} Hours"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    elif text.startswith("⚙️"):
        context.user_data["state"] = None
        p_stat = "সক্রিয় 🔒" if profile.get('pin') else "বন্ধ 🔓"
        msg = f"⚙️ **সেটিংস**\n\n🔒 পিন: {p_stat}\n🌐 ভাষা: {'বাংলা' if lang=='bn' else 'English'}" if lang=="bn" else f"⚙️ **Settings**\n\n🔒 PIN: {p_stat}\n🌐 Lang: {'BN' if lang=='bn' else 'EN'}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"), InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🔑 Set PIN", callback_data="set_pin"), InlineKeyboardButton("🗑️ Remove PIN", callback_data="rem_pin")]
        ])
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
        return

    # 3. Form States
    if state == "WAITING_HABIT_NAME":
        context.user_data["temp_name"] = text
        context.user_data["state"] = "WAITING_DATE"
        await update.message.reply_text("👉 কবে থেকে এটি ছেড়েছেন? ('today', '5 days ago', অথবা YYYY-MM-DD)" if lang=="bn" else "👉 Start date? ('today', '5 days ago', or YYYY-MM-DD)")
        
    elif state == "WAITING_DATE":
        dt = parse_date(text)
        if not dt:
            await update.message.reply_text("❌ ভুল তারিখ ফরম্যাট!" if lang=="bn" else "❌ Invalid date format!")
            return
        try:
            supabase.table("habits").delete().eq("user_id", user_id).execute()
            supabase.table("habits").insert({"user_id": user_id, "name": context.user_data["temp_name"], "created_at": dt.isoformat()}).execute()
            context.user_data["state"] = None
            await update.message.reply_text("🎉 সেটআপ সফল!" if lang=="bn" else "🎉 Setup complete!", reply_markup=get_keyboard(lang))
            await cmd_dashboard(update, context)
        except Exception as e:
            logging.error(f"Save Error: {e}")
            await update.message.reply_text("❌ ডাটাবেজ এরর!" if lang=="bn" else "❌ DB Error!")

    elif state == "WAITING_PIN":
        if len(text) >= 4 and text.isdigit():
            update_user_db(user_id, {"pin": text})
            context.user_data["profile"]["pin"] = text
            context.user_data["unlocked"] = True
            context.user_data["state"] = "WAITING_RECOVERY_SETUP"
            await update.message.reply_text("✅ পিন সেভ হয়েছে!\n\nএখন একটি **রিকভারি ফ্রেজ** (যেমন: প্রিয় রঙের নাম) দিন, যা পিন ভুলে গেলে কাজে লাগবে:" if lang=="bn" else "✅ PIN Saved!\nNow enter a Recovery Phrase:")
        else:
            await update.message.reply_text("❌ কমপক্ষে ৪-ডিজিটের সংখ্যা দিন।" if lang=="bn" else "❌ Must be 4+ digits.")

    elif state == "WAITING_RECOVERY_SETUP":
        update_user_db(user_id, {"recovery_phrase": text})
        context.user_data["profile"]["recovery_phrase"] = text
        context.user_data["state"] = None
        await update.message.reply_text("🛡️ নিরাপত্তা সেটআপ সম্পূর্ণ হয়েছে!" if lang=="bn" else "🛡️ Security setup complete!", reply_markup=get_keyboard(lang))

    elif state == "WAITING_RESET_REASON":
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            habit = get_habit(user_id)
            history = habit.get("reset_history", []) if habit and habit.get("reset_history") else []
            history.append({"date": now_iso, "reason": text})
            
            supabase.table("habits").update({"created_at": now_iso, "reset_history": history}).eq("user_id", user_id).execute()
            context.user_data["state"] = None
            await update.message.reply_text("🔄 টাইমার রিসেট হয়েছে!" if lang=="bn" else "🔄 Timer reset!", reply_markup=get_keyboard(lang))
            await cmd_dashboard(update, context)
        except Exception as e:
            logging.error(f"Reset Error: {e}")
            await update.message.reply_text("❌ এরর হয়েছে!" if lang=="bn" else "❌ Error!")

# --- Callbacks (Buttons) ---
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if "profile" not in context.user_data: context.user_data["profile"] = get_or_create_profile(user_id)
    lang = context.user_data["profile"].get("lang", "bn")
    
    if data == "lang_en":
        update_user_db(user_id, {"lang": "en"})
        context.user_data["profile"]["lang"] = "en"
        await query.message.reply_text("✅ Language changed to English.", reply_markup=get_keyboard("en"))
    elif data == "lang_bn":
        update_user_db(user_id, {"lang": "bn"})
        context.user_data["profile"]["lang"] = "bn"
        await query.message.reply_text("✅ ভাষা বাংলায় পরিবর্তন করা হয়েছে।", reply_markup=get_keyboard("bn"))
    elif data == "set_pin":
        context.user_data["state"] = "WAITING_PIN"
        await query.message.reply_text("🔑 একটি ৪-ডিজিটের পিন দিন:" if lang=="bn" else "🔑 Enter 4-digit PIN:")
    elif data == "rem_pin":
        update_user_db(user_id, {"pin": None, "recovery_phrase": None})
        context.user_data["profile"]["pin"] = None
        await query.message.reply_text("🗑️ পিন রিমুভ করা হয়েছে।" if lang=="bn" else "🗑️ PIN removed.")
    elif data == "do_reset":
        context.user_data["state"] = "WAITING_RESET_REASON"
        await query.message.reply_text("⚠️ রিসেট করার কারণটি লিখে পাঠান:" if lang=="bn" else "⚠️ Enter reason for reset:")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling an update:", exc_info=context.error)

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not found!")
        return
    Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("new", cmd_new_habit))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_error_handler(error_handler)
    
    print("Iron Mind Bot is running (Master Version)...")
    app.run_polling()

if __name__ == "__main__":
    main()
