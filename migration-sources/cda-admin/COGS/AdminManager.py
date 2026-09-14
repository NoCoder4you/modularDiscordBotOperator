import json

import discord
from discord.ext import commands

from COGS.paths import data_path

_ADMIN_JSON = data_path("JSON/admins.json")           # <-- keep the JSON you created here

# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _load_admins() -> set[int]:
    if _ADMIN_JSON.exists():
        with _ADMIN_JSON.open(encoding="utf-8") as fp:
            data = json.load(fp)
            return set(data.get("admins", []))
    _ADMIN_JSON.write_text('{"admins": []}', encoding="utf-8")
    return set()


def _save_admins(admins: set[int]) -> None:
    _ADMIN_JSON.write_text(
        json.dumps({"admins": sorted(admins)}, indent=2), encoding="utf-8"
    )


_admins: set[int] = _load_admins()           # in-memory cache


def is_admin():
    """Commands decorator: only JSON-listed admins may run the command."""
    async def predicate(ctx: commands.Context) -> bool:
        return ctx.author.id in _admins
    return commands.check(predicate)


# --------------------------------------------------------------------------- #
# cog                                                                         #
# --------------------------------------------------------------------------- #
class AdminManager(commands.Cog):
    """`PREFIX addadmin @user` ? give someone admin rights."""

    @commands.command(name="addadmin")
    @is_admin()
    async def add_admin(self, ctx: commands.Context, target: discord.Member):
        """Add *target* to the `admins.json` list."""
        if target.id in _admins:
            await ctx.reply(f"{target.mention} is already an admin.")
            return

        _admins.add(target.id)
        _save_admins(_admins)
        await ctx.reply(f"? {target.mention} added as admin.")

    # (optional) helper to list current admins
    @commands.command(name="admins")
    @is_admin()
    async def list_admins(self, ctx: commands.Context):
        names = [f"<@{aid}>" for aid in _admins]
        await ctx.reply("Current admins: " + ", ".join(names))


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminManager())
