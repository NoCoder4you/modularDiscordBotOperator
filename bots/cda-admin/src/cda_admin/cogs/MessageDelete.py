import discord
from discord.ext import commands


class MessageManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(
        name="delete",
        help="Deletes a message by its message ID, regardless of who sent it."
    )
    @commands.is_owner()
    async def delete_any_message(self, ctx: commands.Context, message_id: int):
        """Deletes any message in the current channel given its ID."""
        try:
            await ctx.message.delete()  # delete the command message itself
            message = await ctx.channel.fetch_message(message_id)
            await message.delete()
            await ctx.send(f"🗑️ Message with ID `{message_id}` deleted successfully.", delete_after=1)
        except discord.NotFound:
            await ctx.send("⚠️ Message not found. Please check the ID.", delete_after=2)
        except discord.Forbidden:
            await ctx.send("🚫 I don't have permission to delete that message.", delete_after=2)
        except discord.HTTPException as e:
            await ctx.send(f"❌ Failed to delete message: {e}", delete_after=2)

async def setup(bot):
    await bot.add_cog(MessageManager(bot))
