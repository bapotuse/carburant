"""Compresse une serie de captures Playwright en WebP.

Une serie pleine page en PNG a deviceScaleFactor 2 pese une trentaine de megaoctets :
c'est trop pour un depot git, ou chaque version resterait dans l'historique a jamais.
Le WebP de qualite 82 divise le poids par environ dix sans que la difference se voie
sur du texte et des aplats.

Usage : uv run python infra/scripts/compresser_captures.py docs/captures/J0
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

QUALITE = 82


def compresser(repertoire: Path) -> int:
    """Convertit chaque PNG du repertoire en WebP et supprime l'original.

    Renvoie le nombre d'octets economises.
    """
    pngs = sorted(repertoire.glob("*.png"))
    if not pngs:
        print(f"Aucun PNG dans {repertoire}.")
        return 0

    avant = sum(f.stat().st_size for f in pngs)
    for png in pngs:
        with Image.open(png) as image:
            image.save(
                png.with_suffix(".webp"),
                format="WEBP",
                quality=QUALITE,
                method=6,
            )
        png.unlink()

    apres = sum(f.stat().st_size for f in repertoire.glob("*.webp"))
    print(
        f"{len(pngs)} captures : {avant / 1e6:.1f} Mo -> {apres / 1e6:.1f} Mo "
        f"({100 * (1 - apres / avant):.0f} % de moins)"
    )
    return avant - apres


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    repertoire = Path(argv[1])
    if not repertoire.is_dir():
        print(f"Repertoire introuvable : {repertoire}", file=sys.stderr)
        return 1
    compresser(repertoire)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
