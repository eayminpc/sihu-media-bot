import os
import re
import asyncio
import tempfile
import shutil
import logging
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
# RENDER WEB SERVER
# IMPORTANT: This makes the bot a proper Render Web Service.
# It does NOT remove Render Free's 15-minute idle rule by itself.
# =========================================================

web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Sihu Media Bot is Running! ❤️", 200

@web_app.route("/health")
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", "10000"))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False)

# =========================================================
# WELCOME
# =========================================================

WELCOME_MESSAGE = """╔════════════════════════════╗
║   🎬✨ S I H U  M E D I A ✨🎬   ║
╚════════════════════════════╝

👋 Welcome to Sihu Media Bot!

🚀 Fast & Easy Media Downloader

🌐 Supported Platforms
▶️ YouTube
📘 Facebook
🎵 TikTok
📸 Instagram

🎵 TikTok / Instagram
• 🎬 Video Download
• 🚫 Without Watermark*

🎥 YouTube
• 🎞️ Video Quality Selection
• 🎬 Best Available Quality
• 🎵 Audio Download

📎 Send a public video link
👇 I will handle the rest!

⚡ Fast • 🎯 High Quality • ❤️ Sihu Media

*Watermark-free output depends on the source/extractor.
"""

# =========================================================
# URL
# =========================================================

URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)

def extract_url(text):
    if not text:
        return None

    match = URL_PATTERN.search(text)

    if not match:
        return None

    return match.group(0).rstrip(".,!?)]}")

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
# YOUTUBE OPTIONS
# Current yt-dlp clients: android_vr is useful because it
# does not require a PO token for GVS.
# =========================================================

YOUTUBE_EXTRACTOR_ARGS = {
    "youtube": {
        "player_client": ["android_vr", "web_embedded"]
    }
}

