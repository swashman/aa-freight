"""Contract Handler models."""

import hashlib
import json
from datetime import timedelta
from typing import List

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from esi.errors import TokenError
from esi.models import Token

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import (
    EveAllianceInfo,
    EveCharacter,
    EveCorporationInfo,
)
from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from freight import __title__
from freight.app_settings import (
    FREIGHT_CONTRACT_SYNC_GRACE_MINUTES,
    FREIGHT_OPERATION_MODE,
    FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE,
    FREIGHT_OPERATION_MODE_CORP_PUBLIC,
    FREIGHT_OPERATION_MODE_MY_ALLIANCE,
    FREIGHT_OPERATION_MODE_MY_CORPORATION,
    FREIGHT_OPERATION_MODES,
)
from freight.constants import AVATAR_SIZE
from freight.helpers import get_or_create_eve_character
from freight.managers import EveEntityManager
from freight.providers import esi

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class Freight(models.Model):
    """Meta model for global app permissions"""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("add_location", "Can add / update locations"),
            ("basic_access", "Can access this app"),
            ("setup_contract_handler", "Can setup contract handler"),
            ("use_calculator", "Can use the calculator"),
            ("view_contracts", "Can view the contracts list"),
            ("view_statistics", "Can view freight statistics"),
        )

    @classmethod
    def operation_mode_friendly(cls, operation_mode) -> str:
        """returns user friendly description of operation mode"""
        msg = [(x, y) for x, y in FREIGHT_OPERATION_MODES if x == operation_mode]
        if len(msg) != 1:
            raise ValueError("Undefined mode")
        return msg[0][1]

    @staticmethod
    def category_for_operation_mode(mode: str) -> str:
        """Eve Entity category for given operation mode."""
        if mode == FREIGHT_OPERATION_MODE_MY_ALLIANCE:
            return EveEntity.CATEGORY_ALLIANCE
        return EveEntity.CATEGORY_CORPORATION


class EveEntity(models.Model):
    """An Eve entity like a corporation or a character"""

    CATEGORY_ALLIANCE = "alliance"
    CATEGORY_CHARACTER = "character"
    CATEGORY_CORPORATION = "corporation"

    CATEGORY_CHOICES = (
        (CATEGORY_ALLIANCE, "Alliance"),
        (CATEGORY_CORPORATION, "Corporation"),
        (CATEGORY_CHARACTER, "Character"),
    )

    id = models.IntegerField(
        primary_key=True, validators=[MinValueValidator(0)], verbose_name=_("id")
    )
    category = models.CharField(
        max_length=32, choices=CATEGORY_CHOICES, verbose_name=_("category")
    )
    name = models.CharField(max_length=254, verbose_name=_("name"))

    objects = EveEntityManager()

    def __str__(self):
        return self.name

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(id={self.id}, category='{self.category}', "
            f"name='{self.name}')"
        )

    @property
    def is_alliance(self) -> bool:
        """Return True if entity is an alliance, else False."""
        return self.category == self.CATEGORY_ALLIANCE

    @property
    def is_corporation(self) -> bool:
        """Return True if entity is an corporation, else False."""
        return self.category == self.CATEGORY_CORPORATION

    @property
    def is_character(self) -> bool:
        """Return True if entity is a character, else False."""
        return self.category == self.CATEGORY_CHARACTER

    def icon_url(self, size=AVATAR_SIZE) -> str:
        """Url to an icon image for this organization."""
        if self.category == self.CATEGORY_ALLIANCE:
            return EveAllianceInfo.generic_logo_url(self.id, size=size)

        if self.category == self.CATEGORY_CORPORATION:
            return EveCorporationInfo.generic_logo_url(self.id, size=size)

        if self.category == self.CATEGORY_CHARACTER:
            return EveCharacter.generic_portrait_url(self.id, size=size)

        raise NotImplementedError(
            f"Avatar URL not implemented for category {self.category}"
        )


