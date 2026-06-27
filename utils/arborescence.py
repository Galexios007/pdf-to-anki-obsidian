"""
utils/arborescence.py — Affiche l'arborescence d'un dossier en ASCII.

Usage :
  python utils/arborescence.py                  ← dossier courant
  python utils/arborescence.py ./cours_pcsi
  python utils/arborescence.py --depth 2        ← limite la profondeur
"""

import argparse
from pathlib import Path


def afficher_arborescence(chemin_dossier: Path, prefixe: str = "", max_depth: int = -1, _depth: int = 0):
    """
    Affiche récursivement l'arborescence d'un dossier en ASCII art.

    Args:
        chemin_dossier: Dossier à afficher.
        prefixe: Préfixe d'indentation (usage interne récursif).
        max_depth: Profondeur max (-1 = illimitée).
        _depth: Profondeur courante (usage interne récursif).
    """
    if not chemin_dossier.exists() or not chemin_dossier.is_dir():
        print(f"Erreur : '{chemin_dossier}' est introuvable ou n'est pas un dossier.")
        return

    if max_depth != -1 and _depth >= max_depth:
        return

    # Dossiers d'abord, puis fichiers, chacun trié alphabétiquement
    contenu = sorted(chemin_dossier.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    pointeurs = ["├── "] * (len(contenu) - 1) + ["└── "] if contenu else []

    for pointeur, element in zip(pointeurs, contenu):
        print(f"{prefixe}{pointeur}{element.name}")
        if element.is_dir():
            extension = "│   " if pointeur == "├── " else "    "
            afficher_arborescence(element, prefixe + extension, max_depth, _depth + 1)


def main():
    parser = argparse.ArgumentParser(
        description="Affiche l'arborescence d'un dossier en ASCII.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "dossier", nargs="?", default=".",
        help="Dossier cible (défaut: répertoire courant)"
    )
    parser.add_argument(
        "--depth", "-d", type=int, default=-1,
        help="Profondeur maximale d'affichage (-1 = illimitée)"
    )
    args = parser.parse_args()

    cible = Path(args.dossier).resolve()
    print(f"[{cible.name}]")
    afficher_arborescence(cible, max_depth=args.depth)


if __name__ == "__main__":
    main()
