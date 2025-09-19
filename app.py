import logging
import requests
import threading
import time
import os
import json
from flask import Flask, Response
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import html
import subprocess
import sys

# ====== CONFIG ======
MAIN_BOT_TOKEN = os.getenv("MAIN_BOT_TOKEN") or "8369379659:AAGCEu_rL9qQn2c12XAv51kFKbJin2gBc7g"
AUTH_TOKEN = os.getenv("AUTH_TOKEN") or "bc5fafa2-8a15-4732-97c8-031fea2a6b92"
OWNER_ID = int(os.getenv("OWNER_ID", 7665143902))
FORCE_SUB_CHANNEL = "@VASUHUB"
DEFAULT_CHANNEL_LINK = "https://t.me/VASUHUB"
API_URL = "https://raazit.acchub.io/api/"
BASE_URL = "https://raazit.acchub.io/api/sms"
FETCH_INTERVAL = 2

# Database files
BOT_CONFIG_FILE = "bot_configs.json"
PENDING_REQUESTS_FILE = "pending_requests.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__)

@app.route("/health")
def health():
    return Response("OK", status=200)

@app.route("/")
def root():
    return Response("OK", status=200)

# Bot config management
def load_bot_configs():
    try:
        with open(BOT_CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_bot_configs(configs):
    with open(BOT_CONFIG_FILE, 'w') as f:
        json.dump(configs, f, indent=2)

def load_pending_requests():
    try:
        with open(PENDING_REQUESTS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_pending_requests(requests):
    with open(PENDING_REQUESTS_FILE, 'w') as f:
        json.dump(requests, f, indent=2)

bot_configs = load_bot_configs()
pending_requests = load_pending_requests()
user_states = {}
active_processes = {}
running_tokens = set()

# OTP Functions
def mask_number(num):
    num = str(num)
    if len(num) > 5:
        return num[:2] + '*' * (len(num) - 5) + num[-3:]
    return num

def fetch_otp_acchubb():
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "auth-token": AUTH_TOKEN,
        "Cookie": f"authToken={AUTH_TOKEN}; authRole=Freelancer",
        "Origin": "https://raazit.acchub.io",
        "Referer": "https://raazit.acchub.io",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0"
    }
    data = {"action": "get_otp", "number": "1234567890"}
    try:
        response = requests.post(API_URL, headers=headers, data=data, timeout=10)
        if response.status_code == 200:
            return response.json().get("data", [])
    except Exception as e:
        logger.error(f"Error fetching OTP: {e}")
    return []

# Force subscription check
def check_subscription(user_id, bot_token):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        params = {"chat_id": FORCE_SUB_CHANNEL, "user_id": user_id}
        response = requests.get(url, params=params)
        data = response.json()
        if data.get("ok"):
            status = data["result"]["status"]
            return status in ["member", "administrator", "creator"]
        return False
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return True

# Simple OTP monitoring using direct API calls
def simple_otp_monitor(config):
    """Simple OTP monitor using direct Telegram API calls"""
    bot_token = config["bot_token"]
    chat_id = config["chat_id"]
    group_link = config["group_link"]
    channel_link = config.get("channel_link", DEFAULT_CHANNEL_LINK)
    sent_ids = set()
    
    logger.info(f"Starting OTP monitor for @{config['bot_username']}")
    
    while True:
        try:
            for otp_entry in fetch_otp_acchubb():
                otp_id = otp_entry.get("id")
                otp_code = otp_entry.get("otp", "").strip()
                
                if otp_code and otp_id not in sent_ids:
                    sent_ids.add(otp_id)
                    
                    msg = (
                        "┏━━━━━━━━━━━┓\n"
                        "<blockquote> 📩 <b>New OTP Notification</b></blockquote>\n"
                        "┣━━━━━┫\n"
                        f"<blockquote>📞 <b>Number:</b> <code>{mask_number(otp_entry.get('did'))}</code></blockquote>\n"
                        f"<blockquote>🌍 <b>Country:</b> <b>{otp_entry.get('country_name')}</b></blockquote>\n"
                        f"<blockquote>🔐 <b>OTP:</b>{html.escape(otp_code)}</blockquote>\n"
                        "┣━━━━━┫\n"
                        " <blockquote>⚡️ <i>Powered by @DDxOTPsBOT Bot System 🤖</i></blockquote>\n"
                        "┗━━━━━━━━━━━┛"
                    )
                    
                    keyboard = {
                        "inline_keyboard": [
                            [
                                {"text": "📩 View OTP", "url": group_link},
                                {"text": "🔔 Channel", "url": channel_link}
                            ]
                        ]
                    }
                    
                    payload = {
                        "chat_id": chat_id,
                        "text": msg,
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps(keyboard)
                    }
                    
                    try:
                        response = requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", data=payload)
                        if response.status_code == 200:
                            logger.info(f"OTP sent to {config['bot_username']}")
                        else:
                            logger.error(f"Failed to send OTP for {config['bot_username']}: {response.text}")
                    except Exception as e:
                        logger.error(f"Error sending OTP for {config['bot_username']}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in OTP monitor for {config['bot_username']}: {e}")
            
        time.sleep(FETCH_INTERVAL)

# Create individual bot file
def create_bot_file(bot_id, config):
    """Create a separate Python file for each cloned bot"""
    bot_filename = f"clone_bot_{bot_id}.py"

    # Always enforce owner's force-sub channel
    owner_channel = "https://t.me/VASUHUB"
    user_channel = config.get("channel_link", owner_channel)

    # Keep both: owner + user channel (owner first)
    if owner_channel not in user_channel:
        channel_link = f"{owner_channel} {user_channel}"
    else:
        channel_link = owner_channel
    bot_code = f'''
import logging
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "{config["bot_token"]}"
CHAT_ID = {config["chat_id"]}
GROUP_LINK = "{config["group_link"]}"
CHANNEL_LINK = "{channel_link}"
AUTH_TOKEN = "{AUTH_TOKEN}"
BASE_URL = "{BASE_URL}"
FORCE_SUB_CHANNEL = "@VASUHUB"

# Memory store for user selections
user_last_selection = {{}}

async def search_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🔍 Usage: /search <country name>")
        return

    query = " ".join(context.args).lower()
    countries = get_countries()

    matched = [c for c in countries if query in c["text"].lower()]
    if not matched:
        await update.message.reply_text("❌ Country not found.")
        return

    if len(matched) > 1:
        keyboard = [[InlineKeyboardButton(c["text"], callback_data=f"country|{{c['id']}}")] for c in matched]
        await update.message.reply_text("🌍 Select a country:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    country = matched[0]
    carriers = get_carriers(country["id"])
    if not carriers:
        res = add_number(country["id"], "")
        if res.get("meta") == 200 and res.get("data"):
            await send_number_message(update, res["data"], country["id"], "")
        else:
            await update.message.reply_text("❌ Numbers currently not available.")
        return

    keyboard = [
    [InlineKeyboardButton(c["text"], callback_data=f"carrier|{{country['id']}}|{{c['id']}}")]
    for c in carriers
]

    await update.message.reply_text("🚚 Select a carrier:", reply_markup=InlineKeyboardMarkup(keyboard))


# handlers

def get_countries():
    headers = {{"Auth-Token": AUTH_TOKEN}}
    resp = requests.get(f"{{BASE_URL}}/combo-list", headers=headers)
    data = resp.json()
    return data.get("data", []) if data.get("meta") == 200 else []

def get_carriers(country_id):
    headers = {{"Auth-Token": AUTH_TOKEN}}
    resp = requests.get(f"{{BASE_URL}}/carrier-list?app={{country_id}}", headers=headers)
    data = resp.json()
    return data.get("data", []) if data.get("meta") == 200 else []

def add_number(app_id, carrier_id):
    headers = {{
        "Auth-Token": AUTH_TOKEN,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest"
    }}
    data = {{
        "authToken": AUTH_TOKEN,
        "app": app_id,
        "carrier": carrier_id
    }}
    return requests.post(f"{{BASE_URL}}/", headers=headers, files={{}}, data=data).json()

def paginate_countries(page=0, per_page=10):
    countries = get_countries()
    start = page * per_page
    end = start + per_page
    buttons = [[InlineKeyboardButton(c["text"], callback_data=f"country|{{c['id']}}")] for c in countries[start:end]]
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"more_countries|{{page-1}}"))
    if end < len(countries):
        nav_buttons.append(InlineKeyboardButton("➡️ More", callback_data=f"more_countries|{{page+1}}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    return buttons

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    try:
        member = await context.bot.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        if member.status not in ["member", "administrator", "creator"]:
            keyboard = [[InlineKeyboardButton("🔔 Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL.replace('@','')}")]]
            await update.message.reply_text(
                "❌ You must join our channel first!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    except Exception as e:
        logger.error("Force-sub error: %s", e)

        # fallback: allow if error
        pass

    # agar subscribed hai to normal flow
    keyboard = paginate_countries(0)
    await update.message.reply_text("🌍 Select a country:", reply_markup=InlineKeyboardMarkup(keyboard))



    
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, *values = query.data.split("|")

    if action == "more_countries":
        page = int(values[0])
        keyboard = paginate_countries(page)
        await query.edit_message_text("🌍 Select a country:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "country":
        country_id = values[0]
        carriers = get_carriers(country_id)
        if not carriers:
            res = add_number(country_id, "")
            if res.get("meta") == 200 and res.get("data"):
                data = res["data"]
                user_last_selection[query.from_user.id] = (country_id, "")
                await send_number_message(query, data, country_id, "")
            else:
                await query.edit_message_text("❌ Numbers currently not available.")
            return
        keyboard = [[InlineKeyboardButton(c["text"], callback_data=f"carrier|{{country_id}}|{{c['id']}}")] for c in carriers]
        await query.edit_message_text("🚚 Select a carrier:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "carrier":
        country_id, carrier_id = values
        res = add_number(country_id, carrier_id)
        if res.get("meta") == 200 and res.get("data"):
            data = res["data"]
            user_last_selection[query.from_user.id] = (country_id, carrier_id)
            await send_number_message(query, data, country_id, carrier_id)
        else:
            await query.edit_message_text("❌ Numbers currently not available.")

    elif action == "change_number":
        if query.from_user.id not in user_last_selection:
            await query.edit_message_text("❌ First get a number.")
            return
        country_id, carrier_id = user_last_selection[query.from_user.id]
        res = add_number(country_id, carrier_id)
        if res.get("meta") == 200 and res.get("data"):
            data = res["data"]
            await send_number_message(query, data, country_id, carrier_id, changed=True)
        else:
            await query.edit_message_text("❌ Numbers currently not available.")

async def send_number_message(query, data, country_id, carrier_id, changed=False):
    msg = (
        ("🔄 <b>Number Changed!</b>\\n\\n" if changed else "✅ <b>Number Added Successfully!</b>\\n\\n") +
        f"📞 <b>Number:</b> <code>{{data.get('did')}}</code>\\n"
        f"<i>Powered by @DDxOTPsBOT ❤️</i>"
    )
    keyboard = [
        [
            InlineKeyboardButton("📩 View OTP", url=GROUP_LINK),
            InlineKeyboardButton("📢 Channel", url=CHANNEL_LINK)
        ],
        [
            InlineKeyboardButton("🔄 Change Number", callback_data="change_number")
        ]
    ]
    await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

if __name__ == "__main__":
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(CommandHandler("search", search_country))
    
    logger.info("Bot @{config["bot_username"]} started!")
    application.run_polling()
'''

    with open(bot_filename, 'w') as f:
        f.write(bot_code)

    return bot_filename
    

# Delete bot function
def delete_bot(bot_id):
    """Delete a bot and its associated resources"""
    try:
        if bot_id in active_processes:
            try:
                active_processes[bot_id].terminate()
                time.sleep(1)
                if active_processes[bot_id].poll() is None:
                    active_processes[bot_id].kill()
                logger.info(f"Stopped process for {bot_id}")
            except Exception as e:
                logger.error(f"Error stopping process for {bot_id}: {e}")
            finally:
                del active_processes[bot_id]
        
        if bot_id in bot_configs:
            bot_token = bot_configs[bot_id]["bot_token"]
            if bot_token in running_tokens:
                running_tokens.remove(bot_token)
            
            del bot_configs[bot_id]
            save_bot_configs(bot_configs)
            
            bot_filename = f"clone_bot_{bot_id}.py"
            if os.path.exists(bot_filename):
                try:
                    os.remove(bot_filename)
                    logger.info(f"Deleted bot file: {bot_filename}")
                except Exception as e:
                    logger.error(f"Error deleting bot file {bot_filename}: {e}")
                
        logger.info(f"Successfully deleted bot {bot_id}")
        return True
    except Exception as e:
        logger.error(f"Error deleting bot {bot_id}: {e}")
        return False

# Main bot handlers
async def main_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not check_subscription(user_id, MAIN_BOT_TOKEN):
        keyboard = [[InlineKeyboardButton("🔔 Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")]]
        await update.message.reply_text("❌ You must join our channel first!", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    if user_id == OWNER_ID:
        keyboard = [
            [InlineKeyboardButton("📊 Bot Statistics", callback_data="stats")],
            [InlineKeyboardButton("🤖 Create New Bot", callback_data="create_bot")],
            [InlineKeyboardButton("📝 My Bots", callback_data="my_bots")],
            [InlineKeyboardButton("⏳ Pending Requests", callback_data="pending_requests")],
            [InlineKeyboardButton("🌐 All Hosted Bots", callback_data="all_bots")]
        ]
        await update.message.reply_text("👑 <b>Owner Panel</b>\n\nWelcome to the bot management system!", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        keyboard = [
            [InlineKeyboardButton("🤖 Request New Bot", callback_data="create_bot")],
            [InlineKeyboardButton("📝 My Bots", callback_data="my_bots")]
        ]
        await update.message.reply_text("🎉 <b>Welcome to OTP Bot Cloning System!</b>\n\nRequest your own OTP monitoring bot!", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def main_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "stats" and user_id == OWNER_ID:
        total_bots = len(bot_configs)
        active_count = len(active_processes)
        pending_count = len(pending_requests)
        stats_text = f"📊 <b>Bot Statistics</b>\n\n🤖 Total Bots: {total_bots}\n🟢 Active: {active_count}\n⏳ Pending: {pending_count}\n👥 Users: {len(set(config['owner_id'] for config in bot_configs.values()))}"
        await query.edit_message_text(stats_text, parse_mode="HTML")
        
    elif query.data == "create_bot":
        if user_id == OWNER_ID:
            user_states[user_id] = {"step": "bot_token"}
            await query.edit_message_text("🤖 <b>Owner: Create New Bot - Step 1/4</b>\n\nSend your bot token from @BotFather", parse_mode="HTML")
        else:
            user_states[user_id] = {"step": "bot_token"}
            await query.edit_message_text("🤖 <b>Request New Bot - Step 1/4</b>\n\nSend your bot token from @BotFather\n\n⚠️ <i>Note: Request will need owner approval</i>", parse_mode="HTML")
        
    elif query.data == "pending_requests" and user_id == OWNER_ID:
        if not pending_requests:
            await query.edit_message_text("✅ No pending requests!")
            return
        
        buttons = []
        for req_id, req_data in pending_requests.items():
            user_info = f"User: {req_data.get('username', 'Unknown')}"
            bot_info = f"Bot: @{req_data['bot_username']}"
            buttons.append([InlineKeyboardButton(f"✅ Approve {req_data['bot_username']}", callback_data=f"approve_{req_id}")])
            buttons.append([InlineKeyboardButton(f"❌ Reject {req_data['bot_username']}", callback_data=f"reject_{req_id}")])
        
        await query.edit_message_text("⏳ <b>Pending Bot Requests:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        
    elif query.data == "all_bots" and user_id == OWNER_ID:
        if not bot_configs:
            await query.edit_message_text("❌ No bots created yet.")
            return
        
        bot_list = "🌐 <b>All Hosted Bots:</b>\n\n"
        buttons = []
        for bot_id, config in bot_configs.items():
            status = "🟢" if bot_id in active_processes else "🔴"
            bot_list += f"{status} @{config['bot_username']} (User: {config['owner_id']})\n"
            buttons.append([InlineKeyboardButton(f"{status} @{config['bot_username']}", callback_data=f"manage_{bot_id}")])
        
        keyboard = buttons + [[InlineKeyboardButton("🔄 Refresh", callback_data="all_bots")]]
        await query.edit_message_text(bot_list, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif query.data.startswith("approve_"):
        if user_id != OWNER_ID:
            return
        req_id = query.data.replace("approve_", "")
        if req_id in pending_requests:
            req_data = pending_requests[req_id]
            
            bot_id = f"bot_{len(bot_configs) + 1}_{req_data['owner_id']}"
            config = {
                "owner_id": req_data["owner_id"],
                "bot_token": req_data["bot_token"],
                "bot_username": req_data["bot_username"],
                "chat_id": req_data["chat_id"],
                "group_link": req_data["group_link"],
                "channel_link": req_data["channel_link"],
                "created_at": time.time(),
                "approved_by": OWNER_ID
            }
            
            bot_configs[bot_id] = config
            save_bot_configs(bot_configs)
            
            start_cloned_bot(bot_id, config)
            
            del pending_requests[req_id]
            save_pending_requests(pending_requests)
            
            try:
                await context.bot.send_message(
                    req_data["owner_id"],
                    f"🎉 <b>Bot Request Approved!</b>\n\n🤖 @{req_data['bot_username']}\n✅ Your bot is now active!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error notifying user {req_data['owner_id']}: {e}")
            
            await query.edit_message_text(f"✅ Approved bot @{req_data['bot_username']}!")
            
    elif query.data.startswith("reject_"):
        if user_id != OWNER_ID:
            return
        req_id = query.data.replace("reject_", "")
        if req_id in pending_requests:
            req_data = pending_requests[req_id]
            
            del pending_requests[req_id]
            save_pending_requests(pending_requests)
            
            try:
                await context.bot.send_message(
                    req_data["owner_id"],
                    f"❌ <b>Bot Request Rejected</b>\n\n🤖 @{req_data['bot_username']}\n\nPlease contact admin for more information.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error notifying user {req_data['owner_id']}: {e}")
            
            await query.edit_message_text(f"❌ Rejected bot @{req_data['bot_username']}!")
        
    elif query.data == "my_bots":
        user_bots = {k: v for k, v in bot_configs.items() if v['owner_id'] == user_id}
        user_pending = {k: v for k, v in pending_requests.items() if v['owner_id'] == user_id}
        
        if not user_bots and not user_pending:
            await query.edit_message_text("❌ No bots created yet.")
            return
        
        buttons = []
        bot_list = "📝 <b>Your Bots:</b>\n\n"
        
        for bot_id, config in user_bots.items():
            status = "🟢" if bot_id in active_processes else "🔴"
            bot_list += f"{status} @{config['bot_username']}\n"
            buttons.append([InlineKeyboardButton(f"{status} @{config['bot_username']}", callback_data=f"manage_{bot_id}")])
        
        if user_pending:
            bot_list += "\n⏳ <b>Pending Approval:</b>\n"
            for req_id, req_data in user_pending.items():
                bot_list += f"⏳ @{req_data['bot_username']}\n"
        
        await query.edit_message_text(bot_list, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
        
    elif query.data.startswith("manage_"):
        bot_id = query.data.replace("manage_", "")
        if bot_id not in bot_configs:
            await query.edit_message_text("❌ Bot no longer exists!")
            return
            
        config = bot_configs[bot_id]
        is_owner = config["owner_id"] == user_id
        is_admin = user_id == OWNER_ID
        
        if not (is_owner or is_admin):
            await query.edit_message_text("❌ You don't have permission to manage this bot!")
            return
            
        status = "🟢 Active" if bot_id in active_processes else "🔴 Inactive"
        bot_info = (
            f"🤖 <b>Bot Management: @{config['bot_username']}</b>\n\n"
            f"👤 Owner: {config['owner_id']}\n"
            f"📱 Chat ID: {config['chat_id']}\n"
            f"🔗 Group Link: {config['group_link']}\n"
            f"📢 Channel Link: {config.get('channel_link', DEFAULT_CHANNEL_LINK)}\n"
            f"📊 Status: {status}\n"
            f"📅 Created: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(config['created_at']))}"
        )
        
        buttons = []
        if bot_id in active_processes:
            buttons.append([InlineKeyboardButton("🛑 Stop Bot", callback_data=f"stop_{bot_id}")])
        else:
            buttons.append([InlineKeyboardButton("▶️ Start Bot", callback_data=f"start_{bot_id}")])
        
        if is_owner or is_admin:
            buttons.append([InlineKeyboardButton("🗑️ Delete Bot", callback_data=f"delete_{bot_id}")])
            
        buttons.append([InlineKeyboardButton("🔙 Back to My Bots", callback_data="my_bots")])
        
        await query.edit_message_text(bot_info, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        
    elif query.data.startswith("stop_"):
        bot_id = query.data.replace("stop_", "")
        if bot_id not in bot_configs:
            await query.edit_message_text("❌ Bot no longer exists!")
            return
            
        config = bot_configs[bot_id]
        if config["owner_id"] != user_id and user_id != OWNER_ID:
            await query.edit_message_text("❌ You don't have permission to stop this bot!")
            return
            
        if bot_id in active_processes:
            try:
                active_processes[bot_id].terminate()
                time.sleep(1)
                if active_processes[bot_id].poll() is None:
                    active_processes[bot_id].kill()
                del active_processes[bot_id]
                running_tokens.remove(config["bot_token"])
                await query.edit_message_text(f"🛑 Bot @{config['bot_username']} stopped successfully!")
            except Exception as e:
                logger.error(f"Error stopping bot {bot_id}: {e}")
                await query.edit_message_text("❌ Error stopping bot!")
        else:
            await query.edit_message_text("❌ Bot is already stopped!")
            
    elif query.data.startswith("start_"):
        bot_id = query.data.replace("start_", "")
        if bot_id not in bot_configs:
            await query.edit_message_text("❌ Bot no longer exists!")
            return
            
        config = bot_configs[bot_id]
        if config["owner_id"] != user_id and user_id != OWNER_ID:
            await query.edit_message_text("❌ You don't have permission to start this bot!")
            return
            
        if bot_id not in active_processes:
            start_cloned_bot(bot_id, config)
            await query.edit_message_text(f"▶️ Bot @{config['bot_username']} started successfully!")
        else:
            await query.edit_message_text("❌ Bot is already running!")
            
    elif query.data.startswith("delete_"):
        bot_id = query.data.replace("delete_", "")
        if bot_id not in bot_configs:
            await query.edit_message_text("❌ Bot no longer exists!")
            return
            
        config = bot_configs[bot_id]
        if config["owner_id"] != user_id and user_id != OWNER_ID:
            await query.edit_message_text("❌ You don't have permission to delete this bot!")
            return
            
        if delete_bot(bot_id):
            try:
                # Notify bot owner if admin deletes their bot
                if user_id == OWNER_ID and config["owner_id"] != OWNER_ID:
                    await context.bot.send_message(
                        config["owner_id"],
                        f"🗑️ <b>Bot Deleted by Admin</b>\n\n🤖 @{config['bot_username']}\n\nYour bot has been deleted by the admin.",
                        parse_mode="HTML"
                    )
                await query.edit_message_text(f"🗑️ Bot @{config['bot_username']} deleted successfully!")
            except Exception as e:
                logger.error(f"Error notifying user {config['owner_id']}: {e}")
                await query.edit_message_text(f"🗑️ Bot @{config['bot_username']} deleted successfully, but failed to notify user!")
        else:
            await query.edit_message_text("❌ Error deleting bot!")

async def main_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    text = update.message.text
    
    if state["step"] == "bot_token":
        if not text or ":" not in text:
            await update.message.reply_text("❌ Invalid bot token! Try again.")
            return
        
        if text in running_tokens:
            await update.message.reply_text("❌ This bot token is already in use! Each bot must have a unique token.")
            return
            
        token_exists = any(config.get('bot_token') == text for config in bot_configs.values())
        token_pending = any(req.get('bot_token') == text for req in pending_requests.values())
        
        if token_exists or token_pending:
            await update.message.reply_text("❌ This bot token is already registered!")
            return
        
        try:
            response = requests.get(f"https://api.telegram.org/bot{text}/getMe")
            if not response.json().get("ok"):
                await update.message.reply_text("❌ Invalid bot token! Try again.")
                return
            
            bot_info = response.json()["result"]
            state["bot_token"] = text
            state["bot_username"] = bot_info["username"]
            state["step"] = "chat_id"
            
            await update.message.reply_text(f"✅ Bot verified: @{bot_info['username']}\n\n🤖 <b>Step 2/4</b>\n\nSend Chat ID for OTPs", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error verifying bot token: {e}")
            await update.message.reply_text("❌ Error verifying bot! Try again.")
            
    elif state["step"] == "chat_id":
        try:
            chat_id = int(text)
            state["chat_id"] = chat_id
            state["step"] = "group_link"
            await update.message.reply_text("✅ Chat ID saved!\n\n<b>Step 3/4</b>\n\nSend group link for 'View OTP' button", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ Invalid Chat ID! Send a number.")
            
    elif state["step"] == "group_link":
        if not text.startswith(("https://t.me/", "@")):
            await update.message.reply_text("❌ Invalid link! Send valid Telegram link.")
            return
        
        state["group_link"] = text
        state["step"] = "channel_link"
        await update.message.reply_text("✅ Group link saved!\n\n📢 <b>Step 4/4</b>\n\nSend channel link for 'View Channel' button (or send /skip to use default)", parse_mode="HTML")
        
    elif state["step"] == "channel_link":
        if text == "/skip":
            state["channel_link"] = DEFAULT_CHANNEL_LINK
        elif not text.startswith(("https://t.me/", "@")):
            await update.message.reply_text("❌ Invalid link! Send valid Telegram channel link or /skip for default.")
            return
        else:
            # Ensure channel link is properly formatted
            channel_link = text
            if channel_link.startswith("@"):
                channel_link = f"https://t.me/{channel_link[1:]}"
            state["channel_link"] = channel_link
            
        state["owner_id"] = user_id
        state["username"] = update.effective_user.username or f"User_{user_id}"
        
        if user_id == OWNER_ID:
            bot_id = f"bot_{len(bot_configs) + 1}_{user_id}"
            config = {
                "owner_id": user_id,
                "bot_token": state["bot_token"],
                "bot_username": state["bot_username"],
                "chat_id": state["chat_id"],
                "group_link": state["group_link"],
                "channel_link": state["channel_link"],
                "created_at": time.time()
            }
            
            bot_configs[bot_id] = config
            save_bot_configs(bot_configs)
            
            start_cloned_bot(bot_id, config)
            
            await update.message.reply_text(
                f"🎉 <b>Bot Created Successfully!</b>\n\n"
                f"🤖 @{state['bot_username']}\n"
                f"📱 Chat: {state['chat_id']}\n"
                f"🔗 Group: {state['group_link']}\n"
                f"📢 Channel: {state['channel_link']}\n\n"
                f"✅ Bot is now active!",
                parse_mode="HTML"
            )
        else:
            req_id = f"req_{int(time.time())}_{user_id}"
            pending_requests[req_id] = {
                "owner_id": user_id,
                "username": state["username"],
                "bot_token": state["bot_token"],
                "bot_username": state["bot_username"],
                "chat_id": state["chat_id"],
                "group_link": state["group_link"],
                "channel_link": state["channel_link"],
                "requested_at": time.time()
            }
            save_pending_requests(pending_requests)
            
            try:
               buttons = [
                 [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{req_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{req_id}")
                   ]
                  ]
               await context.bot.send_message(
        OWNER_ID,
        f"🔔 <b>New Bot Request!</b>\n\n"
        f"👤 User: @{state['username']} ({user_id})\n"
        f"🤖 Bot: @{state['bot_username']}\n"
        f"📱 Chat: {state['chat_id']}\n"
        f"🔗 Group: {state['group_link']}\n"
        f"📢 Channel: {state['channel_link']}\n\n"
        f"⏳ Please review below:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
            except Exception as e:
              logger.error(f"Error notifying owner: {e}")
       
            await update.message.reply_text(
                f"📋 <b>Bot Request Submitted!</b>\n\n"
                f"🤖 @{state['bot_username']}\n"
                f"📱 Chat: {state['chat_id']}\n"
                f"🔗 Group: {state['group_link']}\n"
                f"📢 Channel: {state['channel_link']}\n\n"
                f"⏳ Waiting for owner approval...\n\n"
                f"Contact Admin For Approval @Vxxwo",
                parse_mode="HTML"
            )
        
        del user_states[user_id]

def start_cloned_bot(bot_id, config):
    """Start a cloned bot using subprocess"""
    try:
        if config["bot_token"] in running_tokens:
            logger.error(f"Bot token already in use: @{config['bot_username']}")
            return
        
        if bot_id in active_processes:
            try:
                active_processes[bot_id].terminate()
                time.sleep(1)
                if active_processes[bot_id].poll() is None:
                    active_processes[bot_id].kill()
                logger.info(f"Stopped existing process for {bot_id}")
            except Exception as e:
                logger.error(f"Error stopping existing process for {bot_id}: {e}")
        
        bot_filename = create_bot_file(bot_id, config)
        
        process = subprocess.Popen(
            [sys.executable, bot_filename],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        active_processes[bot_id] = process
        running_tokens.add(config["bot_token"])
        
        threading.Thread(target=simple_otp_monitor, args=(config,), daemon=True).start()
        
        logger.info(f"Started cloned bot: @{config['bot_username']} (PID: {process.pid})")
        
        def monitor_process():
            process.wait()
            if bot_id in active_processes:
                del active_processes[bot_id]
            if config["bot_token"] in running_tokens:
                running_tokens.remove(config["bot_token"])
            logger.info(f"Process ended for @{config['bot_username']}")
        
        threading.Thread(target=monitor_process, daemon=True).start()
        
    except Exception as e:
        logger.error(f"Error starting cloned bot {bot_id}: {e}")

def start_all_saved_bots():
    """Start all saved bots"""
    for bot_id, config in bot_configs.items():
        start_cloned_bot(bot_id, config)
        time.sleep(2)

from telegram.request import HTTPXRequest
import telegram.error

if __name__ == "__main__":
    logger.info("Starting multi-bot system...")

    # Flask ko alag thread pe run karo
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=False),
        daemon=True
    ).start()
    time.sleep(2)

    # Pehle se saved bots start karo
    start_all_saved_bots()
    time.sleep(2)

    # Custom request object with bigger timeouts
    request = HTTPXRequest(connect_timeout=20, read_timeout=20)

    # Main bot application
    application = ApplicationBuilder().token(MAIN_BOT_TOKEN).request(request).build()
    application.add_handler(CommandHandler("start", main_start))
    application.add_handler(CallbackQueryHandler(main_callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_message_handler))

    logger.info("Main bot starting...")

    # Retry loop so bot never crashes on timeout
    while True:
        try:
            application.run_polling()
        except telegram.error.TimedOut:
            logger.warning("⚠️ Telegram TimedOut, retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}, retrying in 10s...")
            time.sleep(10)
