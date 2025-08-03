# flake8: noqa
"""Script for creating generated contracts for testing."""

import os
import sys
from pathlib import Path

myauth_dir = Path(__file__).parent.parent.parent.parent.parent / "myauth"
sys.path.insert(0, str(myauth_dir))

import django
from django.apps import apps

# init and setup django project
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myauth.settings.local")
django.setup()

"""MAIN"""
import random

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from freight.models import Contract, ContractHandler, EveEntity, Location, Pricing
from freight.tests.testdata.factories_2 import ContractFactory

GURISTAS_CORPORATION_ID = 1000127
JITA_44_ID = 60003760
AMARR_ID = 60008494
CONTACTS_COUNT = 1000

# contract handler
handler = ContractHandler.objects.first()
if not handler:
    organization = EveEntity.objects.get_or_create_esi(id=GURISTAS_CORPORATION_ID)
    handler = ContractHandler.objects.create(organization=organization)

# default locations
jita, _ = Location.objects.get_or_create_esi(token=None, location_id=JITA_44_ID)
amarr, _ = Location.objects.get_or_create_esi(token=None, location_id=AMARR_ID)

# pricing
pricing, _ = Pricing.objects.update_or_create(
    start_location=jita,
    end_location=amarr,
    defaults={
        "price_base": 500_000,
        "volume_max": 320_000,
        "days_to_expire": 14,
        "days_to_complete": 3,
        "details": "GENERATED PRICING FOR TESTING",
    },
)

corporation_ids = set(
    EveCorporationInfo.objects.values_list("corporation_id", flat=True)
)
characters = {
    obj.character_id: obj
    for obj in EveCharacter.objects.filter(corporation_id__in=corporation_ids)
}

if len(characters) < 2:
    raise RuntimeError(
        "Need at least 2 EveCharacters with the related EveCorporationInfo."
    )

contracts = []
for _ in range(CONTACTS_COUNT):
    sample_character_ids = random.sample(set(characters.keys()), 2)
    issuer = characters.get(sample_character_ids[0])
    acceptor = characters.get(sample_character_ids[1])
    contracts.append(
        ContractFactory.build(
            handler=handler,
            start_location=jita,
            end_location=amarr,
            issuer=issuer,
            acceptor=acceptor,
            pricing=pricing,
            title="GENERATED CONTRACT",
        )
    )
Contract.objects.bulk_create(contracts, batch_size=500)
print(f"Created {CONTACTS_COUNT} contracts")
