import discord
from discord.ext import commands
import asyncio
from collections import defaultdict
from time import time

class MessagingSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = 1202999519986458765  # Hardcoded guild ID
        self.last_message_timestamps = {}  # Track timestamps of last messages by user ID
        self.autoreply_user_id = 298121351871594497  # Hardcoded user ID for auto-reply

        # Spam protection
        self.MESSAGE_LIMIT = 5  # Maximum allowed messages
        self.TIME_WINDOW = 10   # Time window in seconds
        self.message_tracker = defaultdict(list)  # Tracks message timestamps by user

        # Auto-reply tracking
        self.pending_replies = {}  # Tracks if an auto-reply is pending for a channel

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bot messages
        if message.author.bot:
            return

        # DM Handling
        if isinstance(message.channel, discord.DMChannel):
            # Check for spam
            if not await self.check_spam(message.author):
                await message.channel.send("You are sending messages too quickly. Please slow down.")
                return

            # Retrieve the guild
            guild = self.bot.get_guild(self.guild_id)
            if not guild:
                print("Guild not found. Check guild ID.")
                return

            category_name = self.bot.user.name  # Use the bot's name as the category name
            category = discord.utils.get(guild.categories, name=category_name)

            # Create category if it doesn't exist
            if not category:
                category = await guild.create_category(category_name)

            # Find or create the user's channel
            channel_name = f"{message.author.name.lower()}"  # No discriminator needed
            existing_channel = discord.utils.get(category.channels, name=channel_name)

            if not existing_channel:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True),
                }
                existing_channel = await guild.create_text_channel(
                    channel_name, category=category, overwrites=overwrites
                )
                await existing_channel.send(
                    f"Channel created for messages from {message.author.mention}."
                )

            # Forward the user's DM to the channel
            await existing_channel.send(
                f"{message.content}"
            )

            # Update last message timestamp
            self.last_message_timestamps[message.author.id] = asyncio.get_event_loop().time()

            # Schedule the auto-reply if the user is the target ID
            if message.author.id == self.autoreply_user_id:
                self.pending_replies[existing_channel.id] = True
                await asyncio.create_task(self.schedule_autoreply(guild, message.author, message.channel, existing_channel))

        # Channel Handling in DMs Category
        elif message.channel.category and message.channel.category.name == self.bot.user.name:
            # Mark that a response was made in the channel
            self.pending_replies[message.channel.id] = False

            try:
                username = message.channel.name
                user = discord.utils.get(self.bot.users, name=username)

                if user:
                    # Forward message to the user in their DM
                    await user.send(f"**Reply from {message.author}:**\n{message.content}")
                else:
                    await message.channel.send("User not found. Unable to send the message.")

            except ValueError:
                await message.channel.send("Channel name format is invalid.")

    async def check_spam(self, user):
        """Check if the user is spamming messages."""
        now = time()
        user_timestamps = self.message_tracker[user.id]

        # Add the current timestamp
        user_timestamps.append(now)

        # Remove timestamps outside the time window
        self.message_tracker[user.id] = [ts for ts in user_timestamps if now - ts <= self.TIME_WINDOW]

        # Check if user exceeds the message limit
        return len(self.message_tracker[user.id]) <= self.MESSAGE_LIMIT

    async def schedule_autoreply(self, guild, target_user, original_dm_channel, existing_channel):
        """Schedules an auto-reply if the target user is offline or on Do Not Disturb after 5 minutes."""
        await asyncio.sleep(150)  # Wait 5 minutes (300 seconds)

        # Check if a response has already been made in the channel
        if not self.pending_replies.get(existing_channel.id, True):
            return  # Do not send the auto-reply if a response has been given

        # Fetch the member from the guild
        member = guild.get_member(target_user.id)

        if member:
            automessageadd = "\nYour message has been sent to the autoreply server."

            # Check user's status and dynamically set the embed title and color
            if member.status == discord.Status.offline:
                embed = discord.Embed(
                    title="Offline",
                    description=f"Noah is currently offline. He will reply as soon as he can.{automessageadd}",
                    color=discord.Color.from_str("#cccccc")
                )
            elif member.status == discord.Status.dnd:
                embed = discord.Embed(
                    title="Do Not Disturb",
                    description=f"Noah is currently focused on something else. Please expect a response later.{automessageadd}",
                    color=discord.Color.from_str("#ff0000")
                )
            elif member.status == discord.Status.idle:
                embed = discord.Embed(
                    title="Idle",
                    description=f"Noah is not currently at his laptop. He may reply later.{automessageadd}",
                    color=discord.Color.from_str("#ff9500")
                )
            elif member.status == discord.Status.online:
                embed = discord.Embed(
                    title="Online",
                    description=f"Noah is online and will read your message soon.{automessageadd}",
                    color=discord.Color.from_str("#00ff00")
                )

            await original_dm_channel.send(embed=embed)
        else:
            embed = discord.Embed(
                title="Unknown Status",
                description=f"Unable to determine the status of {target_user.name}.",
                color=discord.Color.orange()
            )
            await original_dm_channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(MessagingSystem(bot))
