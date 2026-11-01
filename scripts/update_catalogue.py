"""Import explicite du catalogue tiers depuis sa source GitHub (pas de copie embarquée)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from skylanders_catalogue import download_catalog, CATALOG_FILE, REPOSITORY  # noqa: E402

if __name__ == "__main__":
    print(f"Source : {REPOSITORY}")
    print("Téléchargement d'un tableau d'identifiants : aucun programme externe exécuté.")
    try:
        n = download_catalog()
    except Exception as exc:
        print(f"Échec de synchronisation : {type(exc).__name__}: {exc}")
        raise SystemExit(1)
    print(f"{n} entrées enregistrées localement : {CATALOG_FILE}")
