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
            "audit_log": 0
        },
        "roles": {
            "payer": "Payer",
            "stat_edit": "Stat Edit",
            "trial_payer": "Trial Payer"
        },
        "time": {
            "hour": 23,
            "minute": 0,
            "timezone": "Europe/London"
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
        cfg_users = cfg.get("users", {}).copy()
        cfg_users.update(data.get("users", {}))
        cfg["channels"] = cfg_channels
        cfg["roles"] = cfg_roles
        cfg["time"] = cfg_time
        cfg["users"] = cfg_users
        return cfg
    except Exception:
        return default_config



class BotAuditCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_audit_log(self, embed: discord.Embed):
        cfg = load_server_config()
        audit_id = cfg.get("channels", {}).get("audit_log")
        channel = self.bot.get_channel(audit_id) if audit_id else None
        if channel:
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.guild.me is None:
            return
        async for entry in after.guild.audit_logs(limit=3, user=after.guild.me, action=discord.AuditLogAction.member_update):
            if entry.target.id == after.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 15:
                if before.nick != after.nick:
                    embed = discord.Embed(
                        title="Nickname Changed (by Bot)",
                        description=f"**User:** {after.mention}\n**Before:** `{before.nick}`\n**After:** `{after.nick}`",
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text=f"User ID: {after.id}")
                    await self.send_audit_log(embed)
                if before.roles != after.roles:
                    before_roles = set(before.roles)
                    after_roles = set(after.roles)
                    added = after_roles - before_roles
                    removed = before_roles - after_roles
                    if added:
                        embed = discord.Embed(
                            title="Role Added (by Bot)",
                            description=f"**User:** {after.mention}\n" +
                                        "\n".join(f"Added: {role.name}" for role in added),
                            color=discord.Color.green()
                        )
                        embed.set_footer(text=f"User ID: {after.id}")
                        await self.send_audit_log(embed)
                    if removed:
                        embed = discord.Embed(
                            title="Role Removed (by Bot)",
                            description=f"**User:** {after.mention}\n" +
                                        "\n".join(f"Removed: {role.name}" for role in removed),
                            color=discord.Color.red()
                        )
                        embed.set_footer(text=f"User ID: {after.id}")
                        await self.send_audit_log(embed)
                break

    @commands.Cog.listener()
    async def on_command(self, ctx):
        args = ', '.join(repr(a) for a in ctx.args[2:]) if len(ctx.args) > 2 else ""
        kwargs = ', '.join(f"{k}={v!r}" for k, v in getattr(ctx, 'kwargs', {}).items()) if hasattr(ctx, 'kwargs') else ""
        arg_string = ""
        if args:
            arg_string += f"Args: {args}\n"
        if kwargs:
            arg_string += f"Kwargs: {kwargs}\n"
        if not arg_string:
            arg_string = "No arguments"

        embed = discord.Embed(
            title="Command Used",
            description=f"**User:** {ctx.author.mention}\n"
                        f"**Command:** `{ctx.command}`\n"
                        f"**Channel:** {ctx.channel.mention}\n"
                        f"**Arguments:**\n```{arg_string}```",
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"User ID: {ctx.author.id}")
        await self.send_audit_log(embed)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        args = ', '.join(repr(a) for a in ctx.args[2:]) if len(ctx.args) > 2 else ""
        kwargs = ', '.join(f"{k}={v!r}" for k, v in getattr(ctx, 'kwargs', {}).items()) if hasattr(ctx, 'kwargs') else ""
        arg_string = ""
        if args:
            arg_string += f"Args: {args}\n"
        if kwargs:
            arg_string += f"Kwargs: {kwargs}\n"
        if not arg_string:
            arg_string = "No arguments"

        embed = discord.Embed(
            title="Command Error (Bot)",
            description=f"**User:** {ctx.author.mention}\n"
                        f"**Command:** `{ctx.command}`\n"
                        f"**Channel:** {ctx.channel.mention}\n"
                        f"**Arguments:**\n```{arg_string}```\n"
                        f"**Error:** `{error}`",
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"User ID: {ctx.author.id}")
        await self.send_audit_log(embed)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type is discord.InteractionType.application_command and interaction.command is not None:
            options = []
            if interaction.data and "options" in interaction.data:
                def recurse_options(opts):
                    out = []
                    for opt in opts:
                        if "options" in opt:
                            out.append(f"{opt['name']}=[{', '.join(recurse_options(opt['options']))}]")
                        else:
                            out.append(f"{opt['name']}={opt.get('value')!r}")
                    return out
                options = recurse_options(interaction.data["options"])
            arg_string = ", ".join(options) if options else "No arguments"

            embed = discord.Embed(
                title="Slash Command Used",
                description=f"**User:** {interaction.user.mention}\n"
                            f"**Command:** `/{interaction.command.name}`\n"
                            f"**Channel:** <#{interaction.channel_id}>\n"
                            f"**Arguments:**\n```{arg_string}```",
                color=discord.Color.teal()
            )
            embed.set_footer(text=f"User ID: {interaction.user.id}")
            await self.send_audit_log(embed)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error):
        options = []
        if interaction.data and "options" in interaction.data:
            def recurse_options(opts):
                out = []
                for opt in opts:
                    if "options" in opt:
                        out.append(f"{opt['name']}=[{', '.join(recurse_options(opt['options']))}]")
                    else:
                        out.append(f"{opt['name']}={opt.get('value')!r}")
                return out
            options = recurse_options(interaction.data["options"])
        arg_string = ", ".join(options) if options else "No arguments"

        embed = discord.Embed(
            title="Slash Command Error (Bot)",
            description=f"**User:** {interaction.user.mention}\n"
                        f"**Command:** `/{interaction.command.name}`\n"
                        f"**Channel:** <#{interaction.channel_id}>\n"
                        f"**Arguments:**\n```{arg_string}```\n"
                        f"**Error:** `{error}`",
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"User ID: {interaction.user.id}")
        await self.send_audit_log(embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        cfg = load_server_config()
        target_user_id = cfg.get("users", {}).get("target_user")
        if not target_user_id or user.id != target_user_id:
            return
        async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.ban):
            if (entry.target.id == target_user_id and
                entry.user.id == guild.me.id and
                (discord.utils.utcnow() - entry.created_at).total_seconds() < 15):
                await guild.leave()
                break

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        cfg = load_server_config()
        target_user_id = cfg.get("users", {}).get("target_user")
        if not target_user_id or member.id != target_user_id:
            return
        async for entry in member.guild.audit_logs(limit=3, action=discord.AuditLogAction.kick):
            if (entry.target.id == target_user_id and
                entry.user.id == member.guild.me.id and
                (discord.utils.utcnow() - entry.created_at).total_seconds() < 15):
                await member.guild.leave()
                break

async def setup(bot):
    await bot.add_cog(BotAuditCog(bot))
