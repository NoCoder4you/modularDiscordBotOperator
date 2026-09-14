import discord
from discord import app_commands
from discord.ext import commands
import json
import os

from COGS.paths import data_path

# Role IDs
ALLOWED_ROLES = {1315693406336450570, 1248310818693582920}
VERIFIED_ROLE_ID = 1277489459226738808
AWAITING_ROLE_ID = 1248310200939581594

class VerificationAdminReset(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.server_data_path = data_path("JSON/server.json")

    def load_server_data(self):
        if os.path.exists(self.server_data_path):
            with open(self.server_data_path, "r", encoding="utf-8") as file:
                return json.load(file)
        return {"verified_users": [], "channels": {"verification": None}}

    def save_server_data(self, data):
        with open(self.server_data_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)

    def has_admin_role(self, member: discord.Member) -> bool:
        return any(role.id in ALLOWED_ROLES for role in member.roles)

    va = app_commands.Group(name="va", description="Administrative commands for server management.")

    @va.command(name="reset", description="Reset a user's verification (admin only).")
    async def reset_verification(self, interaction: discord.Interaction, user: discord.Member):
        if not self.has_admin_role(interaction.user):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You do not have permission to use this command.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        server_data = self.load_server_data()
        before_count = len(server_data.get("verified_users", []))
        # Remove user from verified_users list
        server_data["verified_users"] = [
            u for u in server_data.get("verified_users", [])
            if str(u.get("user_id")) != str(user.id)
        ]
        self.save_server_data(server_data)
        after_count = len(server_data["verified_users"])

        # Only do role swap if the user was actually unverified
        if before_count != after_count:
            verified_role = user.guild.get_role(VERIFIED_ROLE_ID)
            awaiting_role = user.guild.get_role(AWAITING_ROLE_ID)
            actions = []
            try:
                if verified_role in user.roles:
                    await user.remove_roles(verified_role, reason="Reset verification (verifyadmin command)")
                    actions.append(f"Removed **Verified** role")
                if awaiting_role not in user.roles:
                    await user.add_roles(awaiting_role, reason="Reset verification (verifyadmin command)")
                    actions.append(f"Added **Awaiting Verification** role")
            except discord.Forbidden:
                actions.append(":warning: Could not edit roles due to permissions.")

            description = (
                f"Verification for {user.mention} has been **reset** and they were removed from verified users."
                + ("\n" + "\n".join(actions) if actions else "")
            )
            embed = discord.Embed(
                title="Verification Reset",
                description=description,
                color=discord.Color.red()
            )
        else:
            embed = discord.Embed(
                title="Verification Reset",
                description=f"User {user.mention} was **not found** in the verified users list.",
                color=discord.Color.orange()
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(VerificationAdminReset(bot))
