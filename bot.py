# -*- coding: utf-8 -*-
"""
Universal Downloader Bot
TikTok + Pinterest — بدون أكواد + لوحة أدمن متكاملة
"""

import os, json, time, datetime, logging, re, requests, yt_dlp, io, asyncio
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, ChatMember
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ============ إعدادات ============
TOKEN   = "8411679879:AAFYCqR8fjjAlbTiERNx5wxSexifPLjpw-0"
OWNER_ID = 8134190545
DATA_FILE = "bot_db.json"
KEEPALIVE_PORT = int(os.environ.get("PORT", 8082))
WELCOME_BANNER = "assets/welcome_banner.png"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# ============ قاعدة البيانات ============
def _default_db():
    return {
        "users": {},
        "stats": {"downloads": 0},
        "channels": [],      # قنوات الاشتراك الإجباري  [{"id": -100x, "name": "...", "link": "..."}]
        "banned": [],        # مستخدمون محظورون
        "welcome": "👋 أهلاً {name}!\nاختر الخدمة:",
        "forward_msgs": True  # توجيه رسائل المستخدمين للمطور
    }

def load_db():
    if not os.path.exists(DATA_FILE):
        db = _default_db()
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        return db
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
    # تأكد من وجود جميع المفاتيح
    for k, v in _default_db().items():
        if k not in db:
            db[k] = v
    return db

def save_db():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(DB, f, ensure_ascii=False, indent=2)

DB = load_db()

def now_ts():   return int(time.time())
def is_owner(uid): return str(uid) == str(OWNER_ID)
def is_banned(uid): return uid in DB.get("banned", [])

def register_user(user):
    """يسجل المستخدم ويرجع True إذا كان جديداً."""
    uid = str(user.id)
    if uid not in DB["users"]:
        DB["users"][uid] = {
            "first_name": user.first_name or "",
            "username":   user.username or "",
            "joined":     now_ts()
        }
        save_db()
        return True
    return False

# ============ اشتراك إجباري ============
async def check_subscriptions(bot, uid) -> list:
    """يرجع قائمة القنوات التي لم يشترك بها المستخدم."""
    channels = DB.get("channels", [])
    if not channels:
        return []

    async def check_one(ch):
        try:
            member = await bot.get_chat_member(ch["id"], uid)
            if member.status in (ChatMember.LEFT, ChatMember.BANNED):
                return ch
            return None
        except Exception:
            return ch

    results = await asyncio.gather(*[check_one(ch) for ch in channels])
    return [ch for ch in results if ch is not None]

