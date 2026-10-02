from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path


PERSON_PRESETS = ("signature", "initials", "approved")


@dataclass
class PersonPresets:
    id: str
    name: str
    images: dict[str, Path] = field(default_factory=dict)


@dataclass
class PresetLibrary:
    people: list[PersonPresets]
    selected_person_id: str

    @property
    def current_person(self) -> PersonPresets:
        return next(
            (person for person in self.people if person.id == self.selected_person_id),
            self.people[0],
        )

    def add_person(self, name: str) -> PersonPresets:
        clean_name = name.strip()
        if not clean_name or any(p.name.casefold() == clean_name.casefold() for p in self.people):
            raise ValueError("Person name must be nonempty and unique")
        person = PersonPresets(uuid.uuid4().hex, clean_name)
        self.people.append(person)
        self.selected_person_id = person.id
        return person

    def rename_person(self, person_id: str, name: str) -> None:
        clean_name = name.strip()
        if not clean_name or any(
            p.id != person_id and p.name.casefold() == clean_name.casefold()
            for p in self.people
        ):
            raise ValueError("Person name must be nonempty and unique")
        person = next(p for p in self.people if p.id == person_id)
        person.name = clean_name

    def remove_person(self, person_id: str) -> None:
        if len(self.people) == 1:
            raise ValueError("At least one person is required")
        self.people = [person for person in self.people if person.id != person_id]
        if self.selected_person_id == person_id:
            self.selected_person_id = self.people[0].id


def _existing_path(value: object) -> Path | None:
    if not isinstance(value, str):
        return None
    path = Path(value)
    return path if path.is_file() else None


def load_preset_library(path: Path, default_name: str) -> PresetLibrary:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    if raw.get("version") == 2 and isinstance(raw.get("people"), list):
        people = []
        seen_ids = set()
        seen_names = set()
        for entry in raw["people"]:
            if not isinstance(entry, dict):
                continue
            person_id = entry.get("id")
            name = entry.get("name")
            if not isinstance(person_id, str) or not person_id or not isinstance(name, str) or not name.strip():
                continue
            if person_id in seen_ids or name.casefold() in seen_names:
                continue
            seen_ids.add(person_id)
            seen_names.add(name.casefold())
            raw_images = entry.get("images")
            if not isinstance(raw_images, dict):
                raw_images = {}
            images = {
                key: found
                for key in PERSON_PRESETS
                if (found := _existing_path(raw_images.get(key))) is not None
            }
            people.append(PersonPresets(person_id, name, images))
        if people:
            selected = raw.get("selected_person_id")
            if selected not in seen_ids:
                selected = people[0].id
            return PresetLibrary(people, selected)

    images = {
        key: found
        for key in PERSON_PRESETS
        if (found := _existing_path(raw.get(key))) is not None
    }
    person = PersonPresets("default", default_name, images)
    return PresetLibrary([person], person.id)


def save_preset_library(path: Path, library: PresetLibrary) -> None:
    data = {
        "version": 2,
        "selected_person_id": library.selected_person_id,
        "people": [
            {
                "id": person.id,
                "name": person.name,
                "images": {key: str(image) for key, image in person.images.items()},
            }
            for person in library.people
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
