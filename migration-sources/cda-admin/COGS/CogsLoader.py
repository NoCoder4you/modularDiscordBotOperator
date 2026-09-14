import traceback
from pathlib import Path

import discord
from discord.ext import commands

_OWNER_ID = 298121351871594497      # the only user allowed to use the buttons
_ROOT_DIR = Path(__file__).parent   # folder containing bot.py and all cog files
_EXT_PREFIX = ""                    # no prefix because cogs are top-level .py files


class CogToggleButton(discord.ui.Button):
    def __init__(self, extension: str, loaded: bool):
        super().__init__(
            label=extension,
            custom_id=extension,
            style=discord.ButtonStyle.green if loaded else discord.ButtonStyle.red,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != _OWNER_ID:
            await interaction.response.send_message(
                "These buttons aren?t for you ?", ephemeral=True
            )
            return

        bot: commands.Bot = interaction.client
        extension = self.custom_id
        is_loaded = extension in bot.extensions
        try:
            if is_loaded:
                await bot.unload_extension(extension)
            else:
                await bot.load_extension(extension)
            self.style = (
                discord.ButtonStyle.green if not is_loaded else discord.ButtonStyle.red
            )
            await interaction.response.edit_message(view=self.view)
        except Exception as e:
            self.style = discord.ButtonStyle.red
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            await interaction.response.send_message(
                f"?? `{extension}` failed:\n```py\n{tb[:1900]}```",
                ephemeral=True,
            )


class CogManagerView(discord.ui.View):
    def __init__(self, bot: commands.Bot, timeout: int | None = 300):
        super().__init__(timeout=timeout)

        skip_files = {Path(__file__).name, "bot.py", "__init__.py"}
        for file in _ROOT_DIR.glob("*.py"):
            if file.name in skip_files:
                continue
            ext = _EXT_PREFIX + file.stem
            self.add_item(CogToggleButton(ext, ext in bot.extensions))


class CogManager(commands.Cog):
    @commands.command(name="cogs")
    async def show_cogs(self, ctx: commands.Context):
        if ctx.author.id != _OWNER_ID:
            return
        await ctx.send("Toggle cogs below:", view=CogManagerView(ctx.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(CogManager())
