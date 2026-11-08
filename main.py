"""
Telegram 𝗫𝗘𝗡𝗢 𝗚𝗣𝗧 Bot — single-file build.

BEFORE RUNNING:
1. Create the bot with @BotFather and put the token in .env as BOT_TOKEN.
2. Add the bot as ADMINISTRATOR to ALL THREE force-join channels:
     -1002583286874  (𝗡𝗖𝗞 𝗗𝗘𝗩 ™)
     -1004384280494  (⧉ <𝗘𝗥𝗥𝗢𝗥/𝟰𝟬𝟰> ⧉)
     -1003637300526  (𝗡𝗖𝗞 𝗗𝗘𝗩 ™ 𝗦𝗢𝗨𝗥𝗖𝗘 𝗖𝗢𝗗𝗘𝗦 & 𝗔𝗣𝗜𝘀)
   Without admin rights in every channel, get_chat_member fails and every
   user is locked out.
3. VIP channel (-1003876174894) is NOT a gate — only its invite URL is used
   for the permanent subscribe button. Do not add it to CHANNELS.

FEATURES:
- Chat with memory of the recent conversation (HTML-formatted, Read Aloud,
  Copy, Regenerate, Like/Dislike)
- Image generation: prompt enhancement (any language -> detailed English
  prompt), model fallback chain, aspect-ratio control, real image bytes
  uploaded to Telegram, variations, original-quality download
- TTS (gTTS, non-blocking, auto language detection)
- Settings (language, clear history)
- On-demand file generation: PDF (CJK-capable), .py, .js, .html, .json, .txt

Run: python main.py
"""

# ─── 2. Imports ──────────────────────────────────────────────────────────────
import asyncio
import base64
import html
import io
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    CopyTextButton,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from g4f.client import AsyncClient
from gtts import gTTS

# ─── 3. Config (CHANNELS, VIP_CHANNEL, BOT_TOKEN) ───────────────────────────
load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "9105059305:AAESz6zxMY46zley2VMNiFvpneql-b5dPOc").strip()
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing.\n"
        "Create a .env file beside main.py and add:\n"
        "BOT_TOKEN=your_bot_token"
    )

CHANNELS = [
    {
        "id": -1002583286874,
        "url": "https://t.me/NCK_Dev",
        "title": "𝗡𝗖𝗞 𝗗𝗘𝗩 ™",
    },
    {
        "id": -1004384280494,
        "url": "https://t.me/ERRORX404E",
        "title": "⧉ <𝗘𝗥𝗥𝗢𝗥/𝟰𝟬𝟰> ⧉",
    },
    {
        "id": -1003637300526,
        "url": "https://t.me/NCKDEVFreeSC",
        "title": "𝗡𝗖𝗞 𝗗𝗘𝗩 ™ 𝗦𝗢𝗨𝗥𝗖𝗘 𝗖𝗢𝗗𝗘𝗦 & 𝗔𝗣𝗜𝘀",
    },
]

VIP_CHANNEL = {
    "id": -1003876174894,
    "url": "https://t.me/+e3NOnkwiah80ZmVk",
    "title": "VIP — Source Codes",
}

DB_PATH = Path(__file__).with_name("bot.db")
CACHE_TTL_SECONDS = 3600
CACHE_MAX_ENTRIES = 200
SUB_CACHE_TTL_SECONDS = 60
COPY_LIMIT = 256
HISTORY_LIMIT = 8
HISTORY_ITEM_MAX_CHARS = 2000
TELEGRAM_CHUNK = 3500
BOT_VERSION = "1.1.0"

# "" lets g4f pick its own default model as a last resort.
CHAT_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "llama-3.3-70b",
    "mistral-nemo",
    "gemini-1.5-flash",
    "",
]
CHAT_TIMEOUT = 45

# Tried in order until one returns a valid image.
IMAGE_MODELS = ["flux", "flux-dev", "dall-e-3", "sdxl-turbo"]
IMAGE_TOTAL_BUDGET = 170  # seconds for the whole fallback chain
IMAGE_CALL_TIMEOUT = 100

ASPECTS: Dict[str, Dict[str, str]] = {
    "square": {
        "size": "1024x1024",
        "hint": "square 1:1 composition",
        "label": "⬛ Square",
    },
    "portrait": {
        "size": "768x1024",
        "hint": "vertical portrait 3:4 composition",
        "label": "📱 Portrait",
    },
    "landscape": {
        "size": "1024x576",
        "hint": "wide landscape 16:9 composition",
        "label": "🖥 Landscape",
    },
}

CHAT_SYSTEM_PROMPT = """You are a professional AI assistant inside Telegram.

Response style:
- Be concise but complete. No filler, no "As an AI".
- Answer in the user's language.
- Structure long answers with short sections and blank lines between sections.

Formatting rules (Telegram HTML — follow exactly):
- Use <b>bold</b> for key terms, <i>italic</i> for emphasis.
- Use <code>inline code</code> for short snippets, variables, commands.
- Use <pre><code class="language-python">...</code></pre> for multi-line code.
- Use <blockquote>...</blockquote> for quotes or callouts.
- Use bullet lists with "• " at the start of each line.
- Keep paragraphs short (2-3 sentences). Separate sections with a blank line.
- Escape literal < > & inside text as &lt; &gt; &amp;.
- Do NOT use Markdown (**bold**, ## headers, ```code```). Output HTML only.
- Do NOT wrap the entire answer in a code block."""

FILE_SYSTEM_PROMPT = """You generate the raw contents of a single {ftype_name} file.

Rules:
- Output ONLY the file content. No explanations, no introduction, no closing
  remarks, no markdown fences, no HTML formatting tags unless the file itself
  is HTML.
- The content must be complete, valid and ready to save as-is.
{extra}"""

FILE_TYPE_NAMES = {
    "pdf": "PDF document (plain text with simple headings and paragraphs; no markup)",
    "py": "Python source",
    "js": "JavaScript source",
    "html": "complete HTML document (<!DOCTYPE html> with inline CSS)",
    "json": "JSON (strictly valid JSON)",
    "txt": "plain text",
}

IMAGE_ENHANCER_PROMPT = """You are an expert prompt engineer for text-to-image models (FLUX / DALL-E class).
Rewrite the user's request into ONE detailed English image prompt.

Rules:
- Translate to English if needed.
- Keep EVERY subject, object, count, color, action, setting, mood and style the
  user specified. Never drop, contradict or replace them. Never add new main
  subjects or characters.
- If the user wants specific text written in the image, keep it verbatim in
  double quotes.
- If the user gave no style, pick the most fitting one (photorealistic photo,
  digital illustration, 3D render, watercolor, anime, etc.).
- Add concrete visual detail: composition and camera angle, lens or medium,
  lighting, color palette, background, texture, atmosphere.
- Add quality cues: highly detailed, sharp focus, professional composition.
- For people: natural anatomy, detailed realistic faces and hands.
- 40-90 words, a single paragraph of comma-separated descriptive phrases.
- Output ONLY the prompt. No preface, no quotes around it, no markdown, no
  negative prompt."""

