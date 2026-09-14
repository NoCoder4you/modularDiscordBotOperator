import discord
from discord.ext import commands

ALLOWED_USER_ID = 298121351871594497

class LeaveServer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="leave")
    async def leave(self, ctx):
        if ctx.author.id != ALLOWED_USER_ID:
            await ctx.send("You do not have permission to use this command.", delete_after=10)
            return
        await ctx.send("Leaving server...")
        await ctx.guild.leave()

async def setup(bot):
    await bot.add_cog(LeaveServer(bot))
