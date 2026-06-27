"""
utils/comptage.py — Compte les pages PDF et estime le coût API.

Scanne récursivement un dossier de PDFs, compte le total de pages
et calcule une estimation budgétaire pour l'API Batch Anthropic.

Usage :
  python utils/comptage.py                   ← dossier courant
  python utils/comptage.py ./cours_pcsi
  python utils/comptage.py ./cours_pcsi --model sonnet

Prérequis : pip install pypdf
"""

import argparse
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError:
    print("Erreur : 'pypdf' n'est pas installé.")
    print("Lance : pip install pypdf")
    sys.exit(1)


# ─── Tarifs API Batch Anthropic (Batch = -50% vs synchrone) ─────────────────
# Source : https://www.anthropic.com/pricing (vérifier régulièrement)

PRICING = {
    "sonnet": {
        "label":  "Claude Sonnet 4 (Batch)",
        "input":  1.50,   # $ / MTok
        "output": 7.50,   # $ / MTok
    },
    "haiku": {
        "label":  "Claude Haiku 3.5 (Batch)",
        "input":  0.04,   # $ / MTok
        "output": 0.20,   # $ / MTok
    },
}

# Hypothèses de consommation par page scannée (en tokens)
TOKENS_INPUT_PAR_PAGE  = 1500
TOKENS_OUTPUT_PAR_PAGE = 500


def scanner_pdfs(target_dir: Path, model_key: str = "sonnet"):
    """
    Scanne un dossier de PDFs et affiche un rapport avec estimation de coût.
    """
    if not target_dir.exists():
        print(f"Erreur : Le dossier '{target_dir}' est introuvable.")
        sys.exit(1)

    pricing = PRICING.get(model_key, PRICING["sonnet"])
    print(f"Scan récursif : {target_dir.resolve()}")

    total_pdfs   = 0
    total_pages  = 0
    corrompus    = []

    for fichier in sorted(target_dir.rglob("*.pdf")):
        total_pdfs += 1
        try:
            reader = PdfReader(fichier)
            total_pages += len(reader.pages)
        except (PdfReadError, ValueError, TypeError) as e:
            corrompus.append((fichier.name, str(e)))

    # ── Estimation budgétaire ──
    tokens_input  = total_pages * TOKENS_INPUT_PAR_PAGE
    tokens_output = total_pages * TOKENS_OUTPUT_PAR_PAGE
    cout_input    = (tokens_input  / 1_000_000) * pricing["input"]
    cout_output   = (tokens_output / 1_000_000) * pricing["output"]
    cout_total    = cout_input + cout_output

    print("\n" + "═" * 55)
    print("RAPPORT PDF")
    print("═" * 55)
    print(f"  PDFs valides     : {total_pdfs - len(corrompus)}")
    print(f"  Pages totales    : {total_pages}")
    if corrompus:
        print(f"  PDFs corrompus   : {len(corrompus)}")
        for nom, err in corrompus:
            print(f"    ⚠️  {nom} : {err}")
    print()
    print(f"ESTIMATION COÛT — {pricing['label']}")
    print("─" * 55)
    print(f"  Tokens input  (~{TOKENS_INPUT_PAR_PAGE}/page)  : {tokens_input:>12,} tok")
    print(f"  Tokens output (~{TOKENS_OUTPUT_PAR_PAGE}/page)   : {tokens_output:>12,} tok")
    print(f"  Coût input  ({pricing['input']:.2f} $/MTok)   : ${cout_input:>10.2f}")
    print(f"  Coût output ({pricing['output']:.2f} $/MTok)  : ${cout_output:>10.2f}")
    print(f"  ─────────────────────────────────────────")
    print(f"  COÛT TOTAL ESTIMÉ               : ${cout_total:>10.2f}")
    print("═" * 55)
    print("⚠️  Estimation indicative — varie selon la densité des PDFs.")


def main():
    parser = argparse.ArgumentParser(
        description="Compte les pages PDF et estime le coût API Batch Anthropic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "dossier", nargs="?", default=".",
        help="Dossier à scanner (défaut: répertoire courant)"
    )
    parser.add_argument(
        "--model", choices=list(PRICING.keys()), default="sonnet",
        help="Modèle pour l'estimation tarifaire (défaut: sonnet)"
    )
    args = parser.parse_args()
    scanner_pdfs(Path(args.dossier), model_key=args.model)


if __name__ == "__main__":
    main()
