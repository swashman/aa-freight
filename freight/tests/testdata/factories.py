import datetime as dt

from django.utils.timezone import now

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from ...models import Contract, ContractHandler, Pricing


def create_contract_handler(**kwargs):
    kwargs["organization_id"] = kwargs["character"].character.corporation_id
    return ContractHandler.objects.create(**kwargs)


def create_contract(**kwargs):
    contract_id = int(dt.datetime.now().timestamp())
    params = {
        "contract_id": contract_id,
        "collateral": 1_000_000_000,
        "date_expired": now() + dt.timedelta(days=3),
        "date_issued": now(),
        "days_to_complete": 3,
        "for_corporation": False,
        "reward": 100_000_000,
        "status": Contract.Status.OUTSTANDING,
        "title": f"Test contract #{contract_id}",
        "volume": 20_000,
    }
    params.update(kwargs)
    if "end_location" not in params and "end_location_id" not in params:
        params["end_location_id"] = 1022167642188
    if "issuer_corporation" not in params and "issuer_corporation_id" not in params:
        params["issuer_corporation"] = EveCorporationInfo.objects.get(
            corporation_id=92000001
        )
    if "issuer" not in params and "issuer_id" not in params:
        params["issuer"] = EveCharacter.objects.get(character_id=90000002)
    if "start_location" not in params and "start_location_id" not in params:
        params["start_location_id"] = 60003760
    return Contract.objects.create(**params)


def create_pricing(update_contracts: bool = False, **kwargs) -> Pricing:
    obj = Pricing(**kwargs)
    obj.save(update_contracts=update_contracts)
    return obj