WELCOME_TEXT = "👋 Welcome to 𝗫𝗘𝗡𝗢 𝗚𝗣𝗧. Choose an option below:"
JOIN_TEXT = (
    "🔒 To use this bot, please join ALL of our channels first, "
    "then tap Verify."
)
ERROR_TEXT = "⚠️ AI is temporarily unavailable. Please try again in a moment."

# ─── 4. Logging setup ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("xeno_gpt_bot")
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)

# ─── 5. Database helpers ────────────────────────────────────────────────────
db: Optional[aiosqlite.Connection] = None


async def init_db() -> None:
    """Create the SQLite database and required tables."""
    global db
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            language TEXT DEFAULT 'en',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message_id INTEGER,
            rating TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_user ON history (user_id, id)"
    )
    await db.commit()


async def get_language(user_id: int) -> str:
    """Return a user's saved language preference, defaulting to English."""
    assert db is not None
    async with db.execute(
        "SELECT language FROM users WHERE user_id = ?",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return row["language"] if row else "en"


async def set_language(user_id: int, language: str) -> None:
    """Create or update a user's language preference."""
    assert db is not None
    await db.execute(
        """
        INSERT INTO users (user_id, language)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET language = excluded.language
        """,
        (user_id, language),
    )
    await db.commit()


async def add_history(user_id: int, role: str, content: str) -> None:
    """Store one chat message in the user's history."""
    assert db is not None
    await db.execute(
        "INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content),
    )
    await db.commit()


async def get_history(
    user_id: int,
    limit: int = HISTORY_LIMIT,
) -> List[Dict[str, str]]:
    """Return the user's most recent messages, oldest first."""
    assert db is not None
    async with db.execute(
        "SELECT role, content FROM history WHERE user_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()

    return [
        {
            "role": row["role"],
            "content": (row["content"] or "")[:HISTORY_ITEM_MAX_CHARS],
        }
        for row in reversed(rows)
    ]


async def clear_history(user_id: int) -> None:
    """Delete all stored chat history for a user."""
    assert db is not None
    await db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    await db.commit()


async def save_feedback(
    user_id: int,
    message_id: int,
    rating: str,
) -> None:
    """Save a like/dislike rating for an AI response."""
    assert db is not None
    await db.execute(
        "INSERT INTO feedback (user_id, message_id, rating) VALUES (?, ?, ?)",
        (user_id, message_id, rating),
    )
    await db.commit()


# ─── 6. TTL cache ───────────────────────────────────────────────────────────
ttl_cache: Dict[str, Tuple[float, Any]] = {}


def cleanup_cache() -> None:
    """Remove expired entries and cap the cache size."""
    now = time.time()
    for key in list(ttl_cache):
        if ttl_cache[key][0] < now:
            ttl_cache.pop(key, None)

    overflow = len(ttl_cache) - CACHE_MAX_ENTRIES
    if overflow > 0:
        oldest = sorted(ttl_cache, key=lambda k: ttl_cache[k][0])[:overflow]
        for key in oldest:
            ttl_cache.pop(key, None)


def cache_put(value: Any) -> str:
    """Store any value for one hour and return its short cache key."""
    key = uuid.uuid4().hex[:12]
    ttl_cache[key] = (time.time() + CACHE_TTL_SECONDS, value)
    cleanup_cache()
    return key


def cache_get(key: str) -> Optional[Any]:
    """Return a cached value if it exists and has not expired."""
    entry = ttl_cache.get(key)
    if not entry:
        return None

    expires_at, value = entry
    if expires_at < time.time():
        ttl_cache.pop(key, None)
        return None

    return value


# ─── 7. CallbackData factories ──────────────────────────────────────────────
class MenuCB(CallbackData, prefix="menu"):
    """Main-menu callback data."""

    action: str


class ActionCB(CallbackData, prefix="act"):
    """Result-action callback data (chat replies and images)."""

    action: str
    ref: str


# ─── 8. FSM states ──────────────────────────────────────────────────────────
class Chat(StatesGroup):
    waiting_for_message = State()


class Image(StatesGroup):
    waiting_for_prompt = State()


class TTS(StatesGroup):
    waiting_for_text = State()


# ─── 9. Keyboard builders (every builder ends with add_vip_row) ─────────────
def add_vip_row(builder: InlineKeyboardBuilder) -> None:
    """Append the VIP subscribe button as the last row of any keyboard."""
    builder.row(
        InlineKeyboardButton(
            text="⭐ Subscribe to VIP — Get Source Codes",
            url=VIP_CHANNEL["url"],
        )
    )


def join_channels_kb() -> InlineKeyboardMarkup:
    """Build the mandatory force-join keyboard, ending with the VIP row."""
    builder = InlineKeyboardBuilder()

    for channel in CHANNELS:
        builder.row(
            InlineKeyboardButton(
                text=f"📢 {channel['title']}",
                url=channel["url"],
            )
        )

    builder.row(
        InlineKeyboardButton(
            text="✅ Verify Subscription",
            callback_data="verify_sub",
        )
    )

    add_vip_row(builder)
    return builder.as_markup()


def main_menu_kb() -> InlineKeyboardMarkup:
    """Build the main menu keyboard, ending with the VIP row."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Chat", callback_data=MenuCB(action="chat"))
    builder.button(text="🎨 Image", callback_data=MenuCB(action="image"))
    builder.button(text="🔊 TTS", callback_data=MenuCB(action="tts"))
    builder.button(text="⚙️ Settings", callback_data=MenuCB(action="settings"))
    builder.button(text="ℹ️ About", callback_data=MenuCB(action="about"))
    builder.adjust(2, 2, 1)

    add_vip_row(builder)
    return builder.as_markup()


def back_menu_kb() -> InlineKeyboardMarkup:
    """Build a simple Back-to-Menu keyboard, ending with the VIP row."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Back to Menu",
        callback_data=MenuCB(action="back"),
    )

    add_vip_row(builder)
    return builder.as_markup()


def settings_kb(current_language: str) -> InlineKeyboardMarkup:
    """Build the Settings keyboard, ending with the VIP row."""
    language_label = "English" if current_language == "en" else "中文"

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🌐 Language: {language_label}",
        callback_data="toggle_language",
    )
    builder.button(
        text="🧹 Clear History",
        callback_data="clear_history",
    )
    builder.button(
        text="⬅️ Back to Menu",
        callback_data=MenuCB(action="back"),
    )
    builder.adjust(1)

    add_vip_row(builder)
    return builder.as_markup()


