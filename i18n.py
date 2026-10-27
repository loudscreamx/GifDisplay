"""Языки интерфейса. Исходный текст в коде русский и служит ключом: tr("Старт") возвращает перевод на выбранный язык.
Переводы лежат в locales/<код>.json как {"русский текст": "перевод"}; нет перевода — показывается русский.
Новый язык добавляется файлом locales/xx.json и строкой в LANGS."""
import ctypes
import json
import os

# код: название языка на нём самом (показывается в списке выбора)
LANGS = {
    "ru": "Русский", "en": "English", "uk": "Українська", "de": "Deutsch", "fr": "Français", "es": "Español",
    "it": "Italiano", "pt": "Português", "pl": "Polski", "tr": "Türkçe", "zh": "简体中文", "ja": "日本語", "ko": "한국어",
}
# основной язык Windows (LANGID & 0x3ff) -> код
_PRIMARY = {0x19: "ru", 0x09: "en", 0x22: "uk", 0x07: "de", 0x0c: "fr", 0x0a: "es", 0x10: "it", 0x16: "pt",
            0x15: "pl", 0x1f: "tr", 0x04: "zh", 0x11: "ja", 0x12: "ko"}
# языки, на которых подписи виджетов можно рисовать пиксельным шрифтом из программы (латиница и кириллица)
_ON_SCREEN_OK = {"ru", "en", "uk", "de", "fr", "es", "it", "pt", "pl", "tr"}

_catalog = {}
_lang = "ru"


def detect():
    """Язык Windows, если он есть в списке; иначе английский."""
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "en"
    return _PRIMARY.get(lid & 0x3ff, "en")


def set_language(code, locales_dir):
    global _catalog, _lang
    _lang = code if code in LANGS else "en"
    _catalog = {}
    if _lang != "ru":
        try:
            with open(os.path.join(locales_dir, f"{_lang}.json"), encoding="utf-8") as f:
                _catalog = json.load(f)
        except (OSError, ValueError):
            _catalog = {}


def language():
    return _lang


def tr(text, **kw):
    """Перевод строки; подстановки {имя} делаются после перевода: порядок слов в языках разный."""
    out = _catalog.get(text, text)
    return out.format(**kw) if kw else out


def screen_tr(text):
    """Подписи и единицы на самом экране: для языков вне латиницы/кириллицы берётся английский вариант (ключ «screen:…»)."""
    if _lang in _ON_SCREEN_OK:
        return _catalog.get(text, text)
    return _catalog.get("screen:" + text, _catalog.get(text, text))


def up(text):
    """Заглавные буквы по правилам языка: в турецком i -> İ, ı -> I (обычный upper() даёт I для обеих)."""
    if _lang == "tr":
        text = text.replace("i", "İ").replace("ı", "I")
    return text.upper()
