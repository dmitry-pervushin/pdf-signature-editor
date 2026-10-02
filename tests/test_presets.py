import json

import pytest

from pdf_editor.presets import load_preset_library, save_preset_library


def test_old_presets_migrate_to_default_person(tmp_path):
    signature = tmp_path / "signature.png"
    initials = tmp_path / "initials.png"
    approved = tmp_path / "approved.png"
    for path in (signature, initials, approved):
        path.write_bytes(b"image")
    config = tmp_path / "presets.json"
    config.write_text(json.dumps({
        "signature": str(signature), "initials": str(initials), "approved": str(approved),
    }))

    library = load_preset_library(config, "Основной")
    assert library.current_person.name == "Основной"
    assert library.current_person.images == {
        "signature": signature, "initials": initials, "approved": approved,
    }


def test_each_person_has_independent_presets_and_selection_persists(tmp_path):
    config = tmp_path / "presets.json"
    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    first_image.write_bytes(b"image")
    second_image.write_bytes(b"image")

    library = load_preset_library(config, "Основной")
    first = library.current_person
    first.images["signature"] = first_image
    second = library.add_person("Дмитрий")
    second.images["signature"] = second_image
    second.images["approved"] = second_image
    save_preset_library(config, library)

    restored = load_preset_library(config, "Основной")
    assert restored.current_person.name == "Дмитрий"
    assert restored.current_person.images["signature"] == second_image
    assert restored.current_person.images["approved"] == second_image
    assert restored.people[0].images["signature"] == first_image
    assert "approved" not in restored.people[0].images

    with pytest.raises(ValueError):
        restored.add_person("дмитрий")
    restored.remove_person(second.id)
    assert restored.current_person.id == first.id