def build_reply_keyboard(plain_reply: str, ref_key: str) -> InlineKeyboardMarkup:
    """Build response actions for a normal chat reply, ending with VIP row."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔊 Read Aloud",
        callback_data=ActionCB(action="speak", ref=ref_key),
    )
    builder.button(
        text="🔄 Regenerate",
        callback_data=ActionCB(action="regen", ref=ref_key),
    )

    if plain_reply and len(plain_reply) <= COPY_LIMIT:
        builder.add(
            InlineKeyboardButton(
                text="📋 Copy",
                copy_text=CopyTextButton(text=plain_reply),
            )
        )
    else:
        builder.button(
            text="📋 Copy (as message)",
            callback_data=ActionCB(action="copy", ref=ref_key),
        )

    builder.button(
        text="👍 Like",
        callback_data=ActionCB(action="like", ref=ref_key),
    )
    builder.button(
        text="👎 Dislike",
        callback_data=ActionCB(action="dislike", ref=ref_key),
    )
    builder.button(
        text="⬅️ Back to Menu",
        callback_data=MenuCB(action="back"),
    )

    builder.adjust(2, 1, 2, 1)
    add_vip_row(builder)
    return builder.as_markup()


def retry_kb() -> InlineKeyboardMarkup:
    """Build a retry keyboard, ending with the VIP row."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 Retry",
        callback_data="retry_ai",
    )
    builder.button(
        text="⬅️ Back to Menu",
        callback_data=MenuCB(action="back"),
    )
    builder.adjust(2)

    add_vip_row(builder)
    return builder.as_markup()


def image_result_kb(ref: str, aspect: str) -> InlineKeyboardMarkup:
    """Build the image-result keyboard, ending with the VIP row."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 New variation",
        callback_data=ActionCB(action="imgregen", ref=ref),
    )
    builder.button(
        text="📥 Original quality",
        callback_data=ActionCB(action="imgfile", ref=ref),
    )

    for key, spec in ASPECTS.items():
        mark = "✅ " if key == aspect else ""
        builder.button(
            text=f"{mark}{spec['label']}",
            callback_data=ActionCB(action=f"ar_{key}", ref=ref),
        )

    builder.button(
        text="📝 Show prompt",
        callback_data=ActionCB(action="imgprompt", ref=ref),
    )
    builder.button(
        text="⬅️ Back to Menu",
        callback_data=MenuCB(action="back"),
    )
    builder.adjust(2, 3, 1, 1)

    add_vip_row(builder)
    return builder.as_markup()


def image_retry_kb(ref: str) -> InlineKeyboardMarkup:
    """Build the image-failure keyboard, ending with the VIP row."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 Try again",
        callback_data=ActionCB(action="imgregen", ref=ref),
    )
    builder.button(
        text="⬅️ Back to Menu",
        callback_data=MenuCB(action="back"),
    )
    builder.adjust(2)

    add_vip_row(builder)
    return builder.as_markup()


def tts_result_kb() -> InlineKeyboardMarkup:
    """Build the TTS-result keyboard, ending with the VIP row."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Back to Menu",
        callback_data=MenuCB(action="back"),
    )

    add_vip_row(builder)
    return builder.as_markup()


def file_sent_kb() -> InlineKeyboardMarkup:
    """Build the keyboard shown after a generated file, ending with VIP row."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Back to Menu",
        callback_data=MenuCB(action="back"),
    )

    add_vip_row(builder)
    return builder.as_markup()


# ─── 10. Text helpers (HTML sanitising, splitting) ──────────────────────────
ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "a", "blockquote", "tg-spoiler",
}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s[^<>]*)?)/?>")
_FENCE_RE = re.compile(r"```([\w+-]*)\n?(.*?)```", re.S)


def strip_html(text: str) -> str:
    """Convert (Telegram) HTML into readable plain text."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(
        r"</(p|div|li|h[1-6]|pre|blockquote)>",
        "\n",
        text,
        flags=re.I,
    )
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _fence_sub(match: "re.Match[str]") -> str:
    lang = match.group(1)
    code = html.escape(html.unescape(match.group(2).strip("\n")))
    cls = f' class="language-{lang}"' if lang else ""
    return f"<pre><code{cls}>{code}</code></pre>"


def markdown_to_html(text: str) -> str:
    """Convert stray Markdown from the model into Telegram HTML."""
    text = _FENCE_RE.sub(_fence_sub, text)
    parts = re.split(r"(<pre>.*?</pre>)", text, flags=re.S)

    for i, part in enumerate(parts):
        if i % 2 == 1:  # inside <pre>, leave untouched
            continue

        part = re.sub(
            r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$",
            r"<b>\1</b>",
            part,
            flags=re.M,
        )
        part = re.sub(r"^\s*[-*]\s+", "• ", part, flags=re.M)
        part = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", part, flags=re.S)
        part = re.sub(
            r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])",
            r"<i>\1</i>",
            part,
        )
        part = re.sub(
            r"`([^`\n]+)`",
            lambda m: "<code>"
            + html.escape(html.unescape(m.group(1)))
            + "</code>",
            part,
        )
        parts[i] = part

    return "".join(parts)


def sanitize_html(text: str) -> str:
    """Make model HTML safe for Telegram: drop unsupported tags, balance tags."""
    text = re.sub(r"<(?![/a-zA-Z])", "&lt;", text)
    text = re.sub(
        r"&(?!(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);)",
        "&amp;",
        text,
    )
    stack: List[str] = []

    def repl(match: "re.Match[str]") -> str:
        closing = match.group(1) == "/"
        name = match.group(2).lower()
        attrs = match.group(3) or ""
        extra_after = ""

        if name == "br":
            return "\n"
        if name in ("p", "div", "ul", "ol", "table", "tr", "section"):
            return "\n" if closing else ""
        if name == "li":
            return "\n" if closing else "• "
        if re.fullmatch(r"h[1-6]", name):
            name = "b"
            if closing:
                extra_after = "\n"

        if name not in ALLOWED_TAGS:
            return ""

        if closing:
            if name not in stack:
                return ""
            out = ""
            while stack:
                top = stack.pop()
                out += f"</{top}>"
                if top == name:
                    break
            return out + extra_after

        attr_out = ""
        if name == "a":
            href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs)
            if not href:
                return ""
            attr_out = f' href="{href.group(1)}"'
        elif name == "code":
            cls = re.search(
                r'class\s*=\s*["\'](language-[\w+-]+)["\']',
                attrs,
            )
            if cls:
                attr_out = f' class="{cls.group(1)}"'

        stack.append(name)
        return f"<{name}{attr_out}>"

    text = _TAG_RE.sub(repl, text)
    while stack:
        text += f"</{stack.pop()}>"
    return text.strip()


def split_message(text: str, limit: int = TELEGRAM_CHUNK) -> List[str]:
    """Split long text on paragraph/line boundaries to fit Telegram limits."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""

    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = limit
            chunks.append(para[:cut])
            para = para[cut:].lstrip("\n")

        current = para

    if current:
        chunks.append(current)

    return chunks


