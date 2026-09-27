"""
Ashish Video Editor — Telegram Bot
====================================
Shares the SAME Supabase database as the website (schema.sql).
Whatever happens here (new video, payment approval, chat) is instantly
visible on the website too, and vice versa, because both read/write the
same tables.

ENV VARS REQUIRED (set these in Render → Environment):
  BOT_TOKEN                 - from @BotFather
  SUPABASE_URL               - https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY        - service_role key (Settings → API). NOT the anon key.
                                 The bot needs full access, bypassing RLS.
  ADMIN_TELEGRAM_ID           - YOUR personal Telegram numeric ID (get it from @userinfobot)
  WEBSITE_URL                 - e.g. https://ashisheditor.onrender.com  (used to build client links)
  PORT                        - Render sets this automatically for the healthcheck webserver

INSTALL:
  pip install -r requirements.txt

RUN LOCALLY:
  python bot.py

DEPLOY ON RENDER (free):
  - New "Web Service" (needs a bound port, which is why this file also runs
    a tiny aiohttp server — Render's free tier requires a web service, not
    a background worker, to stay on the free plan).
  - Build command:  pip install -r requirements.txt
  - Start command:  python bot.py
"""

import os
import logging
import asyncio
from datetime import date

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)
from supabase import create_client, Client
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
ADMIN_ID = int(os.environ["ADMIN_TELEGRAM_ID"])
WEBSITE_URL = os.environ.get("WEBSITE_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", 10000))

sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# In-memory "what are we waiting for from this admin/client" state.
# Key = telegram user id -> dict describing the pending action.
STATE: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# Small DB helpers (service role -> bypasses RLS, so be careful what we expose)
# ---------------------------------------------------------------------------

def get_profile() -> dict:
    r = sb.table("profile").select("*").eq("id", 1).single().execute()
    return r.data or {}

def get_client_by_token(token: str) -> dict | None:
    r = sb.table("clients").select("*").eq("token", token).limit(1).execute()
    return r.data[0] if r.data else None

def get_client_by_chat(chat_id: int) -> dict | None:
    r = sb.table("clients").select("*").eq("telegram_chat_id", chat_id).limit(1).execute()
    return r.data[0] if r.data else None

def get_client_by_id(cid: str) -> dict | None:
    r = sb.table("clients").select("*").eq("id", cid).limit(1).execute()
    return r.data[0] if r.data else None

def list_clients() -> list[dict]:
    r = sb.table("clients").select("*").order("last_message_at", desc=True).execute()
    return r.data or []

def client_videos(cid: str) -> list[dict]:
    r = sb.table("client_videos").select("*").eq("client_id", cid).order("created_at", desc=True).execute()
    return r.data or []


def client_portal_link(token: str) -> str:
    return f"{WEBSITE_URL}/c/{token}" if WEBSITE_URL else f"(set WEBSITE_URL) /c/{token}"

def video_link(token: str, video_id: str) -> str:
    return f"{WEBSITE_URL}/c/{token}/v/{video_id}" if WEBSITE_URL else f"(set WEBSITE_URL) /c/{token}/v/{video_id}"


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    await context.bot.send_message(ADMIN_ID, text, reply_markup=reply_markup)


