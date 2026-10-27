"""Пресеты как отдельные файлы: presets/<название>.json рядом с программой.

Файл можно скопировать другому человеку или положить в папку presets, и пресет появится в списке. Если рядом с
программой писать нельзя (например, она в Program Files), папка создаётся в настройках пользователя.
"""
import glob
import json
import os
import re


class PresetStore:
    def __init__(self, app_dir, fallback_dir, user_first=False):
        self.app_dir = app_dir
        near, user = os.path.join(app_dir, "presets"), os.path.join(fallback_dir, "presets")
        self.dir = self._pick_dir(*((user, near) if user_first else (near, user)))

    @staticmethod
    def _pick_dir(primary, fallback):
        for d in (primary, fallback):
            try:
                os.makedirs(d, exist_ok=True)
                probe = os.path.join(d, ".write_test")
                with open(probe, "w") as f:
                    f.write("")
                os.remove(probe)
                return d
            except OSError:
                continue
        return primary

    def path(self, name):
        safe = re.sub(r'[\\/:*?"<>|]', "_", name).strip(" .") or "preset"
        return os.path.join(self.dir, safe + ".json")

    def _to_file(self, data):
        data = dict(data)
        media = data.get("media")
        if media:  # внутри папки программы путь записываем относительным: пресет переносится вместе с папкой
            try:
                if os.path.commonpath([os.path.abspath(media), self.app_dir]) == self.app_dir:
                    data["media"] = os.path.relpath(media, self.app_dir)
            except ValueError:  # другой диск
                pass
        return data

    def _from_file(self, data):
        media = data.get("media")
        if media and not os.path.isabs(media):
            data["media"] = os.path.join(self.app_dir, media)
        return data

    def load_all(self):
        """{название: данные} по всем читаемым файлам; повреждённые файлы пропускаются."""
        out = {}
        for p in sorted(glob.glob(os.path.join(self.dir, "*.json"))):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                out[data.get("name") or os.path.splitext(os.path.basename(p))[0]] = self._from_file(data)
        return out

    def save(self, name, data):
        """Записывает пресет файлом (сначала во временный, потом заменой: так не получится наполовину записанный)."""
        data = dict(self._to_file(data), name=name)
        p = self.path(name)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    def delete(self, name):
        try:
            os.remove(self.path(name))
        except FileNotFoundError:
            pass
