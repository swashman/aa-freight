"""Views for freight."""

import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, Q, Sum
from django.forms import HiddenInput
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import format_html
from django.utils.text import format_lazy
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from esi.decorators import token_required
from esi.models import Token

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from . import __title__, constants, tasks
from .app_settings import (
    FREIGHT_APP_NAME,
    FREIGHT_OPERATION_MODE,
    FREIGHT_STATISTICS_MAX_DAYS,
)
from .forms import CalculatorForm
from .helpers import update_or_create_eve_entity_from_evecharacter
from .models import Contract, ContractHandler, EveEntity, Freight, Location, Pricing

logger = LoggerAddTag(get_extension_logger(__name__), __title__)

ADD_LOCATION_TOKEN_TAG = "freight_add_location_token"


def add_common_context(request, context: dict) -> dict:
    """adds the common context used by all view"""
    pending_user_count = (
        Contract.objects.all().issued_by_user(request.user).pending_count()
    )
    my_mode = Freight.operation_mode_friendly(FREIGHT_OPERATION_MODE)
    setup_str = _("Setup")
    button_label = format_lazy(
        "{setup} {operation_mode}", setup=setup_str, operation_mode=my_mode
    )
    new_context = {
        **{
            "app_title": FREIGHT_APP_NAME,
            "pending_all_count": Contract.objects.all().pending_count(),
            "pending_user_count": pending_user_count,
            "setup_contract_handler_label": button_label,
        },
        **context,
    }
    return new_context


@login_required
@permission_required("freight.basic_access")
def index(request):
    """Index view."""
    return redirect("freight:calculator")


@login_required
@permission_required("freight.use_calculator")
def contract_list_user(request):
    """View rendering contract list with contracts of a user only."""
    try:
        user_name = request.user.profile.main_character.character_name
    except AttributeError:
        user_name = request.user.username
    context = {
        "page_title": _("My Contracts"),
        "category": constants.CONTRACT_LIST_USER,
        "user_name": user_name,
    }
    return render(
        request, "freight/contracts_user.html", add_common_context(request, context)
    )


@login_required
@permission_required("freight.view_contracts")
def contract_list_all(request):
    """View rendering contract list with all contracts."""
    context = {
        "page_title": _("All Contracts"),
        "category": constants.CONTRACT_LIST_ALL,
    }
    return render(
        request, "freight/contracts_all.html", add_common_context(request, context)
    )


@login_required
@permission_required("freight.basic_access")
def contract_list_data(request, category: str) -> JsonResponse:
    """Return list of outstanding contracts for contract_list AJAX call."""
    contracts_data = []
    contracts_qs = Contract.objects.select_related(
        "acceptor",
        "acceptor_corporation",
        "end_location",
        "issuer",
        "start_location",
        "pricing",
        "pricing__start_location",
        "pricing__end_location",
    ).contract_list_filter(category=category, user=request.user)
    for contract in contracts_qs:
        route_name, pricing_check = _fetch_pricing_infos(contract)
        notes = _calc_notes(contract)

        start_location_html = format_html(
            '<span class="dotted-underline" title="{}">{}</span> {}',
            contract.start_location,
            contract.start_location.solar_system_name,
            notes,
        )
        end_location_html = format_html(
            '<span class="dotted-underline" title="{}">{}</span>',
            contract.end_location,
            contract.end_location.solar_system_name,
        )
        contracts_data.append(
            {
                "contract_id": contract.contract_id,
                "status": str(contract.status),
                "start_location": {
                    "display": start_location_html,
                    "sort": contract.start_location.name,
                },
                "end_location": {
                    "display": end_location_html,
                    "sort": contract.end_location.name,
                },
                "reward": contract.reward,
                "collateral": contract.collateral,
                "volume": contract.volume,
                "date_issued": contract.date_issued.isoformat(),
                "date_expired": contract.date_expired.isoformat(),
                "issuer": contract.issuer.character_name,
                "date_accepted": (
                    contract.date_accepted.isoformat()
                    if contract.date_accepted
                    else None
                ),
                "acceptor": contract.acceptor_name,
                "has_pricing": contract.has_pricing,
                "has_pricing_errors": contract.has_pricing_errors,
                "pricing_check": pricing_check,
                "route_name": route_name,
                "is_in_progress": contract.is_in_progress,
                "is_failed": contract.is_failed,
                "is_completed": contract.is_completed,
            }
        )
    return JsonResponse({"data": contracts_data})


