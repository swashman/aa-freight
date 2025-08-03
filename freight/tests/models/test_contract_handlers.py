import datetime as dt
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.utils.timezone import now
from esi.errors import TokenError, TokenExpiredError, TokenInvalidError
from esi.models import Token

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.tests.auth_utils import AuthUtils
from app_utils.testing import BravadoOperationStub, NoSocketsTestCase

from freight.app_settings import (
    FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE,
    FREIGHT_OPERATION_MODE_CORP_PUBLIC,
    FREIGHT_OPERATION_MODE_MY_ALLIANCE,
    FREIGHT_OPERATION_MODE_MY_CORPORATION,
    FREIGHT_OPERATION_MODES,
)
from freight.models import Contract, ContractHandler, EveEntity, Freight

from ..testdata.helpers import (
    characters_data,
    contracts_data,
    create_entities_from_characters,
    create_locations,
)

MODULE_PATH = "freight.models.contract_handlers"
PATCH_FREIGHT_OPERATION_MODE = MODULE_PATH + ".FREIGHT_OPERATION_MODE"


class TestContractHandler(NoSocketsTestCase):
    def setUp(self):
        for character in characters_data:
            EveCharacter.objects.create(**character)
            EveCorporationInfo.objects.get_or_create(
                corporation_id=character["corporation_id"],
                defaults={
                    "corporation_name": character["corporation_name"],
                    "corporation_ticker": character["corporation_ticker"],
                    "member_count": 42,
                },
            )

        # 1 user
        self.character = EveCharacter.objects.get(character_id=90000001)
        self.corporation = EveCorporationInfo.objects.get(
            corporation_id=self.character.corporation_id
        )
        self.organization = EveEntity.objects.create(
            id=self.character.alliance_id,
            category=EveEntity.CATEGORY_ALLIANCE,
            name=self.character.alliance_name,
        )
        self.user = User.objects.create_user(
            self.character.character_name, "abc@example.com", "password"
        )
        self.main_ownership = CharacterOwnership.objects.create(
            character=self.character, owner_hash="x1", user=self.user
        )
        self.handler = ContractHandler.objects.create(
            organization=self.organization, character=self.main_ownership
        )

    def test_str(self):
        self.assertEqual(str(self.handler), "Justice League")

    def test_repr(self):
        expected = (
            f"ContractHandler(pk={self.handler.pk}, organization='Justice League')"
        )
        self.assertEqual(repr(self.handler), expected)

    def test_operation_mode_friendly(self):
        self.handler.operation_mode = FREIGHT_OPERATION_MODE_MY_ALLIANCE
        self.assertEqual(self.handler.operation_mode_friendly, "My Alliance")
        self.handler.operation_mode = "undefined operation mode"
        with self.assertRaises(ValueError):
            self.handler.operation_mode_friendly

    def test_get_availability_text_for_contracts(self):
        self.handler.operation_mode = FREIGHT_OPERATION_MODE_MY_ALLIANCE
        self.assertEqual(
            self.handler.get_availability_text_for_contracts(),
            "Private (Justice League) [My Alliance]",
        )
        self.handler.operation_mode = FREIGHT_OPERATION_MODE_MY_CORPORATION
        self.assertEqual(
            self.handler.get_availability_text_for_contracts(),
            "Private (Justice League) [My Corporation]",
        )
        self.handler.operation_mode = FREIGHT_OPERATION_MODE_CORP_PUBLIC
        self.assertEqual(
            self.handler.get_availability_text_for_contracts(),
            "Private (Justice League) ",
        )

    @patch(MODULE_PATH + ".FREIGHT_CONTRACT_SYNC_GRACE_MINUTES", 30)
    def test_is_sync_ok(self):
        # recent sync
        self.handler.last_sync = now()
        self.assertTrue(self.handler.is_sync_ok)

        # sync within grace period
        self.handler.last_sync = now() - dt.timedelta(minutes=29)
        self.assertTrue(self.handler.is_sync_ok)

        # no sync within grace period
        self.handler.last_sync = now() - dt.timedelta(minutes=31)
        self.assertFalse(self.handler.is_sync_ok)