async def edit_or_answer(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Edit a message in place, or send a new one if editing is impossible."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        await message.answer(text, reply_markup=reply_markup)


# ─── 11. Subscription check + middleware ────────────────────────────────────
_sub_cache: Dict[int, float] = {}


async def _is_member(bot: Bot, channel: Dict[str, Any], user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel["id"], user_id)
    except Exception as exc:
        logger.error(
            "Subscription check failed for channel %s: %s "
            "(is the bot an ADMIN there?)",
            channel["id"],
            exc,
        )
        return False

    if member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    ):
        return True

    # A restricted user who is still in the channel counts as a member.
    return member.status == ChatMemberStatus.RESTRICTED and bool(
        getattr(member, "is_member", False)
    )


async def is_subscribed(bot: Bot, user_id: int, use_cache: bool = True) -> bool:
    """Check membership in every required force-join channel."""
    now = time.time()

    if use_cache and _sub_cache.get(user_id, 0) > now:
        return True

    results = await asyncio.gather(
        *(_is_member(bot, channel, user_id) for channel in CHANNELS)
    )

    if all(results):
        if len(_sub_cache) > 5000:
            _sub_cache.clear()
        _sub_cache[user_id] = now + SUB_CACHE_TTL_SECONDS
        return True

    _sub_cache.pop(user_id, None)
    return False


class SubscriptionMiddleware(BaseMiddleware):
    """Gate every message and callback behind force-join membership.

    Exempt: /start (it shows the join screen itself) and the verify button.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def __call__(self, handler, event, data):  # type: ignore[override]
        user = data.get("event_from_user") or getattr(event, "from_user", None)

        if user is None or user.is_bot:
            return await handler(event, data)

        if isinstance(event, Message):
            if event.chat.type != "private":
                return await handler(event, data)
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            if event.data == "verify_sub":
                return await handler(event, data)

        if await is_subscribed(self.bot, user.id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(
                "Please join all channels first.",
                show_alert=True,
            )
            if event.message:
                await edit_or_answer(
                    event.message,
                    JOIN_TEXT,
                    join_channels_kb(),
                )
        elif isinstance(event, Message):
            await event.answer(JOIN_TEXT, reply_markup=join_channels_kb())

        return None


# ─── 12. File generation helpers ────────────────────────────────────────────
_NA = r"(?<![a-z0-9])"
_NZ = r"(?![a-z0-9])"

FILE_INTENT_RE = re.compile(
    r"\b(generate|create|make|write|give|send|export|save|produce|build|"
    r"convert|download|provide|prepare|draft)\b"
    r"|\b(as|in|into)\s+(an?\s+)?(pdf|python|javascript|html|json|text|txt)\b"
    r"|生成|创建|制作|导出|写一个|发给我|给我"
)

FILE_TYPE_PATTERNS = [
    ("pdf", re.compile(_NA + r"pdf" + _NZ)),
    ("json", re.compile(r"\bjson (file|document)\b|\.json" + _NZ)),
    ("html", re.compile(r"\bhtml (file|page|document)\b|\.html?" + _NZ)),
    ("py", re.compile(r"\bpython (file|script)\b|\.py" + _NZ)),
    (
        "js",
        re.compile(
            r"\b(javascript|js) (file|script)\b|(?<!node)\.js" + _NZ
        ),
    ),
    ("txt", re.compile(r"\b(text|txt) file\b|\.txt" + _NZ)),
]


def detect_file_request(user_text: str) -> Optional[str]:
    """Detect explicit file-generation requests and return the file type."""
    t = user_text.lower()

    if not FILE_INTENT_RE.search(t):
        return None

    for ftype, pattern in FILE_TYPE_PATTERNS:
        if pattern.search(t):
            return ftype

    return None


def _pdf_wrap(line: str, font: str, size: float, max_width: float) -> List[str]:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if not line:
        return [""]

    lines: List[str] = []
    current = ""

    for ch in line:
        current += ch
        if stringWidth(current, font, size) <= max_width:
            continue

        space = current.rfind(" ")
        if space > 0:
            lines.append(current[:space].rstrip())
            current = current[space + 1 :]
        else:
            lines.append(current[:-1])
            current = ch

    if current:
        lines.append(current)

    return lines


def make_pdf(text: str) -> bytes:
    """Create an A4 PDF from plain text (wraps lines, supports CJK)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    text = text.replace("\t", "    ")
    font = "Helvetica"

    if any(ord(ch) > 255 for ch in text):
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            font = "STSong-Light"
        except Exception:
            logger.warning("CJK font unavailable; falling back to Latin-1")
            text = text.encode("latin-1", "replace").decode("latin-1")

    size = 11
    leading = 15
    margin = 50

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    max_width = width - 2 * margin
    y = height - margin

    c.setFont(font, size)

    for raw_line in text.split("\n"):
        for chunk in _pdf_wrap(raw_line, font, size, max_width):
            if y < margin:
                c.showPage()
                c.setFont(font, size)
                y = height - margin

            c.drawString(margin, y, chunk)
            y -= leading

    c.save()
    return buf.getvalue()


