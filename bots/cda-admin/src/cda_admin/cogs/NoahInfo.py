import discord
from discord.ext import commands


class InfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.owner_id = 298121351871594497  # Replace with your actual owner ID

    @commands.command(name="lc")
    async def list_channels(self, ctx, channel_type: str = None):
        try:
            owner = await self.bot.fetch_user(self.bot.owner_id)  # Fetch owner directly from Discord
        except Exception:
            await ctx.send("Could not fetch the bot owner. Please ensure the owner ID is set correctly.")
            return

        guild = ctx.guild
        all_channels = list(guild.channels)  # Convert SequenceProxy to a list

        # Filter by type if provided
        if channel_type == "text":
            filtered_channels = [c for c in all_channels if isinstance(c, discord.TextChannel)]
        elif channel_type == "voice":
            filtered_channels = [c for c in all_channels if isinstance(c, discord.VoiceChannel)]
        elif channel_type == "category":
            filtered_channels = [c for c in all_channels if isinstance(c, discord.CategoryChannel)]
        else:
            filtered_channels = all_channels

        # Sort by category name, then by channel name
        filtered_channels.sort(
            key=lambda c: (
                c.category.name if c.category else '',  # Category name
                c.name  # Channel name
            )
        )

        chunks = [filtered_channels[i:i + 5] for i in range(0, len(filtered_channels), 5)]

        await owner.send(f"**Channels:**")
        for chunk in chunks:
            message = "\n".join(
                [
                    f"{channel.category.name if channel.category else 'No Category'} - "
                    f"{'Text' if isinstance(channel, discord.TextChannel) else 'Voice' if isinstance(channel, discord.VoiceChannel) else 'Category'} - "
                    f"{channel.name} - {channel.id}"
                    for channel in chunk
                ]
            )
            await owner.send(f"{message}")

    @commands.command(name="lr")
    async def list_roles(self, ctx):
        try:
            owner = await self.bot.fetch_user(self.bot.owner_id)  # Fetch owner directly from Discord
        except Exception:
            await ctx.send("Could not fetch the bot owner. Please ensure the owner ID is set correctly.")
            return

        guild = ctx.guild
        roles = guild.roles  # Get all roles in the guild

        # Sort roles by hierarchy (highest first)
        roles = sorted(roles, key=lambda r: r.position, reverse=True)

        chunks = [roles[i:i + 5] for i in range(0, len(roles), 5)]

        await owner.send(f"**Roles:**")
        for chunk in chunks:
            message = "\n".join([f"{role.name} - {role.id}" for role in chunk])
            await owner.send(f"{message}")


async def setup(bot):
    await bot.add_cog(InfoCog(bot))
