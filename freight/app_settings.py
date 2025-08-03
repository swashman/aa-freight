"""Settings for Freight."""

from django.utils.translation import gettext_lazy as _

from app_utils.app_settings import clean_setting

DISCORDPROXY_HOST = clean_setting("DISCORDPROXY_HOST", "localhost")
"""Port used to communicate with Discord Proxy."""

DISCORDPROXY_PORT = clean_setting("DISCORDPROXY_PORT", 50051)
"""Host used to communicate with Discord Proxy."""


FREIGHT_APP_NAME = clean_setting("FREIGHT_APP_NAME", "Freight", required_type=str)
"""Name of this app as shown in the Auth sidebar,
page titles and as default avatar name for notifications.
"""

FREIGHT_CONTRACT_SYNC_GRACE_MINUTES = clean_setting(
    "FREIGHT_CONTRACT_SYNC_GRACE_MINUTES", 30
)
"""Sets the number minutes until a delayed sync will be recognized as error."""


FREIGHT_DISCORD_AVATAR_NAME = clean_setting(
    "FREIGHT_DISCORD_AVATAR_NAME", None, required_type=str
)
"""Will be shown as "user name" instead of what is configured as app name
for notifications when defined. Optional.
"""

FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL = clean_setting(
    "FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None, required_type=str
)
"""Webhook URL for the Discord channel
where contract notifications for customers should appear. Optional.
"""

FREIGHT_DISCORD_DISABLE_BRANDING = clean_setting(
    "FREIGHT_DISCORD_DISABLE_BRANDING", False
)
"""Turns off setting the name and avatar url for the webhook.
Notifications will be posted by a bot called "Freight"
with the logo of your organization as avatar image.
"""

FREIGHT_DISCORD_MENTIONS = clean_setting(
    "FREIGHT_DISCORD_MENTIONS", None, required_type=str
)
"""Optional mention string put in front of every notification to create pings.

Typical values are: `@here` or `@everyone`.

You can also mention roles, however you will need to add the role ID for that.
The format is: `<@&role_id>` and you can get the role ID by entering
`_<@role_name>` in a channel on Discord.
See [this link](https://www.reddit.com/r/discordapp/comments/580qib/how_do_i_mention_a_role_with_webhooks/)
for details.
"""

FREIGHT_DISCORD_WEBHOOK_URL = clean_setting(
    "FREIGHT_DISCORD_WEBHOOK_URL", None, required_type=str
)
"""Webhook URL used for the Discord channel
where contract notifications for pilots should appear. Optional.
"""

FREIGHT_DISCORDPROXY_ENABLED = clean_setting("FREIGHT_DISCORDPROXY_ENABLED", False)
"""Whether to use Discord Proxy for sending customer notifications as direct messages.
This requires the app Discord Proxy to be setup and running on your system
and AA's Discord Services to be enabled.
"""

FREIGHT_ESI_TIMEOUT_ENABLED = clean_setting("FREIGHT_ESI_TIMEOUT_ENABLED", True)
"""Whether ESI requests have a timeout."""

FREIGHT_FULL_ROUTE_NAMES = clean_setting("FREIGHT_FULL_ROUTE_NAMES", False)
"""Show full name of locations in route, e.g on calculator drop down."""

FREIGHT_HOURS_UNTIL_STALE_STATUS = clean_setting("FREIGHT_HOURS_UNTIL_STALE_STATUS", 24)
"""Defines after how many hours the status of a contract is considered to be stale.

Customer notifications will not be sent for a contract status that has become stale.
This settings also prevents the app
from sending out customer notifications for old contracts.
"""

FREIGHT_NOTIFY_ALL_CONTRACTS = clean_setting("FREIGHT_NOTIFY_ALL_CONTRACTS", False)
"""Send discord notifications about every contract, even if no pricing defined."""

# modes of operation for Freight
FREIGHT_OPERATION_MODE_MY_ALLIANCE = "my_alliance"
FREIGHT_OPERATION_MODE_MY_CORPORATION = "my_corporation"
FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE = "corp_in_alliance"
FREIGHT_OPERATION_MODE_CORP_PUBLIC = "corp_public"

FREIGHT_OPERATION_MODES = [
    (FREIGHT_OPERATION_MODE_MY_ALLIANCE, _("My Alliance")),
    (FREIGHT_OPERATION_MODE_MY_CORPORATION, _("My Corporation")),
    (FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE, _("Corporation in my Alliance")),
    (FREIGHT_OPERATION_MODE_CORP_PUBLIC, _("Corporation public")),
]

FREIGHT_OPERATION_MODE = clean_setting(
    "FREIGHT_OPERATION_MODE",
    default_value=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
    choices=[x[0] for x in FREIGHT_OPERATION_MODES],
)
"""Operation mode to use.

Note that switching operation modes requires you to remove the existing contract handler
with all its contracts and then setup a new contract handler.
"""

FREIGHT_STATISTICS_MAX_DAYS = clean_setting(
    "FREIGHT_STATISTICS_MAX_DAYS", 90, min_value=1
)
"""Sets the number of days that are considered for creating the statistics."""
