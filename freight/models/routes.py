"""Pricing and location models."""

from typing import List, Optional

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from freight import __title__
from freight.app_settings import FREIGHT_FULL_ROUTE_NAMES
from freight.managers import LocationManager, PricingManager

from .contract_handlers import ContractHandler

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class Location(models.Model):
    """An Eve Online courier contract location: station or Upwell structure"""

    class Category(models.IntegerChoices):
        """A location category."""

        STATION_ID = 3, "station"
        STRUCTURE_ID = 65, "structure"
        UNKNOWN_ID = 0, "(unknown)"

    id = models.BigIntegerField(
        primary_key=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("id"),
        help_text="Eve Online location ID, "
        "either item ID for stations or structure ID for structures",
    )

    category_id = models.PositiveIntegerField(
        choices=Category.choices,
        default=Category.UNKNOWN_ID,
        help_text="Eve Online category ID",
    )
    name = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name=_("name"),
        help_text="In-game name of this station or structure",
    )
    solar_system_id = models.PositiveIntegerField(
        default=None, null=True, blank=True, help_text="Eve Online solar system ID"
    )
    type_id = models.PositiveIntegerField(
        default=None, null=True, blank=True, help_text="Eve Online type ID"
    )

    objects = LocationManager()

    class Meta:
        verbose_name = _("location")
        verbose_name_plural = _("locations")

    def __str__(self):
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(pk={self.pk}, name='{self.name}')"

    @property
    def category(self):
        """Return category ID for this location."""
        return self.category_id

    @property
    def solar_system_name(self):
        """Return solar system name for this location.."""
        return self.name.split(" ", 1)[0]

    @property
    def location_name(self):
        """Return name of this location."""
        return self.name.rsplit("-", 1)[1].strip()

    @classmethod
    def get_esi_scopes(cls):
        """Return ESI scopes required to fetch this data."""
        return ["esi-universe.read_structures.v1"]


