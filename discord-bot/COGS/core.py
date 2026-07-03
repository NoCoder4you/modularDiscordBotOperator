"""Core slash commands for basic bot and guild information."""
from __future__ import annotations

import platform
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands


def _format_uptime(started_at: datetime) -> str:
    delta = datetime.now(timezone.utc) - started_at
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"


def _require_guild(interaction: discord.Interaction) -> discord.Guild:
    if interaction.guild is None:
        raise app_commands.NoPrivateMessage()
    return interaction.guild


class Core(commands.Cog):
    """Core multi-server-safe slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Send a clear message when a guild-only command is used in DMs."""
        if isinstance(error, app_commands.NoPrivateMessage):
            message = "This command can only be used inside a Discord server."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        raise error

    @app_commands.command(name="ping", description="Show bot latency and server context.")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Respond with latency and current guild details."""
        guild = _require_guild(interaction)
        embed = discord.Embed(title="Pong!", colour=discord.Colour.green())
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)} ms", inline=True)
        embed.add_field(name="Status", value="Online", inline=True)
        embed.add_field(name="Current Server", value=guild.name, inline=False)
        embed.add_field(name="Server ID", value=str(guild.id), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botinfo", description="Show bot runtime information.")
    async def botinfo(self, interaction: discord.Interaction) -> None:
        """Respond with bot details and current guild context."""
        guild = _require_guild(interaction)
        user = self.bot.user
        startup_time = getattr(self.bot, "startup_time")
        embed = discord.Embed(title="Bot Information", colour=discord.Colour.blurple())
        embed.add_field(name="Bot Username", value=str(user), inline=True)
        embed.add_field(name="Bot User ID", value=str(user.id if user else "unknown"), inline=True)
        embed.add_field(name="Connected Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Loaded Cogs", value=str(len(self.bot.cogs)), inline=True)
        embed.add_field(name="Python Version", value=platform.python_version(), inline=True)
        embed.add_field(name="discord.py Version", value=discord.__version__, inline=True)
        embed.add_field(name="Uptime", value=_format_uptime(startup_time), inline=False)
        embed.add_field(name="Current Server", value=guild.name, inline=False)
        embed.add_field(name="Current Server ID", value=str(guild.id), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Show information about this server.")
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        """Respond with information only for the guild where the command ran."""
        guild = _require_guild(interaction)
        embed = discord.Embed(title="Server Information", colour=discord.Colour.green())
        embed.add_field(name="Server Name", value=guild.name, inline=True)
        embed.add_field(name="Server ID", value=str(guild.id), inline=True)
        embed.add_field(name="Server Owner", value=str(guild.owner or guild.owner_id), inline=False)
        embed.add_field(name="Member Count", value=str(guild.member_count or 0), inline=True)
        embed.add_field(name="Channel Count", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Role Count", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, style="F"), inline=False)
        joined_at = guild.me.joined_at if guild.me and guild.me.joined_at else None
        embed.add_field(
            name="Bot Joined",
            value=discord.utils.format_dt(joined_at, style="F") if joined_at else "Unknown",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    """Load the Core cog extension."""
    await bot.add_cog(Core(bot))
