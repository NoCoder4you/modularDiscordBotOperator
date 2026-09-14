import discord
from discord.ext import commands, tasks
import aiofiles
import os
from datetime import datetime, timedelta
import asyncio
import json
from pathlib import Path
from zoneinfo import ZoneInfo


# ===========================
# Dynamic Paths + Config
# ===========================

BASE_DIR = Path(__file__).resolve().parent          # /COGS
ROOT_DIR = BASE_DIR.parent                           # /CDA Pay
JSON_DIR = ROOT_DIR / "JSON"                         # /CDA Pay/JSON
BACKUP_DIR = ROOT_DIR / "BACKUPS"                    # /CDA Pay/BACKUPS

JSON_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

SERVER_CONFIG_PATH = JSON_DIR / "server.json"


def load_server_config():
    """Load dynamic server settings."""
    default_config = {
        "channels": {
            "backup_notifications": 0,
            "paystat_allowed": 0,
            "admin_stats": 0,
            "payvoid_allowed": 0,
            "audit_log": 0
        },
        "roles": {
            "payer": "Payer",
            "trial_payer": "Trial Payer",
            "stat_edit": "Stat Edit"
        },
        "time": {
            "timezone": "Europe/London",
            "hour": 0,
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


# ===========================
# Backup Cog
# ===========================

class JSONBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cfg = load_server_config()

        # Determine correct monthly log file
        month_file = datetime.now().strftime("%b_%Y").upper() + ".json"
        self.json_file = JSON_DIR / month_file
        self.ensure_json_file_exists()

        self.notification_channel_id = self.cfg["channels"].get("backup_notifications")

        self.backup_task.start()

        # owner ID
        self.bot.owner_id = 298121351871594497

    def cog_unload(self):
        self.backup_task.cancel()

    # Run once a day at the configured time
    @tasks.loop(hours=24)
    async def backup_task(self):
        await self.backup_json()
        await self.cleanup_old_backups()

    @backup_task.before_loop
    async def before_backup(self):
        await self.bot.wait_until_ready()

        cfg_time = self.cfg["time"]
        tz = ZoneInfo(cfg_time.get("timezone", "Europe/London"))
        now = datetime.now(tz)

        next_run = now.replace(
            hour=cfg_time.get("hour", 21),
            minute=cfg_time.get("minute", 0),
            second=0,
            microsecond=0
        )

        if now >= next_run:
            next_run += timedelta(days=1)

        wait_time = (next_run - now).total_seconds()
        print(f"[BACKUP] First task scheduled in {wait_time} seconds.")
        await asyncio.sleep(wait_time)

    async def backup_json(self):
        try:
            self.ensure_json_file_exists()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Use a more descriptive backup filename based on the monthly JSON
            month_stem = self.json_file.stem  # e.g. DEC_2025
            backup_file = BACKUP_DIR / f"{month_stem}_{timestamp}.json"

            # Read original JSON
            async with aiofiles.open(self.json_file, "r") as f:
                content = await f.read()

            # Write to backup
            async with aiofiles.open(backup_file, "w") as f:
                await f.write(content)

            print(f"[BACKUP] Created: {backup_file}")

            # Notify channel
            channel = self.bot.get_channel(self.notification_channel_id)
            if channel:
                await channel.send(
                    f"Backup created for {month_stem} at {timestamp}.",
                    file=discord.File(backup_file)
                )

        except FileNotFoundError:
            print(f"[BACKUP ERROR] JSON file not found: {self.json_file}")
        except Exception as e:
            print(f"[BACKUP ERROR] {e}")

    def ensure_json_file_exists(self):
        if not self.json_file.exists():
            with open(self.json_file, "w") as file:
                json.dump({
                    "records": {},
                    "daily_totals": {},
                    "weekly_totals": {}
                }, file, indent=4)

    async def cleanup_old_backups(self):
        try:
            now = datetime.now()
            for file in BACKUP_DIR.iterdir():
                if file.is_file():
                    age_days = (now - datetime.fromtimestamp(file.stat().st_ctime)).days
                    if age_days > 7:
                        file.unlink()
                        print(f"[BACKUP] Deleted old backup: {file}")
        except Exception as e:
            print(f"[BACKUP CLEANUP ERROR] {e}")

    @commands.command(name="backup", help="Triggers an immediate backup.")
    async def manual_backup(self, ctx):
        if not any(role.name == "Foundation" for role in ctx.author.roles) and ctx.author.id != self.bot.owner_id:
            return await ctx.send("You do not have permission to use this command.")

        await self.backup_json()
        await self.cleanup_old_backups()
        await ctx.send("Backup completed.", delete_after=10)

async def setup(bot):
    await bot.add_cog(JSONBackup(bot))
