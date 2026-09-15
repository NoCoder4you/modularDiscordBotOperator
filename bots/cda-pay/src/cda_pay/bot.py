"""CDA Pay Discord client and standalone lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord.ext import commands

from shared.heartbeat import HeartbeatReporter
from shared.bot_core.logging import configure_logging

from .config import CDAPayConfig

BOT_ID = "cda-pay"
COG_PACKAGE = "cda_pay.cogs"
logger = logging.getLogger(f"bot.{BOT_ID}")


def discover_extensions() -> list[str]:
    directory = Path(__file__).with_name("cogs")
    return sorted(
        f"{COG_PACKAGE}.{path.stem}"
        for path in directory.glob("*.py")
        if not path.name.startswith("__") and path.stem != "paths"
    )


class CDAPayBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="noah ", intents=discord.Intents.all(), help_command=None)
        self.owner_id = 298121351871594497

    async def setup_hook(self) -> None:
        for extension in discover_extensions():
            try:
                await self.load_extension(extension)
                logger.info("Loaded extension %s", extension)
            except Exception:
                logger.exception("Failed to load extension %s", extension)
        logger.info("CDA Pay setup complete; %d application commands registered", len(self.tree.get_commands()))

    async def on_ready(self) -> None:
        logger.info("Discord READY as %s", self.user)

    async def close(self) -> None:
        logger.info("CDA Pay shutdown requested")
        await super().close()


bot = CDAPayBot()
heartbeat_reporter = HeartbeatReporter("cda-pay", logger=logger)
heartbeat_reporter.attach(bot)


@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx: commands.Context) -> None:
    await bot.tree.sync()
    await ctx.send("Commands synchronized.", delete_after=2.5)


@bot.command(name="stop")
@commands.is_owner()
async def stop_bot(ctx: commands.Context) -> None:
    await bot.close()


def main() -> None:
    config = CDAPayConfig.from_env()
    global logger
    logger = configure_logging(BOT_ID, config.log_level)
    logger.info("Starting CDA Pay")
    try:
        bot.run(config.token, log_handler=None)
    finally:
        logger.info("CDA Pay stopped")