class Pricing(models.Model):
    """Pricing for a courier route"""

    start_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        verbose_name=_("start location"),
        related_name="+",
        help_text=_("Starting station or structure for courier route"),
    )
    end_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        verbose_name=_("end location"),
        related_name="+",
        help_text=_("Destination station or structure for courier route"),
    )

    collateral_min = models.BigIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("collateral minimum"),
        help_text=_("Minimum required collateral in ISK"),
    )
    collateral_max = models.BigIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("collateral maximum"),
        help_text=_("Maximum allowed collateral in ISK"),
    )
    days_to_expire = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        verbose_name=_("days to expire"),
        help_text=_("Recommended days for contracts to expire"),
    )
    days_to_complete = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        verbose_name=_("days to complete"),
        help_text=_("Recommended days for contract completion"),
    )
    details = models.TextField(
        default=None,
        null=True,
        blank=True,
        verbose_name=_("details"),
        help_text=_("Text with additional instructions for using this pricing"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("is active"),
        help_text=_("Disabled pricings will not be used or shown"),
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_("is default"),
        help_text=_(
            "The default pricing will be preselected in the calculator. "
            "Please make sure to only mark one pricing as default."
        ),
    )
    is_bidirectional = models.BooleanField(
        default=True,
        verbose_name=_("is bidirectional"),
        help_text=_(
            "Whether this pricing is valid for contracts "
            "in either direction or only the one specified"
        ),
    )
    price_base = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("price base"),
        help_text=_("Base price in ISK"),
    )
    price_min = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("price minimum"),
        help_text=_("Minimum total price in ISK"),
    )
    price_per_volume = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("price markup from volume"),
        help_text=_("Add-on price per m3 volume in ISK"),
    )
    price_per_collateral_percent = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("price markup from collateral"),
        help_text=_("Add-on price in percent of collateral"),
    )
    volume_max = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("volume maximum"),
        help_text=_("Maximum allowed volume in m3"),
    )
    volume_min = models.FloatField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("volume minimum"),
        help_text=_("Minimum allowed volume in m3"),
    )
    use_price_per_volume_modifier = models.BooleanField(
        default=False,
        verbose_name=_("price per volume modifier enabled"),
        help_text=_("Whether the global price per volume modifier is used"),
    )

    objects = PricingManager()

    class Meta:
        unique_together = (("start_location", "end_location"),)
        verbose_name = _("pricing")
        verbose_name_plural = _("pricings")

    def save(self, *args, **kwargs) -> None:
        update_contracts = kwargs.pop("update_contracts", True)
        super().save(*args, **kwargs)
        if update_contracts:
            self._update_contracts()

    def _update_contracts(self):
        from freight.tasks import update_contracts_pricing

        update_contracts_pricing.delay()

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(pk={self.pk}, name='{self.name_full}')"

    def clean(self):
        if (
            self.price_base is None
            and self.price_min is None
            and self.price_per_volume is None
            and self.price_per_collateral_percent is None
        ):
            raise ValidationError(_("You must specify at least one price component"))

        if self.start_location_id and self.end_location_id:
            if (
                Pricing.objects.filter(
                    start_location=self.end_location,
                    end_location=self.start_location,
                    is_bidirectional=True,
                ).exists()
                and self.is_bidirectional
            ):
                raise ValidationError(
                    _(
                        "There already exists a bidirectional pricing for this route. "
                        "Please set this pricing to non-bidirectional to save it. "
                        "And after you must also set the other pricing to "
                        "non-bidirectional."
                    )
                )

            if (
                Pricing.objects.filter(
                    start_location=self.end_location,
                    end_location=self.start_location,
                    is_bidirectional=False,
                ).exists()
                and self.is_bidirectional
            ):
                raise ValidationError(
                    _(
                        "There already exists a non bidirectional pricing for "
                        "this route. You need to mark this pricing as "
                        "non-bidirectional too to continue."
                    )
                )

    @property
    def name(self) -> str:
        """Return default pricing name."""
        return self._name(FREIGHT_FULL_ROUTE_NAMES)

    @property
    def name_full(self) -> str:
        """Return full pricing name."""
        return self._name(full_name=True)

    @property
    def name_short(self) -> str:
        """Return short pricing name."""
        return self._name(full_name=False)

    def _name(self, full_name: bool) -> str:
        if full_name:
            start_name = self.start_location.name
            end_name = self.end_location.name
        else:
            start_name = self.start_location.solar_system_name
            end_name = self.end_location.solar_system_name

        arrow = "<->" if self.is_bidirectional else "->"
        route_name = f"{start_name} {arrow} {end_name}"
        return route_name

    def price_per_volume_modifier(self):
        """returns the effective price per volume modifier or None"""
        if not self.use_price_per_volume_modifier:
            modifier = None

        else:
            handler = ContractHandler.objects.first()
            if handler:
                modifier = handler.price_per_volume_modifier

            else:
                modifier = None

        return modifier

    def price_per_volume_eff(self):
        """ "returns price per volume incl. potential modifier or None"""
        if not self.price_per_volume:
            price_per_volume = None
        else:
            price_per_volume = self.price_per_volume
            modifier = self.price_per_volume_modifier()
            if modifier:
                price_per_volume = max(
                    0, price_per_volume + (price_per_volume * modifier / 100)
                )

        return price_per_volume

    def requires_volume(self) -> bool:
        """whether this pricing required volume to be specified"""
        return (self.price_per_volume is not None and self.price_per_volume != 0) or (
            self.volume_min is not None and self.volume_min != 0
        )

    def requires_collateral(self) -> bool:
        """whether this pricing required collateral to be specified"""
        return (
            self.price_per_collateral_percent is not None
            and self.price_per_collateral_percent != 0
        ) or (self.collateral_min is not None and self.collateral_min != 0)

    def is_fix_price(self) -> bool:
        """whether this pricing is a fix price"""
        return (
            self.price_base is not None
            and self.price_min is None
            and self.price_per_volume is None
            and self.price_per_collateral_percent is None
        )

    def get_calculated_price(self, volume: float, collateral: float) -> float:
        """returns the calculated price for the given parameters"""

        if not volume:
            volume = 0

        if not collateral:
            collateral = 0

        if volume < 0:
            raise ValueError("volume can not be negative")
        if collateral < 0:
            raise ValueError("collateral can not be negative")

        volume = float(volume)
        collateral = float(collateral)

        price_base = 0 if not self.price_base else self.price_base
        price_min = 0 if not self.price_min else self.price_min

        price_per_volume_eff = self.price_per_volume_eff()
        if not price_per_volume_eff:
            price_per_volume = 0
        else:
            price_per_volume = price_per_volume_eff

        price_per_collateral_percent = (
            0
            if not self.price_per_collateral_percent
            else self.price_per_collateral_percent
        )

        return max(
            price_min,
            (
                price_base
                + volume * price_per_volume
                + collateral * (price_per_collateral_percent / 100)
            ),
        )

    def get_contract_price_check_issues(
        self, volume: float, collateral: float, reward: float = None
    ) -> Optional[List[str]]:
        """Return list of validation error messages or none if ok."""
        if volume and volume < 0:
            raise ValueError("volume can not be negative")
        if collateral and collateral < 0:
            raise ValueError("collateral can not be negative")
        if reward and reward < 0:
            raise ValueError("reward can not be negative")

        issues = []
        if volume is not None and self.volume_min and volume < self.volume_min:
            issues.append(
                f"below the minimum required volume of {self.volume_min:,.0f} m3"
            )
        if volume is not None and self.volume_max and volume > self.volume_max:
            issues.append(
                f"exceeds the maximum allowed volume of {self.volume_max:,.0f} m3"
            )
        if (
            collateral is not None
            and self.collateral_max
            and collateral > self.collateral_max
        ):
            issues.append(
                "exceeds the maximum allowed collateral "
                f"of {self.collateral_max:,.0f} ISK"
            )
        if (
            collateral is not None
            and self.collateral_min
            and collateral < self.collateral_min
        ):
            issues.append(
                "below the minimum required collateral "
                f"of {self.collateral_min:,.0f} ISK"
            )
        if reward is not None:
            calculated_price = self.get_calculated_price(volume, collateral)
            if reward < calculated_price:
                issues.append(
                    "reward is below the calculated price "
                    f"of {calculated_price:,.0f} ISK"
                )
        if len(issues) == 0:
            return None
        return issues
