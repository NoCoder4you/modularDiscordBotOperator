import json
from discord import app_commands
import discord
from discord.ext import commands

from COGS.paths import data_path

SERVER_FILE = data_path("JSON/server.json")


def load_verified_users():
    try:
        with open(SERVER_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            users = set(str(user["user_id"]) for user in data.get("verified_users", []))
            return users
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading verified users: {e}")
        return set()


verified_users = load_verified_users()


def is_verified():
    async def predicate(interaction: discord.Interaction):
        verified = discord.utils.get(interaction.user.roles, name="Verified")
        if verified:
            return True
        await interaction.response.send_message("/verify", ephemeral=True)
        return False

    return app_commands.check(predicate)


def has_grinch_role():
    async def predicate(interaction: discord.Interaction):
        grinch_role = discord.utils.get(interaction.user.roles, name="Grinch")
        if grinch_role:
            return True
        await interaction.response.send_message("Nice Try ;D", ephemeral=True)
        return False

    return app_commands.check(predicate)


def has_authorised_role():
    async def predicate(interaction: discord.Interaction):
        discAdmin = discord.utils.get(interaction.user.roles, name="Discord Admins")
        verified = discord.utils.get(interaction.user.roles, name="Verified")
        if discAdmin:
            if verified:
                return True
        await interaction.response.send_message("You do not have the required 'Discord Admins' role.", ephemeral=True)
        return False

    return app_commands.check(predicate)


class BotCheckCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot):
    await bot.add_cog(BotCheckCog(bot))
