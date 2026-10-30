import os
import logging
from datetime import datetime, timezone, timedelta, time
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

def get_habits(user_id):
    try:
        res = supabase.table("habits").select("*").eq("user_id", user_id).order("id").execute()
        return res.data if res.data else []
    except: return []

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

def format_time_diff(diff: timedelta):
    days = diff.days
    hours, remainder = divmod(diff.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return days, hours, minutes, seconds

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

async def send_daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        users = supabase.table("habits").select("user_id, name, created_at").execute()
        if not users.data: return
        now = datetime.now(timezone.utc)
        for h in users.data:
            st = datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
            days = (now - st).days
            msg = f"🌅 **শুভ সকাল!**\n\nআপনার **{h['name']}** ছাড়ার যাত্রায় আপনি **{days} দিন** পার করেছেন! আজকের দিনটিও সফলতার সাথে পার করুন। 💪"
            try: await context.bot.send_message(chat_id=h["user_id"], text=msg, parse_mode="Markdown")
            except: pass
    except Exception as e:
        logging.error(f"Reminder Error: {e}")

async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_lock(update, context): return
    context.user_data["state"] = None
    
    user_id = update.effective_user.id
    lang = context.user_data.get("profile", {}).get("lang", "bn")
    habits = get_habits(user_id)
    
    if not habits:
        msg = "⚠️ কোনো তথ্য নেই! '➕ নতুন লক্ষ্য' বাটন থেকে হ্যাবিট সেট করুন।" if lang=="bn" else "⚠️ No data! Tap '➕ New Habit Goal'."
        if update.message: await update.message.reply_text(msg, reply_markup=get_keyboard(lang))
        else: await update.callback_query.message.reply_text(msg, reply_markup=get_keyboard(lang))
        return

    msg = "📊 **ড্যাশবোর্ড**\n\n" if lang=="bn" else "📊 **DASHBOARD**\n\n"
    kb = [[InlineKeyboardButton("🌐 Web Dashboard", web_app=WebAppInfo(url=WEBAPP_URL))]]
    now = datetime.now(timezone.utc)
    
    for h in habits:
        st = datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
        diff = max(timedelta(0), now - st)
        days, hours, minutes, seconds = format_time_diff(diff)
        
        # Second added here!
        msg += f"🎯 **লক্ষ্য:** {h['name']} \n📅 **শুরু:** {st.strftime('%Y-%m-%d')}\n⏱️ **সময়:** `{days} দিন, {hours} ঘণ্টা, {minutes} মিনিট, {seconds} সেকেন্ড`\n\n"
        kb.append([
            InlineKeyboardButton(f"🔄 Reset ({h['name']})", callback_data=f"reset_{h['id']}"),
            InlineKeyboardButton(f"🗑️ Delete", callback_data=f"remove_{h['id']}")
        ])
        
    kb.append([InlineKeyboardButton("🔄 Refresh / আপডেট", callback_data="refresh_dash")])
    
    if update.callback_query and update.callback_query.data == "refresh_dash":
        try: await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except: pass 
    elif update.message:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

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
            else: await update.message.reply_text("❌ ভুল ফ্রেজ!" if lang=="bn" else "❌ Wrong phrase!")
        else: await update.message.reply_text("❌ ভুল পিন!" if lang=="bn" else "❌ Wrong PIN!")
        return

    # 2. Main Menus
    if text.startswith("📊") or text.startswith("/dashboard"): return await cmd_dashboard(update, context)
    elif text.startswith("➕") or text.startswith("/new"): return await cmd_new_habit(update, context)
    elif text.startswith("📜"):
        context.user_data["state"] = None
        habits = get_habits(user_id)
        has_history = False
        msg = "📜 **রিসেট হিস্ট্রি:**\n\n" if lang=="bn" else "📜 **Reset History:**\n\n"
        for h in habits:
            history = h.get("reset_history", [])
            if history:
                has_history = True
                msg += f"🎯 **{h['name']}**\n"
                for i, item in enumerate(history[-3:], 1): msg += f"{i}. **{item.get('date', '')[:10]}** - {item.get('reason', '')}\n"
                msg += "\n"
        if not has_history: msg = "📜 কোনো রেকর্ড নেই!" if lang=="bn" else "📜 No records!"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    elif text.startswith("🔥"):
        context.user_data["state"] = None
        habits = get_habits(user_id)
        if not habits: return await update.message.reply_text("⚠️ ডাটা নেই!" if lang=="bn" else "⚠️ No data!")
        
        msg = f"🏆 **আপনার ট্রফি ও স্ট্রিক**\n\n"
        now = datetime.now(timezone.utc)
        tiers = [1, 3, 7, 15, 30, 60, 90, 180, 365]
        
        for h in habits:
            st = datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
            passed_days = max(0, (now - st).days)
            msg += f"🎯 **{h['name']}** (Current: {passed_days} Days)\n"
            
            next_tier_found = False
            for tier in tiers:
                if passed_days >= tier: msg += f"🛡️ **{tier} Days:** অর্জিত ✅\n"
                else:
                    if not next_tier_found:
                        rem = max(timedelta(0), (st + timedelta(days=tier)) - now)
                        rd, rh, rm, rs = format_time_diff(rem)
                        # Second added here too!
                        msg += f"\n🎯 **পরবর্তী লক্ষ্য: {tier} Days**\n⏳ **বাকি:** `{rd}দিন, {rh}ঘণ্টা, {rm}মিনিট, {rs}সেকেন্ড`\n\n"
                        next_tier_found = True
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    elif text.startswith("💰"):
        context.user_data["state"] = None
        habits = get_habits(user_id)
        if not habits: return await update.message.reply_text("⚠️ ডাটা নেই!" if lang=="bn" else "⚠️ No data!")
        
        total_money = 0
        total_time = 0
        msg = ""
        kb = []
        now = datetime.now(timezone.utc)
        
        for h in habits:
            cost = float(h.get("cost_per_day") or 0)
            time_pd = float(h.get("time_per_day") or 0)
            st = datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
            days = max(0, (now - st).days)
            
            saved_m = days * cost
            saved_t = days * time_pd
            total_money += saved_m
            total_time += saved_t
            
            msg += f"🎯 **{h['name']}**\n"
            if cost == 0 and time_pd == 0: msg += "⚠️ কোনো সেভিংস ডাটা সেট করা নেই।\n\n"
            else: msg += f"💵 ৳{saved_m:g} | ⏳ {saved_t:g} ঘণ্টা\n\n"
            
            kb.append([InlineKeyboardButton(f"✏️ Edit Savings: {h['name']}", callback_data=f"edit_sav_{h['id']}")])
            
        header = f"🌟 **সর্বমোট সাশ্রয়:**\n💵 **৳{total_money:g}** \n⏳ **{total_time:g} ঘণ্টা**\n\n"
        await update.message.reply_text(header + msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    elif text.startswith("⚙️") or text.startswith("/settings"):
        context.user_data["state"] = None
        p_stat = "সক্রিয় 🔒" if profile.get('pin') else "বন্ধ 🔓"
        msg = f"⚙️ **সেটিংস**\n\n🔒 পিন: {p_stat}\n🌐 ভাষা: {'বাংলা' if lang=='bn' else 'English'}" if lang=="bn" else f"⚙️ **Settings**\n\n🔒 PIN: {p_stat}\n🌐 Lang: {'BN' if lang=='bn' else 'EN'}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"), InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🔑 Set PIN", callback_data="set_pin"), InlineKeyboardButton("🗑️ Remove PIN", callback_data="rem_pin")]
        ])
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
        return

    elif text.startswith("/help"):
        await update.message.reply_text("❓ **সাহায্য ও সাপোর্ট:**\n\n• /dashboard : ড্যাশবোর্ড খুলতে।\n• /new : নতুন অভ্যাস সেট করতে।\n• পিন ভুলে গেলে লক স্ক্রিনে `reset` লিখুন।", parse_mode="Markdown")
        return

    # 3. Form States
    if state == "WAITING_HABIT_NAME":
        context.user_data["temp_name"] = text
        context.user_data["state"] = "WAITING_DATE"
        await update.message.reply_text("👉 কবে থেকে এটি ছেড়েছেন? ('today', '5 days ago', অথবা YYYY-MM-DD)")
        
    elif state == "WAITING_DATE":
        dt = parse_date(text)
        if not dt: return await update.message.reply_text("❌ ভুল তারিখ ফরম্যাট!")
        context.user_data["temp_date"] = dt.isoformat()
        context.user_data["state"] = "WAITING_COST"
        await update.message.reply_text("💰 এই অভ্যাসে প্রতিদিন কত টাকা খরচ হতো? (শুধু সংখ্যা দিন, যেমন: 100। সেট না করতে চাইলে 0 দিন)")

    elif state == "WAITING_COST":
        try: context.user_data["temp_cost"] = float(text)
        except: context.user_data["temp_cost"] = 0.0
        context.user_data["state"] = "WAITING_TIME"
        await update.message.reply_text("⏳ প্রতিদিন কত ঘণ্টা নষ্ট হতো? (যেমন: 2 বা 1.5। না চাইলে 0 দিন)")

    elif state == "WAITING_TIME":
        try: time_val = float(text)
        except: time_val = 0.0
        
        try:
            supabase.table("habits").insert({
                "user_id": user_id, 
                "name": context.user_data["temp_name"], 
                "created_at": context.user_data["temp_date"],
                "cost_per_day": context.user_data["temp_cost"],
                "time_per_day": time_val
            }).execute()
            context.user_data["state"] = None
            await update.message.reply_text("🎉 লক্ষ্য সেটআপ সফল!", reply_markup=get_keyboard(lang))
            await cmd_dashboard(update, context)
        except Exception as e:
            logging.error(f"Save Error: {e}")
            await update.message.reply_text("❌ ডাটাবেজ এরর! আপনি কি Supabase-এ SQL রান করেছেন?")

    elif state == "EDITING_COST":
        try: context.user_data["temp_cost"] = float(text)
        except: context.user_data["temp_cost"] = 0.0
        context.user_data["state"] = "EDITING_TIME"
        await update.message.reply_text("⏳ প্রতিদিন কত ঘণ্টা নষ্ট হতো? (যেমন: 2 বা 1.5)")

    elif state == "EDITING_TIME":
        try: time_val = float(text)
        except: time_val = 0.0
        try:
            hid = context.user_data.get("temp_habit_id")
            supabase.table("habits").update({
                "cost_per_day": context.user_data["temp_cost"],
                "time_per_day": time_val
            }).eq("id", hid).execute()
            context.user_data["state"] = None
            await update.message.reply_text("✅ সাশ্রয়ের ডাটা আপডেট হয়েছে!", reply_markup=get_keyboard(lang))
        except Exception as e:
            logging.error(f"Update Error: {e}")
            await update.message.reply_text("❌ আপডেট ফেইল হয়েছে।")

    elif state == "WAITING_PIN":
        if len(text) >= 4 and text.isdigit():
            update_user_db(user_id, {"pin": text})
            context.user_data["profile"]["pin"] = text
            context.user_data["unlocked"] = True
            context.user_data["state"] = "WAITING_RECOVERY_SETUP"
            await update.message.reply_text("✅ পিন সেভ হয়েছে!\n\nএখন একটি **রিকভারি ফ্রেজ** (যেমন: প্রিয় রঙের নাম) দিন, যা পিন ভুলে গেলে কাজে লাগবে:")
        else: await update.message.reply_text("❌ কমপক্ষে ৪-ডিজিটের সংখ্যা দিন।")

    elif state == "WAITING_RECOVERY_SETUP":
        update_user_db(user_id, {"recovery_phrase": text})
        context.user_data["profile"]["recovery_phrase"] = text
        context.user_data["state"] = None
        await update.message.reply_text("🛡️ নিরাপত্তা সেটআপ সম্পূর্ণ হয়েছে!", reply_markup=get_keyboard(lang))

    elif state == "WAITING_RESET_REASON":
        try:
            hid = context.user_data.get("temp_habit_id")
            now_iso = datetime.now(timezone.utc).isoformat()
            res = supabase.table("habits").select("*").eq("id", hid).execute()
            if res.data:
                habit = res.data[0]
                history = habit.get("reset_history", []) if habit.get("reset_history") else []
                history.append({"date": now_iso, "reason": text})
                supabase.table("habits").update({"created_at": now_iso, "reset_history": history}).eq("id", hid).execute()
                
            context.user_data["state"] = None
            await update.message.reply_text("🔄 টাইমার রিসেট হয়েছে!", reply_markup=get_keyboard(lang))
            await cmd_dashboard(update, context)
        except Exception as e:
            logging.error(f"Reset Error: {e}")
            await update.message.reply_text("❌ এরর হয়েছে!")