# ---------------------------------------------------------------------------
# /start — branches into: admin, existing linked client, new client via
# deep-link token, or a brand new random visitor (show portfolio)
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    args = context.args

    if chat_id == ADMIN_ID:
        await admin_menu(update, context)
        return

    # Deep link: t.me/YourBot?start=<client_token>
    if args:
        token = args[0]
        client = get_client_by_token(token)
        if client:
            # link this telegram chat to that client (idempotent)
            sb.table("clients").update({
                "telegram_chat_id": chat_id,
                "telegram_username": user.username,
            }).eq("id", client["id"]).execute()
            await update.message.reply_text(
                f"👋 {client.get('greeting') or 'Welcome back'}, {client['name']}!\n"
                f"Aapka portal is bot se bhi jud gaya — video ready hote hi yahin notify hoga."
            )
            await client_menu(update, context, client)
            return

    # No valid token -> new/unknown visitor -> show portfolio, alert admin
    existing = get_client_by_chat(chat_id)
    if existing:
        await client_menu(update, context, existing)
        return

    profile = get_profile()
    portfolio_items = sb.table("portfolio_projects").select("title,category").order("display_order").limit(6).execute().data or []
    lines = [
        f"🎬 *{profile.get('name','Ashish')}* — {profile.get('role','Video Editor')}",
        "",
        profile.get("bio") or "Professional video editing for creators & brands.",
    ]
    if portfolio_items:
        lines.append("\n*Recent work:*")
        lines += [f"• {p['title']} ({p.get('category','')})" for p in portfolio_items]
    if WEBSITE_URL:
        lines.append(f"\n🔗 Full portfolio: {WEBSITE_URL}")
    lines.append("\nAgar aap mera client ho aur aapko link nahi mila, mujhe yahin message kar sakte ho.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    await notify_admin(
        context,
        f"👀 New visitor started the bot.\nName: {user.full_name}\nUsername: @{user.username}\nID: {chat_id}"
    )


# ---------------------------------------------------------------------------
# CLIENT SIDE
# ---------------------------------------------------------------------------

def client_kb():
    return ReplyKeyboardMarkup(
        [["🎬 My Videos", "💰 Wallet"], ["💬 Message Ashish"]],
        resize_keyboard=True
    )

async def client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, client: dict):
    await update.message.reply_text(
        f"Wallet balance: ₹{client['wallet_balance']}\nKya dekhna hai?",
        reply_markup=client_kb()
    )

async def client_show_videos(update: Update, context: ContextTypes.DEFAULT_TYPE, client: dict):
    vids = client_videos(client["id"])
    if not vids:
        await update.message.reply_text("Abhi koi video nahi hai.")
        return
    for v in vids:
        due = max(float(v["price"]) - float(v["amount_paid"]), 0)
        status_emoji = "✅ Ready" if v["status"] == "ready" else "✂️ Editing"
        text = (
            f"*{v['title']}*\n{status_emoji}\n"
            f"Price: ₹{v['price']} | Paid: ₹{v['amount_paid']}"
            + (f" | Due: ₹{due}" if due > 0 else "")
        )
        buttons = []
        if due > 0:
            buttons.append([InlineKeyboardButton(f"Pay ₹{due}", callback_data=f"pay:{client['id']}:{v['id']}:{due}")])
        if v["status"] == "ready" and (v.get("video_url") or v.get("external_link")):
            link = video_link(client["token"], v["id"])
            buttons.append([InlineKeyboardButton("▶️ Watch", url=link)])
        await update.message.reply_text(text, parse_mode="Markdown",
                                         reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)

async def client_show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE, client: dict):
    profile = get_profile()
    tx = sb.table("wallet_transactions").select("*").eq("client_id", client["id"])\
        .order("created_at", desc=True).limit(10).execute().data or []
    lines = [f"💰 Balance: ₹{client['wallet_balance']}", "", "Recent transactions:"]
    for t in tx:
        sign = "+" if t["type"] == "credit" else "-"
        lines.append(f"{sign}₹{t['amount']} — {t.get('note') or ''}")
    upi = profile.get("upi_id")
    if upi:
        lines.append(f"\nPay via UPI: `{upi}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add Payment", callback_data=f"addpay:{client['id']}")]]))

async def client_start_payment(update_or_query, context, client_id, video_id=None, amount=None):
    STATE[update_or_query.effective_user.id] = {
        "action": "awaiting_payment_amount" if amount is None else "awaiting_payment_screenshot",
        "client_id": client_id, "video_id": video_id, "amount": amount,
    }
    chat = update_or_query.effective_chat
    if amount is None:
        await context.bot.send_message(chat.id, "Kitna amount pay kar rahe ho? (sirf number bhejo)")
    else:
        await context.bot.send_message(chat.id, f"₹{amount} — ab payment ka screenshot bhejo (photo).")


