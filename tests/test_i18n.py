from pdf_editor import i18n


def test_supported_locale_formats() -> None:
    assert i18n._language_code("ru_RU.UTF-8") == "ru"
    assert i18n._language_code("fr-FR") == "fr"
    assert i18n._language_code("en_US") == "en"
    assert i18n._language_code("de_DE") is None
    assert i18n._language_code("C") is None


def test_all_languages_have_the_same_messages() -> None:
    expected = set(i18n.TRANSLATIONS["en"])
    for messages in i18n.TRANSLATIONS.values():
        assert set(messages) == expected


def test_message_parameters_are_formatted() -> None:
    previous = i18n.LANGUAGE
    try:
        for language in ("en", "fr", "ru"):
            i18n.LANGUAGE = language
            result = i18n.tr("page_count", current=2, total=7)
            assert "2" in result
            assert "7" in result
    finally:
        i18n.LANGUAGE = previous
