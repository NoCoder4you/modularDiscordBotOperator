import discord
import aiohttp
import asyncio
import json
import os
import time
from urllib.parse import quote
from discord.ext import commands, tasks
from COGS.paths import data_path

class AutoRoleUpdater(commands.Cog):
    # Habbo does not publish a request quota. Keeping every request on one paced
    # lane prevents the scheduled updater and member-join handler from bursting.
    HABBO_INITIAL_REQUEST_INTERVAL = 1.0
    HABBO_MIN_REQUEST_INTERVAL = 0.25
    HABBO_MAX_REQUEST_INTERVAL = 8.0
    HABBO_SUCCESS_WINDOW = 25
    HABBO_MAX_ATTEMPTS = 5

    def __init__(self, bot):
        self.bot = bot
        self.roles_file_path = data_path("JSON/rolesbadges.json")
        self.server_data_path = data_path("JSON/server.json")
        self.roles_data = self.load_roles_data()
        self.server_data = self.load_server_data()
        self.verified_role_id = 1277489459226738808
        self.awaiting_verification_role_id = 1248310200939581594
        self._habbo_request_lock = asyncio.Lock()
        self._next_habbo_request_at = 0.0
        self._habbo_blocked_until = 0.0
        self._habbo_request_interval = self.HABBO_INITIAL_REQUEST_INTERVAL
        self._habbo_success_streak = 0

        self.update_roles_task.start()  # Start the automatic update task

    def cog_unload(self):
        """Stop the background loop when this cog is unloaded or reloaded."""
        self.update_roles_task.cancel()

    async def _wait_for_habbo_request_slot(self):
        """Serialize and space Habbo API calls across every updater entry point."""
        now = time.monotonic()
        allowed_at = max(self._next_habbo_request_at, self._habbo_blocked_until)
        if allowed_at > now:
            await asyncio.sleep(allowed_at - now)

        # Measure again because sleeping advances the monotonic clock.
        self._next_habbo_request_at = time.monotonic() + self._habbo_request_interval

    def _record_habbo_success(self):
        """Cautiously speed up after a sustained run of successful requests."""
        self._habbo_success_streak += 1
        if self._habbo_success_streak < self.HABBO_SUCCESS_WINDOW:
            return

        previous_interval = self._habbo_request_interval
        self._habbo_request_interval = max(
            self.HABBO_MIN_REQUEST_INTERVAL,
            self._habbo_request_interval * 0.8,
        )
        self._habbo_success_streak = 0
        if self._habbo_request_interval != previous_interval:
            print(
                "Habbo API is healthy; request interval reduced to "
                f"{self._habbo_request_interval:.2f}s."
            )

    def _record_habbo_rate_limit(self):
        """Immediately slow future requests after Habbo reports a rate limit."""
        self._habbo_request_interval = min(
            self.HABBO_MAX_REQUEST_INTERVAL,
            self._habbo_request_interval * 2,
        )
        # Require a complete success window before trying a faster rate again.
        self._habbo_success_streak = 0

    async def _defer_habbo_requests(self, delay):
        """Apply a Retry-After delay globally, including concurrent join checks."""
        self._habbo_blocked_until = max(
            self._habbo_blocked_until,
            time.monotonic() + delay,
        )

    async def _get_habbo_json(self, session, url):
        """Fetch JSON with pacing and bounded retries for throttling/outages."""
        for attempt in range(self.HABBO_MAX_ATTEMPTS):
            # Keep the lock until the response is classified so a concurrent
            # caller cannot slip through immediately after a 429 response.
            async with self._habbo_request_lock:
                await self._wait_for_habbo_request_slot()
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            payload = await response.json()
                            self._record_habbo_success()
                            return payload

                        if response.status == 429:
                            # Honour Habbo's requested cooldown. If the header is absent
                            # or malformed, exponential backoff prevents a retry storm.
                            try:
                                delay = max(float(response.headers.get("Retry-After", "")), 1.0)
                            except (TypeError, ValueError):
                                delay = min(2 ** attempt, 60)
                            self._record_habbo_rate_limit()
                            await self._defer_habbo_requests(delay)
                            print(
                                f"Habbo API rate limited; retrying in {delay:.1f}s "
                                f"at a {self._habbo_request_interval:.2f}s interval."
                            )
                            continue

                        if 500 <= response.status < 600:
                            await self._defer_habbo_requests(min(2 ** attempt, 30))
                            continue

                        print(f"Habbo API request failed with HTTP {response.status}: {url}")
                        return None
                except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                    delay = min(2 ** attempt, 30)
                    await self._defer_habbo_requests(delay)
                    print(f"Habbo API request failed ({error}); retrying in {delay}s.")

        print(f"Habbo API request exhausted retries: {url}")
        return None

    async def _get_habbo_user_and_groups(self, session, habbo_name):
        """Return the profile and groups while avoiding a duplicate profile call."""
        encoded_name = quote(habbo_name, safe="")
        profile = await self._get_habbo_json(
            session,
            f"https://www.habbo.com/api/public/users?name={encoded_name}",
        )
        habbo_id = profile.get("uniqueId") if isinstance(profile, dict) else None
        if not habbo_id:
            return None, None

        groups = await self._get_habbo_json(
            session,
            f"https://www.habbo.com/api/public/users/{quote(str(habbo_id), safe='')}/groups",
        )
        return profile, groups if isinstance(groups, list) else None

    def load_roles_data(self):
        """Load the role mapping from JSON."""
        if os.path.exists(self.roles_file_path):
            try:
                with open(self.roles_file_path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    return data.get("roles", {})
            except json.JSONDecodeError:
                print(f"Error decoding {self.roles_file_path}. Ensure it's valid JSON.")
                return {}
        return {}

    def load_server_data(self):
        """Load the list of verified users from JSON."""
        if os.path.exists(self.server_data_path):
            try:
                with open(self.server_data_path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    return data if "verified_users" in data else {"verified_users": []}
            except json.JSONDecodeError:
                print(f"Error decoding {self.server_data_path}. Ensure it's valid JSON.")
                return {"verified_users": []}
        return {"verified_users": []}

    @tasks.loop(minutes=10)  # Runs every 10 minutes
    async def update_roles_task(self):
        """Automatically check and update roles for all verified users."""
        guild = self.bot.get_guild(1248307521119060028)  # Replace with your server's ID

        if not guild:
            print("Guild not found.")
            return

        async with aiohttp.ClientSession() as session:
            for user_data in self.server_data["verified_users"]:
                user_id = int(user_data["user_id"])
                habbo_name = user_data["habbo"]

                member = guild.get_member(user_id)
                if not member:
                    continue  # Skip if user is not found in the server

                profile, groups_data = await self._get_habbo_user_and_groups(session, habbo_name)
                if groups_data is None:
                    continue

                # Reuse the profile motto instead of making a third Habbo API call.
                added_roles, removed_roles = await self.assign_roles(
                    member, groups_data, guild, profile.get("motto", "")
                )

                if added_roles is None and removed_roles is None:
                    continue

                log_channel = guild.get_channel(1248316058520260713)  # Replace with your log channel ID
                if log_channel:
                    embed = discord.Embed(title="Roles Updated", color=discord.Color.green())
                    embed.add_field(name="User", value=f"{member.mention}", inline=False)
                    if added_roles:
                        embed.add_field(name="Added Roles", value="\n".join(added_roles), inline=False)
                    if removed_roles:
                        embed.add_field(name="Removed Roles", value="\n".join(removed_roles), inline=False)
                    await log_channel.send(embed=embed)

    async def assign_roles(self, member, groups_data, guild, motto=""):
        """
        Assign roles based on Habbo groups:
        - EmployeeRoles: assign ONLY the single highest role (based on JSON order).
        - DonatorRoles/Misc/SpecialUnits: additive.
        - 'CDA Employee' and 'iC' umbrella flags come from ANY matched employee role.
        """
        roles_data = self.roles_data
        added_roles = []
        removed_roles = []

        cda_employee_role_id = 1248313244481884220
        ic_member_role_id = 1249819550015426571

        current_roles = {role.id for role in member.roles}
        expected_roles = set()

        # Track all managed role IDs so we can remove ones users shouldn't have
        valid_role_ids = set()
        for category in ["EmployeeRoles", "DonatorRoles", "Misc", "SpecialUnits"]:
            for role_data in roles_data.get(category, []):
                rid = role_data.get("role_id")
                if rid:
                    valid_role_ids.add(rid)

        # Build a set of Habbo group IDs for quick lookups
        group_ids = {g.get("id") for g in groups_data if isinstance(g, dict) and g.get("id")}

        # Employee roles: collect all matches, then pick the highest by JSON order (first match)
        employee_roles = roles_data.get("EmployeeRoles", [])
        matched_employee_roles = [rd for rd in employee_roles if rd.get("group_id") in group_ids]
        highest_employee_role = matched_employee_roles[0] if matched_employee_roles else None

        has_cda_employee = False
        has_ic_role = False

        # Add ONLY the highest employee role
        if highest_employee_role:
            role = guild.get_role(highest_employee_role.get("role_id"))
            if role:
                expected_roles.add(role.id)

        # Umbrella flags from ANY matched employee role
        for emp_role in matched_employee_roles:
            if emp_role.get("cdaemployee") == "yes":
                has_cda_employee = True
            if emp_role.get("iC") == "yes":
                has_ic_role = True

        # Other categories (additive)
        for category in ["DonatorRoles", "Misc", "SpecialUnits"]:
            for role_data in roles_data.get(category, []):
                if role_data.get("group_id") in group_ids:
                    role = guild.get_role(role_data.get("role_id"))
                    if role:
                        expected_roles.add(role.id)

        # Add/remove umbrella roles
        if has_cda_employee:
            expected_roles.add(cda_employee_role_id)
        else:
            valid_role_ids.add(cda_employee_role_id)

        if has_ic_role:
            expected_roles.add(ic_member_role_id)
        else:
            valid_role_ids.add(ic_member_role_id)

        # Compute diffs
        roles_to_add = expected_roles - current_roles
        roles_to_remove = (current_roles - expected_roles) & valid_role_ids
        roles_to_remove -= roles_to_add  # avoid race if role is both in add/remove due to timing

        # Preserve the CDA umbrella role when the already-fetched profile motto
        # identifies the member as CDA; no extra API request is necessary here.
        if cda_employee_role_id in roles_to_remove and "cda" in motto.lower():
            roles_to_remove.remove(cda_employee_role_id)

        # If nothing to do, return early
        if not roles_to_add and not roles_to_remove:
            return None, None

        try:
            # Add needed roles
            for role_id in roles_to_add:
                role = guild.get_role(role_id)
                if role:
                    await member.add_roles(role, reason="AutoRoleUpdater: add")
                    added_roles.append(role.name)

            # Remove unneeded roles
            for role_id in roles_to_remove:
                role = guild.get_role(role_id)
                if role:
                    await member.remove_roles(role, reason="AutoRoleUpdater: remove")
                    removed_roles.append(role.name)

        except discord.Forbidden:
            print(f"Skipping {member.name} - Missing permissions to update roles.")
            return None, None
        except Exception as e:
            print(f"Unexpected error while updating roles for {member.name}: {e}")
            return None, None

        return added_roles, removed_roles

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Runs the moment someone joins the guild."""
        # Are they in server.json ? verified_users?
        entry = next((
            u for u in self.server_data.get("verified_users", [])
            if int(u["user_id"]) == member.id
        ), None)

        if entry is None:
            return  # not a verified user, leave them alone

        # 1) nickname ? Habbo name
        try:
            await member.edit(nick=entry["habbo"])
        except discord.Forbidden:
            pass  # lacking manage-nicknames permission is not fatal

        # 2) remove "Awaiting Verification", add "Verified"
        guild = member.guild
        await member.remove_roles(
            guild.get_role(self.awaiting_verification_role_id),
            reason="User is verified"
        )
        await member.add_roles(
            guild.get_role(self.verified_role_id),
            reason="User is verified"
        )

        # 3) give all other appropriate roles immediately
        async with aiohttp.ClientSession() as session:
            profile, groups_data = await self._get_habbo_user_and_groups(
                session, entry["habbo"]
            )
        if groups_data is not None:
            await self.assign_roles(
                member, groups_data, guild, profile.get("motto", "")
            )

    @update_roles_task.before_loop
    async def before_update_roles_task(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(AutoRoleUpdater(bot))