# ---------------------------------------------------------------------------
# TEXT MESSAGE ROUTER
# ---------------------------------------------------------------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    state = STATE.get(uid)

    # --- Admin flows ---
    if chat_id == ADMIN_ID and state:
        await handle_admin_state(update, context, state)
        return
    if chat_id == ADMIN_ID:
        await admin_menu(update, context)
        return

    # --- Client flows ---
    client = get_client_by_chat(chat_id)
    if not client:
        await update.message.reply_text("Mujhe aapka client link nahi mila. Ashish se apna portal link maango.")
        return

    if state and state.get("action") == "awaiting_payment_amount":
        try:
            amt = float(text)
        except ValueError:
            await update.message.reply_text("Sirf number bhejo, jaise 500")
            return
        await client_start_payment(update, context, client["id"], state.get("video_id"), amt)
        return

    if text == "🎬 My Videos":
        await client_show_videos(update, context, client)
        return
    if text == "💰 Wallet":
        await client_show_wallet(update, context, client)
        return
    if text == "💬 Message Ashish":
        STATE[uid] = {"action": "awaiting_chat_message", "client_id": client["id"]}
        await update.message.reply_text("Apna message likho:", reply_markup=ReplyKeyboardRemove())
        return

    if state and state.get("action") == "awaiting_chat_message":
        sb.table("messages").insert({
            "client_id": client["id"], "sender": "client", "text": text, "channel": "telegram"
        }).execute()
        sb.table("clients").update({"last_message_at": "now()"}).eq("id", client["id"]).execute()
        STATE.pop(uid, None)
        await update.message.reply_text("Bhej diya ✅", reply_markup=client_kb())
        await notify_admin(context, f"💬 New message from {client['name']}:\n{text}",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Reply", callback_data=f"reply:{client['id']}")]]))
        return

    # default: treat as a chat message too
    sb.table("messages").insert({
        "client_id": client["id"], "sender": "client", "text": text, "channel": "telegram"
    }).execute()
    await notify_admin(context, f"💬 {client['name']}: {text}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Reply", callback_data=f"reply:{client['id']}")]]))
    await update.message.reply_text("Bhej diya ✅", reply_markup=client_kb())


# ---------------------------------------------------------------------------
# PHOTO HANDLER — client payment screenshots
# ---------------------------------------------------------------------------

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = STATE.get(uid)
    if not state or state.get("action") != "awaiting_payment_screenshot":
        return  # ignore random photos

    client_id = state["client_id"]
    video_id = state.get("video_id")
    amount = state["amount"]

    file = await update.message.photo[-1].get_file()
    path = f"tg_{client_id}_{file.file_unique_id}.jpg"
    file_bytes = await file.download_as_bytearray()
    sb.storage.from_("screenshots").upload(path, bytes(file_bytes), {"content-type": "image/jpeg"})
    public_url = sb.storage.from_("screenshots").get_public_url(path)

    sb.table("payments").insert({
        "client_id": client_id, "video_id": video_id, "amount": amount,
        "screenshot_url": public_url, "status": "pending", "channel": "telegram",
    }).execute()

    STATE.pop(uid, None)
    client = get_client_by_id(client_id)
    await update.message.reply_text("Payment submit ho gaya ✅ Ashish approve karte hi wallet/video update ho jaayega.",
                                     reply_markup=client_kb())

    await notify_admin(
        context,
        f"🧾 New payment: ₹{amount} from {client['name']}",
    )
    await context.bot.send_photo(
        ADMIN_ID, public_url,
        caption=f"₹{amount} from {client['name']}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"appr:pending_lookup:{client_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rej:pending_lookup:{client_id}"),
        ]])
    )
    # NOTE: we resolve the actual payment id via lookup at approve-time
    # (simplest with the free plan; see button handler below).


