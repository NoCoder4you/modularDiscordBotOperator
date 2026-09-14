import json
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta

from COGS.paths import data_path

class AnnouncerCog(commands.Cog):
    def __init__(self, bot, config_path=None):
        self.bot = bot
        self.config_path = config_path or data_path("JSON/server.json")
        self.announcement_channel_id = self._load_announcement_channel_id()
        self.scheduler = AsyncIOScheduler()
        self.external_emoji = "<:Pay:1305265714042765483>"  # Replace if needed
        self.unicode_emoji = "<:moneybag:>"                           # Fallback emoji
        self._schedule_announcements()
        self.scheduler.start()

    # ??????????????????????????????????????????????????????????
    # Helper methods
    # ??????????????????????????????????????????????????????????
    def _load_announcement_channel_id(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                return config["channels"]["payannounce"]
        except (KeyError, FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"[PayAnnounce] Error loading announcement channel ID: {exc}")
            return None

    def _schedule_announcements(self):
        # (hour, minute, event label, role ID)
        times = [
            (23, 45, "12:00 AM", "1378512350981914634"),  # 12 ? 1 AM
            (0,  45, "1:00 AM",  "1378511887368585266"),  # 1 ? 2 AM
            (5,  45, "6:00 AM",  "1378511110025511002"),  # 6 ? 7 AM
            (6,  45, "7:00 AM",  "1378511732921733211"),  # 7 ? 8 AM
            (11, 45, "12:00 PM", "1378512513729040507"),  # 12 ? 1 PM
            (12, 45, "1:00 PM",  "1378512026158235689"),  # 1 ? 2 PM
            (17, 45, "6:00 PM",  "1378512129564479558"),  # 6 ? 7 PM
            (18, 45, "7:00 PM",  "1378512208366931998"),  # 7 ? 8 PM
        ]

        for hour, minute, label, role_id in times:
            self.scheduler.add_job(
                self._send_announcement,
                CronTrigger(hour=hour, minute=minute),
                args=[label, role_id],
            )

    # ??????????????????????????????????????????????????????????
    # Announcement task
    # ??????????????????????????????????????????????????????????
    async def _send_announcement(self, event_label: str, role_id: str):
        if not self.announcement_channel_id:
            print("[PayAnnounce] Announcement channel ID not set.")
            return

        channel = self.bot.get_channel(self.announcement_channel_id)
        if not channel:
            print("[PayAnnounce] Could not fetch announcement channel.")
            return

        # Use external emoji if the bot can; otherwise, fall back to Unicode
        emoji = (
            self.external_emoji
            if channel.guild.me.guild_permissions.use_external_emojis
            else self.unicode_emoji
        )

        # Parse event_label like "12:00 AM" ? timestamp for the next occurrence
        time_str, period = event_label.split(" ")
        hour, minute = map(int, time_str.split(":"))

        if period == "AM":
            hour = 0 if hour == 12 else hour
        else:  # PM
            hour = hour if hour == 12 else hour + 12

        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target < now:
            target += timedelta(days=1)

        ts = int(target.timestamp())

        await channel.send(
            f"# {emoji} Pay Time: {event_label} {emoji}\n"
            f"## Pay begins at <t:{ts}:T> (<t:{ts}:R>).\n"
            f"## <@&{role_id}>"
        )


# ??????????????????????????????????????????????????????????????
# Cog setup entry-point
# ??????????????????????????????????????????????????????????????
async def setup(bot):
    await bot.add_cog(AnnouncerCog(bot))