def get_youtube_info(url):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 45,
        "retries": 4,
        "fragment_retries": 4,
        "extractor_args": YOUTUBE_EXTRACTOR_ARGS,
    }

    # Optional cookies support:
    # Put a valid Netscape cookies file path in YOUTUBE_COOKIES_FILE
    # only if YouTube still asks for sign-in.
    cookie_file = os.getenv("YOUTUBE_COOKIES_FILE")
    if cookie_file and os.path.exists(cookie_file):
        options["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)

# =========================================================
# YOUTUBE QUALITY MENU
# =========================================================

def create_quality_keyboard(info):
    formats = info.get("formats", [])
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

        fps = fmt.get("fps") or 30

        try:
            fps = int(round(float(fps)))
        except Exception:
            fps = 30

        key = (int(height), fps)
        available[key] = True

    if not available:
        available = {
            (360, 30): True,
            (480, 30): True,
            (720, 30): True,
        }

    qualities = sorted(
        available.keys(),
        key=lambda x: (x[0], x[1]),
        reverse=True,
    )

    buttons = []

    for height, fps in qualities[:12]:
        buttons.append([
            InlineKeyboardButton(
                f"🎥 {height}p • 🎞️ {fps} FPS",
                callback_data=f"ytv:{height}:{fps}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "💎 Best Available Video",
            callback_data="ytv:best:best",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "🎵 Download Audio",
            callback_data="yta:audio:0",
        )
    ])

    return InlineKeyboardMarkup(buttons)

# =========================================================
# DOWNLOAD YOUTUBE VIDEO
# =========================================================

def download_youtube(url, height, fps, folder):
    output_template = os.path.join(
        folder,
        "%(title).180s.%(ext)s",
    )

    if height == "best":
        format_selector = "bestvideo*+bestaudio/best"
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
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 90,
        "concurrent_fragment_downloads": 4,
        "extractor_args": YOUTUBE_EXTRACTOR_ARGS,
    }

    cookie_file = os.getenv("YOUTUBE_COOKIES_FILE")
    if cookie_file and os.path.exists(cookie_file):
        options["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

        prepared = ydl.prepare_filename(info)

        mp4_file = os.path.splitext(prepared)[0] + ".mp4"

        if os.path.exists(mp4_file):
            return mp4_file

        if os.path.exists(prepared):
            return prepared

        for file in Path(folder).glob("*"):
            if file.is_file() and file.suffix.lower() not in (".part",):
                return str(file)

    return None

# =========================================================
# DOWNLOAD YOUTUBE AUDIO
# =========================================================

def download_youtube_audio(url, folder):
    output_template = os.path.join(
        folder,
        "%(title).180s.%(ext)s",
    )

    options = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 90,
        "extractor_args": YOUTUBE_EXTRACTOR_ARGS,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    cookie_file = os.getenv("YOUTUBE_COOKIES_FILE")
    if cookie_file and os.path.exists(cookie_file):
        options["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

        prepared = ydl.prepare_filename(info)
        mp3_file = os.path.splitext(prepared)[0] + ".mp3"

        if os.path.exists(mp3_file):
            return mp3_file

        for file in Path(folder).glob("*"):
            if file.is_file() and file.suffix.lower() in (
                ".mp3",
                ".m4a",
                ".webm",
                ".opus",
            ):
                return str(file)

    return None

# =========================================================
# TIKTOK / FACEBOOK / INSTAGRAM
# =========================================================

def download_generic(url, folder):
    output_template = os.path.join(
        folder,
        "%(title).180s.%(ext)s",
    )

    options = {
        "format": "bestvideo*+bestaudio/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 90,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

        prepared = ydl.prepare_filename(info)
        mp4_file = os.path.splitext(prepared)[0] + ".mp4"

        if os.path.exists(mp4_file):
            return mp4_file

        if os.path.exists(prepared):
            return prepared

        for file in Path(folder).glob("*"):
            if file.is_file() and file.suffix.lower() not in (".part",):
                return str(file)

    return None

# =========================================================
# SEND VIDEO
# =========================================================

async def send_video(message, file_path, caption):
    if not file_path or not os.path.exists(file_path):
        await message.reply_text(
            "❌ Video file could not be created."
        )
        return False

    file_size = os.path.getsize(file_path)

    if file_size > MAX_FILE_SIZE:
        await message.reply_text(
            "❌ This video is too large for Telegram.\n\n"
            "Please choose a lower YouTube quality."
        )
        return False

    try:
        with open(file_path, "rb") as video:
            await message.reply_video(
                video=video,
                caption=caption,
                supports_streaming=True,
                read_timeout=300,
                write_timeout=300,
                connect_timeout=60,
            )
        return True

    except Exception as error:
        logger.exception("Video sending error: %s", error)

        await message.reply_text(
            "❌ Unable to upload the video.\n"
            "Please try again."
        )
        return False

# =========================================================
# SEND AUDIO
# =========================================================

async def send_audio(message, file_path, title="YouTube Audio"):
    if not file_path or not os.path.exists(file_path):
        await message.reply_text(
            "❌ Audio file could not be created."
        )
        return False

    file_size = os.path.getsize(file_path)

    if file_size > MAX_FILE_SIZE:
        await message.reply_text(
            "❌ This audio file is too large to send."
        )
        return False

    try:
        with open(file_path, "rb") as audio:
            await message.reply_audio(
                audio=audio,
                title=title[:64],
                performer="Sihu Media Bot",
                read_timeout=300,
                write_timeout=300,
                connect_timeout=60,
            )
        return True

    except Exception as error:
        logger.exception("Audio sending error: %s", error)

        await message.reply_text(
            "❌ Unable to upload the audio.\n"
            "Please try again."
        )
        return False

# =========================================================
# URL HANDLER
# =========================================================

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    url = extract_url(message.text)

    if not url:
        return

    platform = detect_platform(url)

    # -----------------------------------------------------
    # YOUTUBE
    # -----------------------------------------------------

    if platform == "youtube":
        status = await message.reply_text(
            "🔎 Checking YouTube link...\n"
            "⏳ Please wait..."
        )

        try:
            info = await asyncio.to_thread(
                get_youtube_info,
                url,
            )

            title = info.get("title", "YouTube Video")

            context.user_data["youtube_url"] = url
            context.user_data["youtube_title"] = title

            keyboard = create_quality_keyboard(info)

            await status.edit_text(
                f"🎬 {title[:90]}\n\n"
                "👇 Select an option:",
                reply_markup=keyboard,
            )

        except Exception as error:
            logger.exception(
                "YouTube information error: %s",
                error,
            )

            await status.edit_text(
                "❌ YouTube could not be accessed right now.\n\n"
                "🔄 Try another public YouTube link.\n"
                "💡 If YouTube is asking for verification, "
                "the server may need YouTube cookies."
            )

        return

    # -----------------------------------------------------
    # TIKTOK / FACEBOOK / INSTAGRAM
    # -----------------------------------------------------

    if platform in ("tiktok", "facebook", "instagram"):
        if platform == "tiktok":
            platform_text = "🎵 TikTok • 🚫 Without Watermark"
        elif platform == "instagram":
            platform_text = "📸 Instagram • 🚫 Without Watermark"
        else:
            platform_text = "📘 Facebook"

        status = await message.reply_text(
            f"🔎 {platform_text}\n"
            "⬇️ Downloading video...\n"
            "⏳ Please wait..."
        )

        folder = tempfile.mkdtemp(prefix="sihu_")

        try:
            file_path = await asyncio.to_thread(
                download_generic,
                url,
                folder,
            )

            await status.edit_text(
                f"📥 Download complete!\n\n"
                "📤 Uploading...\n"
                "⏳ Almost there..."
            )

            await send_video(
                message,
                file_path,
                "╔══════════════════════╗\n"
                "🎬 S I H U  M E D I A 🎬\n"
                "╚══════════════════════╝\n\n"
                f"{platform_text}\n"
                "⚡ High Quality • Fast Download\n"
                "❤️ Enjoy Sihu Media Bot",
            )

            try:
                await status.delete()
            except Exception:
                pass

        except Exception as error:
            logger.exception(
                "%s download error: %s",
                platform,
                error,
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
                ignore_errors=True,
            )

        return

    # -----------------------------------------------------
    # UNKNOWN
    # -----------------------------------------------------

    await message.reply_text(
        "❌ Unsupported link.\n\n"
        "Please send a public video link from:\n"
        "▶️ YouTube\n"
        "📘 Facebook\n"
        "🎵 TikTok\n"
        "📸 Instagram"
    )

# =========================================================
# YOUTUBE CALLBACK
# =========================================================

async def quality_callback(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data

    url = context.user_data.get("youtube_url")
    title = context.user_data.get(
        "youtube_title",
        "YouTube Video",
    )

    if not url:
        await query.edit_message_text(
            "❌ Download session expired.\n\n"
            "🔄 Please send the YouTube link again."
        )
        return

    # -----------------------------------------------------
    # AUDIO
    # -----------------------------------------------------

    if data.startswith("yta:"):
        try:
            await query.edit_message_text(
                f"🎵 {title[:80]}\n\n"
                "⬇️ Downloading audio...\n"
                "⏳ Please wait..."
            )
        except Exception:
            pass

        folder = tempfile.mkdtemp(prefix="sihu_audio_")

        try:
            file_path = await asyncio.to_thread(
                download_youtube_audio,
                url,
                folder,
            )

            try:
                await query.edit_message_text(
                    "📥 Download complete!\n\n"
                    "📤 Uploading audio...\n"
                    "⏳ Almost there..."
                )
            except Exception:
                pass

            await send_audio(
                query.message,
                file_path,
                title=title,
            )

        except Exception as error:
            logger.exception(
                "YouTube audio error: %s",
                error,
            )

            await query.message.reply_text(
                "❌ YouTube audio download failed.\n\n"
                "🔄 Please try again."
            )

        finally:
            shutil.rmtree(
                folder,
                ignore_errors=True,
            )

            context.user_data.pop(
                "youtube_url",
                None,
            )
            context.user_data.pop(
                "youtube_title",
                None,
            )

        return

    # -----------------------------------------------------
    # VIDEO
    # -----------------------------------------------------

    if not data.startswith("ytv:"):
        return

    parts = data.split(":")

    if len(parts) != 3:
        return

    height = parts[1]
    fps = parts[2]

    if height == "best":
        download_label = "Best Available"
    else:
        download_label = f"{height}p • {fps} FPS"

    try:
        await query.edit_message_text(
            f"🎬 {title[:80]}\n\n"
            f"⬇️ Downloading: {download_label}\n"
            "⏳ Please wait..."
        )
    except Exception:
        pass

    folder = tempfile.mkdtemp(prefix="sihu_youtube_")

    try:
        file_path = await asyncio.to_thread(
            download_youtube,
            url,
            height,
            fps,
            folder,
        )

        try:
            await query.edit_message_text(
                "📥 Download complete!\n\n"
                "📤 Uploading video...\n"
                "⏳ Almost there..."
            )
        except Exception:
            pass

        await send_video(
            query.message,
            file_path,
            "╔══════════════════════╗\n"
            "🎬 S I H U  M E D I A 🎬\n"
            "╚══════════════════════╝\n\n"
            "▶️ YouTube Video\n"
            f"🎥 Quality: {download_label}\n"
            "🔊 Best Available Audio\n"
            "❤️ Enjoy Sihu Media Bot",
        )

    except Exception as error:
        logger.exception(
            "YouTube video error: %s",
            error,
        )

        await query.message.reply_text(
            "❌ YouTube download failed.\n\n"
            "🔄 Try another quality or another public link."
        )

    finally:
        shutil.rmtree(
            folder,
            ignore_errors=True,
        )

        context.user_data.pop(
            "youtube_url",
            None,
        )
        context.user_data.pop(
            "youtube_title",
            None,
        )

# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    logger.error(
        "Unhandled error:",
        exc_info=context.error,
    )

# =========================================================
# MAIN
# =========================================================

def main():
    # Start Render HTTP server in background.
    threading = __import__("threading")
    threading.Thread(
        target=run_web,
        daemon=True,
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CallbackQueryHandler(
            quality_callback,
            pattern=r"^yt[av]:",
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_url,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("Sihu Media Bot is starting...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WELCOME_MESSAGE,
        disable_web_page_preview=True,
    )

if __name__ == "__main__":
    main()
