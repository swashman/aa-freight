from unittest.mock import patch

from django.test import override_settings

from app_utils.testing import NoSocketsTestCase

from freight.tasks import (
    run_contracts_sync,
    send_contract_notifications,
    update_contracts_esi,
    update_contracts_pricing,
    update_location,
    update_locations,
)

from .testdata.helpers import create_contract_handler_w_contracts

MODULE_PATH = "freight.tasks"


class TestUpdateContractsEsi(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler, cls.user = create_contract_handler_w_contracts()

    @patch(MODULE_PATH + ".ContractHandler.update_contracts_esi")
    def test_exception_when_no_contract_handler(self, mock_update_contracts_esi):
        self.handler.delete()
        with self.assertRaises(RuntimeError):
            update_contracts_esi()

    @patch(MODULE_PATH + ".ContractHandler.update_contracts_esi")
    def test_minimal_run(self, mock_update_contracts_esi):
        update_contracts_esi()
        self.assertTrue(mock_update_contracts_esi.called)


@patch(MODULE_PATH + ".Contract.objects.send_notifications")
class TestSendContractNotifications(NoSocketsTestCase):
    def test_normal_run(self, mock_send_notifications):
        send_contract_notifications()
        self.assertTrue(mock_send_notifications.called)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestRunContractsSync(NoSocketsTestCase):
    @patch(MODULE_PATH + ".update_contracts_esi")
    @patch(MODULE_PATH + ".send_contract_notifications")
    def test_normal_run(
        self, mock_send_contract_notifications, mock_update_contracts_esi
    ):
        run_contracts_sync()
        self.assertTrue(mock_update_contracts_esi.si.called)
        self.assertTrue(mock_send_contract_notifications.si.called)


class TestUpdateContractsPricing(NoSocketsTestCase):
    def test_normal_run(self):
        # given
        create_contract_handler_w_contracts([149409016])
        # when
        result = update_contracts_pricing()
        # then
        self.assertEqual(result, 1)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@patch(MODULE_PATH + ".ContractHandler.token")
@patch(MODULE_PATH + ".Location.objects.update_or_create_esi")
class TestUpdateLocation(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_contract_handler_w_contracts()

    def test_normal_run(self, mock_update_or_create_from_esi, mock_token):
        update_location(1022167642188)
        self.assertTrue(mock_token.called)
        self.assertTrue(mock_update_or_create_from_esi.called)

    def test_update_locations(self, mock_update_or_create_from_esi, mock_token):
        update_locations([1022167642188, 60003760])
        self.assertEqual(mock_update_or_create_from_esi.call_count, 2)
        call_args_1, call_args_2 = mock_update_or_create_from_esi.call_args_list
        _, kwargs_1 = call_args_1
        _, kwargs_2 = call_args_2
        self.assertEqual(kwargs_1["location_id"], 1022167642188)
        self.assertEqual(kwargs_2["location_id"], 60003760)
