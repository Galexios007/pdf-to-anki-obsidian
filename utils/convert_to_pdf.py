"""
utils/convert_to_pdf.py — Convertit des fichiers bureautiques en PDF via LibreOffice.

Prérequis : LibreOffice installé et dans le PATH.
  - macOS   : brew install --cask libreoffice
  - Ubuntu  : sudo apt install libreoffice
  - Windows : télécharger sur https://www.libreoffice.org

Formats supportés : .docx, .doc, .pptx, .ppt, .odt, .txt

Usage :
  python utils/convert_to_pdf.py                     ← dossier courant
  python utils/convert_to_pdf.py ./cours_pcsi
  python utils/convert_to_pdf.py ./cours_pcsi --count-only
"""

import argparse
import subprocess
import sys
from pathlib import Path

EXTENSIONS_CIBLES = {".docx", ".doc", ".pptx", ".ppt", ".odt", ".txt"}


def convert_to_pdf(target_dir: Path, dry_run: bool = False) -> int:
    """
    Convertit tous les fichiers bureautiques d'un dossier en PDF.

    Returns:
        Nombre de fichiers convertis (ou qui seraient convertis en dry_run).
    """
    if not target_dir.exists():
        print(f"Erreur : Le dossier '{target_dir}' n'existe pas.")
        sys.exit(1)

    mode = "DRY-RUN" if dry_run else "CONVERSION"
    print(f"LibreOffice → PDF [{mode}] : {target_dir.resolve()}")

    convertis = 0
    for fichier in sorted(target_dir.iterdir()):
        if fichier.is_file() and fichier.suffix.lower() in EXTENSIONS_CIBLES:
            pdf_cible = fichier.with_suffix(".pdf")
            if pdf_cible.exists():
                print(f"  [IGNORÉ — existe déjà] {fichier.name}")
                continue
            print(f"  [{'SIMULÉ' if dry_run else 'CONVERSION'}] {fichier.name}")
            if not dry_run:
                try:
                    subprocess.run(
                        [
                            "libreoffice", "--headless",
                            "--convert-to", "pdf",
                            "--outdir", str(target_dir),
                            str(fichier),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True,
                    )
                    convertis += 1
                except FileNotFoundError:
                    print("❌ LibreOffice introuvable dans le PATH.")
                    print("   Installe-le ou ajoute-le au PATH.")
                    sys.exit(1)
                except subprocess.CalledProcessError as e:
                    print(f"  ⚠️  Échec conversion {fichier.name} : {e}")
            else:
                convertis += 1

    total_pdfs = len(list(target_dir.glob("*.pdf")))
    print(f"\n{'─' * 45}")
    print(f"Fichiers convertis : {convertis}")
    print(f"Total PDFs présents : {total_pdfs}")
    return convertis


def main():
    parser = argparse.ArgumentParser(
        description="Convertit des fichiers bureautiques en PDF via LibreOffice.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "dossier", nargs="?", default=".",
        help="Dossier à traiter (défaut: répertoire courant)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche ce qui serait converti sans rien faire"
    )
    args = parser.parse_args()
    convert_to_pdf(Path(args.dossier), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
