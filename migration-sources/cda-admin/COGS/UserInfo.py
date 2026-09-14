import discord
import json
import aiohttp
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from COGS.paths import data_path

# Donator Role Color Mapping (HEX)
DONATOR_COLORS = {
    "Emerald": 0x3CFF00,
    "Sapphire": 0x0F52BA,
    "Ruby": 0xFF0000,  # Red
    "Diamond": 0x00FFFB,  # Light Blue
    "Gold": 0xD6B300,  # Gold
    "Silver": 0xC0C0C0,  # Silver
    "Bronze": 0x854200,  # Bronze
    "None": 0x2C2F33  # Discord Default Dark Gray
}

# Load server.json and rolesbadges.json
with open(data_path("JSON/server.json"), "r", encoding="utf-8") as server_file:
    server_data = json.load(server_file)

with open(data_path("JSON/rolesbadges.json"), "r", encoding="utf-8") as roles_file:
    roles_data = json.load(roles_file)

class UserInfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_habbo_username(self, discord_id: str):
        """Find Habbo username for a given Discord user ID."""
        for user in server_data.get("verified_users", []):
            if user["user_id"] == discord_id:
                return user["habbo"]
        return None

    def get_highest_role(self, discord_member: discord.Member, role_category: str):
        """Get the highest role for a given category (EmployeeRoles or DonatorRoles)."""
        all_roles = roles_data.get("roles", {}).get(role_category, [])
        user_roles = {r.id: r for r in discord_member.roles}

        for role in all_roles:
            if role["role_id"] in user_roles:
                return role["role_name"]
        return None

    def get_multiple_roles(self, discord_member: discord.Member, role_category: str):
        """Retrieve all roles from a given category (SpecialUnits or Misc)."""
        all_roles = roles_data.get("roles", {}).get(role_category, [])
        user_roles = {r.id: r for r in discord_member.roles}

        category_roles = [role["role_name"] for role in all_roles if role["role_id"] in user_roles]
        return " ".join(category_roles) if category_roles else "None"

    def format_timestamp(self, iso_timestamp: str):
        """Converts ISO timestamp to human-readable format."""
        try:
            dt = datetime.strptime(iso_timestamp[:19], "%Y-%m-%dT%H:%M:%S")
            return dt.strftime("%d %B %Y at %H:%M UTC")  # Example: "August 10, 2006 at 15:24 UTC"
        except (ValueError, TypeError):
            return "Unknown"

    async def fetch_habbo_profile(self, habbo_name: str):
        """Fetch user profile details from the Habbo API."""
        url = f"https://www.habbo.com/api/public/users?name={habbo_name}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
        return None

    @app_commands.command(name="info", description="Fetch Habbo details of a verified user.")
    async def info(self, interaction: discord.Interaction, member: discord.Member):
        """Handles the /info command."""
        await interaction.response.defer()

        # Get Habbo username
        habbo_name = self.get_habbo_username(str(member.id))
        if not habbo_name:
            embed = discord.Embed(
                title="User Not Verified \u274C",
                description=f"{member.mention} has **not** linked a Habbo account.",
                color=discord.Color.red()
            )
            embed.set_footer(text="Verification required to access Habbo details.")
            await interaction.followup.send(embed=embed)
            return

        # Fetch Habbo profile details
        habbo_data = await self.fetch_habbo_profile(habbo_name)
        if not habbo_data:
            await interaction.followup.send(f"Could not retrieve data for Habbo user: `{habbo_name}`.")
            return

        # Extract necessary profile details
        unique_id = habbo_data.get("uniqueId", "Unknown")
        motto = habbo_data.get("motto", "No motto")
        online_status = "Online \u2705" if habbo_data.get("online", False) else "Offline \u274C"
        last_access = self.format_timestamp(habbo_data.get("lastAccessTime"))
        member_since = self.format_timestamp(habbo_data.get("memberSince"))
        profile_visible = "Visible \u2705" if habbo_data.get("profileVisible", False) else "Hidden \u274C"

        # Get highest EmployeeRole, highest DonatorRole, all SpecialUnits roles, and all Misc roles
        highest_employee_role = self.get_highest_role(member, "EmployeeRoles") or "No assigned division"
        highest_donator_role = self.get_highest_role(member, "DonatorRoles") or "None"
        special_units_roles = self.get_multiple_roles(member, "SpecialUnits")
        misc_roles = self.get_multiple_roles(member, "Misc")
        
        embed_color = DONATOR_COLORS.get(highest_donator_role, 0x2C2F33)

        # Create embed response
        embed = discord.Embed(title=f"Habbo Profile: {habbo_name}", color=embed_color)
        embed.set_thumbnail(url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo_name}&gesture=sml&direction=4&head_direction=4&size=l")
        embed.add_field(name="Unique ID", value=unique_id, inline=False)
        embed.add_field(name="Motto", value=motto, inline=True)
        embed.add_field(name="Status", value=online_status, inline=True)
        embed.add_field(name="Profile Visibility", value=profile_visible, inline=True)
        embed.add_field(name="Last Access", value=last_access, inline=True)
        embed.add_field(name="Member Since", value=member_since, inline=True)
        embed.add_field(name="Donator Level", value=highest_donator_role, inline=False)
        embed.add_field(name="Employee Division", value=highest_employee_role, inline=True)
        embed.add_field(name="Special Units", value=special_units_roles, inline=True)
        embed.add_field(name="Misc Roles", value=misc_roles, inline=True)
        embed.set_footer(text="Habbo Info \u2705")

        await interaction.followup.send(embed=embed)

# Add cog to bot
async def setup(bot):
    await bot.add_cog(UserInfoCog(bot))