class TestContractsSync(NoSocketsTestCase):
    def setUp(self):
        create_entities_from_characters()

        # 1 user
        self.character = EveCharacter.objects.get(character_id=90000001)

        self.alliance = EveEntity.objects.get(id=self.character.alliance_id)
        self.corporation = EveEntity.objects.get(id=self.character.corporation_id)
        self.user = User.objects.create_user(
            self.character.character_name, "abc@example.com", "password"
        )
        self.main_ownership = CharacterOwnership.objects.create(
            character=self.character, owner_hash="x1", user=self.user
        )
        create_locations()

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_CORPORATION)
    def test_abort_on_wrong_operation_mode(self):
        # given
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
            character=self.main_ownership,
        )
        # when/then
        with self.assertRaises(ValueError):
            handler.update_contracts_esi()

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_ALLIANCE)
    def test_abort_when_no_sync_char(self):
        # given
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        )
        # when/Then
        with self.assertRaises(ValueError):
            handler.update_contracts_esi()

    # test expired token
    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_ALLIANCE)
    @patch(MODULE_PATH + ".Token")
    def test_abort_when_token_expired(self, mock_Token):
        # given
        mock_Token.objects.filter.side_effect = TokenExpiredError()
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        )
        # when/then
        with self.assertRaises(TokenExpiredError):
            handler.update_contracts_esi()

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_ALLIANCE)
    @patch(MODULE_PATH + ".Token")
    def test_abort_when_token_invalid(self, mock_Token):
        mock_Token.objects.filter.side_effect = TokenInvalidError()
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        )

        # when/then
        with self.assertRaises(TokenInvalidError):
            handler.update_contracts_esi()

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_ALLIANCE)
    @patch(MODULE_PATH + ".Token")
    def test_abort_when_no_token_exists(self, mock_Token):
        mock_Token.objects.filter.return_value.require_scopes.return_value.require_valid.return_value.first.return_value = (
            None
        )
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        )
        with self.assertRaises(TokenError):
            handler.update_contracts_esi()

    @staticmethod
    def esi_get_corporations_corporation_id_contracts(**kwargs):
        return BravadoOperationStub(contracts_data)

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_ALLIANCE)
    @patch(MODULE_PATH + ".ContractHandler.contracts")
    @patch(MODULE_PATH + ".Token")
    @patch(MODULE_PATH + ".esi")
    def test_continue_when_exception_occurs_during_contract_creation(
        self,
        mock_esi,
        mock_Token,
        mock_Contracts_objects_update_or_create_from_dict,
    ):
        mock_Contracts_objects_update_or_create_from_dict.update_or_create_from_dict.side_effect = (
            OSError
        )
        mock_Contracts = mock_esi.client.Contracts
        mock_Contracts.get_corporations_corporation_id_contracts.side_effect = (
            self.esi_get_corporations_corporation_id_contracts
        )
        mock_Token.objects.filter.return_value.require_scopes.return_value.require_valid.return_value.first.return_value = Mock(
            spec=Token
        )
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        )

        # when
        handler.update_contracts_esi()

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_ALLIANCE)
    @patch(MODULE_PATH + ".Token")
    @patch(MODULE_PATH + ".esi")
    def test_can_sync_contracts_for_my_alliance(self, mock_esi, mock_Token):
        mock_Contracts = mock_esi.client.Contracts
        mock_Contracts.get_corporations_corporation_id_contracts.side_effect = (
            self.esi_get_corporations_corporation_id_contracts
        )
        mock_Token.objects.filter.return_value.require_scopes.return_value.require_valid.return_value.first.return_value = Mock(
            spec=Token
        )
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        )

        handler.update_contracts_esi()

        # should only contain the right contracts
        contract_ids = [
            x["contract_id"]
            for x in Contract.objects.filter(
                status__exact=Contract.Status.OUTSTANDING
            ).values("contract_id")
        ]
        self.assertCountEqual(
            contract_ids, [149409005, 149409014, 149409006, 149409015]
        )

        # 2nd run should not update anything, but reset last_sync
        Contract.objects.all().delete()
        handler.last_sync = None
        handler.save()
        handler.update_contracts_esi()
        self.assertEqual(Contract.objects.count(), 0)
        handler.refresh_from_db()
        self.assertIsNotNone(handler.last_sync)

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_CORPORATION)
    @patch(MODULE_PATH + ".Token")
    @patch(MODULE_PATH + ".esi")
    def test_sync_contracts_for_my_corporation(self, mock_esi, mock_Token):
        mock_Contracts = mock_esi.client.Contracts
        mock_Contracts.get_corporations_corporation_id_contracts.side_effect = (
            self.esi_get_corporations_corporation_id_contracts
        )
        mock_Token.objects.filter.return_value.require_scopes.return_value.require_valid.return_value.first.return_value = Mock(
            spec=Token
        )
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.corporation,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_MY_CORPORATION,
        )

        # run manager sync
        handler.update_contracts_esi()
        handler.refresh_from_db()

        # should only contain the right contracts
        contract_ids = [
            x["contract_id"]
            for x in Contract.objects.filter(
                status__exact=Contract.Status.OUTSTANDING
            ).values("contract_id")
        ]
        self.assertCountEqual(
            contract_ids,
            [
                149409016,
                149409061,
                149409062,
                149409063,
                149409064,
            ],
        )

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE)
    @patch(MODULE_PATH + ".Token")
    @patch(MODULE_PATH + ".esi")
    def test_sync_contracts_for_corp_in_alliance(self, mock_esi, mock_Token):
        mock_Contracts = mock_esi.client.Contracts
        mock_Contracts.get_corporations_corporation_id_contracts.side_effect = (
            self.esi_get_corporations_corporation_id_contracts
        )
        mock_Token.objects.filter.return_value.require_scopes.return_value.require_valid.return_value.first.return_value = Mock(
            spec=Token
        )
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.corporation,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE,
        )

        # run manager sync
        handler.update_contracts_esi()

        # should only contain the right contracts
        contract_ids = [
            x["contract_id"]
            for x in Contract.objects.filter(
                status__exact=Contract.Status.OUTSTANDING
            ).values("contract_id")
        ]
        self.assertCountEqual(
            contract_ids,
            [149409016, 149409017, 149409061, 149409062, 149409063, 149409064],
        )

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_CORP_PUBLIC)
    @patch(MODULE_PATH + ".Token")
    @patch(MODULE_PATH + ".esi")
    def test_can_sync_contracts_for_corp_public(self, mock_esi, mock_Token):
        # create mocks
        mock_Contracts = mock_esi.client.Contracts
        mock_Contracts.get_corporations_corporation_id_contracts.side_effect = (
            self.esi_get_corporations_corporation_id_contracts
        )
        mock_Token.objects.filter.return_value.require_scopes.return_value.require_valid.return_value.first.return_value = Mock(
            spec=Token
        )
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.corporation,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_CORP_PUBLIC,
        )

        # run manager sync
        handler.update_contracts_esi()

        # should only contain the right contracts
        contract_ids = [
            x["contract_id"]
            for x in Contract.objects.filter(
                status__exact=Contract.Status.OUTSTANDING
            ).values("contract_id")
        ]
        self.assertCountEqual(
            contract_ids,
            [
                149409016,
                149409061,
                149409062,
                149409063,
                149409064,
                149409017,
                149409018,
            ],
        )

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_ALLIANCE)
    @patch(MODULE_PATH + ".esi")
    @patch(MODULE_PATH + ".ContractHandler.token")
    def test_should_abort_on_general_exception(self, mock_token, mock_esi):
        # given
        mock_esi.client.Contracts.get_corporations_corporation_id_contracts.side_effect = (
            RuntimeError
        )
        self.user = AuthUtils.add_permission_to_user_by_name(
            "freight.setup_contract_handler", self.user
        )
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            character=self.main_ownership,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
        )
        # when/then
        with self.assertRaises(RuntimeError):
            handler.update_contracts_esi()

    @patch(PATCH_FREIGHT_OPERATION_MODE, FREIGHT_OPERATION_MODE_MY_ALLIANCE)
    def test_operation_mode_friendly(self):
        handler = ContractHandler.objects.create(
            organization=self.alliance,
            operation_mode=FREIGHT_OPERATION_MODE_MY_ALLIANCE,
            character=self.main_ownership,
        )
        self.assertEqual(handler.operation_mode_friendly, FREIGHT_OPERATION_MODES[0][1])

        handler.operation_mode = FREIGHT_OPERATION_MODE_MY_CORPORATION
        self.assertEqual(handler.operation_mode_friendly, FREIGHT_OPERATION_MODES[1][1])

        handler.operation_mode = FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE
        self.assertEqual(handler.operation_mode_friendly, FREIGHT_OPERATION_MODES[2][1])

        handler.operation_mode = FREIGHT_OPERATION_MODE_CORP_PUBLIC
        self.assertEqual(handler.operation_mode_friendly, FREIGHT_OPERATION_MODES[3][1])