class ContractHandler(models.Model):
    """Handler for syncing of contracts belonging to an alliance or corporation."""

    # errors
    ERROR_NONE = 0
    ERROR_TOKEN_INVALID = 1
    ERROR_TOKEN_EXPIRED = 2
    ERROR_INSUFFICIENT_PERMISSIONS = 3
    ERROR_NO_CHARACTER = 4
    ERROR_ESI_UNAVAILABLE = 5
    ERROR_OPERATION_MODE_MISMATCH = 6
    ERROR_UNKNOWN = 99

    ERRORS_LIST = [
        (ERROR_NONE, "No error"),
        (ERROR_TOKEN_INVALID, "Invalid token"),
        (ERROR_TOKEN_EXPIRED, "Expired token"),
        (ERROR_INSUFFICIENT_PERMISSIONS, "Insufficient permissions"),
        (ERROR_NO_CHARACTER, "No character set for fetching alliance contacts"),
        (ERROR_ESI_UNAVAILABLE, "ESI API is currently unavailable"),
        (
            ERROR_OPERATION_MODE_MISMATCH,
            "Operation mode does not match with current setting",
        ),
        (ERROR_UNKNOWN, "Unknown error"),
    ]

    organization = models.OneToOneField(
        EveEntity,
        on_delete=models.CASCADE,
        primary_key=True,
        verbose_name=_("organization"),
    )
    character = models.ForeignKey(
        CharacterOwnership,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        verbose_name=_("character"),
        related_name="+",
        help_text=_("Character used for syncing contracts"),
    )
    operation_mode = models.CharField(
        max_length=32,
        default=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        verbose_name=_("operation mode"),
        help_text=_("Defines what kind of contracts are synced"),
    )
    price_per_volume_modifier = models.FloatField(
        default=None,
        null=True,
        blank=True,
        verbose_name=_("price per volume modifier"),
        help_text=_(
            "Global modifier for price per volume in percent, e.g. 2.5 = +2.5%"
        ),
    )
    version_hash = models.CharField(
        max_length=32,
        null=True,
        default=None,
        blank=True,
        verbose_name=_("version hash"),
        help_text=_("hash to identify changes to contracts"),
    )
    last_sync = models.DateTimeField(
        null=True,
        default=None,
        blank=True,
        verbose_name=_("last sync at"),
        help_text=_("when the last sync happened"),
    )
    last_error = models.IntegerField(
        choices=ERRORS_LIST,
        default=ERROR_NONE,
        help_text="error that occurred at the last sync attempt (if any)",
    )  # TODO: Remove with next migration - no longer used

    class Meta:
        verbose_name = _("contract handler")
        verbose_name_plural = _("contract handler")

    def __str__(self):
        return str(self.organization.name)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(pk={self.pk}, "
            f"organization='{self.organization.name}')"
        )

    @property
    def operation_mode_friendly(self) -> str:
        """returns user friendly description of operation mode"""
        return Freight.operation_mode_friendly(self.operation_mode)

    # @property
    # def last_error_message_friendly(self) -> str:
    #     msg = [(x, y) for x, y in self.ERRORS_LIST if x == self.last_error]
    #     return msg[0][1] if len(msg) > 0 else "Undefined error"

    @classmethod
    def get_esi_scopes(cls) -> List[str]:
        """Return list of required ESI scopes to fetch contracts."""
        return [
            "esi-contracts.read_corporation_contracts.v1",
            "esi-universe.read_structures.v1",
        ]

    @property
    def is_sync_ok(self) -> bool:
        """returns true if they have been no errors
        and last syncing occurred within alloted time
        """
        grace_deadline = now() - timedelta(minutes=FREIGHT_CONTRACT_SYNC_GRACE_MINUTES)
        return self.last_sync and self.last_sync > grace_deadline

    def get_availability_text_for_contracts(self) -> str:
        """returns a text detailing the availability choice for this setup"""

        if self.operation_mode == FREIGHT_OPERATION_MODE_MY_ALLIANCE:
            extra_text = "[My Alliance]"

        elif self.operation_mode == FREIGHT_OPERATION_MODE_MY_CORPORATION:
            extra_text = "[My Corporation]"

        else:
            extra_text = ""

        return f"Private ({self.organization.name}) {extra_text}"

    def token(self) -> Token:
        """Returns an valid esi token for the contract handler.

        Raises exception on any error
        """
        token = (
            Token.objects.filter(
                user=self.character.user,
                character_id=self.character.character.character_id,
            )
            .require_scopes(self.get_esi_scopes())
            .require_valid()
            .first()
        )
        if not token:
            raise TokenError(f"{self}: No valid token found")

        return token

    def update_contracts_esi(self, force_sync=False) -> bool:
        """Update contracts from ESI."""
        self._validate_update_readiness()
        token = self.token()
        contracts = esi.client.Contracts.get_corporations_corporation_id_contracts(
            token=token.valid_access_token(),
            corporation_id=self.character.character.corporation_id,
        ).results()
        if settings.DEBUG:
            self._save_contract_to_file(contracts)

        self._process_contracts_from_esi(contracts, token, force_sync)
        self.last_sync = now()
        self.save(update_fields=["last_sync"])

    def _validate_update_readiness(self):
        if self.operation_mode != FREIGHT_OPERATION_MODE:
            raise ValueError(f"{self}: Current operation mode not matching the handler")

        if self.character is None:
            raise ValueError(f"{self}: No character configured to sync")

        if not self.character.user.has_perm("freight.setup_contract_handler"):
            raise ValueError(
                f"{self}: Character does not have sufficient permission to sync"
            )

    def _save_contract_to_file(self, contracts):
        """saves raw contracts to file for debugging"""
        with open("contracts_raw.json", "w", encoding="utf-8") as file:
            json.dump(contracts, file, cls=DjangoJSONEncoder, sort_keys=True, indent=4)

    def _process_contracts_from_esi(
        self, contracts_all: list, token: object, force_sync: bool
    ):
        # 1st filter: reduce to courier contracts assigned to handler org
        contracts_courier = [
            x
            for x in contracts_all
            if x["type"] == "courier"
            and int(x["assignee_id"]) == int(self.organization.id)
        ]

        # 2nd filter: remove contracts not in scope due to operation mode
        contracts = []
        for contract in contracts_courier:
            issuer, _ = get_or_create_eve_character(contract["issuer_id"])

            assignee_id = int(contract["assignee_id"])
            issuer_corporation_id = int(issuer.corporation_id)
            issuer_alliance_id = int(issuer.alliance_id) if issuer.alliance_id else None

            if self.operation_mode == FREIGHT_OPERATION_MODE_MY_ALLIANCE:
                in_scope = issuer_alliance_id == assignee_id

            elif self.operation_mode == FREIGHT_OPERATION_MODE_MY_CORPORATION:
                in_scope = assignee_id == issuer_corporation_id

            elif self.operation_mode == FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE:
                in_scope = issuer_alliance_id == int(
                    self.character.character.alliance_id
                )

            elif self.operation_mode == FREIGHT_OPERATION_MODE_CORP_PUBLIC:
                in_scope = True

            else:
                raise NotImplementedError(
                    f"Unsupported operation mode: {self.operation_mode}"
                )
            if in_scope:
                contracts.append(contract)

        # determine if contracts have changed by comparing their hashes
        new_version_hash = hashlib.md5(
            json.dumps(contracts, cls=DjangoJSONEncoder).encode("utf-8")
        ).hexdigest()
        if force_sync or new_version_hash != self.version_hash:
            self._store_contract_from_esi(contracts, new_version_hash, token)
        else:
            logger.info("%s: Contracts are unchanged.", self)

    # pylint: disable = no-member
    def _store_contract_from_esi(
        self, contracts: list, new_version_hash: str, token: Token
    ) -> None:
        logger.info("%s: Storing update with %d contracts", self, len(contracts))
        with transaction.atomic():
            self.version_hash = new_version_hash
            for contract in contracts:
                try:
                    self.contracts.update_or_create_from_dict(
                        handler=self, contract=contract, token=token
                    )
                except OSError:
                    logger.exception(
                        "%s: An unexpected error ocurred while trying to load contract "
                        "%s",
                        self,
                        (
                            contract["contract_id"]
                            if "contract_id" in contract
                            else "Unknown"
                        ),
                    )

        self.contracts.update_pricing()
