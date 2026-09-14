import discord
from discord.ext import commands
import asyncio

class PurgeChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="purgeall")
    async def purgeall(self, ctx):
        await ctx.send("Starting channel purge...", delete_after=5)
        channel = ctx.channel
        deleted = 0
        try:
            while True:
                messages = [msg async for msg in channel.history(limit=100)]
                if not messages:
                    break
                await channel.delete_messages(messages)
                deleted += len(messages)
                await asyncio.sleep(2)
            await ctx.send(f"Channel purge complete! {deleted} messages deleted.", delete_after=10)
        except discord.Forbidden:
            await ctx.send("I do not have permission to delete messages.", delete_after=10)
        except discord.HTTPException as e:
            await ctx.send(f"An error occurred: {e}", delete_after=10)

async def setup(bot):
    await bot.add_cog(PurgeChat(bot))
