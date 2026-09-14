import asyncio
import datetime

import discord
from discord.ext import commands, tasks


AWAITING_ROLE_ID = 1248310200939581594
TIMEOUT_HOURS = 24
RATE_LIMIT_DELAY = 2.5
KICK_REASON = "Removed - Awaiting Verification for over 24 hours"


class AwaitingVerificationCleanup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cleanup_task.start()

    @tasks.loop(minutes=15)
    async def cleanup_task(self):
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=TIMEOUT_HOURS)
        for guild in self.bot.guilds:
            role = guild.get_role(AWAITING_ROLE_ID)
            if role is None:
                continue
            for member in role.members:
                joined_at = member.joined_at
                if joined_at is None or joined_at > cutoff:
                    continue
                try:
                    await member.send(
                        "You are being removed because you remained in the Awaiting Verification role for over 24 hours."
                    )
                except discord.HTTPException:
                    pass
                try:
                    await member.kick(reason=KICK_REASON)
                except (discord.Forbidden, discord.HTTPException):
                    continue
                await asyncio.sleep(RATE_LIMIT_DELAY)

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(AwaitingVerificationCleanup(bot))
