import datetime as dt
from typing import Generic, TypeVar

import factory
import factory.fuzzy

from django.utils import timezone

from app_utils.testdata_factories import (
    EveCharacterFactory,
    EveCorporationInfoFactory,
    UserMainFactory,
)

from freight.models import Contract, ContractHandler, EveEntity, Location

T = TypeVar("T")


class BaseMetaFactory(Generic[T], factory.base.FactoryMetaClass):
    def __call__(cls, *args, **kwargs) -> T:
        return super().__call__(*args, **kwargs)


class EveEntityCharacterFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity

    id = factory.Sequence(lambda n: 99100 + n)
    category = EveEntity.CATEGORY_CHARACTER
    name = factory.faker.Faker("name")


class EveEntityCorporationFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity

    id = factory.Sequence(lambda n: 99200 + n)
    category = EveEntity.CATEGORY_CORPORATION
    name = factory.faker.Faker("city")


class EveEntityAllianceFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity

    id = factory.Sequence(lambda n: 99300 + n)
    category = EveEntity.CATEGORY_ALLIANCE
    name = factory.faker.Faker("country")


class LocationFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Location]
):
    class Meta:
        model = Location

    id = factory.Sequence(lambda n: 99900 + n)
    category_id = Location.Category.STATION_ID
    name = factory.faker.Faker("city")


class UserMainDefaultFactory(UserMainFactory):
    main_character__scopes = [
        "esi-universe.read_structures.v1",
        "esi-contracts.read_corporation_contracts.v1",
        "esi-universe.read_structures.v1",
    ]
    permissions__ = [
        "freight.basic_access",
        "freight.use_calculator",
    ]


class UserMainManagerFactory(UserMainDefaultFactory):
    main_character__scopes = [
        "esi-universe.read_structures.v1",
        "esi-contracts.read_corporation_contracts.v1",
        "esi-universe.read_structures.v1",
    ]
    permissions__ = [
        "freight.basic_access",
        # "freight.add_location",
        "freight.setup_contract_handler",
        "freight.use_calculator",
        "freight.view_contracts",
        "freight.view_statistics",
    ]


class ContractHandlerFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[ContractHandler]
):
    class Meta:
        model = ContractHandler

    organization = factory.SubFactory(EveEntityAllianceFactory)


class ContractFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Contract]
):
    class Meta:
        model = Contract

    acceptor = factory.SubFactory(EveCharacterFactory)
    contract_id = factory.Sequence(lambda n: 10_000_000 + n)
    collateral = factory.fuzzy.FuzzyFloat(100_000_000, 1_000_000_000)
    days_to_complete = 3
    date_completed = None
    date_issued = factory.fuzzy.FuzzyDateTime(timezone.now() - dt.timedelta(days=7))
    date_expired = factory.LazyAttribute(
        lambda o: o.date_issued + dt.timedelta(days=o.days_to_complete)
    )
    end_location = factory.SubFactory(LocationFactory)
    for_corporation = False
    handler = factory.SubFactory(ContractHandlerFactory)
    issuer = factory.SubFactory(EveCharacterFactory)
    reward = factory.fuzzy.FuzzyFloat(50_000_000, 100_000_000)
    status = Contract.Status.IN_PROGRESS
    start_location = factory.SubFactory(LocationFactory)
    title = factory.faker.Faker("sentence")
    volume = factory.fuzzy.FuzzyInteger(1_000, 100_000_000)

    @factory.lazy_attribute
    def date_accepted(self):
        return factory.fuzzy.FuzzyDateTime(
            start_dt=self.date_issued,
            end_dt=min(self.date_issued + dt.timedelta(days=2), timezone.now()),
        ).fuzz()

    @factory.lazy_attribute
    def acceptor_corporation(self):
        return EveCorporationInfoFactory(corporation_id=self.acceptor.corporation_id)

    @factory.lazy_attribute
    def issuer_corporation(self):
        return EveCorporationInfoFactory(corporation_id=self.issuer.corporation_id)
