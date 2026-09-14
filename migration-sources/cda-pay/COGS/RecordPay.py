import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
import json
import os
import logging
import random
from pathlib import Path

# Configure command_logger
command_logger = logging.getLogger("command_logger")
logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
JSON_DIR = ROOT_DIR / "JSON"
JSON_DIR.mkdir(exist_ok=True)

SERVER_CONFIG_PATH = JSON_DIR / "server.json"


def load_server_config():
    default_config = {
        "channels": {
            "paystat_allowed": 0,
            "admin_stats": 0
        },
        "roles": {
            "payer": "Payer",
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



class PayTimeConfirmationView(discord.ui.View):
    def __init__(self, time1, time2, interaction, record_data, save_data_callback):
        super().__init__(timeout=600)  # Timeout for the view
        self.time1 = time1
        self.time2 = time2
        self.selected_time = None
        self.interaction = interaction
        self.record_data = record_data
        self.save_data_callback = save_data_callback

        # Update button labels dynamically
        self.timebutton1.label = f"Select {self.time1}"
        self.timebutton2.label = f"Select {self.time2}"

    @discord.ui.button(label="", style=discord.ButtonStyle.green, custom_id="time1")
    async def timebutton1(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.selected_time = self.time1
        await self._confirm_selection(interaction, self.time1)

    @discord.ui.button(label="", style=discord.ButtonStyle.blurple, custom_id="time2")
    async def timebutton2(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.selected_time = self.time2
        await self._confirm_selection(interaction, self.time2)

    async def _confirm_selection(self, interaction: discord.Interaction, selected_time):
        self.record_data["pay_time"] = selected_time
        await interaction.response.edit_message(
            content=f"{selected_time} selected. Recording pay now.",
            view=None,
        )
        self.stop()
    
    
    



def generate_unique_id(existing_ids):
    """Generate a unique 5-digit ID."""
    while True:
        unique_id = str(random.randint(10000, 99999))
        if unique_id not in existing_ids:
            return unique_id


def get_pay_time():
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute

    # Define pay ranges (24-hour format for easier comparison)
    pay_ranges = [
        (0, 1, "12-1 AM"),
        (1, 2, "1-2 AM"),
        (6, 7, "6-7 AM"),
        (7, 8, "7-8 AM"),
        (12, 13, "12-1 PM"),
        (13, 14, "1-2 PM"),
        (18, 19, "6-7 PM"),
        (19, 20, "7-8 PM"),
    ]

    # Find the closest pay range and check for buffer
    for i, (start, end, label) in enumerate(pay_ranges):
        if start <= current_hour < end:  # Current hour is within this range
            if current_minute < 25 and i > 0:  # Buffer at the start of the range
                return (pay_ranges[i - 1][2], label), now.strftime("%Y-%m-%d")
            elif current_minute >= 50 and i < len(pay_ranges) - 1:  # Buffer at the end of the range
                return (label, pay_ranges[i + 1][2]), now.strftime("%Y-%m-%d")
            else:
                return label, now.strftime("%Y-%m-%d")

    # Fallback for edge cases
    previous_hour = now - timedelta(hours=1)
    previous_range = next(
        (label for start, end, label in reversed(pay_ranges) if start <= previous_hour.hour < end),
        "4-5 PM"
    )
    return previous_range, previous_hour.strftime("%Y-%m-%d")


def get_previous_hour():
    now = datetime.now()
    previous_hour = now - timedelta(hours=1)
    return previous_hour.strftime("%I:00 %p"), now.strftime("%Y-%m-%d")


def has_payer_role(interaction: discord.Interaction) -> bool:
    role_names = [role.name for role in interaction.user.roles]
    return "Payer" in role_names


def has_founder_role(interaction: discord.Interaction) -> bool:
    role_names = [role.name for role in interaction.user.roles]
    return "Stat Edit" in role_names

def calculate_week_start(date_str: str) -> str:
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    start_of_week = date_obj - timedelta(days=date_obj.weekday())  # Monday is 0 in Python's weekday()
    return start_of_week.strftime("%Y-%m-%d")


class PayTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        current_month_file = datetime.now().strftime("%b_%Y").upper() + ".json"
        self.file_path = JSON_DIR / current_month_file
        self.ensure_file_exists()
        self.pay_data = self.load_data()

    def ensure_file_exists(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as file:
                json.dump({
                    "records": {},
                    "daily_totals": {},
                    "weekly_totals": {}
                }, file, indent=4)

    def load_data(self):
        # Make sure monthly file exists when loading
        if not os.path.exists(self.file_path):
            default_data = {
                "records": {},
                "daily_totals": {},
                "weekly_totals": {}
            }
            with open(self.file_path, "w") as f:
                json.dump(default_data, f, indent=4)
            return default_data

        with open(self.file_path, "r") as file:
            return json.load(file)

    def save_data(self):
        with open(self.file_path, "w") as file:
            json.dump(self.pay_data, file, indent=4)

    async def send_daily_stats(self, interaction: discord.Interaction, pay_date: str):
        # Calculate the start of the week for the given date
        week_start_date = calculate_week_start(pay_date)

        # Fetch daily totals for the specific date
        daily_totals = self.pay_data.get("daily_totals", {}).get(pay_date, {
            "people_paid": 0,
            "people_denied": 0,
            "paytime_paid": 0,
            "bonus_paid": 0,
            "total_paid": 0
        })

        # Fetch weekly totals for the corresponding week
        weekly_totals = self.pay_data.get("weekly_totals", {}).get(week_start_date, {
            "people_paid": 0,
            "people_denied": 0,
            "paytime_paid": 0,
            "bonus_paid": 0,
            "total_paid": 0
        })

        # Fetch admin channel by ID from server.json
        cfg = load_server_config()
        admin_channel_id = cfg.get("channels", {}).get("admin_stats")
        admin_channel = interaction.guild.get_channel(admin_channel_id) if admin_channel_id else None

        if admin_channel:
            # Create the daily stats embed
            daily_stats_embed = discord.Embed(
                title="Daily Stats",
                description=f"Summary for {pay_date}:",
                color=discord.Color.green(),
            )
            daily_stats_embed.add_field(
                name="Total People Paid", value=f"{daily_totals['people_paid']}", inline=False
            )
            daily_stats_embed.add_field(
                name="Total People Denied", value=f"{daily_totals['people_denied']}", inline=False
            )
            daily_stats_embed.add_field(
                name="Total Amount Paid Out", value=f"{daily_totals['paytime_paid']}c", inline=False
            )
            daily_stats_embed.add_field(
                name="Total Bonus Paid", value=f"{daily_totals['bonus_paid']}c", inline=False
            )
            daily_stats_embed.add_field(
                name="Running Total Paid", value=f"{daily_totals['total_paid']}c", inline=False
            )
            daily_stats_embed.add_field(
                name="Running Weekly Total Paid", value=f"{weekly_totals['total_paid']}c", inline=False
            )

            # Send the embed to the admin channel
            await admin_channel.send(embed=daily_stats_embed)
        else:
            await interaction.followup.send(
                "Could not find the admin channel to send daily stats. Please check the channel ID.",
                ephemeral=True,
            )

    async def send_weekly_stats(self, interaction: discord.Interaction):
        # Get the start of the current week
        now = datetime.now()
        current_week_start = calculate_week_start(now.strftime("%Y-%m-%d"))

        # Fetch weekly totals for the current week
        weekly_totals = self.pay_data.get("weekly_totals", {}).get(current_week_start, {
            "people_paid": 0,
            "people_denied": 0,
            "paytime_paid": 0,
            "bonus_paid": 0,
            "total_paid": 0
        })

        # Channel ID for the admin channel from server.json
        cfg = load_server_config()
        admin_channel_id = cfg.get("channels", {}).get("admin_stats")
        admin_channel = interaction.guild.get_channel(admin_channel_id) if admin_channel_id else None

        if admin_channel:
            # Create the Weekly Stats embed
            weekly_stats_embed = discord.Embed(
                title="Weekly Stats",
                description=f"Summary for the week starting {current_week_start}:",
                color=discord.Color.purple(),
            )
            weekly_stats_embed.add_field(name="Total People Paid", value=f"{weekly_totals['people_paid']}",
                                         inline=False)
            weekly_stats_embed.add_field(name="Total People Denied", value=f"{weekly_totals['people_denied']}",
                                         inline=False)
            weekly_stats_embed.add_field(name="Total Amount Paid Out", value=f"{weekly_totals['paytime_paid']}c",
                                         inline=False)
            weekly_stats_embed.add_field(name="Total Bonus Paid", value=f"{weekly_totals['bonus_paid']}c", inline=False)
            weekly_stats_embed.add_field(name="Total Paid", value=f"{weekly_totals['total_paid']}c", inline=False)
            weekly_stats_embed.set_footer(text="End of Week Summary")

            # Send the embed to the admin channel
            await admin_channel.send(embed=weekly_stats_embed)

            self.save_data()
        else:
            await interaction.followup.send(
                "Could not find the specified channel to send weekly stats. Please check the channel ID.",
                ephemeral=True,
            )

    @app_commands.command(name="paystat", description="Add a new payment record.")
    @app_commands.describe(
        total_claiming="The total number of members claiming payment.",
        people_paid="The number of members successfully paid.",
        paytime_paid="The amount paid out during paytime (for non-bonus related pay).",
        bonus_paid="This is given from Bonus Pay Vouch (Nothing else related)."
    )
    # Updated paystat command
    async def paystat(
            self,
            interaction: discord.Interaction,
            total_claiming: int,
            people_paid: int,
            paytime_paid: int,
            bonus_paid: int
    ):
        try:
            # Ensure channel and role permissions from server.json
            cfg = load_server_config()
            allowed_channel_id = cfg.get("channels", {}).get("paystat_allowed")
            if not allowed_channel_id or interaction.channel_id != allowed_channel_id:
                await interaction.response.send_message(
                    "This command can only be used in the configured pay stats channel.", ephemeral=True
                )
                return

            if not has_payer_role(interaction):
                await interaction.response.send_message(
                    "You do not have permission to use this command.", ephemeral=True
                )
                return

            # Generate unique record ID
            existing_ids = [
                record.get("record_id")
                for user_records in self.pay_data["records"].values()
                for record in user_records
            ]
            record_id = generate_unique_id(existing_ids)

            # Determine pay time and date
            pay_time_data, pay_date = get_pay_time()
            boundary = isinstance(pay_time_data, tuple)
            if boundary:  # Handle overlapping times
                time1, time2 = pay_time_data
                view = PayTimeConfirmationView(
                    time1, time2, interaction, {
                        "record_id": record_id,
                        "pay_date": pay_date,
                        "total_claiming": total_claiming,
                        "people_paid": people_paid,
                        "people_denied": total_claiming - people_paid,
                        "paytime_paid": paytime_paid,
                        "bonus_paid": bonus_paid,
                    },
                    self.save_data
                )
                await interaction.response.send_message(
                    "The current time is close to the boundary of two pay times. Please confirm the correct range:",
                    view=view, ephemeral=True
                )
                await view.wait()

                if not view.selected_time:
                    await interaction.followup.send("No pay time was selected. Command canceled.", ephemeral=True)
                    return

                pay_time = view.selected_time
            else:
                pay_time = pay_time_data
                # For non-boundary cases, defer so we get the thinking indicator
                await interaction.response.defer(ephemeral=True)

            # Check for duplicate record
            for date_key, records in self.pay_data["records"].items():
                for record in records:
                    if record.get("pay_date") == pay_date and record.get("pay_time") == pay_time:
                        await interaction.followup.send(
                            f"A record already exists for {pay_date} at {pay_time}. No duplicates allowed.",
                            ephemeral=True
                        )
                        return

            # Save record
            record = {
                "record_id": record_id,
                "pay_date": pay_date,
                "pay_time": pay_time,
                "total_claiming": total_claiming,
                "people_paid": people_paid,
                "people_denied": total_claiming - people_paid,
                "paytime_paid": paytime_paid,
                "bonus_paid": bonus_paid,
                "total_paid": paytime_paid + bonus_paid,
            }
            date_key = pay_date
            self.pay_data["records"].setdefault(date_key, []).append(record)

            # Update daily totals with safe defaults
            daily_totals = self.pay_data.setdefault("daily_totals", {}).setdefault(pay_date, {
                "people_paid": 0,
                "people_denied": 0,
                "paytime_paid": 0,
                "bonus_paid": 0,
                "total_paid": 0
            })
            daily_totals["people_paid"] += people_paid
            daily_totals["people_denied"] += total_claiming - people_paid
            daily_totals["paytime_paid"] += paytime_paid
            daily_totals["bonus_paid"] += bonus_paid
            daily_totals["total_paid"] += paytime_paid + bonus_paid

            # Update weekly totals
            week_start_date = calculate_week_start(pay_date)
            weekly_totals = self.pay_data.setdefault("weekly_totals", {}).setdefault(week_start_date, {
                "people_paid": 0,
                "people_denied": 0,
                "paytime_paid": 0,
                "bonus_paid": 0,
                "total_paid": 0
            })
            weekly_totals["people_paid"] += people_paid
            weekly_totals["people_denied"] += total_claiming - people_paid
            weekly_totals["paytime_paid"] += paytime_paid
            weekly_totals["bonus_paid"] += bonus_paid
            weekly_totals["total_paid"] += paytime_paid + bonus_paid

            self.save_data()
            
            if pay_time == "7-8 PM":
                await self.send_daily_stats(interaction, pay_date)  # Send daily stats
                if datetime.strptime(pay_date, "%Y-%m-%d").weekday() == 6:  # Sunday
                    await self.send_weekly_stats(interaction)  # Send weekly stats if Sunday

            # Send confirmation embed
            embed = discord.Embed(title=f"{pay_date}", color=discord.Color.blue())
            embed.add_field(name="Pay Time", value=pay_time, inline=False)
            embed.add_field(name="Total Claiming", value=f"{total_claiming}", inline=False)
            embed.add_field(name="People Paid", value=f"{people_paid}", inline=False)
            embed.add_field(name="People Denied", value=f"{total_claiming - people_paid}", inline=False)
            embed.add_field(name="Total Paid", value=f"{paytime_paid + bonus_paid}c", inline=False)
            embed.add_field(name="Record ID", value=f"{record_id}", inline=False)
            embed.set_footer(text=f"Recorded by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)

            # Post the embed publicly in the channel
            response_message = await interaction.channel.send(embed=embed)
            record["message_id"] = response_message.id
            self.save_data()

            # Ephemeral confirmation back to the user
            await interaction.followup.send(
                f"{pay_time} has been successfully recorded.",
                ephemeral=True
            )

        except discord.errors.NotFound as e:
            command_logger.error(f"Unknown webhook error: {e}", exc_info=True)
        except Exception as e:
            command_logger.error(f"Error in paystat command: {e}", exc_info=True)

    @app_commands.command(name="editpay", description="Edit a payment record and update its embed.")
    @app_commands.describe(
        record_id="The unique ID of the record to edit.",
        total_claiming="The updated total claiming amount (optional).",
        people_paid="The updated number of people paid (optional).",
        amount_paid="The updated amount paid (optional).",
        bonus_paid="The updated bonus amount paid (optional).",
        pay_time="The updated pay time (optional, format: 1-2 PM)."
    )
    async def editpay(
            self,
            interaction: discord.Interaction,
            record_id: str,
            total_claiming: int = None,
            people_paid: int = None,
            amount_paid: int = None,
            bonus_paid: int = None,
            pay_time: str = None
    ):
        try:
            # Check for 'founder' role
            if not has_founder_role(interaction):
                await interaction.response.send_message(
                    "You do not have permission to use this command.", ephemeral=True
                )
                return

            # Find the record by its record_id
            found_record = None
            for date_key, records in self.pay_data["records"].items():
                for record in records:
                    if record["record_id"] == record_id:
                        found_record = record
                        break
                if found_record:
                    break

            if not found_record:
                await interaction.response.send_message(
                    f"No record found with ID: {record_id}.", ephemeral=True
                )
                return

            # Track changes for description
            changes = []

            # Original values for adjustments
            original_people_paid = found_record["people_paid"]
            original_total_claiming = found_record["total_claiming"]
            original_amount_paid = found_record["paytime_paid"]
            original_bonus_paid = found_record.get("bonus_paid", 0)

            # Update fields and track changes
            if total_claiming is not None:
                changes.append(f"Total Claiming: {original_total_claiming} -> {total_claiming}")
                found_record["total_claiming"] = total_claiming

            if people_paid is not None:
                if people_paid > (total_claiming or found_record["total_claiming"]):
                    await interaction.response.send_message(
                        f"Error: People paid ({people_paid}) cannot exceed total claiming "
                        f"({total_claiming or found_record['total_claiming']}).", ephemeral=True
                    )
                    return
                changes.append(f"People Paid: {original_people_paid} -> {people_paid}")
                found_record["people_paid"] = people_paid

            if amount_paid is not None:
                changes.append(f"Amount Paid: {original_amount_paid} -> {amount_paid}")
                found_record["paytime_paid"] = amount_paid

            if bonus_paid is not None:
                changes.append(f"Bonus Paid: {original_bonus_paid} -> {bonus_paid}")
                found_record["bonus_paid"] = bonus_paid

            if pay_time is not None:
                changes.append(f"Pay Time: {found_record['pay_time']} -> {pay_time}")
                found_record["pay_time"] = pay_time

            # Recalculate dependent fields
            found_record["people_denied"] = found_record["total_claiming"] - found_record["people_paid"]
            found_record["total_paid"] = found_record["paytime_paid"] + found_record.get("bonus_paid", 0)

            # Update daily and weekly totals
            pay_date = found_record["pay_date"]
            week_start_date = calculate_week_start(pay_date)

            daily_totals = self.pay_data.setdefault("daily_totals", {}).setdefault(pay_date, {
                "people_paid": 0,
                "people_denied": 0,
                "paytime_paid": 0,
                "bonus_paid": 0,
                "total_paid": 0,
            })

            weekly_totals = self.pay_data.setdefault("weekly_totals", {}).setdefault(week_start_date, {
                "people_paid": 0,
                "people_denied": 0,
                "paytime_paid": 0,
                "bonus_paid": 0,
                "total_paid": 0,
            })

            # Adjust totals
            adjustment_people_paid = found_record["people_paid"] - original_people_paid
            adjustment_total_claiming = found_record["total_claiming"] - original_total_claiming
            adjustment_amount_paid = found_record["paytime_paid"] - original_amount_paid
            adjustment_bonus_paid = found_record.get("bonus_paid", 0) - original_bonus_paid
            adjustment_total_paid = adjustment_amount_paid + adjustment_bonus_paid

            daily_totals["people_paid"] += adjustment_people_paid
            daily_totals["people_denied"] = found_record["total_claiming"] - found_record["people_paid"]
            daily_totals["paytime_paid"] += adjustment_amount_paid
            daily_totals["bonus_paid"] += adjustment_bonus_paid
            daily_totals["total_paid"] += adjustment_total_paid

            weekly_totals["people_paid"] += adjustment_people_paid
            weekly_totals["people_denied"] = found_record["total_claiming"] - found_record["people_paid"]
            weekly_totals["paytime_paid"] += adjustment_amount_paid
            weekly_totals["bonus_paid"] += adjustment_bonus_paid
            weekly_totals["total_paid"] += adjustment_total_paid

            self.save_data()

            # Create or update the embed
            embed = discord.Embed(
                title=f"{found_record['pay_date']}",
                description="Changes:\n" + "\n".join(changes) if changes else "No changes made.",
                color=discord.Color.green(),
            )
            embed.add_field(name="Pay Time", value=f"{found_record['pay_time']}", inline=False)
            embed.add_field(name="Total Claiming", value=f"{found_record['total_claiming']}", inline=False)
            embed.add_field(name="People Paid", value=f"{found_record['people_paid']}", inline=False)
            embed.add_field(name="People Denied", value=f"{found_record['people_denied']}", inline=False)
            embed.add_field(name="Total Paid", value=f"{found_record['total_paid']}c", inline=False)
            embed.add_field(name="Record ID", value=f"{record_id}", inline=False)
            embed.set_footer(text=f"Updated by {interaction.user.name}", icon_url=interaction.user.avatar.url)

            message_id = found_record.get("message_id")
            if message_id:
                try:
                    message = await interaction.channel.fetch_message(message_id)
                    await message.edit(embed=embed)
                except discord.NotFound:
                    response_message = await interaction.channel.send(embed=embed)
                    found_record["message_id"] = response_message.id
                    self.save_data()
            else:
                response_message = await interaction.channel.send(embed=embed)
                found_record["message_id"] = response_message.id
                self.save_data()

            await interaction.response.send_message("The embed has been successfully updated.", ephemeral=True)

        except Exception as e:
            command_logger.error(f"Error in editpay command: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your request. Please contact the admin.", ephemeral=True
            )


    def calculate_week_start(self, date_str: str) -> str:
        """Calculate the start of the week (Monday) for a given date."""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        start_of_week = date_obj - timedelta(days=date_obj.weekday())
        print(f"[DEBUG] Calculated week start for {date_str}: {start_of_week.strftime('%Y-%m-%d')}")  # Debug log
        return start_of_week.strftime("%Y-%m-%d")


    @commands.command()
    async def daystat(self, ctx, date: str):
        try:
            # Restrict command to the allowed channel from server.json
            cfg = load_server_config()
            admin_channel_id = cfg.get("channels", {}).get("admin_stats")
            if not admin_channel_id or ctx.channel.id != admin_channel_id:
                await ctx.message.delete()
                return

            # Validate the date format
            datetime.strptime(date, "%Y-%m-%d")

            # Send the daily stats to the current channel
            await self.send_daily_stats(ctx.channel, date)

            # Delete the command prompt
            await ctx.message.delete()

        except ValueError:
            await ctx.message.delete()
            await ctx.author.send("Invalid date format! Please use YYYY-MM-DD.")

    @commands.command()
    async def weekstat(self, ctx, date: str):
        try:
            # Restrict command to the allowed channel from server.json
            cfg = load_server_config()
            admin_channel_id = cfg.get("channels", {}).get("admin_stats")
            if not admin_channel_id or ctx.channel.id != admin_channel_id:
                await ctx.message.delete()
                await ctx.author.send("You can only use this command in the designated stats channel.")
                return

            # Validate the date format
            datetime.strptime(date, "%Y-%m-%d")

            # Calculate the start of the week for the given date
            week_start_date = self.calculate_week_start(date)
            print(f"[DEBUG] Week Start Date: {week_start_date}")  # Debug log

            # Fetch weekly totals for the week starting at the calculated date
            weekly_totals = self.pay_data.get("weekly_totals", {}).get(week_start_date, None)
            print(f"[DEBUG] Weekly Totals Data: {weekly_totals}")  # Debug log

            if not weekly_totals:
                await ctx.send(f"No weekly stats found for the week starting {week_start_date}.")
                return

            # Create the weekly stats embed
            weekly_stats_embed = discord.Embed(
                title="Weekly Stats",
                description=f"Summary for the week starting {week_start_date}:",
                color=discord.Color.purple(),
            )
            weekly_stats_embed.add_field(name="Total People Paid", value=f"{weekly_totals['people_paid']}", inline=False)
            weekly_stats_embed.add_field(
                name="Total People Denied", value=f"{weekly_totals['people_denied']}", inline=False
            )
            weekly_stats_embed.add_field(
                name="Total Amount Paid Out", value=f"{weekly_totals['paytime_paid']}c", inline=False
            )
            weekly_stats_embed.add_field(name="Total Bonus Paid", value=f"{weekly_totals['bonus_paid']}c", inline=False)
            weekly_stats_embed.add_field(
                name="Total Paid", value=f"{weekly_totals['total_paid']}c", inline=False
            )

            # Send the embed to the current channel
            await ctx.send(embed=weekly_stats_embed)

            # Delete the command prompt
            await ctx.message.delete()

        except ValueError:
            await ctx.message.delete()
            await ctx.author.send("Invalid date format! Please use YYYY-MM-DD.")


async def setup(bot):
    await bot.add_cog(PayTracker(bot))
