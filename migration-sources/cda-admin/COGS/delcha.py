import discord
from discord.ext import commands

class ChannelManagement(commands.Cog):
    """Cog for managing channels, including deletion."""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='deletechannel', aliases=['delchan'])
    @commands.has_permissions(manage_channels=True)
    async def delete_channel(self, ctx, *channels: discord.TextChannel):
        """Deletes mentioned channels. Requires 'Manage Channels' permission."""
        if not channels:
            return await ctx.send("?? You need to mention at least one channel to delete!")
        
        for channel in channels:
            try:
                await channel.delete()
                await ctx.send(f'? Successfully deleted {channel.name}')
            except discord.Forbidden:
                await ctx.send(f'? I do not have permission to delete {channel.name}')
            except discord.HTTPException:
                await ctx.send(f'? Failed to delete {channel.name}')

    @delete_channel.error
    async def delete_channel_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("? You don't have permission to delete channels!")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("?? Please mention the channel(s) you want to delete!")

async def setup(bot):
    await bot.add_cog(ChannelManagement(bot))