class TestEveEntity(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_entities_from_characters()
        cls.alliance = EveEntity.objects.get(id=93000001)
        cls.corporation = EveEntity.objects.get(id=92000001)
        cls.character = EveEntity.objects.get(id=90000001)

    def test_str(self):
        self.assertEqual(str(self.character), "Bruce Wayne")

    def test_repr(self):
        expected = (
            f"EveEntity(id={self.character.id}, category='character', "
            "name='Bruce Wayne')"
        )
        self.assertEqual(repr(self.character), expected)

    def test_is_alliance(self):
        self.assertFalse(self.character.is_alliance)
        self.assertFalse(self.corporation.is_alliance)
        self.assertTrue(self.alliance.is_alliance)

    def test_is_corporation(self):
        self.assertFalse(self.character.is_corporation)
        self.assertTrue(self.corporation.is_corporation)
        self.assertFalse(self.alliance.is_corporation)

    def test_is_character(self):
        self.assertTrue(self.character.is_character)
        self.assertFalse(self.corporation.is_character)
        self.assertFalse(self.alliance.is_character)

    def test_avatar_url_alliance(self):
        expected = "https://images.evetech.net/alliances/93000001/logo?size=128"
        self.assertEqual(self.alliance.icon_url(), expected)

    def test_avatar_url_corporation(self):
        expected = "https://images.evetech.net/corporations/92000001/logo?size=128"
        self.assertEqual(self.corporation.icon_url(), expected)

    def test_avatar_url_character(self):
        expected = "https://images.evetech.net/characters/90000001/portrait?size=128"
        self.assertEqual(self.character.icon_url(), expected)


class TestFreight(NoSocketsTestCase):
    def test_get_category_for_operation_mode_1(self):
        self.assertEqual(
            Freight.category_for_operation_mode(FREIGHT_OPERATION_MODE_MY_ALLIANCE),
            EveEntity.CATEGORY_ALLIANCE,
        )
        self.assertEqual(
            Freight.category_for_operation_mode(FREIGHT_OPERATION_MODE_MY_CORPORATION),
            EveEntity.CATEGORY_CORPORATION,
        )
        self.assertEqual(
            Freight.category_for_operation_mode(
                FREIGHT_OPERATION_MODE_CORP_IN_ALLIANCE
            ),
            EveEntity.CATEGORY_CORPORATION,
        )
        self.assertEqual(
            Freight.category_for_operation_mode(FREIGHT_OPERATION_MODE_CORP_PUBLIC),
            EveEntity.CATEGORY_CORPORATION,
        )
