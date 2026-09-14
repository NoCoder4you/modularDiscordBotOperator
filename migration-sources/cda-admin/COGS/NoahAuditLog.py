import discord
from discord.ext import commands

AUDIT_LOG_CHANNEL_ID = 1374748024286351501
TARGET_USER_ID = 298121351871594497

class BotAuditCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_audit_log(self, embed: discord.Embed):
        channel = self.bot.get_channel(AUDIT_LOG_CHANNEL_ID)
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
        if user.id != TARGET_USER_ID:
            return
        async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.ban):
            if (entry.target.id == TARGET_USER_ID and
                entry.user.id == guild.me.id and
                (discord.utils.utcnow() - entry.created_at).total_seconds() < 15):
                await guild.leave()
                break

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.id != TARGET_USER_ID:
            return
        async for entry in member.guild.audit_logs(limit=3, action=discord.AuditLogAction.kick):
            if (entry.target.id == TARGET_USER_ID and
                entry.user.id == member.guild.me.id and
                (discord.utils.utcnow() - entry.created_at).total_seconds() < 15):
                await member.guild.leave()
                break

async def setup(bot):
    await bot.add_cog(BotAuditCog(bot))
