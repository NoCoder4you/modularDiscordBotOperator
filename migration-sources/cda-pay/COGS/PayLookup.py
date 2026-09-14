import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
from pathlib import Path


class PayLookup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Dynamic paths - JSON folder beside bot root
        base_dir = Path(__file__).resolve().parent   # /COGS
        root_dir = base_dir.parent                   # /CDA Pay
        json_dir = root_dir / "JSON"                 # /CDA Pay/JSON
        json_dir.mkdir(exist_ok=True)

        # Monthly file name - e.g. DEC_2025.json
        current_month_file = datetime.now().strftime("%b_%Y").upper() + ".json"
        self.file_path = json_dir / current_month_file

        # Ensure the monthly file exists with a valid structure
        if not self.file_path.exists():
            with open(self.file_path, "w") as f:
                json.dump(
                    {
                        "records": {},
                        "daily_totals": {},
                        "weekly_totals": {}
                    },
                    f,
                    indent=4
                )

        # Load JSON content
        with open(self.file_path, "r") as f:
            self.pay_data = json.load(f)

    # Create the "Admin" command group
    admin = app_commands.Group(name="admin", description="Administrative commands for server management.")

    @admin.command(
        name="lookup",
        description="Look up pay record by message_id, record_id, pay_time, pay_date, amount_paid, or bonus_paid"
    )
    async def lookup(
            self,
            interaction: discord.Interaction,
            message_id: str = None,
            record_id: str = None,
            pay_time: str = None,
            pay_date: str = None,
            min_amount: int = None,
            max_amount: int = None,
            min_bonus: int = None,
            max_bonus: int = None
    ):
        # Check if the user has the "Foundation" role
        foundation_role = discord.utils.get(interaction.user.roles, name="Foundation")
        if not foundation_role:
            await interaction.response.send_message(
                "You do not have the required 'Foundation' role to use this command.", ephemeral=True
            )
            return

        # Validate pay_time and pay_date dependency
        if (pay_time and not pay_date) or (pay_date and not pay_time):
            await interaction.response.send_message(
                "Both `pay_time` and `pay_date` must be provided together.", ephemeral=True
            )
            return

        # Defer the response immediately
        await interaction.response.defer(thinking=True)

        results = []

        # Search logic
        for date_key, records in self.pay_data.get("records", {}).items():
            for record in records:
                amount_paid = record.get("amount_paid", 0)
                bonus_paid = record.get("bonus_paid", 0)
                if (
                        (message_id and str(record.get("message_id")) == message_id) or
                        (record_id and str(record.get("record_id", "XXXXX")) == record_id) or
                        (pay_time and record.get("pay_time") == pay_time and record.get("pay_date") == pay_date) or
                        (
                                min_amount is not None and max_amount is not None and min_amount <= amount_paid <= max_amount) or
                        (min_amount is not None and max_amount is None and amount_paid >= min_amount) or
                        (max_amount is not None and min_amount is None and amount_paid <= max_amount) or
                        (
                                min_bonus is not None and max_bonus is not None and min_bonus <= bonus_paid <= max_bonus) or
                        (min_bonus is not None and max_bonus is None and bonus_paid >= min_bonus) or
                        (max_bonus is not None and min_bonus is None and bonus_paid <= max_bonus)
                ):
                    results.append(record)

        if results:
            for record in results:
                # Use "XXXXX" if record_id is missing
                record_id_value = record.get("record_id", "XXXXX")

                embed = discord.Embed(title="Pay Record Lookup Result", color=discord.Color.blue())
                embed.add_field(name="Record ID", value=record_id_value, inline=False)
                embed.add_field(name="Pay Date", value=record.get("pay_date", "N/A"), inline=False)
                embed.add_field(name="Pay Time", value=record.get("pay_time", "N/A"), inline=False)
                embed.add_field(name="Total Claiming", value=record.get("total_claiming", "N/A"), inline=False)
                embed.add_field(name="People Paid", value=record.get("people_paid", "N/A"), inline=False)
                embed.add_field(name="People Denied", value=record.get("people_denied", "N/A"), inline=False)
                embed.add_field(name="Amount Paid", value=record.get("amount_paid", "N/A"), inline=False)
                embed.add_field(name="Bonus Paid", value=record.get("bonus_paid", "N/A"), inline=False)
                embed.add_field(name="Message ID", value=record.get("message_id", "N/A"), inline=False)

                # Set dynamic footer
                if record_id_value != "XXXXX":
                    embed.set_footer(text=f"Use /editpay with the {record_id_value} to post this embed")
                else:
                    embed.set_footer(text="Record ID is unavailable for edit")

                await interaction.channel.send(embed=embed)

            # Edit the deferred response to indicate the number of results
            await interaction.followup.send(f"**{len(results)} results**")
        else:
            await interaction.followup.send("**No matching records found**")


async def setup(bot):
    await bot.add_cog(PayLookup(bot))