def clean_file_content(ai_reply: str) -> str:
    """Remove markdown fences and common introductory lines from AI output."""
    text = ai_reply.strip()

    fenced = re.search(r"```[\w+-]*\n(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)

    text = re.sub(
        r"^(here is|here's)[^\n]*:\s*\n",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    return text.strip()


def prepare_file_content(ai_reply: str, ftype: str) -> str:
    """Clean model output and normalise it for the requested file type."""
    content = clean_file_content(ai_reply)

    if ftype == "pdf":
        content = strip_html(content)
        content = re.sub(r"\*\*|__", "", content)
        content = re.sub(r"^#{1,6}\s*", "", content, flags=re.M)
    elif ftype == "json":
        try:
            content = json.dumps(
                json.loads(content),
                indent=2,
                ensure_ascii=False,
            )
        except ValueError:
            pass

    return content


def make_file(content: str, ftype: str) -> BufferedInputFile:
    """Turn generated content into a Telegram uploadable file."""
    if ftype == "pdf":
        return BufferedInputFile(
            make_pdf(content),
            filename="response.pdf",
        )

    return BufferedInputFile(
        content.encode("utf-8"),
        filename=f"response.{ftype}",
    )


def is_migration_notice(text: str) -> bool:
    """Detect Microsoft Copilot migration notices returned by a provider."""
    markers = (
        "Copilot moved to a new app",
        "Install the new Copilot app",
        "Copilot history and content will be deleted",
        "unifiedlink.svc.cloud.microsoft",
        "migration_chatblock",
    )

    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


# ─── 13. Handlers: /start ───────────────────────────────────────────────────
router = Router()


@router.message(CommandStart())
async def start_command(
    message: Message,
    bot: Bot,
    state: FSMContext,
) -> None:
    """Show either the force-join keyboard or the main menu."""
    if not message.from_user:
        return

    await state.clear()

    if not await is_subscribed(bot, message.from_user.id):
        await message.answer(JOIN_TEXT, reply_markup=join_channels_kb())
        return

    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


# ─── 14. Handlers: verify_sub callback ──────────────────────────────────────
@router.callback_query(F.data == "verify_sub")
async def verify_subscription(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
) -> None:
    """Recheck all required channels and unlock the main menu if complete."""
    if not callback.from_user or not callback.message:
        await callback.answer("Unable to verify subscription.")
        return

    if await is_subscribed(bot, callback.from_user.id, use_cache=False):
        await state.clear()
        await edit_or_answer(
            callback.message,
            f"✅ Verified! Welcome.\n\n{WELCOME_TEXT}",
            main_menu_kb(),
        )
        await callback.answer("Subscription verified!")
        return

    await callback.answer(
        "You still need to join all three channels.",
        show_alert=True,
    )


# ─── 15. Handlers: main menu callbacks ──────────────────────────────────────
@router.callback_query(MenuCB.filter(F.action == "back"))
async def back_to_menu(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Return the user to the main menu."""
    await state.clear()

    if callback.message:
        await edit_or_answer(callback.message, WELCOME_TEXT, main_menu_kb())

    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "chat"))
async def open_chat(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start the Chat feature."""
    await state.set_state(Chat.waiting_for_message)

    if callback.message:
        await edit_or_answer(
            callback.message,
            "💬 Send me your message.\n\n"
            "Tip: ask for a file, e.g. “make a PDF about…”.",
            back_menu_kb(),
        )

    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "image"))
async def open_image(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start the Image feature."""
    await state.set_state(Image.waiting_for_prompt)

    if callback.message:
        await edit_or_answer(
            callback.message,
            "🎨 Describe the image you want — in any language.\n\n"
            "The more detail you give (subject, style, mood, colors), the "
            "closer the result. I'll turn it into an optimized prompt "
            "automatically.",
            back_menu_kb(),
        )

    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "tts"))
async def open_tts(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start the Text-to-Speech feature."""
    await state.set_state(TTS.waiting_for_text)

    if callback.message:
        await edit_or_answer(
            callback.message,
            "🔊 Send the text you want me to read aloud.",
            back_menu_kb(),
        )

    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "settings"))
async def open_settings(callback: CallbackQuery) -> None:
    """Show the Settings menu."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    language = await get_language(callback.from_user.id)
    await edit_or_answer(
        callback.message,
        "⚙️ Settings\n\nChoose an option:",
        settings_kb(language),
    )
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "about"))
async def open_about(callback: CallbackQuery) -> None:
    """Show bot information and available features."""
    about_text = (
        f"<b>𝗫𝗘𝗡𝗢 𝗚𝗣𝗧</b> v{BOT_VERSION}\n\n"
        "Features:\n"
        "• 💬 AI chat with memory and HTML formatting\n"
        "• 🎨 AI image generation with prompt enhancement\n"
        "• 🔊 Text-to-speech\n"
        "• 📄 On-demand PDF and code/text files\n"
        "• ⚙️ Language preference and history clearing\n\n"
        "Built with aiogram 3.x, g4f, gTTS and SQLite."
    )

    if callback.message:
        await edit_or_answer(callback.message, about_text, back_menu_kb())

    await callback.answer()


@router.callback_query(F.data == "toggle_language")
async def toggle_language(callback: CallbackQuery) -> None:
    """Toggle the user's language preference between English and Chinese."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    current = await get_language(callback.from_user.id)
    new_language = "zh" if current == "en" else "en"
    await set_language(callback.from_user.id, new_language)
    label = "English" if new_language == "en" else "中文"

    await edit_or_answer(
        callback.message,
        "⚙️ Settings\n\nChoose an option:",
        settings_kb(new_language),
    )
    await callback.answer(f"Language: {label}")


@router.callback_query(F.data == "clear_history")
async def clear_history_callback(callback: CallbackQuery) -> None:
    """Clear the user's stored chat history."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    await clear_history(callback.from_user.id)
    await callback.answer("History cleared.")
    await edit_or_answer(
        callback.message,
        "🧹 Chat history cleared.",
        settings_kb(await get_language(callback.from_user.id)),
    )


# ─── 16. Handlers: Chat feature ─────────────────────────────────────────────
async def generate_chat_reply(
    user_text: str,
    language: str,
    file_type: Optional[str],
    context: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Call g4f with model fallbacks and return a valid generated response."""
    if file_type:
        extra = ""
        if file_type == "pdf":
            extra = (
                "- Use plain text only: short headings on their own line, "
                "blank lines between paragraphs, '- ' for bullet points.\n"
            )
        elif file_type == "json":
            extra = "- Output must parse with a strict JSON parser.\n"

        system_prompt = FILE_SYSTEM_PROMPT.format(
            ftype_name=FILE_TYPE_NAMES[file_type],
            extra=extra,
        )
        history: List[Dict[str, str]] = []
    else:
        system_prompt = CHAT_SYSTEM_PROMPT
        if language == "zh":
            system_prompt += "\n\nRespond in Simplified Chinese."
        else:
            system_prompt += (
                "\n\nDefault to English unless the user writes in another "
                "language, then reply in that language."
            )
        history = context or []

    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_text},
    ]

    client = AsyncClient()
    last_error: Optional[Exception] = None

    for model in CHAT_MODELS:
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                ),
                timeout=CHAT_TIMEOUT,
            )

            ai_reply = response.choices[0].message.content or ""

            if not ai_reply.strip():
                raise ValueError("Empty response")

            if is_migration_notice(ai_reply):
                raise ValueError(
                    "Provider returned a Copilot migration notice"
                )

            return ai_reply

        except Exception as exc:
            last_error = exc
            logger.warning("g4f model %r failed: %s", model, exc)

    raise RuntimeError(f"All g4f chat models failed: {last_error}")


