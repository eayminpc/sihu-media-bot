import os
import re
import asyncio
import tempfile
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
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)


# =========================================================
# BOT TOKEN
# =========================================================

BOT_TOKEN = "8743030512:AAHX-OTu9NSjtLpGRfybgrLBQP7bpW6spoI"


# =========================================================
# SETTINGS
# =========================================================

# একসাথে সর্বোচ্চ 4টি update handle করবে
MAX_CONCURRENT_USERS = 4

# Telegram upload/download timeout
REQUEST_TIMEOUT = 900


# =========================================================
# EXTRACT URL FROM MESSAGE
# =========================================================

def extract_url(text):
    if not text:
        return None

    text = text.strip()

    match = re.search(
        r'(https?://[^\s<>"\']+|www\.[^\s<>"\']+)',
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    url = match.group(1).strip()

    # শেষে থাকা punctuation বাদ
    url = url.rstrip(
        ".,!?;:)]}>\"'"
    )

    if url.startswith("www."):
        url = "https://" + url

    return url


# =========================================================
# YOUTUBE URL CHECK
# =========================================================

def is_youtube_url(url):
    try:
        parsed = urlparse(url)

        host = parsed.netloc.lower()

        if host.startswith("www."):
            host = host[4:]

        return (
            host == "youtube.com"
            or host.endswith(".youtube.com")
            or host == "youtu.be"
        )

    except Exception:
        return False


# =========================================================
# GET YOUTUBE FORMATS
# =========================================================

def get_youtube_formats(url):

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(
            url,
            download=False,
        )

    formats = info.get(
        "formats",
        []
    )

    quality_list = []

    seen = set()

    for fmt in formats:

        height = fmt.get("height")
        fps = fmt.get("fps")
        video_codec = fmt.get("vcodec")

        if not height:
            continue

        if video_codec == "none":
            continue

        if height < 144:
            continue

        if not fps:
            fps = 30

        fps = int(
            round(fps)
        )

        key = (
            height,
            fps,
        )

        if key in seen:
            continue

        seen.add(key)

        quality_list.append(
            {
                "height": height,
                "fps": fps,
            }
        )

    quality_list.sort(
        key=lambda x: (
            x["height"],
            x["fps"],
        ),
        reverse=True,
    )

    return info, quality_list


# =========================================================
# DOWNLOAD YOUTUBE
# =========================================================

def download_youtube(
    url,
    folder,
    height,
    fps,
):

    output_template = os.path.join(
        folder,
        "%(title).100s.%(ext)s",
    )

    # প্রথমে exact FPS চেষ্টা করবে
    # না পেলে একই quality
    # না পেলে nearest best
    format_selector = (
        f"bestvideo[height={height}][fps={fps}]+bestaudio/"
        f"bestvideo[height={height}]+bestaudio/"
        f"best[height={height}]/"
        f"best"
    )

    ydl_opts = {

        "outtmpl": output_template,

        "format": format_selector,

        "merge_output_format": "mp4",

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        # বড় video download-এর জন্য
        "retries": 10,

        "fragment_retries": 10,

        "continuedl": True,

        "concurrent_fragment_downloads": 4,
    }

    with yt_dlp.YoutubeDL(
        ydl_opts
    ) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        filename = ydl.prepare_filename(
            info
        )

        base, _ = os.path.splitext(
            filename
        )

        possible_files = [
            base + ".mp4",
            filename,
        ]

        for file_path in possible_files:

            if os.path.exists(
                file_path
            ):
                return file_path

        for name in os.listdir(
            folder
        ):

            path = os.path.join(
                folder,
                name,
            )

            if os.path.isfile(path):
                return path

    return None


# =========================================================
# DOWNLOAD OTHER PLATFORMS
# =========================================================

def download_video(
    url,
    folder,
):

    output_template = os.path.join(
        folder,
        "%(title).100s.%(ext)s",
    )

    ydl_opts = {

        "outtmpl": output_template,

        "format": (
            "bestvideo+bestaudio/"
            "best"
        ),

        "merge_output_format": "mp4",

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        "retries": 10,

        "fragment_retries": 10,

        "continuedl": True,

        "concurrent_fragment_downloads": 4,
    }

    with yt_dlp.YoutubeDL(
        ydl_opts
    ) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        filename = ydl.prepare_filename(
            info
        )

        base, _ = os.path.splitext(
            filename
        )

        possible_files = [
            base + ".mp4",
            filename,
        ]

        for file_path in possible_files:

            if os.path.exists(
                file_path
            ):
                return file_path

        for name in os.listdir(
            folder
        ):

            path = os.path.join(
                folder,
                name,
            )

            if os.path.isfile(path):
                return path

    return None


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(

        "╔══════════════════════════╗\n"
        "      🎬✨ S I H U  M E D I A ✨🎬\n"
        "╚══════════════════════════╝\n\n"

        "👋🌟 Welcome to Sihu Media Bot!\n\n"

        "🚀 Your all-in-one media downloader\n"
        "📥 Download your favorite videos easily\n\n"

        "🌐 Supported Platforms:\n"
        "▶️ YouTube\n"
        "📘 Facebook\n"
        "🎵 TikTok\n"
        "📸 Instagram\n"
        "🌍 And many more!\n\n"

        "🎥 YouTube Features:\n"
        "✨ Quality Selection\n"
        "🎞️ FPS Selection\n"
        "🔊 Best Available Audio\n"
        "💎 Best Available Video Quality\n\n"

        "📎 Send me a public video link\n"
        "👇 I'll handle the rest! 🚀\n\n"

        "⚡ Fast • 🎯 High Quality • 🔊 Best Audio\n\n"

        "❤️ Enjoy Sihu Media Bot ❤️"
    )


# =========================================================
# YOUTUBE QUALITY MENU
# =========================================================

async def show_youtube_quality(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url,
):

    status = await update.message.reply_text(

        "🔍✨ Checking available qualities...\n\n"
        "⏳🎬 Please wait a moment..."
    )

    try:

        info, quality_list = await asyncio.to_thread(
            get_youtube_formats,
            url,
        )

        if not quality_list:

            await status.edit_text(
                "❌ Could not find available video qualities."
            )

            return

        context.user_data[
            "youtube_url"
        ] = url

        title = info.get(
            "title",
            "YouTube video",
        )

        quality_list = quality_list[:20]

        keyboard = []

        for item in quality_list:

            height = item["height"]

            fps = item["fps"]

            button_text = (
                f"🎬 {height}p • "
                f"{fps} FPS"
            )

            callback_data = (
                f"yt:{height}:{fps}"
            )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text,
                        callback_data=callback_data,
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="yt:cancel",
                )
            ]
        )

        await status.edit_text(

            f"🎬✨ {title}\n\n"

            "📺 Choose your video quality:\n"
            "🎞️ FPS is shown with each option.\n\n"

            "👇 Select your preferred quality:",

            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    except Exception as e:

        print(
            "YOUTUBE FORMAT ERROR:",
            repr(e),
        )

        await status.edit_text(

            "❌ Could not read YouTube formats.\n\n"
            "🔄 Please try another public YouTube video."
        )


# =========================================================
# HANDLE NORMAL VIDEO
# =========================================================

async def handle_normal_video(
    update,
    url,
):

    status = await update.message.reply_text(

        "🔍✨ Your link is being processed...\n\n"

        "⏳📥 Downloading your video...\n"
        "🕐💫 Please wait a moment..."
    )

    try:

        with tempfile.TemporaryDirectory() as temp_folder:

            video_path = await asyncio.to_thread(
                download_video,
                url,
                temp_folder,
            )

            if (
                not video_path
                or not os.path.exists(
                    video_path
                )
            ):

                await status.edit_text(

                    "❌ Failed to download the video.\n"
                    "🔄 Please try another public link."
                )

                return

            file_size = os.path.getsize(
                video_path
            )

            file_size_mb = (
                file_size
                / (1024 * 1024)
            )

            await status.edit_text(

                f"📤🚀 Uploading your video...\n\n"
                f"📦 Size: {file_size_mb:.1f} MB\n"
                f"☁️✨ Almost there, please wait..."
            )

            with open(
                video_path,
                "rb",
            ) as video_file:

                await update.message.reply_video(

                    video=video_file,

                    supports_streaming=True,

                    read_timeout=REQUEST_TIMEOUT,

                    write_timeout=REQUEST_TIMEOUT,

                    connect_timeout=60,

                    pool_timeout=60,
                )

            await status.delete()

    except Exception as e:

        print(
            "DOWNLOAD ERROR:",
            repr(e),
        )

        try:

            await status.edit_text(

                "❌ Could not download/upload the video.\n\n"

                "🔎 Possible reasons:\n"
                "• 🔒 Video is not public\n"
                "• 🚫 Website blocked the request\n"
                "• 🔗 Link expired\n"
                "• 🌐 Unsupported video page\n"
                "• 📦 Telegram upload limit\n\n"

                "🔄 Please try another public video."
            )

        except Exception:
            pass


# =========================================================
# HANDLE LINK
# =========================================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    url = extract_url(
        update.message.text
    )

    if not url:

        await update.message.reply_text(

            "❌ কোনো valid video link পাওয়া যায়নি!\n\n"

            "🔗 Please send a public video link again."
        )

        return

    # YouTube
    if is_youtube_url(url):

        await show_youtube_quality(
            update,
            context,
            url,
        )

        return

    # Other platforms
    await handle_normal_video(
        update,
        url,
    )


