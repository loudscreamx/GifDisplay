"""Текст виджета «Часы»: время (24/12 ч, с секундами или без) и дата в нескольких форматах.
Названия месяцев и дней — на языке интерфейса, а для китайского/японского/корейского английские: пиксельный шрифт экрана
иероглифы не рисует."""
import time

import i18n

# код языка: (месяцы по порядку, дни недели с понедельника)
NAMES = {
    "en": ("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), "Mon Tue Wed Thu Fri Sat Sun".split()),
    "ru": ("янв фев мар апр мая июн июл авг сен окт ноя дек".split(), "пн вт ср чт пт сб вс".split()),
    "uk": ("січ лют бер кві тра чер лип сер вер жов лис гру".split(), "пн вт ср чт пт сб нд".split()),
    "de": ("Jan Feb Mär Apr Mai Jun Jul Aug Sep Okt Nov Dez".split(), "Mo Di Mi Do Fr Sa So".split()),
    "fr": ("janv. févr. mars avr. mai juin juil. août sept. oct. nov. déc.".split(), "lun. mar. mer. jeu. ven. sam. dim.".split()),
    "es": ("ene feb mar abr may jun jul ago sep oct nov dic".split(), "lun mar mié jue vie sáb dom".split()),
    "it": ("gen feb mar apr mag giu lug ago set ott nov dic".split(), "lun mar mer gio ven sab dom".split()),
    "pt": ("jan fev mar abr mai jun jul ago set out nov dez".split(), "seg ter qua qui sex sáb dom".split()),
    "pl": ("sty lut mar kwi maj cze lip sie wrz paź lis gru".split(), "pn wt śr cz pt sb nd".split()),
    "tr": ("Oca Şub Mar Nis May Haz Tem Ağu Eyl Eki Kas Ara".split(), "Pzt Sal Çar Per Cum Cmt Paz".split()),
}

# ключ формата -> шаблон; в списке окна показывается пример на сегодняшней дате
DATE_FORMATS = {
    "dmy": "{d:02}.{m:02}.{Y}",
    "dmy2": "{d:02}.{m:02}.{y:02}",
    "ymd": "{Y}-{m:02}-{d:02}",
    "mdy": "{m:02}/{d:02}/{Y}",
    "dm": "{d:02}.{m:02}",
    "dmon": "{d} {mon}",
    "wdmon": "{wd}, {d} {mon}",
    "dmonY": "{d} {mon} {Y}",
}


def time_text(w, t=None):
    t = t or time.localtime()
    sec = f":{t.tm_sec:02}" if w.get("clock_sec") else ""
    if w.get("clock_12h"):
        return f"{t.tm_hour % 12 or 12}:{t.tm_min:02}{sec} {'AM' if t.tm_hour < 12 else 'PM'}"
    return f"{t.tm_hour:02}:{t.tm_min:02}{sec}"


def date_text(fmt, t=None):
    t = t or time.localtime()
    months, days = NAMES.get(i18n.language(), NAMES["en"])
    return DATE_FORMATS.get(fmt, DATE_FORMATS["dmy"]).format(
        d=t.tm_mday, m=t.tm_mon, Y=t.tm_year, y=t.tm_year % 100, mon=months[t.tm_mon - 1], wd=days[t.tm_wday])
