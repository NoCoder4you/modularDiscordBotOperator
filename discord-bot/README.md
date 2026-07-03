# Multi-Server Modular Discord Bot Foundation

This project is a Stage 1 foundation for a Python 3.10+ Discord bot built with `discord.py`. It provides startup wiring, modular cog loading, logging, slash-command syncing, and guild-separated JSON data helpers. It intentionally does **not** include moderation, economy, events, administration, or other feature systems yet.

## Multi-server design

The bot is designed for public use across many Discord servers at the same time. It is not tied to a single guild. Any server-specific data is stored by immutable Discord guild ID, never by guild name:

```text
DATA/guilds/123456789012345678/settings.json
DATA/guilds/987654321098765432/settings.json
```

Guild names can change and can contain filesystem-unfriendly characters, so they are never used as permanent identifiers. Commands that need a guild reject direct-message use with a clear response. If the bot leaves a server, its data is preserved so future re-invites can reuse it; automatic deletion can be implemented in a later privacy/data-removal feature.

## Project structure

```text
discord-bot/
├── bot.py
├── config.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── COGS/
│   ├── __init__.py
│   └── core.py
├── UTILS/
│   ├── __init__.py
│   ├── logger.py
│   └── data_manager.py
├── DATA/
│   ├── .gitkeep
│   └── guilds/
│       └── .gitkeep
└── LOGS/
    └── .gitkeep
```

All bot feature modules belong in the uppercase `COGS` package. Persistent files belong in `DATA`, including JSON, future SQLite databases, caches, guild settings, user records, feature configuration, and backups. Cogs should call `UTILS.data_manager` instead of manually building paths into `DATA`.

## Setup on Linux/macOS

```bash
cd discord-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

## Setup on Windows PowerShell

```powershell
cd discord-bot
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Environment configuration

Edit `.env` after copying `.env.example`:

```env
DISCORD_TOKEN=your_discord_bot_token
TEST_GUILD_ID=
OWNER_ID=
```

- `DISCORD_TOKEN` is required and must never be committed.
- `TEST_GUILD_ID` is optional and is only used for faster development command syncing.
- `OWNER_ID` is optional and is converted to an integer when provided.

## Getting a Discord bot token

1. Open the Discord Developer Portal.
2. Create an application.
3. Add a bot user from the **Bot** page.
4. Reset/copy the token and place it in your local `.env` file.
5. Enable these Developer Portal intents for this foundation:
   - Server Members Intent, used for more complete guild/member information.

## Inviting the bot

Use the OAuth2 URL Generator in the Discord Developer Portal with these scopes:

- `bot`
- `applications.commands`

Select the bot permissions your server needs for the current commands, then open the generated URL in a browser.

## Starting the bot

```bash
python bot.py
```

Slash commands are preferred. A configurable text-command prefix is present for compatibility and future use, but Stage 1 commands are slash commands.

## Slash-command syncing

When `TEST_GUILD_ID` is set, global commands are copied and synced to that one guild for fast development testing. This does not restrict the bot to that guild and does not create test-guild-only production commands. When `TEST_GUILD_ID` is empty, commands sync globally for all installing guilds. Global slash commands can take longer to appear than test-guild commands because Discord propagates global command changes more slowly.

## Adding a new cog

1. Create a new Python file in `COGS`, for example `COGS/example.py`.
2. Define a `commands.Cog` subclass.
3. Add an asynchronous extension setup function:

```python
async def setup(bot):
    await bot.add_cog(Example(bot))
```

The bot automatically loads valid `.py` files in `COGS`, excluding `__init__.py` and files beginning with `_`. Use extension paths like `COGS.core`; do not use lowercase `cogs`.

## Using the data manager

Use `UTILS.data_manager` helpers for guild-scoped JSON data:

```python
from UTILS.data_manager import load_guild_json, save_guild_json

settings = await load_guild_json(guild.id, "settings", {"guild_id": guild.id})
settings["prefix"] = "!"
await save_guild_json(guild.id, "settings", settings)
```

The helpers validate guild IDs and filenames, keep paths inside `DATA`, add `.json` when needed, create missing guild folders, use UTF-8, write readable JSON, and use locked atomic writes to reduce corruption risk.

## Included commands

- `/ping` shows latency, bot status, and the current server context.
- `/botinfo` shows bot runtime details and the current server context.
- `/serverinfo` shows information only for the server where it was used.

All included commands reject direct-message use because they depend on guild context.
