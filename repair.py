"""
repair.py — Utilitaire de nettoyage post-génération du vault Obsidian.

Corrige les espaces parasites dans les délimiteurs LaTeX inline :
  $ expression $  →  $expression$

Ces espaces peuvent être insérés par le modèle malgré les consignes.
Ce script est non-destructif : il ne touche qu'aux espaces en bordure
de blocs inline (entre $ et le contenu), jamais aux blocs $$ display.

Usage :
  python repair.py                          ← utilise OBSIDIAN_VAULT de config.py
  python repair.py --vault ./mon_vault
  python repair.py --vault ./mon_vault --dry-run   ← aperçu sans écriture
"""

import argparse
import re
import time
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
#  LOGIQUE DE NETTOYAGE
# ─────────────────────────────────────────────────────────────────────────────

# Capture tout ce qui est entre $ simples (ne touche pas aux $$ display)
_INLINE_LATEX = re.compile(r"(?<!\$)\$([^\$]+)\$(?!\$)")


def _clean_inline_spaces(match: re.Match) -> str:
    """Supprime les espaces en début et fin de formule inline."""
    return f"${match.group(1).strip()}$"


def patch_vault(vault_path: Path, dry_run: bool = False) -> int:
    """
    Parcourt tous les fichiers .md du vault et nettoie les espaces LaTeX.

    Retourne le nombre de fichiers modifiés.
    """
    if not vault_path.exists():
        raise FileNotFoundError(f"Vault introuvable : {vault_path.resolve()}")

    mode = "DRY-RUN" if dry_run else "ÉCRITURE"
    print(f"🚀 Nettoyage LaTeX [{mode}] : {vault_path.resolve()}")

    files_modified = 0
    start = time.time()

    for md_file in sorted(vault_path.rglob("*.md")):
        original = md_file.read_text(encoding="utf-8")
        patched  = _INLINE_LATEX.sub(_clean_inline_spaces, original)

        if patched != original:
            files_modified += 1
            print(f"  [{'SIMULÉ' if dry_run else 'CORRIGÉ'}] {md_file.relative_to(vault_path)}")
            if not dry_run:
                md_file.write_text(patched, encoding="utf-8")

    elapsed = time.time() - start
    status  = "Simulation terminée" if dry_run else "Terminé"
    print(f"\n✅ {status} — {files_modified} fichier(s) {'à corriger' if dry_run else 'corrigés'} "
          f"en {elapsed:.3f}s")
    return files_modified


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    from config import OBSIDIAN_VAULT
    parser = argparse.ArgumentParser(
        description="Nettoie les espaces parasites dans les formules LaTeX inline du vault Obsidian.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--vault", type=Path, default=OBSIDIAN_VAULT,
        help=f"Chemin du vault Obsidian (défaut: {OBSIDIAN_VAULT})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche les fichiers qui seraient modifiés sans rien écrire"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        patch_vault(args.vault, dry_run=args.dry_run)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        raise SystemExit(1)
