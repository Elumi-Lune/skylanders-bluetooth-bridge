# -*- coding: utf-8 -*-
"""Catalogue de figurines / pièges / objets, conservé sur disque.

Source des paires ID : https://github.com/Texthead1/Skylander-IDs
Les données du dépôt peuvent contenir erreurs, prototypes et objets non commercialisés.
Aucun code téléchargé n'est exécuté : seul un Markdown est lu et validé.
"""
from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

SOURCE = "https://raw.githubusercontent.com/Texthead1/Skylander-IDs/main/README.md"
REPOSITORY = "https://github.com/Texthead1/Skylander-IDs"
HERE = Path(__file__).resolve().parent
CATALOG_FILE = HERE / "catalogue_local.json"
STARTER_FILE = HERE / "catalogue_secours.json"
ROW = re.compile(r"^\s*(.*?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*$")


def classify(section: str, char_id: int, name: str) -> str:
    if section == "Toys For Bob Items/Traps":
        if 210 <= char_id <= 220:
            return "Piège Traptanium"
        if char_id == 235:
            return "Coffre"
        return "Objet magique"
    if "Expansions" in section:
        return "Extension / niveau"
    if "Vehicles" in section or "Vehicles" in name or "Vehicle" in name:
        return "Véhicule / objet"
    if "Trophies" in section:
        return "Trophée"
    if "DEBUG" in section or "Test Characters" in section or "Template" in section:
        return "Test / prototype"
    if section == "Skylanders 2016" and "Creation Crystal" in name:
        return "Cristal de création"
    if "Items" in section or "Battle Pieces" in section:
        return "Objet / accessoire"
    return "Figurine"


def parse_readme(markdown: str) -> list[dict]:
    """Rows from named sections, exactly as reported by source README."""
    section = ""
    rows: list[dict] = []
    for line in markdown.splitlines():
        if line.startswith("### "):
            section = line[4:].strip()
            continue
        m = ROW.match(line)
        if not m or not section:
            continue
        name = m.group(1).strip()
        if not name or name.lower() in ("skylander", "characterid"):
            continue
        char_id, variant = int(m.group(2)), int(m.group(3))
        if not (0 <= char_id <= 65535 and 0 <= variant <= 65535 and len(name) <= 150):
            continue
        rows.append({"name": name, "character_id": char_id, "variant_id": variant,
                     "section": section, "type": classify(section, char_id, name)})
    return rows


def verify_complete(rows: list[dict]) -> None:
    # Bail out on an unexpected change, GitHub error page, or partial download.
    if len(rows) < 350:
        raise ValueError(f"Catalogue incomplet ({len(rows)} entrées ; minimum 350)")
    pairs = {(r['character_id'], r['variant_id']) for r in rows}
    for pair in ((470, 12288), (462, 12288), (113, 4096), (208, 4614), (211, 12289)):
        if pair not in pairs:
            raise ValueError(f"Catalogue incohérent : entrée {pair} absente")


def write_catalog(rows: list[dict], source: str, path: Path = CATALOG_FILE) -> None:
    item = {"source": source, "saved_at": datetime.now(timezone.utc).isoformat(),
            "complete": source == SOURCE, "entries": rows}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(item, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    tmp.replace(path)


def load_catalog() -> dict:
    for path in (CATALOG_FILE, STARTER_FILE):
        try:
            data = json.loads(path.read_text(encoding='utf8'))
            if isinstance(data.get('entries'), list) and data['entries']:
                return data
        except (OSError, ValueError, TypeError):
            pass
    return {"entries": [], "source": "aucune", "complete": False}


def download_catalog() -> int:
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "Skylanders-Bluetooth-Bridge/1.2"})
    with urllib.request.urlopen(req, timeout=16) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Réponse trop volumineuse")
    rows = parse_readme(raw.decode('utf-8-sig'))
    verify_complete(rows)
    write_catalog(rows, SOURCE)
    return len(rows)


def import_readme(path: str) -> int:
    raw = Path(path).read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("README trop volumineux")
    rows = parse_readme(raw.decode('utf-8-sig'))
    verify_complete(rows)
    write_catalog(rows, SOURCE)  # user-selected local copy of the source README
    return len(rows)


class Catalogue:
    def __init__(self, obj: dict):
        self.rows = list(obj.get('entries') or [])
        self.complete = bool(obj.get('complete'))
        self.source = obj.get('source', '')
        self.by_pair: dict[tuple[int, int], list[dict]] = {}
        self.by_id: dict[int, list[dict]] = {}
        for r in self.rows:
            try:
                char_id, variant = int(r['character_id']), int(r['variant_id'])
                self.by_pair.setdefault((char_id, variant), []).append(r)
                self.by_id.setdefault(char_id, []).append(r)
            except (KeyError, TypeError, ValueError):
                continue

    def identify(self, char_id: int, variant: int, slot: int = 0) -> tuple[str, str, bool]:
        exact = self.by_pair.get((char_id, variant), [])
        if exact:
            names = list(dict.fromkeys(r['name'] for r in exact))
            types = list(dict.fromkeys(r['type'] for r in exact))
            name = names[0] if len(names) == 1 else ' / '.join(names[:3])
            return name, ', '.join(types), True
        candidates = self.by_id.get(char_id, [])
        if candidates:
            # Never silently claim an exact variant match.
            base = candidates[0]['name']
            return f"{base} — variante {variant} non référencée", candidates[0]['type'], False
        category = "Piège ?" if slot == 2 else "Objet ?"
        return f"Inconnu (ID {char_id}, variante {variant})", category, False