# ---------------------------------------------------------------------------
# ADMIN — menu, client browser, video add, wallet controls, replies, approvals
# ---------------------------------------------------------------------------

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("👥 Clients", callback_data="admin:clients:0")],
        [InlineKeyboardButton("🧾 Pending Payments", callback_data="admin:pending")],
    ]
    msg = update.message or update.callback_query.message
    await msg.reply_text("Admin panel:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_list_clients(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    clients = list_clients()
    page_size = 8
    chunk = clients[page * page_size:(page + 1) * page_size]
    kb = [[InlineKeyboardButton(c["name"], callback_data=f"admin:client:{c['id']}")] for c in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"admin:clients:{page-1}"))
    if (page + 1) * page_size < len(clients):
        nav.append(InlineKeyboardButton("▶️", callback_data=f"admin:clients:{page+1}"))
    if nav:
        kb.append(nav)
    q = update.callback_query
    await q.edit_message_text("Select a client:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_client_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, client_id: str):
    c = get_client_by_id(client_id)
    if not c:
        return
    text = (
        f"*{c['name']}*\nWallet: ₹{c['wallet_balance']}\n"
        f"Portal: {client_portal_link(c['token'])}\n"
        f"Telegram linked: {'yes' if c.get('telegram_chat_id') else 'no'}"
    )
    kb = [
        [InlineKeyboardButton("➕ Add Video / Send Ready Link", callback_data=f"admin:addvideo:{client_id}")],
        [InlineKeyboardButton("💳 Add to Wallet", callback_data=f"admin:addwallet:{client_id}"),
         InlineKeyboardButton("🎯 Set Balance", callback_data=f"admin:setwallet:{client_id}")],
        [InlineKeyboardButton("💬 Chat", callback_data=f"reply:{client_id}")],
        [InlineKeyboardButton("🗑 Delete Client", callback_data=f"admin:delclient_confirm:{client_id}")],
    ]
    q = update.callback_query
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def handle_admin_state(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict):
    text = update.message.text.strip()
    action = state["action"]

    if action == "awaiting_video_title":
        state["title"] = text
        state["action"] = "awaiting_video_price"
        await update.message.reply_text("Price kitna hai? (0 likho agar free/included hai)")
        return

    if action == "awaiting_video_price":
        try:
            state["price"] = float(text)
        except ValueError:
            await update.message.reply_text("Sirf number bhejo")
            return
        state["action"] = "awaiting_video_link"
        await update.message.reply_text("Ab Drive/external link paste karo (ya 'skip' likho agar sirf file upload karoge baad me website se):")
        return

    if action == "awaiting_video_link":
        link = None if text.lower() == "skip" else text
        client_id = state["client_id"]
        row = sb.table("client_videos").insert({
            "client_id": client_id,
            "title": state["title"],
            "price": state["price"],
            "status": "ready",
            "ready_date": date.today().isoformat(),
            "external_link": link,
        }).execute().data[0]

        client = get_client_by_id(client_id)
        link_url = video_link(client["token"], row["id"])
        await update.message.reply_text(f"✅ Video added & marked ready.\nClient link: {link_url}")

        if client.get("telegram_chat_id"):
            await context.bot.send_message(
                client["telegram_chat_id"],
                f"🎉 Your video *{state['title']}* is ready!\nWatch here: {link_url}",
                parse_mode="Markdown"
            )
        STATE.pop(update.effective_user.id, None)
        return

    if action == "awaiting_wallet_add":
        try:
            amt = float(text)
        except ValueError:
            await update.message.reply_text("Sirf number bhejo")
            return
        client_id = state["client_id"]
        c = get_client_by_id(client_id)
        before = float(c["wallet_balance"])
        after = before + amt
        sb.table("clients").update({"wallet_balance": after}).eq("id", client_id).execute()
        sb.table("wallet_transactions").insert({
            "client_id": client_id, "type": "credit", "amount": amt,
            "note": "Manual admin credit (via bot)", "balance_before": before, "balance_after": after
        }).execute()
        await update.message.reply_text(f"✅ Added ₹{amt}. New balance: ₹{after}")
        STATE.pop(update.effective_user.id, None)
        return

    if action == "awaiting_wallet_set":
        try:
            new_bal = float(text)
        except ValueError:
            await update.message.reply_text("Sirf number bhejo")
            return
        client_id = state["client_id"]
        c = get_client_by_id(client_id)
        before = float(c["wallet_balance"])
        diff = new_bal - before
        sb.table("clients").update({"wallet_balance": new_bal}).eq("id", client_id).execute()
        sb.table("wallet_transactions").insert({
            "client_id": client_id, "type": "credit" if diff >= 0 else "debit",
            "amount": abs(diff), "note": "Manual balance override (via bot)",
            "balance_before": before, "balance_after": new_bal
        }).execute()
        await update.message.reply_text(f"✅ Balance set to ₹{new_bal}")
        STATE.pop(update.effective_user.id, None)
        return

    if action == "awaiting_admin_reply":
        client_id = state["client_id"]
        client = get_client_by_id(client_id)
        sb.table("messages").insert({
            "client_id": client_id, "sender": "admin", "text": text, "channel": "telegram"
        }).execute()
        await update.message.reply_text("✅ Sent")
        if client.get("telegram_chat_id"):
            await context.bot.send_message(client["telegram_chat_id"], f"✉️ Ashish: {text}")
        STATE.pop(update.effective_user.id, None)
        return


# ---------------------------------------------------------------------------
# CALLBACK QUERIES (inline buttons)
# ---------------------------------------------------------------------------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id

    if data.startswith("admin:clients:"):
        await admin_list_clients(update, context, int(data.split(":")[2]))
        return
    if data.startswith("admin:client:"):
        await admin_client_detail(update, context, data.split(":")[2])
        return
    if data.startswith("admin:addvideo:"):
        cid = data.split(":")[2]
        STATE[uid] = {"action": "awaiting_video_title", "client_id": cid}
        await q.message.reply_text("Video ka title bhejo:")
        return
    if data.startswith("admin:addwallet:"):
        cid = data.split(":")[2]
        STATE[uid] = {"action": "awaiting_wallet_add", "client_id": cid}
        await q.message.reply_text("Kitna add karna hai wallet me?")
        return
    if data.startswith("admin:setwallet:"):
        cid = data.split(":")[2]
        STATE[uid] = {"action": "awaiting_wallet_set", "client_id": cid}
        await q.message.reply_text("Naya exact balance kya set karna hai?")
        return
    if data.startswith("admin:delclient_confirm:"):
        cid = data.split(":")[2]
        c = get_client_by_id(cid)
        await q.edit_message_text(
            f"⚠️ {c['name']} ko permanently delete karna hai? (video, chat, payment history sab)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Yes, delete", callback_data=f"admin:delclient:{cid}"),
                InlineKeyboardButton("Cancel", callback_data="admin:clients:0"),
            ]])
        )
        return
    if data.startswith("admin:delclient:"):
        cid = data.split(":")[2]
        sb.table("clients").delete().eq("id", cid).execute()
        await q.edit_message_text("🗑 Client deleted.")
        return
    if data == "admin:pending":
        pend = sb.table("payments").select("*, clients(name)").eq("status", "pending").execute().data or []
        if not pend:
            await q.edit_message_text("Koi pending payment nahi hai ✅")
            return
        for p in pend:
            name = p.get("clients", {}).get("name", "?")
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"appr:id:{p['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"rej:id:{p['id']}"),
            ]])
            await q.message.reply_text(f"₹{p['amount']} from {name}\n{p.get('note') or ''}", reply_markup=kb)
        return

    if data.startswith("appr:") or data.startswith("rej:"):
        approve = data.startswith("appr:")
        _, mode, ref = data.split(":")
        if mode == "id":
            payment_id = ref
        else:  # pending_lookup by client_id -> grab their most recent pending payment
            rows = sb.table("payments").select("id").eq("client_id", ref).eq("status", "pending")\
                .order("submitted_at", desc=True).limit(1).execute().data
            if not rows:
                await q.edit_message_caption(caption="Already decided.")
                return
            payment_id = rows[0]["id"]

        if approve:
            sb.rpc("approve_payment", {"p_payment_id": payment_id}).execute()
            result_text = "✅ Approved & applied"
        else:
            sb.rpc("reject_payment", {"p_payment_id": payment_id}).execute()
            result_text = "❌ Rejected"

        if q.message.photo:
            await q.edit_message_caption(caption=result_text)
        else:
            await q.edit_message_text(result_text)
        return

    if data.startswith("reply:"):
        cid = data.split(":")[1]
        STATE[uid] = {"action": "awaiting_admin_reply", "client_id": cid}
        recent = sb.table("messages").select("*").eq("client_id", cid).order("created_at", desc=True).limit(5).execute().data or []
        transcript = "\n".join(f"{m['sender']}: {m['text']}" for m in reversed(recent))
        await q.message.reply_text(f"Recent:\n{transcript}\n\nReply likho:")
        return

    if data.startswith("pay:"):
        _, cid, vid, amount = data.split(":")
        await client_start_payment(update, context, cid, vid, float(amount))
        return
    if data.startswith("addpay:"):
        cid = data.split(":")[1]
        await client_start_payment(update, context, cid, None, None)
        return


