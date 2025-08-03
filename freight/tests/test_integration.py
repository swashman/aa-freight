import re

from django.test import override_settings
from django.urls import reverse
from django_webtest import WebTest

from allianceauth.tests.auth_utils import AuthUtils
from app_utils.testing import NoSocketsTestCase

from freight.models import Contract, Location, Pricing

from .testdata.factories import create_pricing
from .testdata.helpers import create_contract_handler_w_contracts

_RE_COMBINE_WHITESPACE = re.compile(r"\s+")


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestCalculatorWeb(WebTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _, cls.user = create_contract_handler_w_contracts()
        cls.user = AuthUtils.add_permission_to_user_by_name(
            "freight.use_calculator", cls.user
        )

        jita = Location.objects.get(id=60003760)
        amamake = Location.objects.get(id=1022167642188)
        amarr = Location.objects.get(id=60008494)
        cls.pricing_1 = create_pricing(
            start_location=jita,
            end_location=amamake,
            price_base=50000000,
            price_per_volume=150,
            price_per_collateral_percent=2,
            collateral_max=5000000000,
            volume_max=320000,
            days_to_complete=3,
            days_to_expire=7,
        )
        cls.pricing_2 = create_pricing(
            start_location=jita, end_location=amarr, price_base=100000000
        )
        Contract.objects.update_pricing()

    def _calculate_price(self, pricing: Pricing, volume=None, collateral=None) -> tuple:
        """Performs a full price query with the calculator

        returns tuple of price_str, form, request
        """
        self.app.set_user(self.user)
        # load page and get our form
        response = self.app.get(reverse("freight:calculator"))
        form = response.forms["form_calculator"]

        # enter these values into form
        form["pricing"] = pricing.pk
        if volume:
            form["volume"] = volume
        if collateral:
            form["collateral"] = collateral

        # submit form and get response
        response = form.submit()
        form = response.forms["form_calculator"]

        # extract the price string
        price_str = response.html.find(id="text_price_2").string
        price_str = _RE_COMBINE_WHITESPACE.sub(
            " ", price_str
        ).strip()  # remove whitespaces to one
        return price_str, form, response

    def test_can_calculate_pricing_1(self):
        price_str, _, _ = self._calculate_price(self.pricing_1, 50000, 2000000000)
        expected = "98,000,000 ISK"
        self.assertEqual(price_str, expected)

    def test_can_calculate_pricing_2(self):
        price_str, _, _ = self._calculate_price(self.pricing_2)
        expected = "100,000,000 ISK"
        self.assertEqual(price_str, expected)

    def test_aborts_on_missing_collateral(self):
        price_str, form, _ = self._calculate_price(self.pricing_1, 50000)
        expected = "- ISK"
        self.assertEqual(price_str, expected)
        self.assertIn("Issues", form.text)
        self.assertIn("collateral is required", form.text)

    def test_aborts_on_missing_volume(self):
        price_str, form, _ = self._calculate_price(self.pricing_1, None, 500000)
        expected = "- ISK"
        self.assertEqual(price_str, expected)
        self.assertIn("Issues", form.text)
        self.assertIn("volume is required", form.text)

    def test_aborts_on_too_high_volume(self):
        price_str, form, _ = self._calculate_price(self.pricing_1, 400000, 500000)
        expected = "- ISK"
        self.assertEqual(price_str, expected)
        self.assertIn("Issues", form.text)
        self.assertIn("exceeds the maximum allowed volume", form.text)

    def test_aborts_on_too_high_collateral(self):
        price_str, form, _ = self._calculate_price(self.pricing_1, 40000, 6000000000)
        expected = "- ISK"
        self.assertEqual(price_str, expected)
        self.assertIn("Issues", form.text)
        self.assertIn("exceeds the maximum allowed collateral", form.text)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestCalculatorWeb2(WebTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _, cls.user = create_contract_handler_w_contracts()
        cls.user = AuthUtils.add_permission_to_user_by_name(
            "freight.use_calculator", cls.user
        )

    def test_can_handle_no_pricing(self):
        # given
        self.app.set_user(self.user)
        # when
        response = self.app.get(reverse("freight:calculator"))
        # then
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please define a pricing/route!", response.text)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestPricingSave(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _, cls.user = create_contract_handler_w_contracts([149409016])

    def test_pricing_save_handler(self):
        # given
        jita = Location.objects.get(id=60003760)
        amamake = Location.objects.get(id=1022167642188)
        # when
        pricing = Pricing.objects.create(
            start_location=jita, end_location=amamake, price_base=500000000
        )
        # then
        contract_1 = Contract.objects.get(contract_id=149409016)
        self.assertEqual(contract_1.pricing, pricing)