async def send_chat_reply(
    message: Message,
    ai_reply: str,
    ref_key: str,
) -> None:
    """Send an AI reply (split if long) with a plain-text fallback."""
    plain = strip_html(ai_reply)
    keyboard = build_reply_keyboard(plain, ref_key)

    chunks = [
        sanitize_html(chunk)
        for chunk in split_message(markdown_to_html(ai_reply))
    ]
    chunks = [chunk for chunk in chunks if chunk.strip()] or [plain or "…"]

    for index, chunk in enumerate(chunks):
        markup = keyboard if index == len(chunks) - 1 else None

        try:
            await message.answer(
                chunk,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            logger.warning("HTML parse fallback: %s", exc)
            await message.answer(
                strip_html(chunk) or "…",
                parse_mode=None,
                reply_markup=markup,
            )


async def deliver_reply(
    message: Message,
    user_id: int,
    prompt: str,
    ai_reply: str,
    file_type: Optional[str],
    context: List[Dict[str, str]],
    save_history: bool,
) -> None:
    """Send either a requested file or a formatted chat reply."""
    if file_type:
        try:
            content = prepare_file_content(ai_reply, file_type)
            file = make_file(content, file_type)
            await message.answer_document(file)
        except Exception:
            logger.exception("File generation failed")
            await message.answer(
                "⚠️ Could not generate PDF. Try again."
                if file_type == "pdf"
                else "⚠️ Could not generate file. Try again.",
                reply_markup=retry_kb(),
            )
            return

        await message.answer("✅ File sent.", reply_markup=file_sent_kb())

        if save_history:
            await add_history(user_id, "user", prompt)
            await add_history(
                user_id,
                "assistant",
                f"[Sent a .{file_type} file for this request]",
            )
        return

    ref_key = cache_put(
        {
            "prompt": prompt,
            "reply": ai_reply,
            "context": context,
            "file_type": None,
        }
    )

    if save_history:
        await add_history(user_id, "user", prompt)
        await add_history(user_id, "assistant", ai_reply)

    await send_chat_reply(message, ai_reply, ref_key)


@router.message(Chat.waiting_for_message, F.text)
async def handle_chat_message(
    message: Message,
    bot: Bot,
) -> None:
    """Generate a chat response or an on-demand requested file."""
    if not message.from_user or not message.text:
        return

    user_id = message.from_user.id
    user_text = message.text[:4000]
    file_type = detect_file_request(user_text)

    try:
        language = await get_language(user_id)
        context = [] if file_type else await get_history(user_id)

        await bot.send_chat_action(
            message.chat.id,
            "upload_document" if file_type else "typing",
        )

        ai_reply = await generate_chat_reply(
            user_text,
            language,
            file_type,
            context,
        )
    except Exception:
        logger.exception("g4f chat request failed")
        await message.answer(ERROR_TEXT, reply_markup=retry_kb())
        return

    await deliver_reply(
        message,
        user_id,
        user_text,
        ai_reply,
        file_type,
        context,
        save_history=True,
    )


@router.callback_query(ActionCB.filter(F.action == "regen"))
async def regenerate_reply(
    callback: CallbackQuery,
    callback_data: ActionCB,
) -> None:
    """Regenerate an AI response from the ORIGINAL user prompt."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    entry = cache_get(callback_data.ref)

    if not entry:
        await callback.answer(
            "Expired. Please send your message again.",
            show_alert=True,
        )
        return

    await callback.answer("Regenerating…")

    prompt: str = entry["prompt"]
    context: List[Dict[str, str]] = entry.get("context", [])
    file_type = detect_file_request(prompt)
    language = await get_language(callback.from_user.id)

    try:
        ai_reply = await generate_chat_reply(
            prompt,
            language,
            file_type,
            context,
        )
    except Exception:
        logger.exception("Regeneration failed")
        await callback.message.answer(ERROR_TEXT, reply_markup=retry_kb())
        return

    await deliver_reply(
        callback.message,
        callback.from_user.id,
        prompt,
        ai_reply,
        file_type,
        context,
        save_history=False,
    )


@router.callback_query(ActionCB.filter(F.action == "copy"))
async def copy_long_reply(
    callback: CallbackQuery,
    callback_data: ActionCB,
) -> None:
    """Send a long AI response as code messages for easy copying."""
    entry = cache_get(callback_data.ref)

    if not callback.message:
        await callback.answer()
        return

    if not entry:
        await callback.answer(
            "Expired. Please regenerate.",
            show_alert=True,
        )
        return

    plain = strip_html(entry["reply"])

    for chunk in split_message(plain, 3500):
        await callback.message.answer(
            f"<code>{html.escape(chunk)}</code>"
        )

    await callback.answer("Long-press the message above to copy.")


@router.callback_query(ActionCB.filter(F.action == "like"))
async def like_reply(callback: CallbackQuery) -> None:
    """Save a positive feedback rating."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    await save_feedback(
        callback.from_user.id,
        callback.message.message_id,
        "like",
    )
    await callback.answer("Thanks for your feedback!")


@router.callback_query(ActionCB.filter(F.action == "dislike"))
async def dislike_reply(callback: CallbackQuery) -> None:
    """Save a negative feedback rating."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    await save_feedback(
        callback.from_user.id,
        callback.message.message_id,
        "dislike",
    )
    await callback.answer("Thanks for your feedback!")


@router.callback_query(F.data == "retry_ai")
async def retry_ai(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Return the user to the Chat prompt after an AI error."""
    await state.set_state(Chat.waiting_for_message)

    if callback.message:
        await edit_or_answer(
            callback.message,
            "💬 Send me your message.",
            back_menu_kb(),
        )

    await callback.answer()


# ─── 17. TTS helpers + handlers ─────────────────────────────────────────────
def pick_tts_lang(text: str, language: str) -> str:
    """Pick a gTTS language: detect Chinese text, else use the setting."""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in text if ch.isalpha()) or 1

    if cjk / letters > 0.3:
        return "zh-CN"

    return "zh-CN" if language == "zh" else "en"


def _tts_sync(text: str, lang: str) -> bytes:
    buf = io.BytesIO()
    gTTS(text=text, lang=lang).write_to_fp(buf)
    return buf.getvalue()