def _calc_notes(contract):
    if contract.title or settings.DEBUG:
        if settings.DEBUG:
            title_first = f"{contract.title} " if contract.title else ""
            title = f"{title_first}{contract.contract_id}"
        else:
            title = contract.title

        notes = format_html('<i class="far fa-envelope" title="{}"></i>', title)
    else:
        notes = ""
    return notes


def _fetch_pricing_infos(contract):
    if contract.has_pricing:
        route_name = contract.pricing.name
        if not contract.has_pricing_errors:
            tooltip_text = route_name
            icon_html = format_html(
                '<span class="{}"><i class="fas fa-check" title="{}"></i></span>',
                "text-success",
                tooltip_text,
            )
        else:
            issues_text = "\n".join(contract.get_issue_list())
            tooltip_text = f"{route_name}\n{issues_text}"
            icon_html = format_html(
                (
                    '<span class="{}">'
                    '<i class="fas fa-exclamation-triangle" title="{}"></i>'
                    "</span>"
                ),
                "text-danger",
                tooltip_text,
            )

        pricing_check = icon_html
    else:
        route_name = ""
        pricing_check = "-"
    return route_name, pricing_check


@login_required
@permission_required("freight.use_calculator")
def calculator(request, pricing_pk=None):
    """Calculator view."""
    if request.method != "POST":
        pricing = Pricing.objects.get_or_default(pricing_pk)
        form = CalculatorForm(initial={"pricing": pricing})
        price = None
        volume = None
        collateral = None
    else:
        form = CalculatorForm(request.POST)
        request.POST._mutable = True  # pylint: disable=protected-access
        pricing_pk = form.data.get("pricing")
        pricing = Pricing.objects.get_or_default(pricing_pk)
        volume, collateral, price = form.get_calculated_data(pricing)

    if pricing:
        price_per_volume_eff = pricing.price_per_volume_eff()
        if not pricing.requires_volume():
            form.fields["volume"].widget = HiddenInput()
        if not pricing.requires_collateral():
            form.fields["collateral"].widget = HiddenInput()
    else:
        price_per_volume_eff = None

    if price:
        if pricing.days_to_expire:
            expires_on = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(days=pricing.days_to_expire)
        else:
            expires_on = None
    else:
        collateral = None
        volume = None
        expires_on = None

    handler = ContractHandler.objects.select_related("organization").first()
    if handler:
        organization_name = handler.organization.name
        availability = handler.get_availability_text_for_contracts()
    else:
        organization_name = None
        availability = None
    context = {
        "page_title": _("Reward Calculator"),
        "form": form,
        "pricing": pricing,
        "has_pricing": Pricing.objects.exists(),
        "price": price,
        "organization_name": organization_name,
        "collateral": collateral if collateral is not None else 0,
        "volume": volume if volume is not None else None,
        "expires_on": expires_on,
        "availability": availability,
        "pricing_price_per_volume_eff": price_per_volume_eff,
    }
    return render(
        request, "freight/calculator.html", add_common_context(request, context)
    )


@login_required
@permission_required("freight.setup_contract_handler")
@token_required(scopes=ContractHandler.get_esi_scopes())
def setup_contract_handler(request, token):
    """View for setting up a new contract handler."""
    success = True
    token_char = get_object_or_404(EveCharacter, character_id=token.character_id)
    if (
        Freight.category_for_operation_mode(FREIGHT_OPERATION_MODE)
        == EveEntity.CATEGORY_ALLIANCE
    ) and token_char.alliance_id is None:
        messages.error(
            request,
            _(
                "Can not setup contract handler, "
                "because %s is not a member of any alliance"
            )
            % token_char,
        )
        success = False

    owned_char = None
    if success:
        try:
            owned_char = CharacterOwnership.objects.get(
                user=request.user, character=token_char
            )
        except CharacterOwnership.DoesNotExist:
            messages.error(
                request,
                _(
                    "You can only use your main or alt characters to setup "
                    "the contract handler. "
                    "However, character %s is neither. ",
                )
                % token_char.character_name,
            )
            success = False

    if success:
        handler = ContractHandler.objects.first()
        if handler and handler.operation_mode != FREIGHT_OPERATION_MODE:
            messages.error(
                request,
                _(
                    "There already is a contract handler installed for a "
                    "different operation mode. You need to first delete the "
                    "existing contract handler in the admin section "
                    "before you can set up this app for a different operation mode."
                ),
            )
            success = False

    if success:
        organization = update_or_create_eve_entity_from_evecharacter(
            token_char, Freight.category_for_operation_mode(FREIGHT_OPERATION_MODE)
        )[0]

        handler = ContractHandler.objects.update_or_create(
            organization=organization,
            defaults={
                "character": owned_char,
                "operation_mode": FREIGHT_OPERATION_MODE,
            },
        )[0]
        tasks.run_contracts_sync.delay(force_sync=True)
        messages.success(
            request,
            _(
                "Contract Handler setup started for "
                "%(organization)s organization "
                "with %(character)s as sync character. "
                "Operation mode: %(operation_mode)s. "
                "Started syncing of courier contracts. "
            )
            % {
                "organization": organization.name,
                "character": handler.character.character.character_name,
                "operation_mode": handler.operation_mode_friendly,
            },
        )
    return redirect("freight:index")


