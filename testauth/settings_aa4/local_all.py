# flake8: noqa

from .local_core import *

# Add any additional apps to this list.
INSTALLED_APPS += [
    "allianceauth.services.modules.discord",
]

# Discord Configuration
DISCORD_GUILD_ID = ""
DISCORD_CALLBACK_URL = ""
DISCORD_APP_ID = ""
DISCORD_APP_SECRET = ""
DISCORD_BOT_TOKEN = "MYDUMMYTOKEN"
DISCORD_SYNC_NAMES = False
