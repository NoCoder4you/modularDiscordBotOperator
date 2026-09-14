import discord
from discord.ext import commands
import asyncio
import json
import os

from COGS.paths import data_path

NICEBLOCK_FILE = data_path("JSON/niceblock_users.json")

def load_enabled_users():
    if not os.path.isfile(NICEBLOCK_FILE):
        return []
    with open(NICEBLOCK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_enabled_users(users):
    with open(NICEBLOCK_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f)

class NiceBlock(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_users = load_enabled_users()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.author.id in self.enabled_users:
            reply = await message.channel.send("thats nice")
            await asyncio.sleep(0.5)
            try:
                await reply.delete()
            except discord.NotFound:
                pass
        await self.bot.process_commands(message)

    @commands.group()
    async def niceblock(self, ctx):
        """Enable or disable 'thats nice' for a user."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `!niceblock enable @user` or `!niceblock disable @user`.")

    @niceblock.command()
    async def enable(self, ctx, user: discord.Member):
        if user.id not in self.enabled_users:
            self.enabled_users.append(user.id)
            save_enabled_users(self.enabled_users)
            await ctx.send(f"Enabled 'thats nice' for {user.mention}.")
        else:
            await ctx.send(f"Already enabled for {user.mention}.")

    @niceblock.command()
    async def disable(self, ctx, user: discord.Member):
        if user.id in self.enabled_users:
            self.enabled_users.remove(user.id)
            save_enabled_users(self.enabled_users)
            await ctx.send(f"Disabled 'thats nice' for {user.mention}.")
        else:
            await ctx.send(f"Already disabled for {user.mention}.")

async def setup(bot):
    await bot.add_cog(NiceBlock(bot))
