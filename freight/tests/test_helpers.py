from allianceauth.eveonline.models import EveCharacter
from app_utils.testing import NoSocketsTestCase

from freight.helpers import update_or_create_eve_entity_from_evecharacter
from freight.models import EveEntity

from .testdata.helpers import load_eve_characters


class TestCreateEveEntityFromEveCharacter(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_eve_characters()
        cls.character = EveCharacter.objects.get(character_id=90000001)

    def test_can_create_corporation_from_evecharacter(self):
        corporation, _ = update_or_create_eve_entity_from_evecharacter(
            self.character, category=EveEntity.CATEGORY_CORPORATION
        )
        self.assertEqual(int(corporation.id), 92000001)

    def test_can_create_alliance_from_evecharacter(self):
        alliance, _ = update_or_create_eve_entity_from_evecharacter(
            self.character, category=EveEntity.CATEGORY_ALLIANCE
        )
        self.assertEqual(int(alliance.id), 93000001)

    def test_can_create_character_alliance_from_evecharacter(self):
        char2, _ = update_or_create_eve_entity_from_evecharacter(
            self.character, category=EveEntity.CATEGORY_CHARACTER
        )
        self.assertEqual(int(char2.id), 90000001)

    def test_raises_exception_when_trying_to_create_alliance_from_non_member(self):
        character = EveCharacter.objects.get(character_id=90000005)
        with self.assertRaises(ValueError):
            update_or_create_eve_entity_from_evecharacter(
                character, category=EveEntity.CATEGORY_ALLIANCE
            )

    def test_raises_exception_when_trying_to_create_invalid_category_from_evechar(self):
        with self.assertRaises(ValueError):
            update_or_create_eve_entity_from_evecharacter(
                self.character, category="xxx"
            )
