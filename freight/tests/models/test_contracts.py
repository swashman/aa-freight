import datetime as dt
from unittest.mock import patch

from dhooks_lite import Embed

from django.contrib.auth.models import User
from django.utils.timezone import now

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from app_utils.django import app_labels
from app_utils.testing import NoSocketsTestCase

from freight.models import (
    Contract,
    ContractCustomerNotification,
    ContractHandler,
    EveEntity,
    Location,
)

from ..testdata.factories import create_pricing
from ..testdata.helpers import characters_data, create_contract_handler_w_contracts

if "discord" in app_labels():
    from allianceauth.services.modules.discord.models import DiscordUser
else:
    DiscordUser = None

try:
    from discordproxy.client import DiscordClient
    from discordproxy.exceptions import to_discord_proxy_exception
    from discordproxy.tests.factories import create_rpc_error

except ImportError:
    DiscordClient = None


MODULE_PATH = "freight.models.contracts"
PATCH_FREIGHT_OPERATION_MODE = MODULE_PATH + ".FREIGHT_OPERATION_MODE"


class TestContract(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        cls.character = EveCharacter.objects.get(character_id=90000001)
        cls.corporation = EveCorporationInfo.objects.get(
            corporation_id=cls.character.corporation_id
        )
        cls.organization = EveEntity.objects.create(
            id=cls.character.alliance_id,
            category=EveEntity.CATEGORY_ALLIANCE,
            name=cls.character.alliance_name,
        )
        cls.user = User.objects.create_user(
            cls.character.character_name, "abc@example.com", "password"
        )
        cls.main_ownership = CharacterOwnership.objects.create(
            character=cls.character, owner_hash="x1", user=cls.user
        )
        # Locations
        cls.jita = Location.objects.create(
            id=60003760,
            name="Jita IV - Moon 4 - Caldari Navy Assembly Plant",
            solar_system_id=30000142,
            type_id=52678,
            category_id=3,
        )
        cls.amamake = Location.objects.create(
            id=1022167642188,
            name="Amamake - 3 Time Nearly AT Winners",
            solar_system_id=30002537,
            type_id=35834,
            category_id=65,
        )
        cls.handler = ContractHandler.objects.create(
            organization=cls.organization, character=cls.main_ownership
        )

    def setUp(self):
        # create contracts
        self.pricing = create_pricing(
            start_location=self.jita, end_location=self.amamake, price_base=500000000
        )
        self.contract = Contract.objects.create(
            handler=self.handler,
            contract_id=1,
            collateral=0,
            date_issued=now(),
            date_expired=now() + dt.timedelta(days=5),
            days_to_complete=3,
            end_location=self.amamake,
            for_corporation=False,
            issuer_corporation=self.corporation,
            issuer=self.character,
            reward=50000000,
            start_location=self.jita,
            status=Contract.Status.OUTSTANDING,
            volume=50000,
            pricing=self.pricing,
        )

    def test_str(self):
        expected = "1: Jita -> Amamake"
        self.assertEqual(str(self.contract), expected)

    def test_repr(self):
        excepted = "Contract(contract_id=1, start_location=Jita, end_location=Amamake)"
        self.assertEqual(repr(self.contract), excepted)

    # def test_hours_issued_2_completed(self):
    #     self.contract.date_completed = self.contract.date_issued + dt.timedelta(hours=9)
    #     self.assertEqual(self.contract.hours_issued_2_completed, 9)
    #     self.contract.date_completed = None
    #     self.assertIsNone(self.contract.hours_issued_2_completed)

    def test_date_latest(self):
        # initial contract only had date_issued
        self.assertEqual(self.contract.date_issued, self.contract.date_latest)

        # adding date_accepted to contract
        self.contract.date_accepted = self.contract.date_issued + dt.timedelta(days=1)
        self.assertEqual(self.contract.date_accepted, self.contract.date_latest)

        # adding date_completed to contract
        self.contract.date_completed = self.contract.date_accepted + dt.timedelta(
            days=1
        )
        self.assertEqual(self.contract.date_completed, self.contract.date_latest)

    @patch(MODULE_PATH + ".FREIGHT_HOURS_UNTIL_STALE_STATUS", 24)
    def test_has_stale_status(self):
        # initial contract only had date_issued
        # date_issued is now
        self.assertFalse(self.contract.has_stale_status)

        # date_issued is 30 hours ago
        self.contract.date_issued = self.contract.date_issued - dt.timedelta(hours=30)
        self.assertTrue(self.contract.has_stale_status)

    def test_acceptor_name(self):
        contract = self.contract
        self.assertIsNone(contract.acceptor_name)

        contract.acceptor_corporation = self.corporation
        self.assertEqual(contract.acceptor_name, self.corporation.corporation_name)

        contract.acceptor = self.character
        self.assertEqual(contract.acceptor_name, self.character.character_name)

    def test_get_issues_list(self):
        self.assertListEqual(self.contract.get_issue_list(), [])
        self.contract.issues = '["one", "two"]'
        self.assertListEqual(self.contract.get_issue_list(), ["one", "two"])

    def test_generate_embed_w_pricing(self):
        x = self.contract._generate_embed()
        self.assertIsInstance(x, Embed)
        self.assertEqual(x.color, Contract.EMBED_COLOR_PASSED)

    def test_generate_embed_w_pricing_issues(self):
        self.contract.issues = ["we have issues"]
        x = self.contract._generate_embed()
        self.assertIsInstance(x, Embed)
        self.assertEqual(x.color, Contract.EMBED_COLOR_FAILED)

    def test_generate_embed_wo_pricing(self):
        self.contract.pricing = None
        x = self.contract._generate_embed()
        self.assertIsInstance(x, Embed)


@patch(MODULE_PATH + ".dhooks_lite.Webhook.execute", spec=True)
class TestContractSendPilotNotification(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler, _ = create_contract_handler_w_contracts()
        cls.contract = Contract.objects.get(contract_id=149409005)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", None)
    def test_aborts_without_webhook_url(self, mock_webhook_execute):
        mock_webhook_execute.return_value.status_ok = True
        self.contract.send_pilot_notification()
        self.assertEqual(mock_webhook_execute.call_count, 0)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", False)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_MENTIONS", None)
    def test_with_branding_and_wo_mentions(self, mock_webhook_execute):
        mock_webhook_execute.return_value.status_ok = True
        self.contract.send_pilot_notification()
        self.assertEqual(mock_webhook_execute.call_count, 1)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", True)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_MENTIONS", None)
    def test_wo_branding_and_wo_mentions(self, mock_webhook_execute):
        mock_webhook_execute.return_value.status_ok = True
        self.contract.send_pilot_notification()
        self.assertEqual(mock_webhook_execute.call_count, 1)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", True)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_MENTIONS", "@here")
    def test_with_branding_and_with_mentions(self, mock_webhook_execute):
        mock_webhook_execute.return_value.status_ok = True
        self.contract.send_pilot_notification()
        self.assertEqual(mock_webhook_execute.call_count, 1)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", True)
    @patch(MODULE_PATH + ".FREIGHT_DISCORD_MENTIONS", True)
    def test_wo_branding_and_with_mentions(self, mock_webhook_execute):
        mock_webhook_execute.return_value.status_ok = True
        self.contract.send_pilot_notification()
        self.assertEqual(mock_webhook_execute.call_count, 1)

    @patch(MODULE_PATH + ".FREIGHT_DISCORD_WEBHOOK_URL", "url")
    def test_log_error_from_execute(self, mock_webhook_execute):
        mock_webhook_execute.return_value.status_ok = False
        mock_webhook_execute.return_value.status_code = 404
        self.contract.send_pilot_notification()
        self.assertEqual(mock_webhook_execute.call_count, 1)


