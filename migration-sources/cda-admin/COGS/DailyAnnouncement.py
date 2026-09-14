from discord.ext import commands
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import discord
import asyncio

class DailyAnnouncement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = BackgroundScheduler()
        self.channel_id = 1293689337065508928  # Replace with your channel ID
        self.start_scheduler()

    def start_scheduler(self):
        # Schedule the announcement at 12 AM UTC (UK Time without daylight saving)
        self.scheduler.add_job(
            self.sync_announcement,  # Use a synchronous wrapper for the async method
            CronTrigger(hour=0, minute=0, timezone="UTC"),  # 12 AM UK Time
            id="daily_announcement",
            replace_existing=True
        )
        self.scheduler.start()

    def sync_announcement(self):
        # Run the async method in the bot's event loop
        asyncio.run_coroutine_threadsafe(
            self.daily_announcement(), self.bot.loop
        )

    async def daily_announcement(self):
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            # Customize the message with external and Unicode emojis
            heart = ":heart:"
            cda_emoji = "<:CDA:1268920299127308308>"
            message = f"# {heart} {cda_emoji} NEW DAY FOR COLLECTING BONUS PAYS! {cda_emoji} {heart}"
            await channel.send(message)
        else:
            print(f"Channel with ID {self.channel_id} not found.")

    def cog_unload(self):
        self.scheduler.shutdown()

async def setup(bot):
    await bot.add_cog(DailyAnnouncement(bot))
