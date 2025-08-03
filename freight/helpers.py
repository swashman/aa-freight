"""Helpers for Freight."""

from typing import Any, Tuple

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo


def update_or_create_eve_entity_from_evecharacter(
    character: EveCharacter, category: str
) -> Tuple[Any, bool]:
    """Update or create an EveEntity object from an EveCharacter object."""
    from .models import EveEntity

    if category == EveEntity.CATEGORY_ALLIANCE:
        if not character.alliance_id:
            raise ValueError("character is not an alliance member")
        return EveEntity.objects.update_or_create(
            id=character.alliance_id,
            defaults={
                "name": character.alliance_name,
                "category": EveEntity.CATEGORY_ALLIANCE,
            },
        )

    if category == EveEntity.CATEGORY_CORPORATION:
        return EveEntity.objects.update_or_create(
            id=character.corporation_id,
            defaults={
                "name": character.corporation_name,
                "category": EveEntity.CATEGORY_CORPORATION,
            },
        )

    if category == EveEntity.CATEGORY_CHARACTER:
        return EveEntity.objects.update_or_create(
            id=character.character_id,
            defaults={
                "name": character.character_name,
                "category": EveEntity.CATEGORY_CHARACTER,
            },
        )

    raise ValueError(f"Invalid category: f{category}")


def get_or_create_eve_character(character_id: int) -> Tuple[Any, bool]:
    """Get or create EveCharacter object."""
    try:
        return EveCharacter.objects.get(character_id=character_id), False
    except EveCharacter.DoesNotExist:
        return EveCharacter.objects.create_character(character_id=character_id), True


def get_or_create_eve_corporation_info(corporation_id: int) -> Tuple[Any, bool]:
    """Get or create EveCorporationInfo object."""
    try:
        return (
            EveCorporationInfo.objects.get(corporation_id=corporation_id),
            False,
        )
    except EveCorporationInfo.DoesNotExist:
        return (
            EveCorporationInfo.objects.create_corporation(corp_id=corporation_id),
            True,
        )