if DiscordUser:

    @patch(MODULE_PATH + ".dhooks_lite.Webhook.execute", spec=True)
    class TestContractSendCustomerNotification(NoSocketsTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            cls.handler, cls.user = create_contract_handler_w_contracts()
            cls.character = cls.user.profile.main_character
            cls.corporation = cls.character.corporation
            cls.contract_1 = Contract.objects.get(contract_id=149409005)
            cls.contract_2 = Contract.objects.get(contract_id=149409019)
            cls.contract_3 = Contract.objects.get(contract_id=149409118)
            cls.jita = Location.objects.get(id=60003760)
            cls.amamake = Location.objects.get(id=1022167642188)
            cls.amarr = Location.objects.get(id=60008494)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_can_send_outstanding(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)
            obj = self.contract_1.customer_notifications.get(
                status=Contract.Status.OUTSTANDING
            )
            self.assertAlmostEqual(
                obj.date_notified, now(), delta=dt.timedelta(seconds=30)
            )

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_can_send_in_progress(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            # when
            self.contract_2.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)
            obj = self.contract_2.customer_notifications.get(
                status=Contract.Status.IN_PROGRESS
            )
            self.assertAlmostEqual(
                obj.date_notified, now(), delta=dt.timedelta(seconds=30)
            )

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_can_send_finished(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            # when
            self.contract_3.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)
            obj = self.contract_3.customer_notifications.get(
                status=Contract.Status.FINISHED
            )
            self.assertAlmostEqual(
                obj.date_notified, now(), delta=dt.timedelta(seconds=30)
            )

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        def test_aborts_without_webhook_url(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MODULE_PATH + ".DiscordUser", None)
        def test_aborts_without_discord(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MODULE_PATH + ".User.objects")
        def test_aborts_without_issuer(self, mock_objects, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            mock_objects.filter.return_value.first.return_value = None
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_DISABLE_BRANDING", True)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_can_send_wo_branding(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_log_error_from_execute(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = False
            mock_webhook_execute.return_value.status_code = 404
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_can_send_without_acceptor(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            my_contract = Contract.objects.create(
                handler=self.handler,
                contract_id=9999,
                collateral=0,
                date_issued=now(),
                date_expired=now() + dt.timedelta(days=5),
                days_to_complete=3,
                end_location=self.amamake,
                for_corporation=False,
                issuer_corporation=self.corporation,
                issuer=self.character,
                reward=50000000,
                start_location=self.jita,
                status=Contract.Status.IN_PROGRESS,
                volume=50000,
            )
            # when
            my_contract.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        def test_can_send_failed(self, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            my_contract = Contract.objects.create(
                handler=self.handler,
                contract_id=9999,
                collateral=0,
                date_issued=now(),
                date_expired=now() + dt.timedelta(days=5),
                days_to_complete=3,
                end_location=self.amamake,
                for_corporation=False,
                issuer_corporation=self.corporation,
                issuer=self.character,
                reward=50000000,
                start_location=self.jita,
                status=Contract.Status.FAILED,
                volume=50000,
            )
            # when
            my_contract.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 1)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", False)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", "url")
        @patch(MODULE_PATH + ".DiscordUser.objects")
        def test_aborts_without_Discord_user(self, mock_objects, mock_webhook_execute):
            # given
            mock_webhook_execute.return_value.status_ok = True
            mock_objects.get.side_effect = DiscordUser.DoesNotExist
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertEqual(mock_webhook_execute.call_count, 0)


if DiscordUser and DiscordClient:

    class TestContractSendCustomerNotificationDiscordProxy(NoSocketsTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            cls.handler, cls.user = create_contract_handler_w_contracts()
            cls.character = cls.user.profile.main_character
            cls.corporation = cls.character.corporation
            cls.contract_1 = Contract.objects.get(contract_id=149409005)
            cls.contract_2 = Contract.objects.get(contract_id=149409019)
            cls.contract_3 = Contract.objects.get(contract_id=149409118)
            cls.jita = Location.objects.get(id=60003760)
            cls.amamake = Location.objects.get(id=1022167642188)
            cls.amarr = Location.objects.get(id=60008494)

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", True)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODULE_PATH + ".DiscordClient", spec=True)
        def test_can_send_status_via_grpc(self, mock_DiscordClient):
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertTrue(
                mock_DiscordClient.return_value.create_direct_message.called
            )
            obj = self.contract_1.customer_notifications.get(
                status=Contract.Status.OUTSTANDING
            )
            self.assertAlmostEqual(
                obj.date_notified, now(), delta=dt.timedelta(seconds=30)
            )

        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", True)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODULE_PATH + ".DiscordClient", spec=True)
        def test_can_handle_grpc_error(self, mock_DiscordClient):
            # given
            my_exception = to_discord_proxy_exception(create_rpc_error())
            my_exception.details = lambda: "{}"
            mock_DiscordClient.return_value.create_direct_message.side_effect = (
                my_exception
            )
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertTrue(
                mock_DiscordClient.return_value.create_direct_message.called
            )

        @patch(MODULE_PATH + ".DISCORDPROXY_HOST", "1.2.3.4")
        @patch(MODULE_PATH + ".DISCORDPROXY_PORT", 56789)
        @patch(MODULE_PATH + ".FREIGHT_DISCORDPROXY_ENABLED", True)
        @patch(MODULE_PATH + ".FREIGHT_DISCORD_CUSTOMERS_WEBHOOK_URL", None)
        @patch(MODULE_PATH + ".DiscordClient", spec=True)
        def test_can_use_custom_config_for_discordproxy(self, mock_DiscordClient):
            # when
            self.contract_1.send_customer_notification()
            # then
            self.assertTrue(
                mock_DiscordClient.return_value.create_direct_message.called
            )
            _, kwargs = mock_DiscordClient.call_args
            self.assertEqual(kwargs["target"], "1.2.3.4:56789")


class TestContractCustomerNotification(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        cls.character = EveCharacter.objects.get(character_id=90000001)
        cls.corporation = EveCorporationInfo.objects.get(
            corporation_id=cls.character.corporation_id
        )
        cls.organization = EveEntity.objects.create(
            id=cls.character.alliance_id,
            category=EveEntity.CATEGORY_ALLIANCE,
            name=cls.character.alliance_name,
        )
        cls.user = User.objects.create_user(
            cls.character.character_name, "abc@example.com", "password"
        )
        cls.main_ownership = CharacterOwnership.objects.create(
            character=cls.character, owner_hash="x1", user=cls.user
        )
        # Locations
        cls.location_1 = Location.objects.create(
            id=60003760,
            name="Jita IV - Moon 4 - Caldari Navy Assembly Plant",
            solar_system_id=30000142,
            type_id=52678,
            category_id=3,
        )
        cls.location_2 = Location.objects.create(
            id=1022167642188,
            name="Amamake - 3 Time Nearly AT Winners",
            solar_system_id=30002537,
            type_id=35834,
            category_id=65,
        )
        cls.handler = ContractHandler.objects.create(
            organization=cls.organization, character=cls.main_ownership
        )

    def setUp(self):
        # create contracts
        self.pricing = create_pricing(
            start_location=self.location_1,
            end_location=self.location_2,
            price_base=500000000,
        )
        self.contract = Contract.objects.create(
            handler=self.handler,
            contract_id=1,
            collateral=0,
            date_issued=now(),
            date_expired=now() + dt.timedelta(days=5),
            days_to_complete=3,
            end_location=self.location_2,
            for_corporation=False,
            issuer_corporation=self.corporation,
            issuer=self.character,
            reward=50000000,
            start_location=self.location_1,
            status=Contract.Status.OUTSTANDING,
            volume=50000,
            pricing=self.pricing,
        )
        self.notification = ContractCustomerNotification.objects.create(
            contract=self.contract,
            status=Contract.Status.IN_PROGRESS,
            date_notified=now(),
        )

    def test_str(self):
        expected = f"{self.contract.contract_id} - in_progress"
        self.assertEqual(str(self.notification), expected)

    def test_repr(self):
        expected = (
            f"ContractCustomerNotification(pk={self.notification.pk}, "
            f"contract_id={self.notification.contract.contract_id}, "
            "status=in_progress)"
        )
        self.assertEqual(repr(self.notification), expected)
