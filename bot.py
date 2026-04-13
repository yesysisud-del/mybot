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
