from http import HTTPStatus
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase

from app_utils.testing import create_user_from_evecharacter

from freight.admin import ContractAdmin
from freight.models import Contract

from ..tests.testdata.factories import (
    create_contract,
    create_contract_handler,
    create_pricing,
)
from .testdata.helpers import create_entities_from_characters, create_locations

MODULE_PATH = "freight.admin"


class MockRequest(object):
    def __init__(self, user=None):
        self.user = user


class TestContractAdmin(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_locations()
        create_entities_from_characters()
        cls.modeladmin = ContractAdmin(model=Contract, admin_site=AdminSite())
        cls.user = User.objects.create_superuser("Clark Kent")
        _, character_ownership = create_user_from_evecharacter(90000001)
        cls.handler = create_contract_handler(character=character_ownership)
        cls.contract = create_contract(handler=cls.handler)

    @patch(MODULE_PATH + ".ContractAdmin.message_user", spec=True)
    @patch(MODULE_PATH + ".Contract.send_pilot_notification")
    def test_should_send_pilots_notification(
        self, mock_send_pilot_notification, mock_message_user
    ):
        # given
        obj_qs = Contract.objects.filter(pk=self.contract.pk)
        # when
        self.modeladmin.send_pilots_notification(MockRequest(self.user), obj_qs)
        # then
        self.assertEqual(mock_send_pilot_notification.call_count, 1)
        self.assertTrue(mock_message_user.called)

    @patch(MODULE_PATH + ".ContractAdmin.message_user", spec=True)
    @patch(MODULE_PATH + ".Contract.send_customer_notification")
    def test_should_send_customer_notification(
        self, mock_send_customer_notification, mock_message_user
    ):
        # given
        obj_qs = Contract.objects.filter(pk=self.contract.pk)
        # when
        self.modeladmin.send_customer_notification(MockRequest(self.user), obj_qs)
        # then
        self.assertEqual(mock_send_customer_notification.call_count, 1)
        self.assertTrue(mock_message_user.called)

    def test_should_open_list(self):
        # given
        self.client.force_login(self.user)
        # when
        response = self.client.get("/admin/freight/contract/")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)


class TestPricingAdmin(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_superuser("Clark Kent")
        create_locations()
        create_pricing(
            start_location_id=60003760,
            end_location_id=1022167642188,
            price_base=100000000,
        )

    def test_should_open_list(self):
        # given
        self.client.force_login(self.user)
        # when
        response = self.client.get("/admin/freight/pricing/")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)