# ---------------------------------------------------------------------------
# Small aiohttp server: healthcheck (Render needs a bound port) + a webhook
# endpoint Supabase Database Webhooks can call so that actions done on the
# WEBSITE (not the bot) also push a Telegram notification to you/the client.
#
# In Supabase: Database → Webhooks → new webhook on INSERT for `payments`
# and `messages`, pointing at  https://<your-render-url>/notify
# ---------------------------------------------------------------------------

async def handle_health(request):
    return web.Response(text="ok")

async def handle_notify(request):
    app_tg = request.app["tg_app"]
    payload = await request.json()
    table = payload.get("table")
    record = payload.get("record", {})

    if table == "payments" and record.get("status") == "pending":
        client = get_client_by_id(record["client_id"])
        if client:
            await app_tg.bot.send_message(
                ADMIN_ID,
                f"🧾 New payment (via website): ₹{record['amount']} from {client['name']}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Approve", callback_data=f"appr:id:{record['id']}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"rej:id:{record['id']}"),
                ]])
            )

    if table == "messages" and record.get("sender") == "client" and record.get("channel") == "web":
        client = get_client_by_id(record["client_id"])
        if client:
            await app_tg.bot.send_message(
                ADMIN_ID,
                f"💬 (website) {client['name']}: {record['text']}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Reply", callback_data=f"reply:{client['id']}")]])
            )
    if table == "messages" and record.get("sender") == "admin" and record.get("channel") == "web":
        client = get_client_by_id(record["client_id"])
        if client and client.get("telegram_chat_id"):
            await app_tg.bot.send_message(client["telegram_chat_id"], f"✉️ Ashish: {record['text']}")

    return web.json_response({"ok": True})


async def run_webserver(tg_app: Application):
    app = web.Application()
    app["tg_app"] = tg_app
    app.router.add_get("/", handle_health)
    app.router.add_post("/notify", handle_notify)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info(f"Healthcheck/webhook server on :{PORT}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    async def post_init(application: Application):
        await run_webserver(application)

    app.post_init = post_init
    log.info("Bot starting (polling)...")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
