import os
import sys
import discord
from discord.ext import commands, tasks
import asyncio
import logging
import random
import json

# Setup basic configuration for logging
LOG_FILE = "/home/pi/discord-bots/bots/CDA Admin/bot_errors.log"
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s:%(levelname)s:%(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

BOT_TOKEN = ""

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="noah ", intents=intents, help_command=None)


SERVER_FILE = "/home/pi/discord-bots/bots/CDA Admin/server.json"

# Dynamically discover .py files in the COGS directory
def discover_extensions():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cogs_dir = os.path.join(current_dir, "COGS")
    if not os.path.isdir(cogs_dir):
        logging.error(f"COGS directory not found at {cogs_dir}")
        return []
    return [
        f"COGS.{file[:-3]}"
        for file in os.listdir(cogs_dir)
        if file.endswith(".py") and not file.startswith("__")
    ]

def resolve_extension_name(extension: str) -> str:
    if "." in extension:
        return extension
    return f"COGS.{extension}"

# Load all extensions
async def load_cogs():
    extensions = discover_extensions()
    for extension in extensions:
        try:
            await bot.load_extension(extension)
            print(f'[LOADED] - {extension}')
        except Exception as e:
            logging.error(f"Failed to load cog {extension}: {e}")
            print(f"--- !!! [FAILED] !!! --- - {extension}: {e}")
    print("All Cogs Loaded")

# Custom Help Command with Owner Check
@bot.command(name="help")
async def custom_help(ctx):
    """Custom help command with pagination for the bot owner and support message for others."""
    if ctx.author.id != 298121351871594497:  # Check if the author is the bot owner
        embed = discord.Embed(
            title="Support",
            description="Message this bot, and a message will be sent to Noah's Discord Server.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
        return

    # Organize commands by cogs
    cog_commands = {}
    for command in bot.commands:
        if command.hidden:
            continue
        cog_name = command.cog_name or "Uncategorized"
        cog_commands.setdefault(cog_name, []).append(command)

    # Create embeds for each cog
    embeds = []
    for cog_name, commands_list in cog_commands.items():
        embed = discord.Embed(
            title=f"Help - {cog_name}",
            description=f"Commands in the `{cog_name}` category",
            color=discord.Color.blue()
        )
        for cmd in commands_list:
            embed.add_field(
                name=f"`{ctx.prefix}{cmd.name}`",
                value=cmd.help or "No description provided.",
                inline=False
            )
        embeds.append(embed)

    # Pagination setup
    if not embeds:
        await ctx.send("No commands available.", delete_after=5)
        return

    current_page = 0
    message = await ctx.send(embed=embeds[current_page])
    reactions = ["\u2B05\uFE0F", "\u27A1\uFE0F"]  # Unicode for ?? and ??

    for reaction in reactions:
        await message.add_reaction(reaction)

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in reactions and reaction.message.id == message.id

    while True:
        try:
            reaction, user = await bot.wait_for("reaction_add", timeout=30.0, check=check)
            if str(reaction.emoji) == "\u2B05\uFE0F":  # Left Arrow
                current_page = (current_page - 1) % len(embeds)
            elif str(reaction.emoji) == "\u27A1\uFE0F":  # Right Arrow
                current_page = (current_page + 1) % len(embeds)
            await message.edit(embed=embeds[current_page])
            await message.remove_reaction(reaction.emoji, user)
        except asyncio.TimeoutError:
            await message.clear_reactions()
            break

# Load, Unload, Reload Commands
@bot.command(name="load")
@commands.is_owner()
async def load(ctx, extension: str):
    try:
        resolved_extension = resolve_extension_name(extension)
        await bot.load_extension(resolved_extension)
        await ctx.send(f"Loaded `{resolved_extension}` successfully.", delete_after=2.5)
    except Exception as e:
        logging.error(f"Failed to load cog {extension}: {e}")
        await ctx.send(f"Failed to load `{extension}`: {e}", delete_after=2.5)

@bot.command(name="unload")
@commands.is_owner()
async def unload(ctx, extension: str):
    """Dynamically unload a cog."""
    try:
        resolved_extension = resolve_extension_name(extension)
        await bot.unload_extension(resolved_extension)
        await ctx.send(f"Unloaded `{resolved_extension}` successfully.", delete_after=2.5)
    except Exception as e:
        logging.error(f"Failed to unload cog {extension}: {e}")
        await ctx.send(f"Failed to unload `{extension}`: {e}", delete_after=2.5)

@bot.command(name="rc")
@commands.is_owner()
async def reload(ctx, extension: str):
    """Dynamically reload a cog."""
    try:
        resolved_extension = resolve_extension_name(extension)
        await bot.reload_extension(resolved_extension)
        await ctx.send(f"Reloaded `{resolved_extension}` successfully.", delete_after=2.5)
    except Exception as e:
        logging.error(f"Failed to reload cog {extension}: {e}")
        await ctx.send(f"Failed to reload `{extension}`: {e}", delete_after=2.5)

@bot.command(name="reload")
@commands.is_owner()
async def reload_all(ctx):
    """Reload all cogs."""
    try:
        await ctx.message.delete()
        extensions = discover_extensions()
        for extension in extensions:
            await asyncio.sleep(1)
            await bot.reload_extension(extension)
        await ctx.send("All cogs reloaded successfully.", delete_after=2.5)
    except Exception as e:
        logging.error(f"Failed to reload all cogs: {e}")
        await ctx.send(f"Failed to reload cogs: {e}", delete_after=2.5)


@bot.command(name="restart")
@commands.is_owner()
async def restart(ctx):
    """Restart the bot dynamically."""
    try:
        await ctx.send("Restarting the bot... Please wait!", delete_after=2.5)
        print("Bot is restarting...")
        await bot.close()  # Closes the bot's connection to Discord
        os.execv(sys.executable, ['python'] + sys.argv)  # Restarts the script
    except Exception as e:
        logging.error(f"Failed to restart the bot: {e}")
        await ctx.send(f"Failed to restart the bot: {e}", delete_after=5)

def load_statuses(file_path="/home/pi/discord-bots/bots/CDA Admin/statuses.txt"):
    try:
        with open(file_path, "r") as file:
            statuses = [line.strip() for line in file if line.strip()]
            if not statuses:
                raise ValueError("Status file is empty.")
            return statuses
    except Exception as e:
        logging.error(f"Error loading statuses: {e}")
        return ["Default status message."]

@tasks.loop(minutes=0.25)
async def update_status():
    statuses = load_statuses()
    current_status = discord.Activity(type=discord.ActivityType.watching, name=random.choice(statuses))
    await bot.change_presence(activity=current_status)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.CheckFailure):
        return
    logging.error(f"Unhandled app command error: {error}")

@bot.command(name="sync")
@commands.is_owner()
async def sync(command):
    await bot.tree.sync()

@bot.command(name="stop")
@commands.is_owner()
async def stop(ctx):
    await bot.close()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    await load_cogs()

    
        # Start the update_status task if not already running
    if not update_status.is_running():
        update_status.start()
    print("Status update task started.")
    
    for command in bot.tree.walk_commands():
        print(f"Command: {command.name} (Group: {command.parent})")


bot.run(BOT_TOKEN)
