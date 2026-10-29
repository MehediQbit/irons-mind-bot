import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_or_create_user(telegram_id: int):
    """ইউজার ডাটাবেজে আছে কি না চেক করে এবং না থাকলে যুক্ত করে।"""
    res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    if not res.data:
        supabase.table("users").insert({"telegram_id": telegram_id}).execute()
        return {"telegram_id": telegram_id, "pin_hash": None, "passkey_id": None}
    return res.data[0]

def set_user_pin(telegram_id: int, pin_hash: str):
    """ইউজারের পিন সেভ বা আপডেট করে।"""
    supabase.table("users").update({"pin_hash": pin_hash}).eq("telegram_id", telegram_id).execute()

def add_habit(telegram_id: int, habit_name: str, description: str = ""):
    """নতুন অভ্যাস যোগ করে।"""
    data = {
        "telegram_id": telegram_id,
        "habit_name": habit_name,
        "description": description
    }
    res = supabase.table("habits").insert(data).execute()
    return res.data

def get_user_habits(telegram_id: int):
    """ইউজারের সব অভ্যাসের তালিকা নিয়ে আসে।"""
    res = supabase.table("habits").select("*").eq("telegram_id", telegram_id).execute()
    return res.data
      
