"""Bot entry point — aiohttp server hosting Bot Framework + web chat endpoints."""

import logging
import os
import sys

from aiohttp import web
from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity

from config.settings import Settings
from bot.bot_handler import ChatBot
from agent.kernel import AgentKernel
from data.loader import DataLoader

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ── Settings ────────────────────────────────────────────
settings = Settings()

# ── Logging ─────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── Bot Framework adapter ──────────────────────────────
adapter_settings = BotFrameworkAdapterSettings(
    app_id=settings.microsoft_app_id,
    app_password=settings.microsoft_app_password,
    channel_auth_tenant=settings.microsoft_app_tenant_id or None,
)
adapter = BotFrameworkAdapter(adapter_settings)


async def _on_error(context: TurnContext, error: Exception) -> None:
    """Global error handler — logs the error and notifies the user."""
    logger.error("Unhandled bot error: %s", error, exc_info=True)
    await context.send_activity("Sorry, something went wrong. Please try again.")


adapter.on_turn_error = _on_error

# ── Data → Agent → Bot wiring ─────────────────────────
data_loader = DataLoader(settings)
agent_kernel = AgentKernel(settings, data_loader)
bot = ChatBot(agent_kernel)


# ── HTTP endpoint ──────────────────────────────────────
async def messages(req: web.Request) -> web.Response:
    """POST /api/messages — Bot Framework webhook."""
    try:
        body = await req.json()
        logger.info("Received activity type: %s", body.get("type", "unknown"))
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")

        response = await adapter.process_activity(activity, auth_header, bot.on_turn)

        if response:
            return web.json_response(data=response.body, status=response.status)
        return web.Response(status=201)
    except Exception as e:
        logger.error("Error processing request: %s", e, exc_info=True)
        return web.Response(status=500, text=str(e))


# ── Simple REST chat endpoint (web UI) ────────────────
async def chat_api(req: web.Request) -> web.Response:
    """POST /api/chat — simple JSON chat for the web UI."""
    try:
        body = await req.json()
        user_msg = (body.get("message") or "").strip()
        conv_id = body.get("conversation_id", "web-default")

        if not user_msg:
            return web.json_response({"reply": "Please send a message."})

        logger.info("Web chat [%s]: %s", conv_id, user_msg[:120])
        reply = await agent_kernel.ask(conv_id, user_msg)
        return web.json_response({"reply": reply})
    except Exception as e:
        logger.error("Chat API error: %s", e, exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


# ── Serve web UI ──────────────────────────────────────
async def index_page(req: web.Request) -> web.Response:
    """GET / — serve the chat web UI."""
    return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))


def main() -> None:
    """Start the aiohttp web server."""
    app = web.Application()
    app.router.add_get("/", index_page)
    app.router.add_post("/api/messages", messages)
    app.router.add_post("/api/chat", chat_api)
    app.router.add_static("/static", STATIC_DIR)

    logger.info("Bot listening on http://0.0.0.0:%s", settings.bot_port)
    logger.info("Web chat UI at  http://localhost:%s", settings.bot_port)
    web.run_app(app, host="0.0.0.0", port=settings.bot_port)


if __name__ == "__main__":
    main()
