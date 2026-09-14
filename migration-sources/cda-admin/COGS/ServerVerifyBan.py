import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import json
import os
from COGS.BotCheck import has_authorised_role
from COGS.paths import data_path


class BanOnSightCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.verification_file = data_path("JSON/server.json")
        self.punishment_file = data_path("JSON/punishment.json")
        self.verified_role_id = 1320054879477170299  # Replace with your Verified role ID
        self.load_data()

    def load_data(self):
        """Load verification and punishment data."""
        if os.path.exists(self.verification_file):
            with open(self.verification_file, "r", encoding="utf-8") as file:
                self.verification_data = json.load(file)
        else:
            self.verification_data = {"verified_users": [], "channels": {}}

        if os.path.exists(self.punishment_file):
            with open(self.punishment_file, "r", encoding="utf-8") as file:
                self.punishment_data = json.load(file)
        else:
            self.punishment_data = {"banned_users": {"BoS": {}, "DNH": {}, "NP": {}}, "banned_groups": []}

        # Ensure banned_users structure exists
        self.punishment_data.setdefault("banned_users", {})
        for category in ["BoS", "DNH", "NP"]:
            self.punishment_data["banned_users"].setdefault(category, {})

    def save_punishment_data(self):
        """Save punishment data back to the file."""
        with open(self.punishment_file, "w", encoding="utf-8") as file:
            json.dump(self.punishment_data, file, indent=4)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        before_roles = set(before.roles)
        after_roles = set(after.roles)

        # Check if a verified role is added
        verified_role = discord.utils.get(after.guild.roles, id=self.verified_role_id)
        if verified_role and verified_role not in before_roles and verified_role in after_roles:
            user_id = str(after.id)

            # Debug: Log available verification data
            print(f"Verification data loaded: {self.verification_data.get('verified_users', [])}")

            # Fetch verification data
            verified_user = next(
                (user for user in self.verification_data.get("verified_users", []) if user["user_id"] == user_id), None
            )
            if not verified_user:
                print(f"No verification data found for user {after.name} (user_id: {user_id}).")
                return

            habbo_name = verified_user.get("habbo")
            hotel = verified_user.get("hotel", "com")

            if not habbo_name:
                print(f"No Habbo username found for user {after.name}.")
                return

            # Check banned lists
            banned_lists = []
            for list_type, users in self.punishment_data.get("banned_users", {}).items():
                if habbo_name in users:
                    banned_lists.append(list_type)

            if banned_lists:
                print(f"User {after.name} (user_id: {user_id}) is on the banned lists: {banned_lists}")

            # Fetch Habbo API data
            habbo_user_url = f"https://www.habbo.{hotel}/api/public/users?name={habbo_name}"
            habbo_groups_url_template = f"https://www.habbo.com/api/public/users/{{}}/groups"
            matched_banned_groups = []

            async with aiohttp.ClientSession() as session:
                try:
                    # Fetch Habbo user details
                    async with session.get(habbo_user_url) as user_response:
                        if user_response.status != 200:
                            print(f"Failed to fetch user info for {habbo_name}. Status: {user_response.status}")
                            return

                        user_data = await user_response.json()
                        habbo_id = user_data.get("uniqueId")
                        if not habbo_id:
                            print(f"Habbo ID not found for user: {habbo_name}")
                            return

                    # Fetch Habbo user groups
                    habbo_groups_url = habbo_groups_url_template.format(habbo_id)
                    async with session.get(habbo_groups_url) as groups_response:
                        if groups_response.status != 200:
                            print(f"Failed to fetch groups for user {habbo_name}. Status: {groups_response.status}")
                            return

                        groups_data = await groups_response.json()

                    # Check groups against banned list
                    banned_group_ids = {group["badge_id"] for group in self.punishment_data["banned_groups"]}
                    matched_banned_groups = [
                        group for group in groups_data if group.get("id") in banned_group_ids
                    ]

                except Exception as e:
                    print(f"Error during Habbo group check: {str(e)}")

            # Ban the user if they are on banned lists or in banned groups
            if banned_lists or matched_banned_groups:
                reasons = []
                if banned_lists:
                    reasons.append(f"You are currently on: **{', '.join(banned_lists)}**")
                if matched_banned_groups:
                    reasons.append("You are currently in a banned group.\n Please leave the group - Speak to a member of Foundation with CDA for reconsideration")

                reason = " | ".join(reasons)

                # Notify user via DM
                try:
                    embed = discord.Embed(
                        title="Banned From The CDA Server",
                        description=(
                            f"**Reason:** \n{reason}\n"
                            "If you believe this is a mistake, or would like to **appeal**, please contact the Foundation team."
                        ),
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Automatic Ban Notification")
                    await after.send(embed=embed)
                except discord.Forbidden:
                    print(f"Could not DM user {after.name}. They may have DMs disabled.")

                # Ban the user
                try:
                    await after.guild.ban(after, reason=reason)
                    log_channel_id = self.verification_data["channels"].get("botlogs")
                    if log_channel_id:
                        log_channel = after.guild.get_channel(log_channel_id)
                        if log_channel:
                            embed = discord.Embed(
                                title="Automated Ban",
                                description=(
                                    f"**User:** {after.mention}\n"
                                    f"**Reason:** {reason}"
                                ),
                                color=discord.Color.red()
                            )
                            await log_channel.send(embed=embed)
                except discord.Forbidden:
                    print(f"Failed to ban user {after.name} due to lack of permissions.")

    def check_banned_lists(self, user_id: str):
        banned_lists = []
        for list_type, users in self.verification_data.get("banned_users", {}).items():
            if user_id in users:
                banned_lists.append(list_type)
        return banned_lists

    def resolve_habbo_name(self, user_id: str):
        """Resolve the Habbo name from the user ID."""
        user_data = next(
            (user for user in self.verification_data.get("verified_users", []) if user["user_id"] == user_id), None
        )
        return user_data.get("habbo") if user_data else None

    admin = app_commands.Group(name="admin", description="Administrative commands for server management.")

    def create_embed(self, title: str, description: str, color: discord.Color, fields: list = None) -> discord.Embed:
        """Helper function to create an embed message."""
        embed = discord.Embed(title=title, description=description, color=color)
        if fields:
            for field in fields:
                embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
        return embed

    @admin.command(name="bos",
                   description="Add a Habbo name to the Ban on Sight (BoS) list with a reason.")
    @has_authorised_role()
    async def add_bos(self, interaction: discord.Interaction, habbo_name: str, reason: str = "No reason provided"):
        await self.add_to_banned_list(interaction, habbo_name, "BoS", reason)

    @admin.command(name="dnh",
                   description="Add a Habbo name to the Do Not Hire (DNH) list with a reason.")
    @has_authorised_role()
    async def add_dnh(self, interaction: discord.Interaction, habbo_name: str, reason: str = "No reason provided"):
        await self.add_to_banned_list(interaction, habbo_name, "DNH", reason)

    @admin.command(name="np",
                   description="Add a Habbo name to the National Punishment (NP) list with a reason.")
    @has_authorised_role()
    async def add_np(self, interaction: discord.Interaction, habbo_name: str, reason: str = "No reason provided"):
        await self.add_to_banned_list(interaction, habbo_name, "NP", reason)

    async def add_to_banned_list(self, interaction: discord.Interaction, habbo_name: str, list_type: str, reason: str):
        if list_type not in ["BoS", "DNH", "NP"]:
            embed = self.create_embed(
                title="Error: Invalid List",
                description=f"List type **{list_type}** is not valid. Use one of: BoS, DNH, NP.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Ensure the list exists
        self.punishment_data["banned_users"].setdefault(list_type, {})

        if habbo_name not in self.punishment_data["banned_users"][list_type]:
            self.punishment_data["banned_users"][list_type][habbo_name] = {"Reason": reason}
            self.save_punishment_data()

            embed = self.create_embed(
                title=f"{list_type} Added",
                description=f"Habbo: **{habbo_name}** \nPunishment: **{list_type}**",
                color=discord.Color.green(),
                fields=[{"name": "Reason", "value": reason, "inline": False}]
            )
            embed.set_thumbnail(
                url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo_name}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = self.create_embed(
                title=f"Error: Habbo Already in {list_type}",
                description=f"Habbo: **{habbo_name}**\nPunishment: **{list_type}**",
                color=discord.Color.red()
            )
            embed.set_thumbnail(
                url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo_name}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin.command(name="remove",
                   description="Remove a Habbo name from a banned list.")
    @has_authorised_role()
    async def remove(self, interaction: discord.Interaction, habbo_name: str, category: str):
        category = category.upper()
        valid_categories = {"BOS": "BoS", "DNH": "DNH", "NP": "NP"}

        if category not in valid_categories:
            embed = self.create_embed(
                title="Error: Invalid Category",
                description=f"Category **{category}** is not valid. Use one of: BoS, DNH, NP.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        formatted_category = valid_categories[category]

        # Check if the Habbo name exists in the category
        if habbo_name in self.punishment_data["banned_users"].get(formatted_category, {}):
            del self.punishment_data["banned_users"][formatted_category][habbo_name]
            self.save_punishment_data()
            embed = self.create_embed(
                title=f"{formatted_category} Removed",
                description=f"Habbo: **{habbo_name}**\nRemoved: **{formatted_category}**",
                color=discord.Color.green()
            )
            embed.set_thumbnail(
                url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo_name}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = self.create_embed(
                title=f"Error: Habbo Not in {formatted_category}",
                description=f"Habbo name **{habbo_name}** is not in the {formatted_category} list.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def add_to_list(self, interaction: discord.Interaction, habbo_name: str, list_type: str, reason: str):
        if list_type not in ["BoS", "DNH", "NP"]:
            await interaction.response.send_message("Invalid list type.")
            return

        # Ensure the list exists
        self.punishment_data["banned_users"].setdefault(list_type, {})

        if habbo_name not in self.punishment_data["banned_users"][list_type]:
            self.punishment_data["banned_users"][list_type][habbo_name] = {"Reason": reason}
            self.save_punishment_data()
            await interaction.response.send_message(
                f"Habbo name {habbo_name} has been added to the {list_type} list with reason: {reason}."
            )
        else:
            await interaction.response.send_message(
                f"Habbo name {habbo_name} is already in the {list_type} list."
            )

    banned_agencies = app_commands.Group(name="agencies", description="Manage banned agencies")

    @banned_agencies.command(name="add",
                             description="Add an agency to the banned agencies list.")
    @has_authorised_role()
    async def add_agency(self, interaction: discord.Interaction, agency_name: str, reason: str = "No reason provided"):
        banned_groups = self.punishment_data.get("banned_groups", [])

        for group in banned_groups:
            if group["name"].lower() == agency_name.lower():
                embed = discord.Embed(
                    title="Agency Already Banned",
                    description=f"Agency: **{agency_name}**",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Add the agency to the banned list
        banned_groups.append({"name": agency_name, "reason": reason})
        self.punishment_data["banned_groups"] = banned_groups
        self.save_punishment_data()
        embed = discord.Embed(
            title="Agency Added",
            description=f"Agency: **{agency_name}**",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @banned_agencies.command(name="remove",
                             description="Remove an agency from the banned agencies list.")
    @has_authorised_role()
    async def remove_agency(self, interaction: discord.Interaction, agency_name: str):
        banned_groups = self.punishment_data.get("banned_groups", [])

        # Search for the agency to remove
        for group in banned_groups:
            if group["name"].lower() == agency_name.lower():
                banned_groups.remove(group)
                self.punishment_data["banned_groups"] = banned_groups
                self.save_punishment_data()
                embed = discord.Embed(
                    title="Agency Removed",
                    description=f"Agency: **{agency_name}**",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed)
                return

        # If not found, send a message
        embed = discord.Embed(
            title="Error: Agency Not Found",
            description=f"Agency **'{agency_name}'** is not in the banned agencies list.",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Register subgroups under admin
    admin.add_command(banned_agencies)

async def setup(bot):
    await bot.add_cog(BanOnSightCog(bot))
