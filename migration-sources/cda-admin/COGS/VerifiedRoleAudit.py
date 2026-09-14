import asyncio
import json

import discord
from discord.ext import commands

from COGS.paths import data_path

VERIFIED_ROLE_NAME = "Verified"
EMPLOYEE_ROLE_ID = 1248313244481884220
SPECIAL_VISITOR_ROLE_ID = 1249423888677601392
EMPLOYEE_ROLE_NAME = "CDA Employee"
SPECIAL_VISITOR_ROLE_NAME = "Special Visitor"
ALERT_CHANNEL_NAME = "⚡｜butt-kicking"
DISCORD_OFFICERS_ROLE_NAME = "Discord Officers"
KICK_REASON = "Kicked from Server - Verified Without Employee or Special Visitor"

RATE_LIMIT_DELAY = 2.5
EMBED_TITLE = "Role Compliance Check"


def _has_role(member: discord.Member, role_name: str) -> bool:
    return any(role.name.lower() == role_name.lower() for role in member.roles)


def _has_role_id(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def _has_any_role_id(member: discord.Member, role_ids: set[int]) -> bool:
    return any(role.id in role_ids for role in member.roles)


def _load_roles_data() -> dict:
    roles_path = data_path("JSON/rolesbadges.json")
    try:
        with open(roles_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    return data.get("roles", {}) if isinstance(data, dict) else {}


def _load_exempt_role_ids(roles_data: dict) -> set[int]:
    exempt_role_ids: set[int] = set()

    for role_data in roles_data.get("DonatorRoles", []):
        role_id = role_data.get("role_id")
        if isinstance(role_id, int):
            exempt_role_ids.add(role_id)

    for role_data in roles_data.get("Misc", []):
        role_name = str(role_data.get("role_name", "")).strip()
        normalized_name = role_name.replace("\n", "").strip().lower()
        if normalized_name == "veteran":
            role_id = role_data.get("role_id")
            if isinstance(role_id, int):
                exempt_role_ids.add(role_id)

    return exempt_role_ids


def _load_employee_role_ids(roles_data: dict) -> set[int]:
    employee_role_ids: set[int] = {EMPLOYEE_ROLE_ID}

    for role_data in roles_data.get("EmployeeRoles", []):
        role_id = role_data.get("role_id")
        if isinstance(role_id, int):
            employee_role_ids.add(role_id)

    return employee_role_ids


def _needs_action(
    member: discord.Member,
    exempt_role_ids: set[int],
    employee_role_ids: set[int],
) -> bool:
    has_verified = _has_role(member, VERIFIED_ROLE_NAME)
    has_employee = _has_any_role_id(member, employee_role_ids)
    has_special = _has_role_id(member, SPECIAL_VISITOR_ROLE_ID)
    has_exempt_role = _has_any_role_id(member, exempt_role_ids)
    return has_verified and not (has_employee or has_special) and not has_exempt_role


class ActionView(discord.ui.View):
    def __init__(self, target_user_id: int, exempt_role_ids: set[int], employee_role_ids: set[int]):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id
        self.exempt_role_ids = exempt_role_ids
        self.employee_role_ids = employee_role_ids

    @discord.ui.button(label="Ignore", style=discord.ButtonStyle.secondary)
    async def ignore_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("You don't have permission to kick members.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return

        member = guild.get_member(self.target_user_id)
        if member is None:
            await interaction.response.send_message("User is no longer in the server.", ephemeral=True)
            return

        if not _needs_action(member, self.exempt_role_ids, self.employee_role_ids):
            await interaction.response.send_message(
                "User already has the required role(s).",
                ephemeral=True,
            )
            return

        try:
            try:
                await member.send(
                    "You are being kicked from the server because you have the Verified role "
                    "without an eligible employee or Special Visitor role. Please contact staff "
                    "if you believe this is a mistake."
                )
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass
            await member.kick(reason=KICK_REASON)
            await interaction.response.send_message(f"✅ {member.mention} has been kicked.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to kick that member.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Failed to kick the member due to an HTTP error.", ephemeral=True)


class VerifiedRoleAudit(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ready_once = False
        self._alerted_users: set[int] = set()
        self._lock = asyncio.Lock()
        roles_data = _load_roles_data()
        self._exempt_role_ids = _load_exempt_role_ids(roles_data)
        self._employee_role_ids = _load_employee_role_ids(roles_data)

    def _get_alert_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        return discord.utils.get(guild.text_channels, name=ALERT_CHANNEL_NAME)

    def _get_discord_officers_role(self, guild: discord.Guild) -> discord.Role | None:
        return discord.utils.get(guild.roles, name=DISCORD_OFFICERS_ROLE_NAME)

    async def _already_alerted(self, channel: discord.abc.Messageable, user_id: int) -> bool:
        if user_id in self._alerted_users:
            return True

        mention_a = f"<@{user_id}>"
        mention_b = f"<@!{user_id}>"
        try:
            async for msg in channel.history(limit=200):
                if msg.author.id != self.bot.user.id:
                    continue
                if (mention_a in msg.content) or (mention_b in msg.content):
                    if msg.embeds and msg.embeds[0].title == EMBED_TITLE:
                        self._alerted_users.add(user_id)
                        return True
        except Exception:
            pass
        return False

    async def _post_alert(self, member: discord.Member, include_officers_mention: bool = False):
        channel = self._get_alert_channel(member.guild)
        if channel is None:
            return

        async with self._lock:
            if await self._already_alerted(channel, member.id):
                return

            embed = discord.Embed(
                title=EMBED_TITLE,
                description=(
                    f"{member.mention} has **{VERIFIED_ROLE_NAME}** but has neither "
                    f"**{EMPLOYEE_ROLE_NAME}** (or an employee role) nor "
                    f"**{SPECIAL_VISITOR_ROLE_NAME}**."
                ),
                color=discord.Color.orange(),
            )
            view = ActionView(
                target_user_id=member.id,
                exempt_role_ids=self._exempt_role_ids,
                employee_role_ids=self._employee_role_ids,
            )
            content = member.mention
            if include_officers_mention:
                officers_role = self._get_discord_officers_role(member.guild)
                if officers_role is not None:
                    content = f"{officers_role.mention} {content}"
            await channel.send(content=content, embed=embed, view=view)
            self._alerted_users.add(member.id)

    async def _scan_guild(self, guild: discord.Guild):
        for member in guild.members:
            if _needs_action(member, self._exempt_role_ids, self._employee_role_ids):
                await self._post_alert(member)
                await asyncio.sleep(RATE_LIMIT_DELAY)

    @commands.Cog.listener()
    async def on_ready(self):
        if self._ready_once:
            return
        self._ready_once = True
        for guild in self.bot.guilds:
            await self._scan_guild(guild)
            await asyncio.sleep(RATE_LIMIT_DELAY)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if _needs_action(after, self._exempt_role_ids, self._employee_role_ids) and not _needs_action(
            before, self._exempt_role_ids, self._employee_role_ids
        ):
            await asyncio.sleep(RATE_LIMIT_DELAY)
            await self._post_alert(after, include_officers_mention=True)

    @commands.command(name="rolescan")
    async def manual_scan(self, ctx: commands.Context):
        await self._scan_guild(ctx.guild)
        await ctx.reply("Scan complete.", mention_author=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerifiedRoleAudit(bot))
