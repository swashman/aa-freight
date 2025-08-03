from unittest.mock import patch

from django.core.exceptions import ValidationError

from app_utils.testing import NoSocketsTestCase

from freight.models import ContractHandler, Location, Pricing

from ..testdata.factories import create_pricing
from ..testdata.helpers import create_contract_handler_w_contracts, create_locations

MODULE_PATH = "freight.models.routes"


class TestLocation(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.jita, cls.amamake, _ = create_locations()

    def test_str(self):
        self.assertEqual(
            str(self.jita.name), "Jita IV - Moon 4 - Caldari Navy Assembly Plant"
        )

    def test_repr(self):
        expected = (
            f"Location(pk={self.amamake.pk}, "
            "name='Amamake - 3 Time Nearly AT "
            "Winners')"
        )
        self.assertEqual(repr(self.amamake), expected)

    def test_category(self):
        self.assertEqual(self.jita.category, Location.Category.STATION_ID)

    def test_solar_system_name_station(self):
        self.assertEqual(self.jita.solar_system_name, "Jita")

    def test_solar_system_name_structure(self):
        self.assertEqual(self.amamake.solar_system_name, "Amamake")

    def test_location_name_station(self):
        self.assertEqual(self.jita.location_name, "Caldari Navy Assembly Plant")

    def test_location_name_structure(self):
        self.assertEqual(self.amamake.location_name, "3 Time Nearly AT Winners")


class TestPricing(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler, _ = create_contract_handler_w_contracts()
        cls.jita = Location.objects.get(id=60003760)
        cls.amamake = Location.objects.get(id=1022167642188)
        cls.amarr = Location.objects.get(id=60008494)

    @patch(MODULE_PATH + ".FREIGHT_FULL_ROUTE_NAMES", False)
    def test_str(self):
        p = Pricing(
            start_location=self.jita, end_location=self.amamake, price_base=50000000
        )
        expected = "Jita <-> Amamake"
        self.assertEqual(str(p), expected)

    def test_repr(self):
        p = Pricing(
            start_location=self.jita, end_location=self.amamake, price_base=50000000
        )
        expected = (
            f"Pricing(pk={p.pk}, "
            "name='Jita IV - Moon 4 - Caldari Navy Assembly Plant "
            "<-> Amamake - 3 Time Nearly AT Winners')"
        )
        self.assertEqual(repr(p), expected)

    @patch(MODULE_PATH + ".FREIGHT_FULL_ROUTE_NAMES", False)
    def test_name_from_settings_short(self):
        p = Pricing(
            start_location=self.jita, end_location=self.amamake, price_base=50000000
        )
        self.assertEqual(p.name, "Jita <-> Amamake")

    def test_name_short(self):
        p = Pricing(
            start_location=self.jita, end_location=self.amamake, price_base=50000000
        )
        self.assertEqual(p.name_short, "Jita <-> Amamake")

    @patch(MODULE_PATH + ".FREIGHT_FULL_ROUTE_NAMES", True)
    def test_name_from_settings_full(self):
        p = Pricing(
            start_location=self.jita, end_location=self.amamake, price_base=50000000
        )
        self.assertEqual(
            p.name,
            "Jita IV - Moon 4 - Caldari Navy Assembly Plant <-> "
            "Amamake - 3 Time Nearly AT Winners",
        )

    def test_name_full(self):
        p = Pricing(
            start_location=self.jita, end_location=self.amamake, price_base=50000000
        )
        self.assertEqual(
            p.name_full,
            "Jita IV - Moon 4 - Caldari Navy Assembly Plant <-> "
            "Amamake - 3 Time Nearly AT Winners",
        )

    def test_create_pricings(self):
        # first pricing
        create_pricing(
            start_location=self.jita,
            end_location=self.amamake,
            price_base=500000000,
        )
        # pricing with different route
        create_pricing(
            start_location=self.amarr,
            end_location=self.amamake,
            price_base=250000000,
        )
        # pricing with reverse route then pricing 1
        create_pricing(
            start_location=self.amamake,
            end_location=self.jita,
            price_base=350000000,
        )

    def test_create_pricing_no_2nd_bidirectional_allowed(self):
        create_pricing(
            start_location=self.jita,
            end_location=self.amamake,
            price_base=500000000,
            is_bidirectional=True,
        )
        p = create_pricing(
            start_location=self.amamake,
            end_location=self.jita,
            price_base=500000000,
            is_bidirectional=True,
        )
        with self.assertRaises(ValidationError):
            p.clean()

    def test_create_pricing_no_2nd_unidirectional_allowed(self):
        create_pricing(
            start_location=self.jita,
            end_location=self.amamake,
            price_base=500000000,
            is_bidirectional=True,
        )
        p = create_pricing(
            start_location=self.amamake,
            end_location=self.jita,
            price_base=500000000,
            is_bidirectional=False,
        )
        p.clean()
        # this test case has been temporary inverted to allow users
        # to migrate their pricings
        """
        with self.assertRaises(ValidationError):
            p.clean()
        """

    def test_create_pricing_2nd_must_be_unidirectional_a(self):
        create_pricing(
            start_location=self.jita,
            end_location=self.amamake,
            price_base=500000000,
            is_bidirectional=False,
        )
        p = create_pricing(
            start_location=self.amamake,
            end_location=self.jita,
            price_base=500000000,
            is_bidirectional=True,
        )
        with self.assertRaises(ValidationError):
            p.clean()

    def test_create_pricing_2nd_ok_when_unidirectional(self):
        create_pricing(
            start_location=self.jita,
            end_location=self.amamake,
            price_base=500000000,
            is_bidirectional=False,
        )
        p = create_pricing(
            start_location=self.amamake,
            end_location=self.jita,
            price_base=500000000,
            is_bidirectional=False,
        )
        p.clean()

    def test_name_uni_directional(self):
        p = Pricing(
            start_location=self.jita,
            end_location=self.amamake,
            price_base=50000000,
            is_bidirectional=False,
        )
        self.assertEqual(p.name, "Jita -> Amamake")

    def test_get_calculated_price(self):
        p = Pricing()
        p.price_per_volume = 50
        self.assertEqual(p.get_calculated_price(10, 0), 500)

        p = Pricing()
        p.price_per_collateral_percent = 2
        self.assertEqual(p.get_calculated_price(10, 1000), 20)

        p = Pricing()
        p.price_per_volume = 50
        p.price_per_collateral_percent = 2
        self.assertEqual(p.get_calculated_price(10, 1000), 520)

        p = Pricing()
        p.price_base = 20
        self.assertEqual(p.get_calculated_price(10, 1000), 20)

        p = Pricing()
        p.price_min = 1000
        self.assertEqual(p.get_calculated_price(10, 1000), 1000)

        p = Pricing()
        p.price_base = 20
        p.price_per_volume = 50
        self.assertEqual(p.get_calculated_price(10, 1000), 520)

        p = Pricing()
        p.price_base = 20
        p.price_per_volume = 50
        p.price_min = 1000
        self.assertEqual(p.get_calculated_price(10, 1000), 1000)

        p = Pricing()
        p.price_base = 20
        p.price_per_volume = 50
        p.price_per_collateral_percent = 2
        p.price_min = 500
        self.assertEqual(p.get_calculated_price(10, 1000), 540)

        with self.assertRaises(ValueError):
            p.get_calculated_price(-5, 0)

        with self.assertRaises(ValueError):
            p.get_calculated_price(50, -5)

        p = Pricing()
        p.price_base = 0
        self.assertEqual(p.get_calculated_price(None, None), 0)

        p = Pricing()
        p.price_per_volume = 50
        self.assertEqual(p.get_calculated_price(10, None), 500)

        p = Pricing()
        p.price_per_collateral_percent = 2
        self.assertEqual(p.get_calculated_price(None, 100), 2)

    def test_get_contract_pricing_errors(self):
        p = Pricing()
        p.price_base = 50
        self.assertIsNone(p.get_contract_price_check_issues(10, 20, 50))

        p = Pricing()
        p.price_base = 500
        p.volume_max = 300
        self.assertIsNotNone(p.get_contract_price_check_issues(350, 1000))

        p = Pricing()
        p.price_base = 500
        p.volume_min = 100
        self.assertIsNotNone(p.get_contract_price_check_issues(50, 1000))

        p = Pricing()
        p.price_base = 500
        p.collateral_max = 300
        self.assertIsNotNone(p.get_contract_price_check_issues(350, 1000))

        p = Pricing()
        p.price_base = 500
        p.collateral_min = 300
        self.assertIsNotNone(p.get_contract_price_check_issues(350, 200))

        p = Pricing()
        p.price_base = 500
        self.assertIsNotNone(p.get_contract_price_check_issues(350, 200, 400))

        p = Pricing()
        p.price_base = 500
        with self.assertRaises(ValueError):
            p.get_contract_price_check_issues(-5, 0)

        with self.assertRaises(ValueError):
            p.get_contract_price_check_issues(50, -5)

        with self.assertRaises(ValueError):
            p.get_contract_price_check_issues(50, 5, -5)

    def test_collateral_min_allows_zero(self):
        p = Pricing()
        p.price_base = 500
        p.collateral_min = 0
        self.assertIsNone(p.get_contract_price_check_issues(350, 0))

    def test_collateral_min_allows_none(self):
        p = Pricing()
        p.price_base = 500
        self.assertIsNone(p.get_contract_price_check_issues(350, 0))

    def test_zero_collateral_allowed_for_collateral_pricing(self):
        p = Pricing()
        p.collateral_min = 0
        p.price_base = 500
        p.price_per_collateral_percent = 2

        self.assertIsNone(p.get_contract_price_check_issues(350, 0))
        self.assertEqual(p.get_calculated_price(350, 0), 500)

    def test_requires_volume(self):
        self.assertTrue(Pricing(price_per_volume=10000).requires_volume())
        self.assertTrue(Pricing(volume_min=10000).requires_volume())
        self.assertTrue(
            Pricing(price_per_volume=10000, volume_min=10000).requires_volume()
        )
        self.assertFalse(Pricing().requires_volume())

    def test_requires_collateral(self):
        self.assertTrue(Pricing(price_per_collateral_percent=2).requires_collateral())
        self.assertTrue(Pricing(collateral_min=50000000).requires_collateral())
        self.assertTrue(
            Pricing(
                price_per_collateral_percent=2, collateral_min=50000000
            ).requires_collateral()
        )
        self.assertFalse(Pricing().requires_collateral())

    def test_clean_force_error(self):
        p = Pricing()
        with self.assertRaises(ValidationError):
            p.clean()

    def test_is_fix_price(self):
        self.assertTrue(Pricing(price_base=50000000).is_fix_price())
        self.assertFalse(
            Pricing(price_base=50000000, price_min=40000000).is_fix_price()
        )
        self.assertFalse(
            Pricing(price_base=50000000, price_per_volume=400).is_fix_price()
        )
        self.assertFalse(
            Pricing(price_base=50000000, price_per_collateral_percent=2).is_fix_price()
        )
        self.assertFalse(Pricing().is_fix_price())

    def test_clean_normal(self):
        p = Pricing(price_base=50000000)
        p.clean()


class TestPricingPricePerVolumeModifier(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler, _ = create_contract_handler_w_contracts()

    def test_return_none_if_not_set(self):
        p = Pricing()
        self.assertIsNone(p.price_per_volume_modifier())
        self.assertIsNone(p.price_per_volume_eff())

    def test_is_ignored_in_price_calculation_if_not_set(self):
        p = Pricing()
        p.price_per_volume = 50
        self.assertEqual(p.get_calculated_price(10, None), 500)

    def test_returns_none_if_not_set_in_pricing(self):
        self.handler.price_per_volume_modifier = 10
        self.handler.save()
        p = Pricing()
        p.price_per_volume = 50

        self.assertIsNone(p.price_per_volume_modifier())

    def test_can_calculate_with_plus_value(self):
        self.handler.price_per_volume_modifier = 10
        self.handler.save()

        p = Pricing()
        p.price_per_volume = 50
        p.use_price_per_volume_modifier = True

        self.assertEqual(p.price_per_volume_eff(), 55)
        self.assertEqual(p.get_calculated_price(10, None), 550)

    def test_can_calculate_with_negative_value(self):
        self.handler.price_per_volume_modifier = -10
        self.handler.save()

        p = Pricing()
        p.price_per_volume = 50
        p.use_price_per_volume_modifier = True

        self.assertEqual(p.price_per_volume_eff(), 45)
        self.assertEqual(p.get_calculated_price(10, None), 450)

    def test_calculated_price_is_never_negative(self):
        self.handler.price_per_volume_modifier = -200
        self.handler.save()

        p = Pricing()
        p.price_per_volume = 50
        p.use_price_per_volume_modifier = True

        self.assertEqual(p.price_per_volume_eff(), 0)

    def test_returns_none_if_not_set_for_handler(self):
        p = Pricing(price_base=50000000)
        p.use_price_per_volume_modifier = True
        self.assertIsNone(p.price_per_volume_modifier())

    def test_returns_none_if_no_handler_defined(self):
        ContractHandler.objects.all().delete()
        p = Pricing(price_base=50000000)
        p.use_price_per_volume_modifier = True
        self.assertIsNone(p.price_per_volume_modifier())
