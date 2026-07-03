"""Startup entry point for the multi-server modular Discord bot."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands

from config import ConfigError, load_config
from UTILS.data_manager import ensure_data_root, ensure_guild_data
from UTILS.logger import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)
COGS_DIR = Path(__file__).resolve().parent / "COGS"


class ModularDiscordBot(commands.Bot):
    """Discord bot with automatic cog loading and multi-guild data setup."""

    def __init__(self) -> None:
        self.config = load_config()
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = False
        super().__init__(
            command_prefix=self.config.command_prefix,
            intents=intents,
            owner_id=self.config.owner_id,
            help_command=None,
        )
        self.startup_time = datetime.now(timezone.utc)
        self._ready_logged = False

    async def setup_hook(self) -> None:
        """Prepare data directories, load cogs, and sync slash commands."""
        await ensure_data_root()
        await self._load_cogs()
        await self._sync_commands()

    async def _load_cogs(self) -> None:
        """Load all valid Python extension modules from the uppercase COGS package."""
        for path in sorted(COGS_DIR.glob("*.py")):
            if path.name == "__init__.py" or path.name.startswith("_"):
                continue
            extension = f"COGS.{path.stem}"
            try:
                await self.load_extension(extension)
                logger.info("Loaded extension %s", extension)
            except Exception:
                logger.exception("Failed to load extension %s; continuing startup.", extension)

    async def _sync_commands(self) -> None:
        """Sync slash commands globally or to a development test guild."""
        if self.config.test_guild_id:
            guild = discord.Object(id=self.config.test_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(
                "Synced %s slash command(s) to test guild ID %s for development.",
                len(synced),
                self.config.test_guild_id,
            )
            return
        synced = await self.tree.sync()
        logger.info("Synced %s slash command(s) globally.", len(synced))

    async def on_ready(self) -> None:
        """Log the first ready event without duplicating startup messages."""
        if self._ready_logged:
            return
        self._ready_logged = True
        logger.info(
            "Bot ready as %s (%s) in %s guild(s).",
            self.user,
            self.user.id if self.user else "unknown",
            len(self.guilds),
        )

    async def on_disconnect(self) -> None:
        """Log gateway disconnects."""
        logger.warning("Bot disconnected from Discord gateway.")

    async def on_resumed(self) -> None:
        """Log successful gateway session resumes."""
        logger.info("Bot resumed Discord gateway session.")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Create initial guild data when invited to a server."""
        logger.info("Joined guild %s (%s).", guild.name, guild.id)
        await ensure_guild_data(guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Log guild removal while preserving data for future re-invites."""
        logger.info("Removed from guild %s (%s); preserving guild data.", guild.name, guild.id)

    async def on_command_error(
        self,
        context: commands.Context[commands.Bot],
        exception: commands.CommandError,
    ) -> None:
        """Handle legacy text-command errors without leaking sensitive data."""
        logger.warning("Command error in %s: %s", context.command, exception)

    async def close(self) -> None:
        """Log graceful shutdown before closing the Discord connection."""
        logger.info("Shutting down bot.")
        await super().close()


async def main() -> None:
    """Run the bot until shutdown."""
    try:
        bot = ModularDiscordBot()
    except ConfigError as exc:
        logger.critical("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    async with bot:
        await bot.start(bot.config.discord_token, reconnect=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Shutdown requested by keyboard interrupt.")