@login_required
@token_required(scopes=Location.get_esi_scopes())
@permission_required("freight.add_location")
def add_location(request, token):
    """1st view when adding a new location."""
    request.session[ADD_LOCATION_TOKEN_TAG] = token.pk
    return redirect("freight:add_location_2")


@login_required
@permission_required("freight.add_location")
def add_location_2(request):
    """2nd view when adding a new location."""
    from .forms import AddLocationForm

    if ADD_LOCATION_TOKEN_TAG not in request.session:
        raise RuntimeError("Missing token in session")

    token = get_object_or_404(Token, pk=request.session[ADD_LOCATION_TOKEN_TAG])
    if request.method != "POST":
        form = AddLocationForm()
    else:
        form = AddLocationForm(request.POST)
        if form.is_valid():
            location_id = form.cleaned_data["location_id"]
            try:
                location, created = Location.objects.update_or_create_esi(
                    token=token, location_id=location_id, add_unknown=False
                )
            except OSError as ex:
                messages.error(
                    request,
                    _(
                        "Failed to add location with token from %(character)s "
                        "for location ID %(id)s: %(error)s"
                    )
                    % {
                        "character": token.character_name,
                        "id": location_id,
                        "error": type(ex).__name__,
                    },
                )
            else:
                action_txt = _("Added:") if created else _("Updated:")
                messages.success(request, f"{action_txt} {location.name}")
                return redirect("freight:add_location_2")
    context = {
        "page_title": _("Add / Update Location"),
        "form": form,
        "token_char_name": token.character_name,
    }
    return render(
        request, "freight/add_location.html", add_common_context(request, context)
    )


@login_required
@permission_required("freight.view_statistics")
def statistics(request):
    """View for rendering the statistics page."""
    context = {
        "page_title": "Statistics",
        "max_days": FREIGHT_STATISTICS_MAX_DAYS,
    }
    return render(
        request, "freight/statistics.html", add_common_context(request, context)
    )


@login_required
@permission_required("freight.view_statistics")
def statistics_routes_data(request):
    """Returns total for statistics as JSON."""
    cutoff_date = now() - datetime.timedelta(days=FREIGHT_STATISTICS_MAX_DAYS)
    finished_contracts = Q(contracts__status=Contract.Status.FINISHED) & Q(
        contracts__date_completed__gte=cutoff_date
    )
    route_totals = (
        Pricing.objects.annotate(
            contracts_count=Count("contracts", filter=finished_contracts)
        )
        .select_related("start_location", "end_location")
        .annotate(rewards=Sum("contracts__reward", filter=finished_contracts))
        .annotate(collaterals=Sum("contracts__collateral", filter=finished_contracts))
        .annotate(volume=Sum("contracts__volume", filter=finished_contracts))
        .annotate(
            pilots=Count(
                "contracts__acceptor", distinct=True, filter=finished_contracts
            )
        )
        .annotate(
            customers=Count(
                "contracts__issuer", distinct=True, filter=finished_contracts
            )
        )
    )
    totals = [
        {
            "name": route.name,
            "contracts": route.contracts_count,
            "rewards": route.rewards,
            "collaterals": route.collaterals,
            "volume": route.volume,
            "pilots": route.pilots,
            "customers": route.customers,
        }
        for route in route_totals
        if route.contracts_count > 0
    ]
    return JsonResponse({"data": totals})