async def send_speech(
    message: Message,
    user_id: int,
    raw_text: str,
) -> None:
    """Synthesize speech off the event loop and send it as audio."""
    text = strip_html(raw_text)[:4500]

    if not text:
        await message.answer(
            "⚠️ There is no text to read aloud.",
            reply_markup=tts_result_kb(),
        )
        return

    try:
        language = await get_language(user_id)
        lang = pick_tts_lang(text, language)
        data = await asyncio.wait_for(
            asyncio.to_thread(_tts_sync, text, lang),
            timeout=90,
        )
        await message.answer_audio(
            BufferedInputFile(data, filename="speech.mp3"),
            title="𝗫𝗘𝗡𝗢 𝗚𝗣𝗧",
            reply_markup=tts_result_kb(),
        )
    except Exception:
        logger.exception("TTS generation failed")
        await message.answer(
            "⚠️ Could not generate audio. Try again.",
            reply_markup=retry_kb(),
        )


@router.callback_query(ActionCB.filter(F.action == "speak"))
async def speak_reply(
    callback: CallbackQuery,
    callback_data: ActionCB,
) -> None:
    """Convert an AI response into speech and send it as audio."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    entry = cache_get(callback_data.ref)

    if not entry:
        await callback.answer(
            "Expired. Please regenerate.",
            show_alert=True,
        )
        return

    await callback.answer("Generating audio…")
    await callback.message.bot.send_chat_action(
        callback.message.chat.id,
        "record_voice",
    )
    await send_speech(callback.message, callback.from_user.id, entry["reply"])


@router.message(TTS.waiting_for_text, F.text)
async def handle_tts_text(message: Message) -> None:
    """Generate and send speech audio for user-provided text."""
    if not message.from_user or not message.text:
        return

    await message.bot.send_chat_action(message.chat.id, "record_voice")
    await send_speech(message, message.from_user.id, message.text)


# ─── 18. Image generation pipeline ──────────────────────────────────────────
busy_users: set = set()

_PORTRAIT_RE = re.compile(
    r"\b(portrait|vertical|phone wallpaper|mobile wallpaper|poster|"
    r"full[- ]body|full length|story|tall)\b|竖"
)
_LANDSCAPE_RE = re.compile(
    r"\b(landscape|wide|panorama|panoramic|banner|desktop wallpaper|"
    r"cinematic|widescreen|scenery|skyline|horizon)\b|横|风景"
)


def detect_aspect(prompt: str) -> str:
    """Guess the best aspect ratio from the user's wording."""
    t = prompt.lower()

    if _PORTRAIT_RE.search(t):
        return "portrait"
    if _LANDSCAPE_RE.search(t):
        return "landscape"

    return "square"


def image_ext(data: bytes) -> str:
    """Return a file extension from image magic bytes."""
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:3] == b"GIF":
        return "gif"
    return ""


async def enhance_image_prompt(user_prompt: str) -> str:
    """Rewrite the user's idea into a detailed English prompt (safe fallback)."""
    cleaned = user_prompt.strip()

    # Already very detailed: don't risk altering the user's intent.
    if len(cleaned.split()) >= 60 or len(cleaned) > 700:
        return cleaned

    client = AsyncClient()

    for model in CHAT_MODELS[:3]:
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": IMAGE_ENHANCER_PROMPT},
                        {"role": "user", "content": cleaned},
                    ],
                ),
                timeout=25,
            )
            text = (response.choices[0].message.content or "").strip()
            text = text.strip("`\"' \n")

            if (
                not text
                or is_migration_notice(text)
                or len(text) > 1200
                or len(text) < len(cleaned) // 2
            ):
                raise ValueError("Unusable enhancement")

            return text

        except Exception as exc:
            logger.warning("Prompt enhancement via %r failed: %s", model, exc)

    return cleaned