# --- Callbacks ---
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    if data != "refresh_dash": await query.answer()
    if "profile" not in context.user_data: context.user_data["profile"] = get_or_create_profile(user_id)
    lang = context.user_data["profile"].get("lang", "bn")
    
    if data == "refresh_dash":
        await cmd_dashboard(update, context)
    elif data.startswith("reset_"):
        context.user_data["temp_habit_id"] = data.split("_")[1]
        context.user_data["state"] = "WAITING_RESET_REASON"
        await query.message.reply_text("⚠️ রিসেট করার কারণটি লিখে পাঠান:")
    elif data.startswith("remove_"):
        hid = data.split("_")[1]
        supabase.table("habits").delete().eq("id", hid).execute()
        await query.message.reply_text("🗑️ লক্ষ্যটি মুছে ফেলা হয়েছে।")
        await cmd_dashboard(update, context)
    elif data.startswith("edit_sav_"):
        hid = data.split("_", 2)[2]
        context.user_data["temp_habit_id"] = hid
        context.user_data["state"] = "EDITING_COST"
        await query.message.reply_text("💰 প্রতিদিন কত টাকা খরচ হতো? (শুধু সংখ্যা দিন, যেমন: 100)")
    elif data == "lang_en":
        update_user_db(user_id, {"lang": "en"})
        context.user_data["profile"]["lang"] = "en"
        await query.message.reply_text("✅ Language changed to English.", reply_markup=get_keyboard("en"))
    elif data == "lang_bn":
        update_user_db(user_id, {"lang": "bn"})
        context.user_data["profile"]["lang"] = "bn"
        await query.message.reply_text("✅ ভাষা বাংলায় পরিবর্তন করা হয়েছে।", reply_markup=get_keyboard("bn"))
    elif data == "set_pin":
        context.user_data["state"] = "WAITING_PIN"
        await query.message.reply_text("🔑 একটি ৪-ডিজিটের পিন দিন:")
    elif data == "rem_pin":
        update_user_db(user_id, {"pin": None, "recovery_phrase": None})
        context.user_data["profile"]["pin"] = None
        await query.message.reply_text("🗑️ পিন রিমুভ করা হয়েছে।")

def main():
    if not BOT_TOKEN: return
    Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    
    if app.job_queue:
        app.job_queue.run_daily(send_daily_reminder, time=time(hour=9, minute=0, tzinfo=timezone.utc))
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("new", cmd_new_habit))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    
    print("Iron Mind Bot is running (Multi-Habit Version with Seconds)...")
    app.run_polling()

if __name__ == "__main__":
    main()
