import os
import re
import asyncio
import tempfile
import shutil
import logging
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 49 * 1024 * 1024


# =========================================================
# WELCOME MESSAGE
# =========================================================

WELCOME_MESSAGE = """╔══════════════════════════╗
      🎬✨ S I H U  M E D I A ✨🎬
╚══════════════════════════╝

👋🌟 Welcome to Sihu Media Bot!

🚀 Your all-in-one media downloader
📥 Download your favorite videos easily

🌐 Supported Platforms:
▶️ YouTube
📘 Facebook
🎵 TikTok
📸 Instagram
🌍 And many more!

🎥 YouTube Features:
✨ Quality Selection
🎞️ FPS Selection
🔊 Best Available Audio
💎 Best Available Video Quality

📎 Send me a public video link
👇 I'll handle the rest! 🚀

⚡ Fast • 🎯 High Quality • 🔊 Best Audio

❤️ Enjoy Sihu Media Bot ❤️"""


# =========================================================
# URL DETECTION
# =========================================================

URL_PATTERN = re.compile(
    r"https?://[^\s]+",
    re.IGNORECASE
)


def extract_url(text):
    if not text:
        return None

    match = URL_PATTERN.search(text)

    if not match:
        return None

    return match.group(0).rstrip(
        ".,!?)]}"
    )


def detect_platform(url):
    try:
        host = urlparse(url).netloc.lower()

        if "youtube.com" in host or "youtu.be" in host:
            return "youtube"

        if "tiktok.com" in host:
            return "tiktok"

        if "facebook.com" in host or "fb.watch" in host:
            return "facebook"

        if "instagram.com" in host:
            return "instagram"

    except Exception:
        pass

    return "unknown"


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        WELCOME_MESSAGE,
        disable_web_page_preview=True
    )


# =========================================================
# YOUTUBE INFO
# =========================================================

def get_youtube_info(url):

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_args": {
            "youtube": {
                "player_client": [
                    "android",
                    "web"
                ]
            }
        },
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(
            url,
            download=False
        )


# =========================================================
# YOUTUBE QUALITY MENU
# =========================================================

def create_quality_keyboard(info):

    formats = info.get(
        "formats",
        []
    )

    available = {}

    for fmt in formats:

        video_codec = fmt.get("vcodec")

        if not video_codec or video_codec == "none":
            continue

        height = fmt.get("height")

        if not height:
            continue

        if height < 144 or height > 2160:
            continue

        fps = fmt.get("fps")

        if not fps:
            fps = 30

        fps = int(round(fps))

        key = (
            int(height),
            fps
        )

        available[key] = True

    if not available:
        available = {
            (360, 30): True,
            (480, 30): True,
            (720, 30): True,
        }

    qualities = sorted(
        available.keys(),
        key=lambda x: (
            x[0],
            x[1]
        ),
        reverse=True
    )

    buttons = []

    for height, fps in qualities:

        buttons.append([
            InlineKeyboardButton(
                f"🎥 {height}p • 🎞️ {fps} FPS",
                callback_data=f"yt:{height}:{fps}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "💎 Best Available",
            callback_data="yt:best:best"
        )
    ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# YOUTUBE DOWNLOAD
# =========================================================

def download_youtube(
    url,
    height,
    fps,
    folder
):

    output_template = os.path.join(
        folder,
        "%(title)s.%(ext)s"
    )

    if height == "best":

        format_selector = (
            "bestvideo*+bestaudio/"
            "best"
        )

    else:

        height_value = int(height)
        fps_value = int(fps)

        format_selector = (
            f"bestvideo[height<={height_value}]"
            f"[fps<={fps_value}]"
            f"+bestaudio/"
            f"best[height<={height_value}]"
        )

    options = {
        "format": format_selector,
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 4,
        "fragment_retries": 4,
        "socket_timeout": 60,
        "concurrent_fragment_downloads": 4,
        "extractor_args": {
            "youtube": {
                "player_client": [
                    "android",
                    "web"
                ]
            }
        },
    }

    with yt_dlp.YoutubeDL(options) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )

        prepared = ydl.prepare_filename(
            info
        )

        mp4_file = (
            os.path.splitext(prepared)[0]
            + ".mp4"
        )

        if os.path.exists(mp4_file):
            return mp4_file

        if os.path.exists(prepared):
            return prepared

        files = list(
            Path(folder).glob("*")
        )

        for file in files:

            if file.is_file():
                return str(file)

    return None


# =========================================================
# TIKTOK / FACEBOOK / INSTAGRAM
# =========================================================

def download_generic(
    url,
    folder
):

    output_template = os.path.join(
        folder,
        "%(title)s.%(ext)s"
    )

    options = {
        "format": (
            "bestvideo*+bestaudio/"
            "best"
        ),
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 4,
        "fragment_retries": 4,
        "socket_timeout": 60,
    }

    with yt_dlp.YoutubeDL(options) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )

        prepared = ydl.prepare_filename(
            info
        )

        mp4_file = (
            os.path.splitext(prepared)[0]
            + ".mp4"
        )

        if os.path.exists(mp4_file):
            return mp4_file

        if os.path.exists(prepared):
            return prepared

        files = list(
            Path(folder).glob("*")
        )

        for file in files:

            if file.is_file():
                return str(file)

    return None


# =========================================================
# SEND VIDEO
# =========================================================

