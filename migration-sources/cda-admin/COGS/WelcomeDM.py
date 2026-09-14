import discord


async def send_welcome_dm(user: discord.User, habbo: str):
    avatar_url = (
        "https://www.habbo.com/habbo-imaging/avatarimage"
        f"?user={habbo}&direction=3&head_direction=3&gesture=nor&action=wav&size=l"
    )
    welcome_embed = discord.Embed(
        title="Welcome to the CDA Discord Server!",
        description=(
            "Thanks for joining CDA! You're almost ready to go.\n"
            "**You have 24 hours to verify your account or you may be removed.**"
        ),
        color=discord.Color.blue()
    )
    welcome_embed.set_thumbnail(url=avatar_url)
    welcome_embed.set_image(url=avatar_url)

    try:
        await user.send(embed=welcome_embed)
    except discord.Forbidden:
        print(f"Could not DM user {user.id}. They may have DMs disabled.")
