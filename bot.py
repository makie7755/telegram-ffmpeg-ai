import os
import json
import asyncio
import logging
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from openai import OpenAI

from video_editor import render_video, probe_video

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
log = logging.getLogger("video-bot")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
ALLOWED_IDS = {
    int(x.strip()) for x in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    if x.strip()
}
if not ALLOWED_IDS:
    raise RuntimeError("Set TELEGRAM_ALLOWED_USER_IDS to your Telegram numeric user ID.")

client = OpenAI(api_key=OPENAI_API_KEY)

AI_INSTRUCTIONS = """
You are an assistant that translates a user's video-editing request into a safe JSON plan.
Return ONLY JSON with this exact shape:
{
  "reply": "short friendly explanation in Filipino",
  "operations": [
    {"op":"trim","start":"00:00:05","duration":"00:00:20"},
    {"op":"resize","width":1920,"height":1080},
    {"op":"compress","crf":23},
    {"op":"convert","format":"mp4"}
  ]
}
Allowed operations only: trim, resize, compress, convert.
Rules:
- Use [] if the user has not given an editing request yet.
- trim requires start and duration in HH:MM:SS format. Never invent missing values; if missing, return [] and ask a question in reply.
- resize requires width and height. Allowed target pairs: 1280x720, 1920x1080, 3840x2160.
- compress accepts crf integer 18 through 30; use 23 unless user specifies quality.
- convert format must be mp4 or mkv.
- Do not include shell commands, paths, arbitrary filters, URLs, or extra keys.
- If user asks for unsupported features (music, subtitles, transitions, effects, overlays), explain briefly that these are not in this first version and return [].
- Reply in the user's language, preferably Filipino/Taglish.
"""

def authorized(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id in ALLOWED_IDS)

async def reject_if_unauthorized(update: Update) -> bool:
    if not authorized(update):
        if update.effective_message:
            await update.effective_message.reply_text("Paumanhin, hindi ka authorized gumamit ng bot na ito.")
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    await update.message.reply_text(
        "Hello! Ako ang AI FFmpeg Video Editor.\\n\\n"
        "1) I-send ang video bilang Telegram video.\\n"
        "2) Pagkatapos, i-send ang editing instruction, halimbawa: "
        "'I-trim mula 00:00:05 nang 20 seconds at gawing 1080p'.\\n\\n"
        "Supported sa unang version: trim, resize, compress, convert.\\n"
        "/help para sa guide."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    await update.message.reply_text(
        "Workflow: send video muna, saka i-send ang instruction.\\n"
        "Examples:\\n"
        "• I-trim mula 00:00:10 nang 15 seconds\\n"
        "• Gawing 1080p\\n"
        "• I-compress, balanced quality\\n"
        "• I-convert sa mp4\\n\\n"
        "Tip: Isang video lang ang naka-queue bawat user. "
        "Sa MVP na ito, hanggang 20 MB ang incoming download limit ng Telegram cloud Bot API."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    await update.message.reply_text("Online ako. FFmpeg: " + await ffmpeg_version())

async def ffmpeg_version():
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-version",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return out.decode(errors="ignore").splitlines()[0] if proc.returncode == 0 else "not available"

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    msg = update.effective_message
    media = msg.video or msg.document
    if not media:
        return
    if msg.document and not (msg.document.mime_type or "").startswith("video/"):
        await msg.reply_text("Paki-send ang video file (MP4, MOV, MKV, atbp.).")
        return
    if media.file_size and media.file_size > 20 * 1024 * 1024:
        await msg.reply_text("Lampas 20 MB ang file. Limit ito ng Telegram cloud Bot API download sa setup na ito.")
        return

    workdir = Path(tempfile.mkdtemp(prefix=f"video_{update.effective_user.id}_"))
    input_path = workdir / "input_video"
    try:
        tg_file = await context.bot.get_file(media.file_id)
        await tg_file.download_to_drive(custom_path=input_path)
        context.user_data["video_path"] = str(input_path)
        context.user_data["workdir"] = str(workdir)
        info = await asyncio.to_thread(probe_video, str(input_path))
        await msg.reply_text(
            f"Natanggap ko ang video. Duration: {info.get('duration', 'unknown')} sec.\\n"
            "Ngayon, i-send ang editing instruction mo."
        )
    except Exception:
        log.exception("Video download/probe failed")
        await msg.reply_text("Hindi ko ma-process ang video. Subukan ulit gamit ang mas maliit na file.")

async def plan_with_ai(request: str) -> dict:
    response = await asyncio.to_thread(
        client.responses.create,
        model=MODEL,
        instructions=AI_INSTRUCTIONS,
        input=request,
    )
    return json.loads(response.output_text)

async def handle_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_unauthorized(update):
        return
    msg = update.effective_message
    video_path = context.user_data.get("video_path")
    if not video_path or not Path(video_path).exists():
        await msg.reply_text("Wala pa akong natatanggap na video. I-send muna ang video bago ang instruction.")
        return

    await msg.reply_text("Iniintindi ko ang instruction mo...")
    try:
        plan = await plan_with_ai(msg.text or "")
        operations = plan.get("operations", [])
        reply = plan.get("reply", "Narito ang editing plan.")
        if not operations:
            await msg.reply_text(reply)
            return

        await msg.reply_text("Sisimulan ko na ang rendering. Hintayin ang finished video...")
        output_path = str(Path(context.user_data["workdir"]) / "edited_output.mp4")
        output_path = await asyncio.to_thread(render_video, video_path, output_path, operations)
        if Path(output_path).stat().st_size > 49 * 1024 * 1024:
            await msg.reply_text("Tapos na ang render pero lampas sa 49 MB ang output. Hindi ito maipapadala ng bot sa Telegram cloud API.")
        else:
            with open(output_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename="edited_video.mp4",
                    caption="Tapos na! Narito ang edited video."
                )
        # Remove job files after delivery attempt.
        import shutil
        shutil.rmtree(context.user_data.get("workdir", ""), ignore_errors=True)
        context.user_data.pop("video_path", None)
        context.user_data.pop("workdir", None)
    except json.JSONDecodeError:
        log.exception("AI returned invalid JSON")
        await msg.reply_text("Hindi ko naintindihan ang editing plan. Paki-rephrase ang instruction.")
    except Exception:
        log.exception("Editing failed")
        await msg.reply_text("Nagkaroon ng error sa pag-edit. Tingnan ang Render logs para sa detalye.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, receive_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_instruction))
    log.info("Starting Telegram FFmpeg AI bot")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