def subscription_kb(not_joined: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(f"📢 {ch['name']}", url=ch["link"])] for ch in not_joined]
    buttons.append([InlineKeyboardButton("✅ تحققت من اشتراكي", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

# ============ تحميل مباشر ============
def fetch_bytes(url: str, max_mb: int = 45) -> io.BytesIO | None:
    """يحمّل ملف من URL ويرجعه كـ BytesIO (حد 45 MB)."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            size = int(r.headers.get("Content-Length", 0))
            if size > max_mb * 1024 * 1024:
                log.warning(f"File too large: {size} bytes")
                return None
            buf = io.BytesIO()
            downloaded = 0
            for chunk in r.iter_content(chunk_size=1024 * 256):
                buf.write(chunk)
                downloaded += len(chunk)
                if downloaded > max_mb * 1024 * 1024:
                    log.warning("File exceeded size limit during download")
                    return None
            buf.seek(0)
            return buf
    except Exception as e:
        log.error(f"fetch_bytes failed: {e}")
        return None

# ============ KeepAlive ============
flask_app = Flask("keepalive")

@flask_app.get("/")
def home(): return "Bot is alive ✅"

def keep_alive():
    Thread(target=lambda: flask_app.run(host="0.0.0.0", port=KEEPALIVE_PORT), daemon=True).start()

# ============ أدوات مساعدة ============
def escape_md(text):
    if not text: return ""
    for ch in ['_', '*', '`', '[']:
        text = str(text).replace(ch, f'\\{ch}')
    return text

# ============ لوحات الأزرار ============
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 TikTok", callback_data="site:tiktok")],
        [InlineKeyboardButton("📌 Pinterest", callback_data="site:pinterest")],
    ])

def after_download_kb(site):
    names = {"tiktok": "TikTok", "pinterest": "Pinterest"}
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔄 تحميل {names.get(site, site)} آخر", callback_data=f"site:{site}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])

def retry_kb(site):
    names = {"tiktok": "TikTok", "pinterest": "Pinterest"}
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔁 حاول مرة أخرى", callback_data=f"site:{site}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])

def admin_kb():
    fwd = DB.get("forward_msgs", True)
    fwd_btn = "📨 التوجيه: ✅ شغّال" if fwd else "📨 التوجيه: ❌ موقوف"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 إدارة القنوات الإجبارية", callback_data="admin:channels")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin:stats")],
        [InlineKeyboardButton("📣 بث رسالة", callback_data="admin:broadcast")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin:ban"),
         InlineKeyboardButton("✅ رفع الحظر", callback_data="admin:unban")],
        [InlineKeyboardButton("✏️ تغيير رسالة الترحيب", callback_data="admin:welcome")],
        [InlineKeyboardButton("🖼 تغيير صورة الترحيب", callback_data="admin:changebanner")],
        [InlineKeyboardButton(fwd_btn, callback_data="admin:toggleforward")],
    ])

def channels_kb():
    buttons = []
    for i, ch in enumerate(DB.get("channels", [])):
        buttons.append([InlineKeyboardButton(f"🗑 حذف: {ch['name']}", callback_data=f"delch:{i}")])
    buttons.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="admin:addchannel")])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin:back")])
    return InlineKeyboardMarkup(buttons)

# ============ دوال التحميل ============
def ytdlp_extract(url):
    try:
        opts = {
            "quiet": True, "noprogress": True,
            "skip_download": True, "no_warnings": True,
            "format": "bestvideo+bestaudio/best",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        log.error(f"yt-dlp failed: {e}")
        return None

def tiktok_best(url):
    # خطة A: tikwm API
    try:
        j = requests.get("https://www.tikwm.com/api/", params={"url": url, "hd": 1}, timeout=15).json()
        d = j.get("data")
        if d:
            if d.get("images"):
                music_url = (d.get("music_info") or {}).get("play") or d.get("music")
                return "photos", d["images"], d.get("title"), music_url
            v = d.get("hdplay") or d.get("play")
            if v:
                return "video", v, d.get("title"), None
    except Exception as e:
        log.error(f"tikwm failed: {e}")

    # خطة B: yt-dlp
    info = ytdlp_extract(url)
    if info:
        if info.get("entries"):
            photos = [e.get("url") for e in info["entries"] if e.get("url")]
            if photos: return "photos", photos, info.get("title"), None
        if info.get("url"):
            return "video", info["url"], info.get("title"), None

    return None, None, None, None

def pinterest_best(url):
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    try:
        if "pin.it" in url or "pinterest" not in url:
            url = requests.get(url, allow_redirects=True, headers=headers, timeout=10).url
        html = requests.get(url, headers=headers, timeout=12).text

        # فيديو
        for pat in [
            r'"contentUrl"\s*:\s*"(https://v[12]\.pinimg\.com/videos/[^"]+\.mp4[^"]*)"',
            r'(https://v[12]\.pinimg\.com/videos/[^"\'<>\s]+\.mp4)',
        ]:
            m = re.search(pat, html)
            if m:
                return "video", m.group(1).replace("\\u002F", "/"), "Pinterest Video"

        # صورة — أعلى جودة
        for size in ["originals", "1200x", "736x", "564x"]:
            m = re.search(rf'"url"\s*:\s*"(https://i\.pinimg\.com/{size}/[^"]+)"', html)
            if m:
                return "photo", m.group(1).replace("\\u002F", "/"), "Pinterest Image"

        m = re.search(r'(https://i\.pinimg\.com/[^"\'<>\s]+\.(?:jpg|jpeg|png|webp))', html)
        if m:
            return "photo", m.group(1), "Pinterest Image"

    except Exception as e:
        log.error(f"Pinterest failed: {e}")
    return None, None, None

# ============ Handlers ============
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new = register_user(user)
    uid = user.id

    # إشعار المطوّر بمستخدم جديد
    if is_new and not is_owner(uid):
        try:
            uname = f"@{user.username}" if user.username else f"ID: {uid}"
            total = len(DB["users"])
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"👤 *مستخدم جديد!*\n"
                     f"الاسم: {user.first_name or 'بدون اسم'}\n"
                     f"الحساب: {uname}\n"
                     f"🆔 `{uid}`\n"
                     f"إجمالي المستخدمين: `{total}`",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

    if is_owner(uid):
        await update.message.reply_text("🔧 لوحة التحكم:", reply_markup=admin_kb())
        return

    if is_banned(uid):
        await update.message.reply_text("⛔ أنت محظور من استخدام البوت.")
        return

    not_joined = await check_subscriptions(context.bot, uid)
    if not_joined:
        await update.message.reply_text(
            "📢 يجب الاشتراك في القنوات التالية أولاً:",
            reply_markup=subscription_kb(not_joined)
        )
        return

    welcome = DB.get("welcome", "👋 أهلاً {name}!\nاختر الخدمة:")
    caption = welcome.replace("{name}", user.first_name or "")
    try:
        with open(WELCOME_BANNER, "rb") as img:
            await update.message.reply_photo(photo=img, caption=caption, reply_markup=main_menu_kb())
    except Exception:
        await update.message.reply_text(caption, reply_markup=main_menu_kb())

async def cbq_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    # ===== القائمة الرئيسية =====
    if data == "main_menu":
        user = q.from_user
        welcome = DB.get("welcome", "👋 أهلاً {name}!\nاختر الخدمة:")
        caption = welcome.replace("{name}", user.first_name or "")
        try:
            with open(WELCOME_BANNER, "rb") as img:
                await q.message.reply_photo(photo=img, caption=caption, reply_markup=main_menu_kb())
        except Exception:
            await q.message.reply_text(caption, reply_markup=main_menu_kb())
        return

    # ===== تحقق الاشتراك =====
    if data == "check_sub":
        not_joined = await check_subscriptions(context.bot, uid)
        if not_joined:
            await q.message.edit_reply_markup(reply_markup=subscription_kb(not_joined))
        else:
            user = q.from_user
            welcome = DB.get("welcome", "👋 أهلاً {name}!\nاختر الخدمة:")
            await q.message.edit_text(
                welcome.replace("{name}", user.first_name or ""),
                reply_markup=main_menu_kb()
            )
        return

    # ===== لوحة الأدمن =====
    if is_owner(uid) and (data.startswith("admin:") or data.startswith("delch:")):
        if data == "admin:back":
            await q.message.edit_text("🔧 لوحة التحكم:", reply_markup=admin_kb())

        elif data == "admin:channels":
            txt = "📢 *القنوات الإجبارية:*\n"
            if DB["channels"]:
                for i, ch in enumerate(DB["channels"], 1):
                    txt += f"{i}\\. {escape_md(ch['name'])}\n"
            else:
                txt += "_لا توجد قنوات_"
            await q.message.edit_text(txt, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=channels_kb())

        elif data == "admin:addchannel":
            context.user_data["admin_action"] = "addchannel"
            await q.message.reply_text(
                "أرسل معلومات القناة بهذا الشكل:\n"
                "`ID | اسم القناة | رابط الدعوة`\n\n"
                "مثال:\n`-1001234567890 | قناتي | https://t.me/mychannel`"
            , parse_mode=ParseMode.MARKDOWN)

        elif data.startswith("delch:"):
            idx = int(data.split(":")[1])
            if 0 <= idx < len(DB["channels"]):
                removed = DB["channels"].pop(idx)
                save_db()
                await q.message.reply_text(f"✅ تم حذف القناة: {removed['name']}")
            txt = "📢 *القنوات الإجبارية:*\n" + (
                "\n".join(f"{i+1}. {escape_md(ch['name'])}" for i, ch in enumerate(DB["channels"]))
                if DB["channels"] else "_لا توجد قنوات_"
            )
            await q.message.edit_text(txt, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=channels_kb())

        elif data == "admin:stats":
            total_users = len(DB["users"])
            downloads   = DB["stats"].get("downloads", 0)
            await q.message.reply_text(
                f"📊 *الإحصائيات:*\n"
                f"👥 المستخدمون: `{total_users}`\n"
                f"⬇️ التحميلات: `{downloads}`\n"
                f"🚫 المحظورون: `{len(DB.get('banned', []))}`"
            , parse_mode=ParseMode.MARKDOWN)

        elif data == "admin:broadcast":
            context.user_data["admin_action"] = "broadcast"
            await q.message.reply_text("📣 أرسل نص الرسالة التي تريد بثها لجميع المستخدمين:")

        elif data == "admin:ban":
            context.user_data["admin_action"] = "ban"
            await q.message.reply_text("🚫 أرسل ID المستخدم المراد حظره:")

        elif data == "admin:unban":
            context.user_data["admin_action"] = "unban"
            await q.message.reply_text("✅ أرسل ID المستخدم المراد رفع الحظر عنه:")

        elif data == "admin:welcome":
            context.user_data["admin_action"] = "welcome"
            await q.message.reply_text(
                "✏️ أرسل نص رسالة الترحيب الجديدة.\n"
                "يمكنك استخدام `{name}` لاسم المستخدم."
            , parse_mode=ParseMode.MARKDOWN)

        elif data == "admin:changebanner":
            context.user_data["admin_action"] = "changebanner"
            await q.message.reply_text("🖼 أرسل الصورة الجديدة التي تريدها صورة ترحيب:")

        elif data == "admin:toggleforward":
            DB["forward_msgs"] = not DB.get("forward_msgs", True)
            save_db()
            state = "✅ شغّال" if DB["forward_msgs"] else "❌ موقوف"
            await q.message.edit_reply_markup(reply_markup=admin_kb())
            await q.message.reply_text(f"📨 توجيه الرسائل الآن: {state}")
        return

    # ===== اختيار الموقع =====
    if data.startswith("site:"):
        if is_banned(uid):
            await q.message.reply_text("⛔ أنت محظور.")
            return
        not_joined = await check_subscriptions(context.bot, uid)
        if not_joined:
            await q.message.reply_text("📢 يجب الاشتراك أولاً:", reply_markup=subscription_kb(not_joined))
            return
        site = data.split(":")[1]
        context.user_data["await_site"] = site
        names = {"tiktok": "TikTok", "pinterest": "Pinterest"}
        await q.message.reply_text(f"🔗 أرسل رابط {names.get(site, site)}:")

async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    user = update.effective_user
    uid  = user.id
    text = (msg.text or "").strip()
    register_user(user)

    if is_banned(uid) and not is_owner(uid):
        await msg.reply_text("⛔ أنت محظور من استخدام البوت.")
        return

    # ===== توجيه الرسائل للمطور =====
    if not is_owner(uid) and DB.get("forward_msgs", True):
        try:
            uname = f"@{user.username}" if user.username else f"ID: {uid}"
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"💬 رسالة من مستخدم\n"
                     f"━━━━━━━━━━━━━\n"
                     f"👤 الاسم: {user.first_name or 'بدون اسم'}\n"
                     f"🔗 الحساب: {uname}\n"
                     f"🆔 {uid}\n"
                     f"━━━━━━━━━━━━━"
            )
            await context.bot.forward_message(
                chat_id=OWNER_ID,
                from_chat_id=uid,
                message_id=msg.message_id
            )
        except Exception as e:
            log.error(f"Forward failed: {e}")

    # ===== أوامر الأدمن =====
    if is_owner(uid) and "admin_action" in context.user_data:
        act = context.user_data.pop("admin_action")

        if act == "addchannel":
            parts = [p.strip() for p in text.split("|")]
            if len(parts) == 3:
                try:
                    ch_id   = int(parts[0])
                    ch_name = parts[1]
                    ch_link = parts[2]
                    DB["channels"].append({"id": ch_id, "name": ch_name, "link": ch_link})
                    save_db()
                    await msg.reply_text(f"✅ تمت إضافة القناة: {ch_name}", reply_markup=admin_kb())
                except Exception:
                    await msg.reply_text("❌ تأكد من الصيغة:\n`ID | الاسم | الرابط`", parse_mode=ParseMode.MARKDOWN)
            else:
                await msg.reply_text("❌ الصيغة غير صحيحة. مثال:\n`-1001234567890 | قناتي | https://t.me/ch`", parse_mode=ParseMode.MARKDOWN)

        elif act == "broadcast":
            users = list(DB["users"].keys())
            await msg.reply_text(f"⏳ جار البث إلى {len(users)} مستخدم...")
            sent, failed = 0, 0
            for uid_str in users:
                try:
                    await context.bot.send_message(chat_id=int(uid_str), text=text)
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed += 1
            await msg.reply_text(f"✅ تم البث.\nنجح: {sent} | فشل: {failed}")

        elif act == "ban":
            try:
                ban_id = int(text)
                if ban_id not in DB["banned"]:
                    DB["banned"].append(ban_id)
                    save_db()
                await msg.reply_text(f"✅ تم حظر المستخدم: `{ban_id}`", parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await msg.reply_text("❌ أرسل ID صحيح.")

        elif act == "unban":
            try:
                unban_id = int(text)
                if unban_id in DB["banned"]:
                    DB["banned"].remove(unban_id)
                    save_db()
                await msg.reply_text(f"✅ تم رفع الحظر عن: `{unban_id}`", parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await msg.reply_text("❌ أرسل ID صحيح.")

        elif act == "welcome":
            DB["welcome"] = text
            save_db()
            await msg.reply_text("✅ تم تحديث رسالة الترحيب.")
        return

    # ===== تحقق الاشتراك للمستخدمين =====
    if not is_owner(uid):
        not_joined = await check_subscriptions(context.bot, uid)
        if not_joined:
            await msg.reply_text("📢 يجب الاشتراك في القنوات أولاً:", reply_markup=subscription_kb(not_joined))
            return

    # ===== التحميل =====
    site = context.user_data.get("await_site")
    if not site:
        await msg.reply_text("📋 اختر الخدمة:", reply_markup=main_menu_kb())
        return

    m = re.search(r"(https?://\S+)", text)
    if not m:
        await msg.reply_text("❌ أرسل رابطاً صحيحاً يبدأ بـ http أو https.")
        return

    url     = m.group(1)
    waiting = await msg.reply_text("⏳ جاري التحميل...")

    # إشعار المطور بإرسال رابط
    try:
        site_names = {"tiktok": "TikTok 🎵", "pinterest": "Pinterest 📌"}
        uname = f"@{user.username}" if user.username else f"ID: {uid}"
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔗 *مستخدم أرسل رابط!*\n"
                 f"━━━━━━━━━━━━━\n"
                 f"👤 الاسم: {user.first_name or 'بدون اسم'}\n"
                 f"🔗 الحساب: {uname}\n"
                 f"🆔 `{uid}`\n"
                 f"━━━━━━━━━━━━━\n"
                 f"📂 المنصة: {site_names.get(site, site)}\n"
                 f"🌐 الرابط: `{url}`",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass

    success = False
    dl_kind = None
    dl_title = None
    try:
        if site == "tiktok":
            kind, v, tit, music_url = tiktok_best(url)
            if not v:
                await waiting.edit_text(
                    "❌ لم يتم التحميل\nتعذّر جلب محتوى TikTok، تأكد من الرابط وحاول مجدداً.",
                    reply_markup=retry_kb(site)
                )
                context.user_data.pop("await_site", None)
                return

            dl_kind = kind
            dl_title = tit or "TikTok"
            caption = f"✅ {tit}" if tit else "✅ TikTok"

            if kind == "video":
                await waiting.edit_text("⏳ جاري تحميل الفيديو...")
                try:
                    await msg.reply_video(video=v, caption=caption)
                except Exception:
                    data = await asyncio.to_thread(fetch_bytes, v)
                    await msg.reply_video(video=data if data else v, caption=caption)

            elif kind == "photos":
                await waiting.edit_text("⏳ جاري إرسال الصور...")
                batches = [v[i:i+10] for i in range(0, len(v), 10)]
                tasks = [msg.reply_media_group(media=[InputMediaPhoto(url) for url in batch]) for batch in batches]
                if music_url:
                    tasks.append(msg.reply_audio(audio=music_url, caption="🎵 أغنية البوست"))
                await asyncio.gather(*tasks, return_exceptions=True)

            success = True

        elif site == "pinterest":
            kind, v, tit = pinterest_best(url)
            if not v:
                await waiting.edit_text(
                    "❌ لم يتم التحميل\nتعذّر جلب محتوى Pinterest، تأكد من الرابط وحاول مجدداً.",
                    reply_markup=retry_kb(site)
                )
                context.user_data.pop("await_site", None)
                return

            dl_kind = kind
            dl_title = tit or "Pinterest"
            await waiting.edit_text("⏳ جاري تحميل الملف...")
            caption = f"✅ {tit}" if tit else "✅ Pinterest"

            if kind == "video":
                try:
                    await msg.reply_video(video=v, caption=caption)
                except Exception:
                    data = await asyncio.to_thread(fetch_bytes, v)
                    await msg.reply_video(video=data if data else v, caption=caption)
            else:
                try:
                    await msg.reply_photo(photo=v, caption=caption)
                except Exception:
                    data = await asyncio.to_thread(fetch_bytes, v)
                    await msg.reply_photo(photo=data if data else v, caption=caption)

            success = True

    except Exception as e:
        log.error(f"Download error: {e}")
        success = False

    context.user_data.pop("await_site", None)

    if success:
        DB["stats"]["downloads"] = DB["stats"].get("downloads", 0) + 1
        save_db()
        try:
            await waiting.delete()
        except Exception:
            pass
        await msg.reply_text("✅ تم التحميل بنجاح!", reply_markup=after_download_kb(site))

        # إشعار المطور بالتحميل
        try:
            site_names = {"tiktok": "TikTok 🎵", "pinterest": "Pinterest 📌"}
            kind_names = {"video": "فيديو 🎬", "photos": "صور 🖼", "photo": "صورة 🖼"}
            uname = f"@{user.username}" if user.username else f"ID: {uid}"
            total_dl = DB["stats"].get("downloads", 0)
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"⬇️ *تحميل جديد!*\n"
                     f"━━━━━━━━━━━━━\n"
                     f"👤 الاسم: {user.first_name or 'بدون اسم'}\n"
                     f"🔗 الحساب: {uname}\n"
                     f"🆔 `{uid}`\n"
                     f"━━━━━━━━━━━━━\n"
                     f"📂 المنصة: {site_names.get(site, site)}\n"
                     f"🎞 النوع: {kind_names.get(dl_kind, dl_kind or '—')}\n"
                     f"📝 العنوان: {dl_title or '—'}\n"
                     f"━━━━━━━━━━━━━\n"
                     f"📊 إجمالي التحميلات: `{total_dl}`",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
    else:
        try:
            await waiting.edit_text(
                "❌ لم يتم التحميل\nحدث خطأ غير متوقع، حاول مرة أخرى.",
                reply_markup=retry_kb(site)
            )
        except Exception:
            pass

async def forward_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        return
    args = context.args
    if args and args[0].lower() == "off":
        DB["forward_msgs"] = False
        save_db()
        await update.message.reply_text("📨 تم إيقاف توجيه الرسائل.", reply_markup=admin_kb())
    elif args and args[0].lower() == "on":
        DB["forward_msgs"] = True
        save_db()
        await update.message.reply_text("📨 تم تشغيل توجيه الرسائل.", reply_markup=admin_kb())
    else:
        state = "✅ شغّال" if DB.get("forward_msgs", True) else "❌ موقوف"
        await update.message.reply_text(
            f"📨 حالة التوجيه: {state}\n\n"
            f"لتغييرها:\n`/forward on` — تشغيل\n`/forward off` — إيقاف",
            parse_mode=ParseMode.MARKDOWN
        )

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    user = update.effective_user
    uid  = user.id

    if not is_owner(uid):
        return

    if context.user_data.get("admin_action") == "changebanner":
        context.user_data.pop("admin_action")
        try:
            photo = msg.photo[-1]
            file  = await context.bot.get_file(photo.file_id)
            os.makedirs("assets", exist_ok=True)
            await file.download_to_drive("assets/welcome_banner.png")
            await msg.reply_text("✅ تم تحديث صورة الترحيب بنجاح!", reply_markup=admin_kb())
        except Exception as e:
            log.error(f"Banner update failed: {e}")
            await msg.reply_text("❌ فشل تحديث الصورة، حاول مرة أخرى.")

# ============ Main ============
def main():
    keep_alive()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("forward", forward_cmd))
    app.add_handler(CallbackQueryHandler(cbq_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, photo_handler))
    log.info("🚀 Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
