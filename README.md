# Telegram FFmpeg AI Video Editor (MVP)

A Telegram bot hosted as a Render Background Worker. It uses OpenAI to interpret editing instructions and FFmpeg to execute a restricted set of operations.

## Included in this first version
- Telegram video upload
- AI instruction parsing (Filipino/English)
- Trim, resize (720p/1080p/4K), compress, convert (MP4/MKV)
- Sends the rendered file back to Telegram
- User ID allowlist

Not included yet: music mixing, subtitles, transitions, effects, overlays, multi-clip merge, persistent job queue, and large-file Telegram Local Bot API support.

## Before deployment
1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Create an OpenAI API key at [OpenAI API keys](https://platform.openai.com/api-keys). API usage is billed separately from a ChatGPT subscription.
3. Get your numeric Telegram user ID using a trusted user-ID bot, then put it in `TELEGRAM_ALLOWED_USER_IDS`.
4. Push this folder to a GitHub repository.

## Deploy to Render
1. In Render, choose **New +** -> **Blueprint** and connect the GitHub repository, or create a Background Worker using this repository and Dockerfile.
2. If using Blueprint, Render reads `render.yaml`.
3. Set `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, and `TELEGRAM_ALLOWED_USER_IDS` in the Render environment settings.
4. Deploy and check the worker logs.

Do not commit `.env`, bot tokens, or API keys to GitHub.

## How to use
1. Open your Telegram bot and send `/start`.
2. Send a video (Telegram cloud Bot API download limit in this MVP: 20 MB).
3. Send a separate text instruction, e.g. `I-trim mula 00:00:05 nang 20 seconds at gawing 1080p`.
4. Wait for the output.

## Notes and limitations
- Render worker local disk is ephemeral. This MVP processes files temporarily and deletes job files after sending the output. Do not expect files to survive restarts.
- Telegram's hosted Bot API has file transfer limits; this MVP rejects incoming videos above 20 MB and outputs above 49 MB. A self-hosted Telegram Local Bot API server or external object storage is a later upgrade.
- Video rendering uses CPU and can take time. Choose a Render worker plan with enough CPU/RAM for your video sizes.
- The AI only produces a JSON editing plan. The application validates operations and constructs FFmpeg arguments itself; it never executes AI-generated shell commands.
- This is an MVP starter project, not a production-grade multi-user job queue.