async def send_video(
    message,
    file_path,
    caption
):

    if not file_path:

        await message.reply_text(
            "❌ Unable to create the video.\n"
            "Please try again."
        )

        return

    if not os.path.exists(file_path):

        await message.reply_text(
            "❌ Downloaded file was not found."
        )

        return

    file_size = os.path.getsize(
        file_path
    )

    if file_size > MAX_FILE_SIZE:

        await message.reply_text(
            "❌ This video is too large to send.\n\n"
            "Please choose a lower quality."
        )

        return

    try:

        with open(
            file_path,
            "rb"
        ) as video:

            await message.reply_video(
                video=video,
                caption=caption,
                supports_streaming=True,
                read_timeout=180,
                write_timeout=180,
                connect_timeout=60,
            )

    except Exception as error:

        logger.exception(
            "Video sending error: %s",
            error
        )

        await message.reply_text(
            "❌ Unable to send the video.\n"
            "Please try again."
        )


# =========================================================
# URL HANDLER
# =========================================================

async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message

    url = extract_url(
        message.text
    )

    if not url:
        return

    platform = detect_platform(
        url
    )

    # =====================================================
    # YOUTUBE
    # =====================================================

    if platform == "youtube":

        status = await message.reply_text(
            "🔎 Checking YouTube video...\n"
            "⏳ Please wait..."
        )

        try:

            info = await asyncio.to_thread(
                get_youtube_info,
                url
            )

            title = info.get(
                "title",
                "YouTube Video"
            )

            context.user_data[
                "youtube_url"
            ] = url

            context.user_data[
                "youtube_title"
            ] = title

            keyboard = create_quality_keyboard(
                info
            )

            await status.edit_text(
                f"🎬 {title[:100]}\n\n"
                "👇 Select Video Quality:",
                reply_markup=keyboard
            )

        except Exception as error:

            logger.exception(
                "YouTube information error: %s",
                error
            )

            await status.edit_text(
                "❌ Unable to get YouTube video information.\n\n"
                "🔄 Please try another link."
            )

        return

    # =====================================================
    # TIKTOK / FACEBOOK / INSTAGRAM
    # =====================================================

    if platform in (
        "tiktok",
        "facebook",
        "instagram"
    ):

        status = await message.reply_text(
            "🔎 Link detected!\n"
            "⬇️ Downloading video...\n"
            "⏳ Please wait..."
        )

        folder = tempfile.mkdtemp(
            prefix="sihu_"
        )

        try:

            file_path = await asyncio.to_thread(
                download_generic,
                url,
                folder
            )

            try:
                await status.delete()
            except Exception:
                pass

            await send_video(
                message,
                file_path,
                "🎬 Sihu Media Bot\n"
                "⚡ Fast • 🎯 High Quality • 🔊 Best Audio\n"
                "❤️ Enjoy Sihu Media Bot ❤️"
            )

        except Exception as error:

            logger.exception(
                "%s download error: %s",
                platform,
                error
            )

            try:

                await status.edit_text(
                    "❌ Download failed.\n\n"
                    "🔄 Please try another public video link."
                )

            except Exception:
                pass

        finally:

            shutil.rmtree(
                folder,
                ignore_errors=True
            )

        return

    # =====================================================
    # UNKNOWN URL
    # =====================================================

    await message.reply_text(
        "❌ Unsupported link.\n\n"
        "Please send a public video link from:\n"
        "▶️ YouTube\n"
        "📘 Facebook\n"
        "🎵 TikTok\n"
        "📸 Instagram"
    )


# =========================================================
# YOUTUBE QUALITY CALLBACK
# =========================================================

async def quality_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data

    if not data.startswith("yt:"):
        return

    parts = data.split(":")

    if len(parts) != 3:
        return

    height = parts[1]
    fps = parts[2]

    url = context.user_data.get(
        "youtube_url"
    )

    title = context.user_data.get(
        "youtube_title",
        "YouTube Video"
    )

    if not url:

        await query.edit_message_text(
            "❌ Download session expired.\n\n"
            "🔄 Please send the YouTube link again."
        )

        return

    try:

        await query.edit_message_text(
            f"🎬 {title[:80]}\n\n"
            f"⬇️ Downloading: {height}p • {fps} FPS\n"
            "⏳ Please wait..."
        )

    except Exception:
        pass

    folder = tempfile.mkdtemp(
        prefix="sihu_youtube_"
    )

    try:

        file_path = await asyncio.to_thread(
            download_youtube,
            url,
            height,
            fps,
            folder
        )

        await send_video(
            query.message,
            file_path,
            "🎬 Sihu Media Bot\n"
            "💎 High Quality Video\n"
            "🔊 Best Available Audio\n"
            "❤️ Enjoy Sihu Media Bot ❤️"
        )

    except Exception as error:

        logger.exception(
            "YouTube download error: %s",
            error
        )

        try:

            await query.message.reply_text(
                "❌ YouTube download failed.\n\n"
                "🔄 Please try another quality or link."
            )

        except Exception:
            pass

    finally:

        shutil.rmtree(
            folder,
            ignore_errors=True
        )

        context.user_data.pop(
            "youtube_url",
            None
        )

        context.user_data.pop(
            "youtube_title",
            None
        )


# =========================================================
# GLOBAL ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Unhandled error:",
        exc_info=context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            quality_callback,
            pattern=r"^yt:"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_url
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Sihu Media Bot is starting..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
