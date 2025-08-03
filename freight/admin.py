"""Admin site for Freight."""

# pylint: disable=missing-class-docstring, missing-function-docstring


from django.conf import settings
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from . import tasks
from .models import (
    Contract,
    ContractCustomerNotification,
    ContractHandler,
    EveEntity,
    Location,
    Pricing,
)
from .tasks import update_locations


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "_category", "_solar_system")
    list_filter = ("category_id",)
    search_fields = ["name"]
    list_select_related = True
    list_display_links = None
    actions = ["update_location"]

    def has_add_permission(self, *args, **kwargs):
        return False

    def has_change_permission(self, *args, **kwargs):
        return False

    @admin.display(ordering="category_id", description=_("category"))
    def _category(self, obj):
        return obj.get_category_id_display()

    @admin.display(description=_("solar system"))
    def _solar_system(self, obj):
        return obj.solar_system_name

    @admin.action(description=_("Update selected locations from ESI"))
    def update_location(self, request, queryset):
        location_ids = []
        for obj in queryset:
            location_ids.append(obj.pk)

        update_locations.delay(location_ids)
        self.message_user(
            request,
            (
                _(
                    "Started updating %d locations. "
                    "This can take a short while to complete."
                )
                % len(location_ids)
            ),
        )


@admin.register(Pricing)
class PricingAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "start_location",
        "end_location",
        "_bidirectional",
        "_default",
        "_active",
    )
    list_filter = (
        "is_bidirectional",
        "is_active",
        ("start_location", admin.RelatedOnlyFieldListFilter),
        ("end_location", admin.RelatedOnlyFieldListFilter),
    )
    list_select_related = True

    @admin.display(boolean=True, description=_("bidirectional"))
    def _bidirectional(self, obj):
        return obj.is_bidirectional

    @admin.display(boolean=True, description=_("active"))
    def _active(self, obj):
        return obj.is_active

    @admin.display(boolean=True, description=_("default"))
    def _default(self, obj):
        return obj.is_default


@admin.register(ContractHandler)
class ContractHandlerAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "character",
        "operation_mode",
        "last_sync",
        "_is_sync_ok",
    )
    actions = ("start_sync", "send_notifications", "update_pricing")
    readonly_fields = (
        "organization",
        "character",
        "operation_mode",
        "version_hash",
        "last_sync",
    )

    def get_fields(self, request, obj=None):
        """Do not show some specific fields."""
        fields = super().get_fields(request, obj)
        return [name for name in fields if name != "last_error"]

    def has_add_permission(self, *args, **kwargs):
        return False

    @admin.display(boolean=True, description=_("sync ok"))
    def _is_sync_ok(self, obj):
        return obj.is_sync_ok

    @admin.action(description=_("Fetch contracts from Eve Online server"))
    def start_sync(self, request, queryset):
        for obj in queryset:
            tasks.run_contracts_sync.delay(force_sync=True)
            self.message_user(request, _("Started syncing contracts for: %s") % obj)

    @admin.action(description=_("Send notifications for outstanding contracts"))
    def send_notifications(self, request, queryset):
        for obj in queryset:
            tasks.send_contract_notifications.delay(force_sent=True)
            self.message_user(
                request, _("Started sending notifications for: %s ") % obj
            )

    @admin.action(description=_("Update pricing info for all contracts"))
    def update_pricing(self, request, queryset):
        del queryset
        tasks.update_contracts_pricing.delay()
        self.message_user(
            request, "Started updating pricing relations for all contracts"
        )


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = [
        "contract_id",
        "status",
        "date_issued",
        "issuer",
        "pricing",
        "_pilots_notified",
        "_customer_notified",
    ]
    list_filter = (
        "status",
        ("issuer", admin.RelatedOnlyFieldListFilter),
        ("pricing", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ["issuer"]
    list_select_related = (
        "issuer",
        "pricing",
        "pricing__start_location",
        "pricing__end_location",
    )
    actions = ["send_pilots_notification", "send_customer_notification"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("customer_notifications")

    def has_add_permission(self, *args, **kwargs):
        return False

    def has_change_permission(self, *args, **kwargs):
        return False

    @admin.display(boolean=True, description=_("pilots notified"))
    def _pilots_notified(self, contract):
        if contract.pricing_id is None:
            return None
        return contract.date_notified is not None

    @admin.display(description=_("customer notified"))
    def _customer_notified(self, contract):
        if contract.pricing_id is None:
            return "?"
        notifications = [x.status for x in contract.customer_notifications.all()]
        if not notifications:
            return None
        return ", ".join(sorted(notifications, reverse=True))

    @admin.action(
        description=_("Sent pilots notification for selected contracts to Discord")
    )
    def send_pilots_notification(self, request, queryset):
        for obj in queryset:
            obj.send_pilot_notification()
            self.message_user(
                request,
                _("Sent pilots notification for contract %d to Discord")
                % obj.contract_id,
            )

    @admin.action(
        description=_("Sent customer notification for selected contracts to Discord")
    )
    def send_customer_notification(self, request, queryset):
        for obj in queryset:
            obj.send_customer_notification(force_sent=True)
            self.message_user(
                request,
                _("Sent customer notification for contract %d to Discord")
                % obj.contract_id,
            )


if settings.DEBUG:

    @admin.register(ContractCustomerNotification)
    class ContractCustomerNotificationAdmin(admin.ModelAdmin):
        def has_add_permission(self, *args, **kwargs):
            return False

        def has_change_permission(self, *args, **kwargs):
            return False

    @admin.register(EveEntity)
    class EveEntityAdmin(admin.ModelAdmin):
        list_display = ("name", "category")
        list_filter = ("category",)

        def has_add_permission(self, *args, **kwargs):
            return False

        def has_change_permission(self, *args, **kwargs):
            return False
