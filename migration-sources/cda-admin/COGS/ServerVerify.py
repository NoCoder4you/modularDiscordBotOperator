from discord import app_commands
import discord
from discord.ext import commands, tasks
import aiohttp
import json
import os
import time
import random
import string
from COGS.BotCheck import is_verified
from COGS.paths import data_path
from COGS.WelcomeDM import send_welcome_dm


class HabboVerifyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.roles_file_path = data_path("JSON/rolesbadges.json")
        self.roles_data = self.load_roles_data()
        self.server_data_path = data_path("JSON/server.json")
        self.verification_file_path = data_path("JSON/verification_codes.json")
        self.server_data = self.load_server_data()
        self.verification_data = self.load_verification_codes()
        self.cleanup_task.start()

    def load_roles_data(self):
        if os.path.exists(self.roles_file_path):
            try:
                with open(self.roles_file_path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    roles_data = data.get("roles", {})
                    if not isinstance(roles_data, dict):
                        raise ValueError("The 'roles' key must contain a dictionary.")
                    self.validate_roles_data(roles_data)
                    return roles_data
            except json.JSONDecodeError:
                print(f"Error decoding {self.roles_file_path}. Ensure it's valid JSON.")
                return {}
        else:
            print(f"{self.roles_file_path} not found.")
            return {}

    def validate_roles_data(self, roles_data):
        if not isinstance(roles_data, dict):
            raise ValueError("roles_data must be a dictionary.")
        for key in ["EmployeeRoles", "DonatorRoles", "Misc", "SpecialUnits"]:
            if key not in roles_data:
                raise ValueError(f"Missing expected key: '{key}' in roles_data.")
            if not isinstance(roles_data[key], list):
                raise ValueError(f"'{key}' must be a list of roles.")

    def load_server_data(self):
        if os.path.exists(self.server_data_path):
            try:
                with open(self.server_data_path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    if "verified_users" not in data:
                        data["verified_users"] = []
                    if "channels" not in data:
                        data["channels"] = {
                            "verification": None
                        }
                    return data
            except json.JSONDecodeError:
                print(f"Error decoding {self.server_data_path}. Ensure it's valid JSON.")
                return {"verified_users": [], "channels": {"verification": None}}
        return {"verified_users": [], "channels": {"verification": None}}

    def save_server_data(self):
        with open(self.server_data_path, "w", encoding="utf-8") as file:
            json.dump(self.server_data, file, indent=4)

    def load_verification_codes(self):
        if os.path.exists(self.verification_file_path):
            try:
                with open(self.verification_file_path, "r", encoding="utf-8") as file:
                    return json.load(file)
            except json.JSONDecodeError:
                print(f"Error decoding {self.verification_file_path}. Ensure it's valid JSON.")
                return {"verification_data": {}}
        return {"verification_data": {}}

    def save_verification_codes(self):
        with open(self.verification_file_path, "w", encoding="utf-8") as file:
            json.dump(self.verification_data, file, indent=4)

    @tasks.loop(minutes=2.5)
    async def cleanup_task(self):
        current_time = time.time()
        expired_keys = [
            user_id for user_id, data in self.verification_data["verification_data"].items()
            if current_time - data['timestamp'] > 600
        ]
        for key in expired_keys:
            del self.verification_data["verification_data"][key]
        self.save_verification_codes()

    def generate_unique_code(self):
        return ''.join(random.choices(string.ascii_letters + string.digits, k=5))


    async def assign_roles(self, member, groups_data, guild):
        ic_role_id = 1249819550015426571
        cdaemployee_role_id = 1248313244481884220

        roles_data = self.roles_data

        ic_role = guild.get_role(ic_role_id)
        cdaemployee_role = guild.get_role(cdaemployee_role_id)

        added_roles = []
        removed_roles = []

        # Process EmployeeRoles
        employee_roles = roles_data.get("EmployeeRoles", [])
        highest_employee_role = None

        for role_data in employee_roles:
            for group in groups_data:
                if role_data.get("group_id") == group.get("id"):
                    highest_employee_role = role_data
                    break
            if highest_employee_role:
                break

        for role_data in employee_roles:
            role = guild.get_role(role_data.get("role_id"))
            if role and role in member.roles:
                try:
                    await member.remove_roles(role)
                    removed_roles.append(role.name)
                except discord.Forbidden:
                    pass

        if highest_employee_role:
            role = guild.get_role(highest_employee_role.get("role_id"))
            if role and role not in member.roles:
                try:
                    await member.add_roles(role)
                    added_roles.append(role.name)
                except discord.Forbidden:
                    pass

        if highest_employee_role:
            if highest_employee_role.get("iC") == "yes" and ic_role and ic_role not in member.roles:
                try:
                    await member.add_roles(ic_role)
                    added_roles.append(ic_role.name)
                except discord.Forbidden:
                    pass
            if highest_employee_role.get("cdaemployee") == "yes" and cdaemployee_role and cdaemployee_role not in member.roles:
                try:
                    await member.add_roles(cdaemployee_role)
                    added_roles.append(cdaemployee_role.name)
                except discord.Forbidden:
                    pass

        for category in ["DonatorRoles", "Misc", "SpecialUnits"]:
            for role_data in roles_data.get(category, []):
                for group in groups_data:
                    if role_data.get("group_id") == group.get("id"):
                        role = guild.get_role(role_data.get("role_id"))
                        if role and role not in member.roles:
                            try:
                                await member.add_roles(role)
                                added_roles.append(role.name)
                            except discord.Forbidden:
                                pass

        return added_roles, removed_roles

    async def send_roles_message(self, interaction: discord.Interaction, habbo: str):
        general_channel_id = self.server_data["channels"].get("general")
        general_channel = interaction.guild.get_channel(general_channel_id)

        if not general_channel:
            print(f"General channel with ID {general_channel_id} not found.")
            return

        avatar_url = f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"

        # Create the embed message
        embed = discord.Embed(
            title="Welcome to the CDA Discord Server!",
            description=(
                "### Employee, Donator and Other Roles are updated automatically!\n"
                "### <#1249416377492832306> for the latest CDA updates!\n"
                "### <#1249417127958413465> for all the latest events!\n"
                "### <#1249447238384619662> for more roles!"
            ),
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=avatar_url)

        # Send the message into the general channel with automatic deletion
        try:
            await general_channel.send(
                content=f"{interaction.user.mention}!",
                embed=embed,
                delete_after=600
            )
        except discord.Forbidden:
            print("Failed to send a message in the general channel due to missing permissions.")
        except Exception as e:
            print(f"Unexpected error while sending to the general channel: {e}")

    @app_commands.command(name="verify", description="Start and check Habbo verification.")
    @app_commands.describe(
        habbo="Input your Habbo Username only.",
    )
    async def verify(self, interaction: discord.Interaction, habbo: str):
        try:
            await interaction.response.defer(ephemeral=True)

            user_id = str(interaction.user.id)
            verification_channel_id = self.server_data["channels"].get("verification")
            banlogs_channel_id = self.server_data["channels"].get("banlogs")
            verified_role_id = 1277489459226738808  # Replace with actual Verified role ID
            role_to_remove_id = 1248310200939581594  # Replace with actual Role ID to remove

            # Check if the user is already verified
            for verified_user in self.server_data["verified_users"]:
                if verified_user["user_id"] == user_id:
                    embed = discord.Embed(
                        title="Already Verified \u2705",
                        description=f"**Verified:** `{verified_user['habbo']}`",
                        color=discord.Color.green()
                    )
                    embed.set_thumbnail(
                        url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

            # Check for ongoing verification
            if user_id in self.verification_data["verification_data"]:
                ongoing_verification = self.verification_data["verification_data"][user_id]
                verification_code = ongoing_verification["code"]
                stored_habbo = ongoing_verification["habbo"]

                # Check if the provided Habbo name matches the stored name
                if stored_habbo.lower() != habbo.lower():
                    embed = discord.Embed(
                        title="Verification Failed",
                        description=(f"The provided Habbo name `{habbo}` does not match "
                                     f"the name used during the initial verification: `{stored_habbo}`.\n"
                                     "Please use the correct Habbo name or restart the verification process."),
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                # Validate the Habbo motto
                url = f"https://www.habbo.com/api/public/users?name={habbo}"

                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            json_data = await response.json()
                            motto = json_data.get("motto")
                            habbo_name = json_data.get("name")

                            if motto and verification_code in motto:
                                # User verified successfully
                                self.server_data["verified_users"].append({
                                    "user_id": user_id,
                                    "habbo": habbo
                                })
                                del self.verification_data["verification_data"][user_id]
                                self.save_server_data()
                                self.save_verification_codes()

                                guild = interaction.guild
                                verification_channel = guild.get_channel(verification_channel_id)
                                banlogs_channel = guild.get_channel(banlogs_channel_id)
                                member = guild.get_member(interaction.user.id)
                                verified_role = guild.get_role(verified_role_id)
                                role_to_remove = guild.get_role(role_to_remove_id)

                                # Send a message to the verification channel
                                if verification_channel:
                                    embed = discord.Embed(
                                        title="User Verified",
                                        description=(f"**User:** {interaction.user.mention}\n"
                                                     f"**Habbo:** `{habbo_name}`\n"
                                                     f"**Verified:** \u2705"),
                                        color=discord.Color.green()
                                    )
                                    embed.set_thumbnail(
                                        url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
                                    )
                                    await verification_channel.send(embed=embed)

                                # Log verification success in the banlogs channel
                                if banlogs_channel:
                                    embed = discord.Embed(
                                        title="Verification Log",
                                        description=(f"**User:** {interaction.user.mention}\n"
                                                     f"**Habbo:** `{habbo_name}`\n"
                                                     f"**Verified:** \u2705"),
                                        color=discord.Color.blue()
                                    )
                                    embed.set_thumbnail(
                                        url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
                                    )
                                    await banlogs_channel.send(embed=embed)

                                # Update the user's nickname
                                if member and habbo_name:
                                    try:
                                        await member.edit(nick=habbo_name)
                                    except discord.Forbidden:
                                        pass  # Ignore permission errors

                                # Assign the verified role
                                if member and verified_role:
                                    try:
                                        await member.add_roles(verified_role)
                                    except discord.Forbidden:
                                        pass

                                # Remove the specified role
                                if member and role_to_remove:
                                    try:
                                        await member.remove_roles(role_to_remove)
                                    except discord.Forbidden:
                                        pass
                                        
                                if member:
                                    async with aiohttp.ClientSession() as session:
                                        user_url = f"https://www.habbo.com/api/public/users?name={habbo}"
                                        async with session.get(user_url) as user_response:
                                            if user_response.status == 200:
                                                user_data = await user_response.json()
                                                habbo_id = user_data.get("uniqueId")  # Get unique Habbo ID
                                                
                                                # Fetch the groups data to assign roles automatically
                                                groups_url = f"https://www.habbo.com/api/public/users/{habbo_id}/groups"
                                                async with session.get(groups_url) as groups_response:
                                                    if groups_response.status == 200:
                                                        groups_data = await groups_response.json()
                                                        
                                                        # Call assign_roles function to apply roles automatically
                                                        added_roles, removed_roles = await self.assign_roles(member, groups_data, guild)

                                # Notify the user of successful verification
                                embed = discord.Embed(
                                    title="Verification Successful",
                                    description=(f"**Habbo:** `{habbo_name}`\n**Verified:** \u2705"),
                                    color=discord.Color.green()
                                )
                                embed.set_thumbnail(
                                    url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
                                )
                                await interaction.followup.send(embed=embed, ephemeral=True)
                                # After successful verification
                                await self.send_roles_message(interaction, habbo)
                                return
                            else:
                                # Verification failed due to missing code in motto
                                embed = discord.Embed(
                                    title="Verification Failed",
                                    description=(f"Your motto does not contain the verification code.\n"
                                                 f"## `{verification_code}`\n"
                                                 "Please ensure your motto contains the correct code and try again."),
                                    color=discord.Color.red()
                                )
                                embed.set_thumbnail(
                                    url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
                                )
                                await interaction.followup.send(embed=embed, ephemeral=True)
                                return

            # Generate a new verification code if none exists
            verification_code = self.generate_unique_code()
            self.verification_data["verification_data"][user_id] = {
                "code": verification_code,
                "habbo": habbo,
                "timestamp": time.time(),
            }
            self.save_verification_codes()

            await send_welcome_dm(interaction.user, habbo)

            verify_embed = discord.Embed(
                title="Verify Your Habbo Account",
                description=(
                    "Add the code below to your Habbo motto, then run **`/verify`** again.\n"
                    f"## `{verification_code}`\n"
                    "If you entered the wrong Habbo name, wait up to 5 minutes and retry."
                ),
                color=discord.Color.green()
            )
            verify_embed.set_image(
                url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
            )
            try:
                await interaction.user.send(embed=verify_embed)
            except discord.Forbidden:
                print(f"Could not DM user {interaction.user.id}. They may have DMs disabled.")

            embed = discord.Embed(
                title="Verification Started",
                description=(f"Please include the following code in your Habbo motto:\n"
                             f"If the username you have inputted is incorrect, please wait up to 5 minutes.\n"
                             f"## `{verification_code}`\n"
                             "Run **`/verify`** again to complete the process."),
                color=discord.Color.blue()
            )
            embed.set_thumbnail(
                url=f"https://www.habbo.com/habbo-imaging/avatarimage?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"An unexpected error occurred: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HabboVerifyCog(bot))