async def _download_image(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Unsupported image URL: {url[:80]}")

    timeout = aiohttp.ClientTimeout(total=60)
    headers = {"User-Agent": "Mozilla/5.0 (XenoGPT)"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as http:
        async with http.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


async def _extract_image_bytes(response: Any) -> bytes:
    item = response.data[0]

    b64 = getattr(item, "b64_json", None)
    if b64:
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        data = base64.b64decode(b64)
    else:
        url = getattr(item, "url", None)
        if not url:
            raise ValueError("Provider returned no image")
        data = await _download_image(url)

    if len(data) < 2000 or not image_ext(data):
        raise ValueError("Provider returned invalid image data")

    return data


async def generate_image(prompt: str, aspect: str) -> Tuple[bytes, str]:
    """Generate an image, trying every model and response format in turn."""
    spec = ASPECTS[aspect]
    full_prompt = f"{prompt}, {spec['hint']}"
    client = AsyncClient()
    deadline = time.time() + IMAGE_TOTAL_BUDGET
    last_error: Optional[Exception] = None

    async def call(model: str, fmt: str, use_size: bool) -> bytes:
        kwargs: Dict[str, Any] = {
            "model": model,
            "prompt": full_prompt,
            "response_format": fmt,
        }
        if use_size and aspect != "square":
            kwargs["size"] = spec["size"]

        remaining = max(10.0, min(IMAGE_CALL_TIMEOUT, deadline - time.time()))
        response = await asyncio.wait_for(
            client.images.generate(**kwargs),
            timeout=remaining,
        )
        return await _extract_image_bytes(response)

    for model in IMAGE_MODELS:
        for fmt in ("b64_json", "url"):
            if time.time() >= deadline:
                break

            try:
                try:
                    return await call(model, fmt, True), model
                except TypeError:
                    # Provider does not accept `size`; retry without it.
                    return await call(model, fmt, False), model
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Image model %s (%s) failed: %s",
                    model,
                    fmt,
                    exc,
                )

    raise RuntimeError(f"All image models failed: {last_error}")


async def safe_edit(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Edit a status message, ignoring Telegram edit errors."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        pass


async def run_image_job(
    target: Message,
    user_id: int,
    prompt: str,
    aspect: str,
    enhanced: Optional[str] = None,
) -> None:
    """Enhance the prompt, generate the image, and send it with controls."""
    if user_id in busy_users:
        await target.answer(
            "⏳ Still working on your previous image. Please wait a moment."
        )
        return

    busy_users.add(user_id)
    status = await target.answer("🎨 Preparing your image…")

    try:
        await target.bot.send_chat_action(target.chat.id, "upload_photo")

        if enhanced is None:
            enhanced = await enhance_image_prompt(prompt)

        await safe_edit(
            status,
            "🎨 Generating your image… this can take up to a minute.",
        )

        image, model = await generate_image(enhanced, aspect)
        logger.info("Image generated with %s (%d bytes)", model, len(image))

        ref = cache_put(
            {
                "prompt": prompt,
                "enhanced": enhanced,
                "aspect": aspect,
                "image": image,
            }
        )

        short = prompt if len(prompt) <= 180 else prompt[:177] + "…"
        caption = f"🖼 <i>{html.escape(short)}</i>"
        file = BufferedInputFile(image, filename=f"image.{image_ext(image)}")
        keyboard = image_result_kb(ref, aspect)

        sent = False
        if len(image) <= 9_500_000:
            try:
                await target.answer_photo(
                    file,
                    caption=caption,
                    reply_markup=keyboard,
                )
                sent = True
            except TelegramBadRequest as exc:
                logger.warning("Photo rejected, sending as file: %s", exc)

        if not sent:
            # Photo limits exceeded (size/dimensions): send as a file.
            await target.answer_document(
                file,
                caption=caption,
                reply_markup=keyboard,
            )

        try:
            await status.delete()
        except TelegramBadRequest:
            pass

    except Exception:
        logger.exception("Image generation failed")
        ref = cache_put(
            {"prompt": prompt, "enhanced": enhanced, "aspect": aspect}
        )
        await safe_edit(
            status,
            "⚠️ I couldn't generate this image right now. "
            "The image servers may be busy — please try again.",
            image_retry_kb(ref),
        )

    finally:
        busy_users.discard(user_id)


@router.message(Image.waiting_for_prompt, F.text)
async def handle_image_prompt(message: Message) -> None:
    """Generate an image from the user's description."""
    if not message.from_user or not message.text:
        return

    prompt = message.text.strip()

    if len(prompt) > 1000:
        await message.answer(
            "⚠️ That description is too long. Please keep it under "
            "1000 characters."
        )
        return

    await run_image_job(
        message,
        message.from_user.id,
        prompt,
        detect_aspect(prompt),
    )


@router.callback_query(ActionCB.filter(F.action == "imgregen"))
async def image_regenerate(
    callback: CallbackQuery,
    callback_data: ActionCB,
) -> None:
    """Make a new variation (or retry after a failure)."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    entry = cache_get(callback_data.ref)

    if not entry:
        await callback.answer(
            "Expired. Please send your description again.",
            show_alert=True,
        )
        return

    if callback.from_user.id in busy_users:
        await callback.answer(
            "Still working on your previous image…",
            show_alert=True,
        )
        return

    await callback.answer("Creating a new version…")

    # After a success, re-enhance for a genuinely different variation;
    # after a failure, reuse the already enhanced prompt.
    enhanced = None if entry.get("image") else entry.get("enhanced")

    await run_image_job(
        callback.message,
        callback.from_user.id,
        entry["prompt"],
        entry["aspect"],
        enhanced,
    )


@router.callback_query(ActionCB.filter(F.action.startswith("ar_")))
async def image_change_aspect(
    callback: CallbackQuery,
    callback_data: ActionCB,
) -> None:
    """Regenerate the same image idea in another aspect ratio."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    entry = cache_get(callback_data.ref)
    aspect = callback_data.action[3:]

    if not entry or aspect not in ASPECTS:
        await callback.answer(
            "Expired. Please send your description again.",
            show_alert=True,
        )
        return

    if callback.from_user.id in busy_users:
        await callback.answer(
            "Still working on your previous image…",
            show_alert=True,
        )
        return

    if aspect == entry.get("aspect"):
        await callback.answer("Already in this format.")
        return

    await callback.answer(f"Creating {ASPECTS[aspect]['label']} version…")
    await run_image_job(
        callback.message,
        callback.from_user.id,
        entry["prompt"],
        aspect,
        entry.get("enhanced"),
    )


@router.callback_query(ActionCB.filter(F.action == "imgfile"))
async def image_original_file(
    callback: CallbackQuery,
    callback_data: ActionCB,
) -> None:
    """Send the untouched, uncompressed image as a document."""
    entry = cache_get(callback_data.ref)

    if not callback.message:
        await callback.answer()
        return

    if not entry or not entry.get("image"):
        await callback.answer(
            "Expired. Please regenerate.",
            show_alert=True,
        )
        return

    image: bytes = entry["image"]
    await callback.answer("Sending original…")
    await callback.message.answer_document(
        BufferedInputFile(image, filename=f"image.{image_ext(image)}"),
    )


@router.callback_query(ActionCB.filter(F.action == "imgprompt"))
async def image_show_prompt(
    callback: CallbackQuery,
    callback_data: ActionCB,
) -> None:
    """Show the optimized prompt that was used."""
    entry = cache_get(callback_data.ref)

    if not callback.message:
        await callback.answer()
        return

    if not entry:
        await callback.answer("Expired.", show_alert=True)
        return

    await callback.message.answer(
        "📝 <b>Prompt used:</b>\n\n"
        f"<code>{html.escape(entry.get('enhanced') or entry['prompt'])}</code>"
    )
    await callback.answer()


@router.callback_query(F.data == "retry_image")
async def retry_image(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Return the user to the Image prompt (legacy button)."""
    await state.set_state(Image.waiting_for_prompt)

    if callback.message:
        await edit_or_answer(
            callback.message,
            "🎨 Describe the image you want.",
            back_menu_kb(),
        )

    await callback.answer()


# ─── 19. Fallback: text outside any feature ─────────────────────────────────
# Must stay LAST so the state-specific handlers above take precedence.
@router.message(F.text, ~F.text.startswith("/"))
async def fallback_text(message: Message) -> None:
    """Point users without an active feature to the menu."""
    await message.answer(
        "Pick a feature from the menu to get started:",
        reply_markup=main_menu_kb(),
    )


# ─── 20. Error handler ──────────────────────────────────────────────────────
async def global_error_handler(event: ErrorEvent) -> bool:
    """Log unexpected errors without crashing the bot."""
    logger.error("Unhandled error", exc_info=event.exception)

    update = event.update
    message = getattr(update, "message", None)
    callback = getattr(update, "callback_query", None)
    target = message or (callback.message if callback else None)

    if target:
        try:
            await target.answer(ERROR_TEXT, reply_markup=retry_kb())
        except Exception:
            logger.exception("Could not send error message")

    return True


# ─── 21. main() + startup ───────────────────────────────────────────────────
async def main() -> None:
    """Initialize the database, bot, dispatcher, middleware and polling."""
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    # Outer middleware on the dispatcher gates every router, before filters.
    subscription_mw = SubscriptionMiddleware(bot)
    dp.message.outer_middleware(subscription_mw)
    dp.callback_query.outer_middleware(subscription_mw)

    dp.errors.register(global_error_handler)
    dp.include_router(router)

    logger.info("𝗫𝗘𝗡𝗢 𝗚𝗣𝗧 bot v%s is starting…", BOT_VERSION)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        if db:
            await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