@login_required
@permission_required("freight.view_statistics")
def statistics_pilots_data(request):
    """returns totals for statistics as JSON"""
    cutoff_date = now() - datetime.timedelta(days=FREIGHT_STATISTICS_MAX_DAYS)
    finished_contracts = Q(contracts_acceptor__status=Contract.Status.FINISHED) & Q(
        contracts_acceptor__date_completed__gte=cutoff_date
    )
    pilot_totals = (
        EveCharacter.objects.exclude(contracts_acceptor__isnull=True)
        .annotate(
            contracts_count=Count("contracts_acceptor", filter=finished_contracts)
        )
        .annotate(rewards=Sum("contracts_acceptor__reward", filter=finished_contracts))
        .annotate(
            collaterals=Sum("contracts_acceptor__collateral", filter=finished_contracts)
        )
        .annotate(volume=Sum("contracts_acceptor__volume", filter=finished_contracts))
    )
    totals = [
        {
            "name": pilot.character_name,
            "corporation": pilot.corporation_name,
            "contracts": pilot.contracts_count,
            "rewards": pilot.rewards,
            "collaterals": pilot.collaterals,
            "volume": pilot.volume,
        }
        for pilot in pilot_totals
        if pilot.contracts_count > 0
    ]
    return JsonResponse({"data": totals})


@login_required
@permission_required("freight.view_statistics")
def statistics_pilot_corporations_data(request):
    """returns totals for statistics as JSON"""
    cutoff_date = now() - datetime.timedelta(days=FREIGHT_STATISTICS_MAX_DAYS)
    finished_contracts = Q(
        contracts_acceptor_corporation__status=Contract.Status.FINISHED
    ) & Q(contracts_acceptor_corporation__date_completed__gte=cutoff_date)

    corporation_totals = (
        EveCorporationInfo.objects.exclude(contracts_acceptor_corporation__isnull=True)
        .select_related("alliance")
        .annotate(
            contracts_count=Count(
                "contracts_acceptor_corporation", filter=finished_contracts
            )
        )
        .annotate(
            rewards=Sum(
                "contracts_acceptor_corporation__reward", filter=finished_contracts
            )
        )
        .annotate(
            collaterals=Sum(
                "contracts_acceptor_corporation__collateral", filter=finished_contracts
            )
        )
        .annotate(
            volume=Sum(
                "contracts_acceptor_corporation__volume", filter=finished_contracts
            )
        )
    )
    totals = []
    for corporation in corporation_totals:
        if corporation.contracts_count > 0:
            alliance = (
                corporation.alliance.alliance_name if corporation.alliance else ""
            )
            totals.append(
                {
                    "name": corporation.corporation_name,
                    "alliance": alliance,
                    "contracts": corporation.contracts_count,
                    "rewards": corporation.rewards,
                    "collaterals": corporation.collaterals,
                    "volume": corporation.volume,
                }
            )
    return JsonResponse({"data": totals})


@login_required
@permission_required("freight.view_statistics")
def statistics_customer_data(request):
    """returns totals for statistics as JSON"""
    cutoff_date = now() - datetime.timedelta(days=FREIGHT_STATISTICS_MAX_DAYS)
    finished_contracts = Q(contracts_issuer__status=Contract.Status.FINISHED) & Q(
        contracts_issuer__date_completed__gte=cutoff_date
    )
    customer_totals = (
        EveCharacter.objects.exclude(contracts_issuer__isnull=True)
        .annotate(contracts_count=Count("contracts_issuer", filter=finished_contracts))
        .annotate(rewards=Sum("contracts_issuer__reward", filter=finished_contracts))
        .annotate(
            collaterals=Sum("contracts_issuer__collateral", filter=finished_contracts)
        )
        .annotate(volume=Sum("contracts_issuer__volume", filter=finished_contracts))
    )
    totals = []
    for customer in customer_totals:
        if customer.contracts_count > 0:
            totals.append(
                {
                    "name": customer.character_name,
                    "corporation": customer.corporation_name,
                    "contracts": customer.contracts_count,
                    "rewards": customer.rewards,
                    "collaterals": customer.collaterals,
                    "volume": customer.volume,
                }
            )
    return JsonResponse({"data": totals})
