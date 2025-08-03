"""Contract models."""

# pylint: disable = import-outside-toplevel, ungrouped-imports

import json
from datetime import timedelta
from typing import List, Optional, Set
from urllib.parse import urljoin

import dhooks_lite

from django.db import models, transaction
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from allianceauth.authentication.models import User
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from app_utils.datetime import DATETIME_FORMAT
from app_utils.django import app_labels
from app_utils.helpers import humanize_number
from app_utils.logging import LoggerAddTag
from app_utils.urls import site_absolute_url

from freight import __title__
from freight.app_settings import (
    DISCORDPROXY_HOST,
    DISCORDPROXY_PORT,
    FREIGHT_APP_NAME,
    FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL,
    FREIGHT_DISCORD_DISABLE_BRANDING,
    FREIGHT_DISCORD_MENTIONS,
    FREIGHT_DISCORD_WEBHOOK_URL,
    FREIGHT_DISCORDPROXY_ENABLED,
    FREIGHT_HOURS_UNTIL_STALE_STATUS,
)
from freight.constants import AVATAR_SIZE
from freight.managers import ContractManager

from .contract_handlers import ContractHandler
from .routes import Location, Pricing

if "discord" in app_labels():
    from allianceauth.services.modules.discord.models import DiscordUser
else:
    DiscordUser = None  # pylint: disable=invalid-name

try:
    from discordproxy.client import DiscordClient
    from discordproxy.discord_api_pb2 import Embed
    from discordproxy.exceptions import DiscordProxyException
    from google.protobuf import json_format
