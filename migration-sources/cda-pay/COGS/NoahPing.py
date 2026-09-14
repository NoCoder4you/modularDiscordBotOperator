import discord
from discord.ext import commands
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # /COGS
ROOT_DIR = BASE_DIR.parent                          # /CDA Pay
JSON_DIR = ROOT_DIR / "JSON"                        # /CDA Pay/JSON
JSON_DIR.mkdir(exist_ok=True)
SERVER_CONFIG_PATH = JSON_DIR / "server.json"


def load_server_config():
    default_config = {
        "channels": {
            "admin_stats": 0,
            "paystat_allowed": 0,
            "payvoid_allowed": 0,
            "audit_log": 0,
            "backup_notifications": 0,
            "mention_log": 0
        },
        "roles": {
            "payer": "Payer",
            "trial_payer": "Trial Payer",
            "stat_edit": "Stat Edit"
        },
        "time": {
            "timezone": "Europe/London",
            "hour": 23,
            "minute": 0
        },
        "users": {
            "target_user": 0
        }
    }

    if not SERVER_CONFIG_PATH.exists():
        with open(SERVER_CONFIG_PATH, "w") as f:
            json.dump(default_config, f, indent=4)
        return default_config

    try:
        with open(SERVER_CONFIG_PATH, "r") as f:
            data = json.load(f)

        cfg = default_config.copy()

        cfg_channels = cfg["channels"].copy()
        cfg_channels.update(data.get("channels", {}))

        cfg_roles = cfg["roles"].copy()
        cfg_roles.update(data.get("roles", {}))

        cfg_time = cfg["time"].copy()
        cfg_time.update(data.get("time", {}))

        cfg_users = cfg["users"].copy()
        cfg_users.update(data.get("users", {}))

        cfg["channels"] = cfg_channels
        cfg["roles"] = cfg_roles
        cfg["time"] = cfg_time
        cfg["users"] = cfg_users

        return cfg
    except Exception:
        return default_config



class MentionLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        cfg = load_server_config()
        target_user_id = cfg.get("users", {}).get("target_user")
        log_channel_id = cfg.get("channels", {}).get("mention_log")

        if not target_user_id or not log_channel_id:
            return

        # Check if the target user is mentioned
        if any(user.id == target_user_id for user in message.mentions):
            log_channel = self.bot.get_channel(log_channel_id)
            if not log_channel:
                return

            message_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
            target_user_mention = f"<@{target_user_id}>"
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
            await log_channel.send(target_user_mention)
            await log_channel.send(embed=log_embed)

async def setup(bot):
    await bot.add_cog(MentionLogger(bot))
