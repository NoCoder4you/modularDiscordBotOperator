import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord import app_commands
from discord.ext import commands

BASE_DIR = Path(__file__).resolve().parent          # /COGS
ROOT_DIR = BASE_DIR.parent                          # /CDA Pay
JSON_DIR = ROOT_DIR / "JSON"                        # /CDA Pay/JSON
JSON_DIR.mkdir(exist_ok=True)

SERVER_CONFIG_PATH = JSON_DIR / "server.json"
VOID_DATA_FILE = JSON_DIR / "CDAVoidData.json"

def load_server_config():
    default_config = {'channels': {'admin_stats': 0, 'paystat_allowed': 0, 'payvoid_allowed': 0},
 'roles': {'payer': 'Payer',
           'stat_edit': 'Stat Edit',
           'trial_payer': 'Trial Payer'},
 'time': {'hour': 23, 'minute': 0, 'timezone': 'Europe/London'}}

    if not SERVER_CONFIG_PATH.exists():
        with open(SERVER_CONFIG_PATH, "w") as f:
            json.dump(default_config, f, indent=4)
        return default_config

    try:
        with open(SERVER_CONFIG_PATH, "r") as f:
            data = json.load(f)
        cfg = default_config.copy()
        # merge channels
        cfg_channels = cfg["channels"].copy()
        cfg_channels.update(data.get("channels", {}))
        cfg_roles = cfg["roles"].copy()
        cfg_roles.update(data.get("roles", {}))
        cfg_time = cfg["time"].copy()
        cfg_time.update(data.get("time", {}))
        cfg["channels"] = cfg_channels
        cfg["roles"] = cfg_roles
        cfg["time"] = cfg_time
        return cfg
    except Exception:
        return default_config

def get_payer_mentions(guild: discord.Guild):
    cfg = load_server_config()
    payer_name = cfg.get("roles", {}).get("payer", "Payer")
    trial_name = cfg.get("roles", {}).get("trial_payer", "Trial Payer")
    wanted = {payer_name, trial_name}
    roles = [r for r in getattr(guild, "roles", []) if r.name in wanted]
    mention_text = " ".join(r.mention for r in roles)
    allowed = discord.AllowedMentions(roles=roles)
    return mention_text, allowed


# ─────────────────────────────
def ensure_file():
    if not os.path.exists(VOID_DATA_FILE):
        with open(VOID_DATA_FILE, "w") as f:
            json.dump({"voids": {}}, f, indent=4)
# ─────────────────────────────


def has_payer_role(member: discord.Member) -> bool:
    cfg = load_server_config()
    payer_name = cfg.get("roles", {}).get("payer", "Payer")
    trial_name = cfg.get("roles", {}).get("trial_payer", "Trial Payer")
    wanted = {payer_name, trial_name}
    return any(getattr(role, "name", None) in wanted for role in getattr(member, "roles", []))

# ─────────────────────────────

class PayVoid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        ensure_file()
        with open(VOID_DATA_FILE, "r") as f:
            self.data: dict = json.load(f)

        # weekly reset – uses timezone + hour/minute from server config
        cfg = load_server_config()
        tcfg = cfg.get("time", {})
        tz_name = tcfg.get("timezone", "Europe/London")
        reset_hour = int(tcfg.get("hour", 23))
        reset_minute = int(tcfg.get("minute", 0))

        self.scheduler = AsyncIOScheduler(timezone=tz_name)
        self.scheduler.add_job(
            self.reset_voids,
            trigger="cron",
            day_of_week="sun",
            hour=reset_hour,
            minute=reset_minute,
            id="weekly_void_reset",
            coalesce=True,
            misfire_grace_time=300,
        )
        self.scheduler.start()

    # ── helpers ───────────────────────────────────────────
    def save(self):
        with open(VOID_DATA_FILE, "w") as f:
            json.dump(self.data, f, indent=4)

    def reset_voids(self):
        self.data["voids"] = {}
        self.save()

    # ── /payvoid ──────────────────────────────────────────
    @app_commands.command(
        name="payvoid",
        description="Void a user’s pay. Three voids = 24hr Pay Ban."
    )
    @app_commands.describe(username="Type the username exactly.")
    async def payvoid(self, interaction: discord.Interaction, username: str):
        # --- errors returned ephemerally ---
        cfg = load_server_config()
        allowed_channel_id = cfg.get("channels", {}).get("payvoid_allowed")
        if not allowed_channel_id or interaction.channel_id != allowed_channel_id:
            await interaction.response.send_message(
                "Wrong channel for this command.", ephemeral=True
            )
            return
        if not has_payer_role(interaction.user):
            await interaction.response.send_message(
                "You don’t have permission to do that.", ephemeral=True
            )
            return
        # ------------------------------------

        key   = username.strip().lower()
        label = username.strip()

        rec = self.data["voids"].setdefault(
            key, {"void_count": 0, "ban_until": None}
        )

        # ── if already banned, start a new 24 h period immediately ──
        if rec["ban_until"]:
            active_until = datetime.fromisoformat(rec["ban_until"])
            if active_until > datetime.now():
                new_until_raw = datetime.now() + timedelta(hours=24)
                new_until = new_until_raw.replace(minute=0, second=0, microsecond=0)
                rec["ban_until"] = new_until.isoformat()
                self.save()

                mention_text, allowed_mentions = get_payer_mentions(interaction.guild)

                embed = discord.Embed(
                    title="Pay Ban",
                    description=(
                        f"**User:** `{label}`\n"
                        f"**Until:** <t:{int(new_until.timestamp())}:f>"
                    ),
                    color=discord.Color.red()
                )
                await interaction.response.send_message(
                    content=mention_text,
                    embed=embed,
                    allowed_mentions=allowed_mentions
                )
                return
            # ban expired → clear
            rec.update({"void_count": 0, "ban_until": None})

        # ── record the void ──
        rec["void_count"] += 1

        # ── third void → apply fresh 24hr ban ──
        if rec["void_count"] >= 3:
            rec["void_count"] = 0
            ban_until_raw = datetime.now() + timedelta(hours=24)
            ban_until = ban_until_raw.replace(minute=0, second=0, microsecond=0)
            rec["ban_until"] = ban_until.isoformat()
            self.save()

            mention_text, allowed_mentions = get_payer_mentions(interaction.guild)

            embed = discord.Embed(
                title="Pay Ban",
                description=(
                    f"**User:** `{label}`\n"
                    f"**Until:** <t:{int(ban_until.timestamp())}:f>"
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(
                content=mention_text,
                embed=embed,
                allowed_mentions=allowed_mentions
            )
        else:
            # ── 1/3 or 2/3 voids ──
            self.save()
            embed = discord.Embed(
                title="Void Recorded",
                description=f"**User:** `{label}`\n **Voids:** {rec['void_count']}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)

    # ── cleanup ───────────────────────────────────────────
    def cog_unload(self):
        self.scheduler.shutdown(wait=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(PayVoid(bot))
