# verify_watch.py
import json
import asyncio
import discord
from discord.ext import commands

from COGS.paths import data_path

SERVER_JSON_PATH = data_path("JSON/server.json")
VERIFIED_ROLE_NAME = "Verified"
ALERT_CHANNEL_ID = 1404605698960003123
KICK_REASON = "Kicked from Server - Not Verified with Bot After Warning"

# Delay between actions to avoid rate limits
RATE_LIMIT_DELAY = 2.5


def _load_verified_ids() -> set[str]:
    try:
        with open(SERVER_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()
    return {
        str(entry.get("user_id"))
        for entry in data.get("verified_users", [])
        if isinstance(entry, dict) and "user_id" in entry
    }


def _has_verified_role(member: discord.Member) -> bool:
    return any(r.name.lower() == VERIFIED_ROLE_NAME.lower() for r in member.roles)


class ActionView(discord.ui.View):
    # timeout=None ensures buttons don't timeout
    def __init__(self, target_user_id: int):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

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

        try:
            await member.kick(reason=KICK_REASON)
            await interaction.response.send_message(f"✅ {member.mention} has been kicked.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to kick that member.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Failed to kick the member due to an HTTP error.", ephemeral=True)


class VerifyWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ready_once = False
        self._alerted_users: set[int] = set()
        self._lock = asyncio.Lock()

    async def _already_alerted(self, channel: discord.abc.Messageable, user_id: int) -> bool:
        # In-memory check first
        if user_id in self._alerted_users:
            return True

        # Fallback: scan recent channel history to avoid duplicates after restarts
        mention_a = f"<@{user_id}>"
        mention_b = f"<@!{user_id}>"
        try:
            async for msg in channel.history(limit=200):
                if msg.author.id != self.bot.user.id:
                    continue
                if (mention_a in msg.content) or (mention_b in msg.content):
                    if msg.embeds and msg.embeds[0].title == "Verification Check Needed":
                        self._alerted_users.add(user_id)
                        return True
        except Exception:
            # If we can't read history, don't block posting; rely on in-memory set
            pass
        return False

    async def _post_alert(self, member: discord.Member):
        channel = self.bot.get_channel(ALERT_CHANNEL_ID)
        if channel is None:
            return

        async with self._lock:
            if await self._already_alerted(channel, member.id):
                return

            embed = discord.Embed(
                title="Verification Check Needed",
                description=f"{member.mention} has the **{VERIFIED_ROLE_NAME}** role but is not in `server.json`.",
                color=discord.Color.orange(),
            )
            view = ActionView(target_user_id=member.id)
            await channel.send(content=member.mention, embed=embed, view=view)
            self._alerted_users.add(member.id)

    async def _scan_guild(self, guild: discord.Guild):
        verified_ids = _load_verified_ids()
        for member in guild.members:
            if _has_verified_role(member) and str(member.id) not in verified_ids:
                await self._post_alert(member)
                await asyncio.sleep(RATE_LIMIT_DELAY)  # delay between posts

    @commands.Cog.listener()
    async def on_ready(self):
        if self._ready_once:
            return
        self._ready_once = True
        for guild in self.bot.guilds:
            await self._scan_guild(guild)
            await asyncio.sleep(RATE_LIMIT_DELAY)  # small delay between guild scans

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        before_has = _has_verified_role(before)
        after_has = _has_verified_role(after)
        if before_has or not after_has:
            return
        verified_ids = _load_verified_ids()
        if str(after.id) not in verified_ids:
            await asyncio.sleep(RATE_LIMIT_DELAY)  # smooth bursts
            await self._post_alert(after)

    @commands.command(name="verscan")
    async def manual_scan(self, ctx: commands.Context):
        await self._scan_guild(ctx.guild)
        await ctx.reply("Scan complete.", mention_author=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerifyWatch(bot))