except ImportError:
    DiscordClient = None

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class Contract(models.Model):
    """An Eve Online courier contract with additional meta data"""

    class Status(models.TextChoices):
        """A contract status."""

        OUTSTANDING = "outstanding", _("outstanding")
        IN_PROGRESS = "in_progress", _("in progress")
        FINISHED_ISSUER = "finished_issuer", _("finished issuer")
        FINISHED_CONTRACTOR = "finished_contractor", _("finished contractor")
        FINISHED = "finished", _("finished")
        CANCELED = "canceled", _("canceled")
        REJECTED = "rejected", _("rejected")
        FAILED = "failed", _("failed")
        DELETED = "deleted", _("deleted")
        REVERSED = "reversed", _("reversed")

        @classmethod
        def completed(cls) -> Set["Contract.Status"]:
            """Return status representing a completed contract."""
            return {
                cls.FINISHED_ISSUER,
                cls.FINISHED_CONTRACTOR,
                cls.FINISHED_ISSUER,
                cls.CANCELED,
                cls.REJECTED,
                cls.DELETED,
                cls.FINISHED,
                cls.FAILED,
            }

        @classmethod
        def for_customer_notification(cls) -> Set["Contract.Status"]:
            """Return status relevant for custom notification."""
            return {cls.OUTSTANDING, cls.IN_PROGRESS, cls.FINISHED, cls.FAILED}

    EMBED_COLOR_PASSED = 0x008000
    EMBED_COLOR_FAILED = 0xFF0000

    handler = models.ForeignKey(
        ContractHandler, on_delete=models.CASCADE, related_name="contracts"
    )
    contract_id = models.IntegerField(verbose_name=_("contract ID"))

    acceptor = models.ForeignKey(
        EveCharacter,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        verbose_name=_("acceptor"),
        related_name="contracts_acceptor",
        help_text=_("Character of acceptor or None if accepted by corp"),
    )
    acceptor_corporation = models.ForeignKey(
        EveCorporationInfo,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        verbose_name=_("acceptor corporation"),
        related_name="contracts_acceptor_corporation",
        help_text=_("Corporation of acceptor"),
    )
    collateral = models.FloatField(verbose_name=_("collateral"))
    date_accepted = models.DateTimeField(
        default=None,
        null=True,
        blank=True,
        verbose_name=_("date accepted"),
    )
    date_completed = models.DateTimeField(
        default=None,
        null=True,
        blank=True,
        verbose_name=_("date completed"),
    )
    date_expired = models.DateTimeField(verbose_name=_("date expired"))
    date_issued = models.DateTimeField(
        verbose_name=_("date issues"),
    )
    date_notified = models.DateTimeField(
        default=None,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("date notified"),
        help_text=_("Datetime of latest notification, None = none has been sent"),
    )
    days_to_complete = models.IntegerField(
        verbose_name=_("days to complete"),
    )
    end_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        verbose_name=_("end location"),
        related_name="contracts_end_location",
    )
    for_corporation = models.BooleanField(verbose_name=_("for corporation"))
    issuer_corporation = models.ForeignKey(
        EveCorporationInfo,
        on_delete=models.CASCADE,
        verbose_name=_("issuer corporation"),
        related_name="contracts_issuer_corporation",
    )
    issuer = models.ForeignKey(
        EveCharacter,
        on_delete=models.CASCADE,
        verbose_name=_("issuer"),
        related_name="contracts_issuer",
    )
    issues = models.TextField(
        default=None,
        null=True,
        blank=True,
        verbose_name=_("issues"),
        help_text=_("List or price check issues as JSON array of strings or None"),
    )
    pricing = models.ForeignKey(
        Pricing,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        verbose_name=_("pricing"),
        related_name="contracts",
    )
    reward = models.FloatField(verbose_name=_("reward"))
    start_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        verbose_name=_("start location"),
        related_name="contracts_start_location",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        db_index=True,
        verbose_name=_("status"),
    )
    title = models.CharField(
        max_length=100,
        default=None,
        null=True,
        blank=True,
        verbose_name=_("title"),
    )
    volume = models.FloatField(verbose_name=_("volume"))

    objects = ContractManager()

    class Meta:
        indexes = [models.Index(fields=["status"])]
        unique_together = (("handler", "contract_id"),)
        verbose_name = _("contract")
        verbose_name_plural = _("contracts")

    def __str__(self) -> str:
        return (
            f"{self.contract_id}: {self.start_location.solar_system_name} "
            f"-> {self.end_location.solar_system_name}"
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(contract_id={self.contract_id}, "
            f"start_location={self.start_location.solar_system_name}, "
            f"end_location={self.end_location.solar_system_name})"
        )

    @property
    def is_completed(self) -> bool:
        """whether this contract is completed or active"""
        return self.status in self.Status.completed()

    @property
    def is_in_progress(self) -> bool:
        """Return True if this contract is in progress, else False."""
        return self.status == self.Status.IN_PROGRESS

    @property
    def is_failed(self) -> bool:
        """Return True if this contract is failed, else False."""
        return self.status == self.Status.FAILED

    @property
    def has_expired(self) -> bool:
        """returns true if this contract is expired"""
        return self.date_expired < now()

    @property
    def has_pricing(self) -> bool:
        """Return True if this contract has pricing, else False."""
        return bool(self.pricing)

    @property
    def has_pricing_errors(self) -> bool:
        """Return True if this contract has pricing errors, else False."""
        return bool(self.issues)

    # @property
    # def hours_issued_2_completed(self) -> float:
    #     if self.date_completed:
    #         delta = self.date_completed - self.date_issued
    #         return delta.days * 24 + (delta.seconds / 3600)

    #     return None

    @property
    def date_latest(self) -> bool:
        """latest status related date of this contract"""
        if self.date_completed:
            date = self.date_completed
        elif self.date_accepted:
            date = self.date_accepted
        else:
            date = self.date_issued

        return date

    @property
    def has_stale_status(self) -> bool:
        """whether the status of this contract has become stale"""
        return self.date_latest < now() - timedelta(
            hours=FREIGHT_HOURS_UNTIL_STALE_STATUS
        )

    @property
    def acceptor_name(self) -> str:
        "returns the name of the acceptor character or corporation or None"

        if self.acceptor:
            name = self.acceptor.character_name
        elif self.acceptor_corporation:
            name = self.acceptor_corporation.corporation_name
        else:
            name = None

        return name

    def get_price_check_issues(self, pricing: Pricing) -> Optional[List[str]]:
        """Return list of pricing issues."""
        return pricing.get_contract_price_check_issues(
            self.volume, self.collateral, self.reward
        )

    def get_issue_list(self) -> list:
        """returns current pricing issues as list of strings"""
        if self.issues:
            return json.loads(self.issues)
        return []

    def _generate_embed_description(self) -> object:
        """generates a Discord embed for this contract"""
        desc = (
            f"**From**: {self.start_location}\n"
            f"**To**: {self.end_location}\n"
            f"**Volume**: {self.volume:,.0f} m3\n"
            f"**Reward**: {humanize_number(self.reward)} ISK\n"
            f"**Collateral**: {humanize_number(self.collateral)} ISK\n"
            f"**Status**: {self.status}\n"
        )
        if self.pricing:
            if not self.has_pricing_errors:
                check_text = "passed"
                color = self.EMBED_COLOR_PASSED
            else:
                check_text = "FAILED"
                color = self.EMBED_COLOR_FAILED
        else:
            check_text = "N/A"
            color = None
        desc += (
            f"**Contract Check**: {check_text}\n"
            f"**Issued on**: {self.date_issued.strftime(DATETIME_FORMAT)}\n"
            f"**Issued by**: {self.issuer}\n"
            f"**Expires on**: {self.date_expired.strftime(DATETIME_FORMAT)}\n"
        )
        if self.acceptor_name:
            desc += f"**Accepted by**: {self.acceptor_name}\n"
        if self.date_accepted:
            desc += f"**Accepted on**: {self.date_accepted.strftime(DATETIME_FORMAT)}\n"
        desc += f"**Contract ID**: {self.contract_id}\n"
        return {"desc": desc, "color": color}

    def _generate_embed(self, for_issuer=False) -> dhooks_lite.Embed:
        embed_desc = self._generate_embed_description()
        if for_issuer:
            url = urljoin(site_absolute_url(), reverse("freight:contract_list_user"))
        else:
            url = urljoin(site_absolute_url(), reverse("freight:contract_list_all"))
        return dhooks_lite.Embed(
            author=dhooks_lite.Author(
                name=self.issuer.character_name, icon_url=self.issuer.portrait_url()
            ),
            title=(
                f"{self.start_location.solar_system_name} >> "
                f"{self.end_location.solar_system_name} "
                f"| {self.volume:,.0f} m3 | {self.status.upper()}"
            ),
            url=url,
            description=embed_desc["desc"],
            color=embed_desc["color"],
        )

    def send_pilot_notification(self):
        """sends pilot notification about this contract to the DISCORD webhook"""
        if FREIGHT_DISCORD_WEBHOOK_URL:
            if FREIGHT_DISCORD_DISABLE_BRANDING:
                username = None
                avatar_url = None
            else:
                username = FREIGHT_APP_NAME
                avatar_url = self.handler.organization.icon_url(size=AVATAR_SIZE)

            hook = dhooks_lite.Webhook(
                FREIGHT_DISCORD_WEBHOOK_URL, username=username, avatar_url=avatar_url
            )
            with transaction.atomic():
                logger.info(
                    "%s: Trying to sent pilot notification about contract %s to %s",
                    self,
                    self.contract_id,
                    FREIGHT_DISCORD_WEBHOOK_URL,
                )
                if FREIGHT_DISCORD_MENTIONS:
                    contents = str(FREIGHT_DISCORD_MENTIONS) + " "
                else:
                    contents = ""

                contract_list_url = urljoin(
                    site_absolute_url(), reverse("freight:contract_list_all")
                )
                contents += (
                    f"There is a new courier contract from {self.issuer} "
                    "looking to be picked up "
                    f"[[show]({contract_list_url})]:"
                )

                embed = self._generate_embed()
                response = hook.execute(
                    content=contents, embeds=[embed], wait_for_response=True
                )
                if response.status_ok:
                    self.date_notified = now()
                    self.save()
                else:
                    logger.warning(
                        "%s: Failed to send message. HTTP code: %s",
                        self,
                        response.status_code,
                    )
        else:
            logger.debug("%s: FREIGHT_DISCORD_WEBHOOK_URL not configured", self)

    def send_customer_notification(self, force_sent=False):
        """sends customer notification about this contract to Discord
        force_sent: send notification even if one has already been sent
        """
        if (
            FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL or FREIGHT_DISCORDPROXY_ENABLED
        ) and DiscordUser:
            status_to_report = None
            for status in self.Status.for_customer_notification():
                if self.status == status and (
                    force_sent or not self.customer_notifications.filter(status=status)
                ):
                    status_to_report = status
                    break

            if status_to_report:
                self._report_to_customer(status_to_report)
        else:
            logger.debug(
                "%s: FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL not configured or "
                "Discord services not installed or Discord Proxy not enabled",
                self,
            )

    def _report_to_customer(self, status_to_report):
        issuer_user = User.objects.filter(
            character_ownerships__character=self.issuer
        ).first()
        if not issuer_user:
            logger.warning(
                "%s: Could not find matching user for issuer: %s", self, self.issuer
            )
            return
        try:
            discord_user_id = DiscordUser.objects.get(user=issuer_user).uid
        except DiscordUser.DoesNotExist:
            logger.warning(
                "%s: Could not find Discord user for issuer: %s", self, issuer_user
            )
            return

        if FREIGHT_DISCORDPROXY_ENABLED:
            self._send_to_customer_via_discordproxy(status_to_report, discord_user_id)

        elif FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL:
            self._send_to_customer_via_webhook(status_to_report, discord_user_id)

    def _send_to_customer_via_webhook(self, status_to_report, discord_user_id):
        if FREIGHT_DISCORD_DISABLE_BRANDING:
            username = None
            avatar_url = None
        else:
            username = FREIGHT_APP_NAME
            avatar_url = self.handler.organization.icon_url(size=AVATAR_SIZE)

        hook = dhooks_lite.Webhook(
            FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL,
            username=username,
            avatar_url=avatar_url,
        )
        logger.info(
            "%s: Trying to send customer notification"
            " about contract %s on status %s to %s",
            self,
            self.contract_id,
            status_to_report,
            FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL,
        )
        embed = self._generate_embed(for_issuer=True)
        contents = self._generate_contents(discord_user_id, status_to_report)
        response = hook.execute(
            content=contents, embeds=[embed], wait_for_response=True
        )
        if response.status_ok:
            ContractCustomerNotification.objects.update_or_create(
                contract=self,
                status=status_to_report,
                defaults={"date_notified": now()},
            )
        else:
            logger.warning(
                "%s: Failed to send message. HTTP code: %s",
                self,
                response.status_code,
            )

    def _send_to_customer_via_discordproxy(self, status_to_report, discord_user_id):
        logger.info(
            "%s: Trying to send customer notification "
            "about contract %s on status %s to discord dm",
            self,
            self.contract_id,
            status_to_report,
        )
        embed_dct = self._generate_embed(for_issuer=True).asdict()
        embed = json_format.ParseDict(embed_dct, Embed())
        contents = self._generate_contents(
            discord_user_id, status_to_report, include_mention=False
        )
        client = DiscordClient(target=f"{DISCORDPROXY_HOST}:{DISCORDPROXY_PORT}")
        try:
            client.create_direct_message(
                user_id=discord_user_id, content=contents, embed=embed
            )
        except DiscordProxyException as ex:
            logger.error("Failed to send message to Discord: %s", ex)
        else:
            ContractCustomerNotification.objects.update_or_create(
                contract=self,
                status=status_to_report,
                defaults={"date_notified": now()},
            )

    def _generate_contents(
        self, discord_user_id, status_to_report, include_mention=True
    ):
        contents = f"<@{discord_user_id}>\n" if include_mention else ""
        if self.acceptor_name:
            acceptor_text = f"by {self.acceptor_name} "
        else:
            acceptor_text = ""
        if status_to_report == self.Status.OUTSTANDING:
            contents += "We have received your contract"
            if self.has_pricing_errors:
                issues = self.get_issue_list()
                contents += (
                    ", but we found some issues.\n"
                    "Please create a new courier contract "
                    "and correct the following issues:\n"
                )
                for issue in issues:
                    contents += f"• {issue}\n"
            else:
                contents += " and it will be picked up by one of our pilots shortly."
        elif status_to_report == self.Status.IN_PROGRESS:
            contents += (
                f"Your contract has been picked up {acceptor_text}"
                "and will be delivered to you shortly."
            )
        elif status_to_report == self.Status.FINISHED:
            contents += (
                "Your contract has been **delivered**.\n"
                "Thank you for using our freight service."
            )
        elif status_to_report == self.Status.FAILED:
            contents += (
                f"Your contract has been **failed** {acceptor_text}"
                "Thank you for using our freight service."
            )
        else:
            raise NotImplementedError()
        return contents


class ContractCustomerNotification(models.Model):
    """record of contract notification to customer about state"""

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        verbose_name=_("contract"),
        related_name="customer_notifications",
    )
    status = models.CharField(
        max_length=32,
        choices=Contract.Status.choices,
        db_index=True,
        verbose_name=_("status"),
    )
    date_notified = models.DateTimeField(
        verbose_name=_("date notified"), help_text="datetime of notification"
    )

    class Meta:
        unique_together = (("contract", "status"),)
        verbose_name = _("contract customer notification")
        verbose_name_plural = _("contract customer notifications")

    def __str__(self):
        return f"{self.contract.contract_id} - {self.status}"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(pk={self.pk}, "
            f"contract_id={self.contract.contract_id}, status={self.status})"
        )