# =========================================================
# YOUTUBE QUALITY BUTTON
# =========================================================

async def youtube_quality_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    data = query.data

    if data == "yt:cancel":

        await query.edit_message_text(
            "❌ Download cancelled."
        )

        return

    try:

        _, height, fps = data.split(":")

        height = int(height)

        fps = int(fps)

    except Exception:

        await query.edit_message_text(
            "❌ Invalid quality selection."
        )

        return

    url = context.user_data.get(
        "youtube_url"
    )

    if not url:

        await query.edit_message_text(

            "❌ YouTube link expired.\n"
            "🔄 Please send the link again."
        )

        return

    await query.edit_message_text(

        f"🚀✨ Download Started!\n\n"

        f"📺 Quality: {height}p\n"
        f"🎞️ FPS: {fps}\n"
        f"🔊 Audio: Best Available\n"
        f"💎 Video: Best Available\n\n"

        f"⏳📥 Downloading...\n"
        f"🕐💫 Please wait!"
    )

    try:

        with tempfile.TemporaryDirectory() as temp_folder:

            video_path = await asyncio.to_thread(

                download_youtube,

                url,

                temp_folder,

                height,

                fps,
            )

            if (
                not video_path
                or not os.path.exists(
                    video_path
                )
            ):

                await query.message.reply_text(

                    "❌ Failed to download this quality.\n"
                    "🔄 Please try another quality."
                )

                return

            file_size = os.path.getsize(
                video_path
            )

            file_size_mb = (
                file_size
                / (1024 * 1024)
            )

            # এখানে আর 50 MB reject করা হচ্ছে না
            await query.message.reply_text(

                f"📤🚀 Uploading your video...\n\n"
                f"📺 Quality: {height}p\n"
                f"🎞️ FPS: {fps}\n"
                f"🔊 Audio: Best Available\n"
                f"📦 Size: {file_size_mb:.1f} MB\n\n"
                f"☁️✨ Please wait..."
            )

            with open(
                video_path,
                "rb",
            ) as video_file:

                await query.message.reply_video(

                    video=video_file,

                    supports_streaming=True,

                    read_timeout=REQUEST_TIMEOUT,

                    write_timeout=REQUEST_TIMEOUT,

                    connect_timeout=60,

                    pool_timeout=60,
                )

    except Exception as e:

        print(
            "YOUTUBE DOWNLOAD/UPLOAD ERROR:",
            repr(e),
        )

        await query.message.reply_text(

            "❌ Could not upload the video.\n\n"

            "🔎 Check that the Local Telegram "
            "Bot API Server is running.\n\n"

            "📦 Large files require the local "
            "Bot API Server."
        )

    finally:

        context.user_data.pop(
            "youtube_url",
            None,
        )


# =========================================================
# MAIN
# =========================================================

def main():

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)

        # একই সময়ে 4 জন user-এর update process করবে
        .concurrent_updates(
            MAX_CONCURRENT_USERS
        )

        # Parallel Telegram requests-এর জন্য
        .connection_pool_size(32)

        .pool_timeout(60)

        .connect_timeout(60)

        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            youtube_quality_callback,
            pattern=r"^yt:",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link,
        )
    )

    print(
        "╔══════════════════════════════════╗"
    )

    print(
        "   🎬 Sihu Media Bot is running! 🚀"
    )

    print(
        "   👥 Multi User: ENABLED"
    )

    print(
        "   🔊 Best Audio • 💎 Best Video"
    )

    print(
        "╚══════════════════════════════════╝"
    )

    app.run_polling()


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    main()