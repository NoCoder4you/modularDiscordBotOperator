import discord
from discord import app_commands
from discord.ext import commands

AUTHORIZED_USER_ID = 298121351871594497

WHITE = discord.Color.from_rgb(255, 255, 255)  # True white

class EmbedModal(discord.ui.Modal, title="Create/Edit an Embed"):
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.message_id_input = discord.ui.TextInput(label="Message ID (edit existing)", required=False)
        self.title_input = discord.ui.TextInput(label="Title", required=False, max_length=256)
        self.description_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False)
        self.footer_input = discord.ui.TextInput(label="Footer Text (optional)", required=False, max_length=128)
        self.add_item(self.message_id_input)
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        message_id = self.message_id_input.value.strip() if self.message_id_input.value else None
        title = self.title_input.value.strip() if self.title_input.value else "CDA Admin Embed"
        description = self.description_input.value.strip() if self.description_input.value else None
        user_footer = self.footer_input.value.strip() if self.footer_input.value else ""
        footer_text = f"CDA Admin - {user_footer}" if user_footer else "CDA Admin"
        bot_avatar = interaction.client.user.display_avatar.url if interaction.client.user else None

        if message_id:
            try:
                message = await interaction.channel.fetch_message(int(message_id))
                if not message.embeds:
                    raise discord.NotFound(response=None, message="No embed found.", code=0)
                old = message.embeds[0]
                embed = discord.Embed(
                    title=title if title else old.title,
                    description=description if description else old.description,
                    color=WHITE,
                )
                embed.set_footer(text=footer_text)
                if bot_avatar:
                    embed.set_thumbnail(url=bot_avatar)
                await message.edit(embed=embed)
                await interaction.response.send_message(f"Embed **updated**! (Message ID: {message_id})", ephemeral=True)
                self.bot.embed_manager[message.id] = embed
                return
            except (discord.NotFound, AttributeError):
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=WHITE,
                )
                embed.set_footer(text=footer_text)
                if bot_avatar:
                    embed.set_thumbnail(url=bot_avatar)
                msg = await interaction.channel.send(embed=embed)
                self.bot.embed_manager[msg.id] = embed
                await interaction.response.send_message(f"Embed **created**! (Message ID: {msg.id})", ephemeral=True)
                return
            except discord.HTTPException:
                return await interaction.response.send_message("Failed to edit the embed.", ephemeral=True)
        else:
            embed = discord.Embed(
                title=title,
                description=description,
                color=WHITE,
            )
            embed.set_footer(text=footer_text)
            if bot_avatar:
                embed.set_thumbnail(url=bot_avatar)
            msg = await interaction.channel.send(embed=embed)
            self.bot.embed_manager[msg.id] = embed
            await interaction.response.send_message(f"Embed **created**! (Message ID: {msg.id})", ephemeral=True)

class EmbedManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.embed_manager = {}

    @app_commands.command(name="nem", description="Create or edit an embed. Only one person can use this.")
    async def nem(self, interaction: discord.Interaction):
        if interaction.user.id == AUTHORIZED_USER_ID:
            modal = EmbedModal(self.bot)
            await interaction.response.send_modal(modal)
        else:
            bot_avatar = interaction.client.user.display_avatar.url if interaction.client.user else None
            embed = discord.Embed(
                title="Access Denied",
                description=f"Sorry {interaction.user.mention}, you are **not authorized** to use this command.",
                color=discord.Color.red()
            )
            embed.set_footer(text="CDA Admin - Restricted Command")
            if bot_avatar:
                embed.set_thumbnail(url=bot_avatar)
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedManager(bot))
