import discord
from discord.ext import commands

TARGET_USER_ID = 298121351871594497
LOG_CHANNEL_ID = 1375980861219934238

class MentionLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Check if the target user is mentioned
        if any(user.id == TARGET_USER_ID for user in message.mentions):
            # Log the original message in the specified channel and ping the target user
            log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                message_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
                target_user_mention = f"<@{TARGET_USER_ID}>"
                log_embed = discord.Embed(
                    title="Target User Mentioned",
                    description=(
                        f"**Author:** {message.author.mention}\n"
                        f"**Channel:** {message.channel.mention}\n\n"
                        f"**Message:**\n{message.content}\n\n"
                        f"-# [Jump to Message]({message_link})"
                    ),
                    color=discord.Color.orange()
                )
                log_embed.set_footer(text=f"Message ID: {message.id}")
                await log_channel.send(f"{target_user_mention}")
                await log_channel.send(embed=log_embed)

async def setup(bot):
    await bot.add_cog(MentionLogger(bot))
