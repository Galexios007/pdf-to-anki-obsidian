"""
run_batch.py — Point d'entrée CLI du pipeline batch.

WORKFLOW EN DEUX PHASES :

  Phase 1 — Soumettre :
    python run_batch.py --submit
    python run_batch.py --submit --subject Mathématiques
    python run_batch.py --submit --subject SI
    python run_batch.py --submit --limit 5            ← test sur 5 fichiers

  Phase 2 — Récupérer (15 min à 2h plus tard) :
    python run_batch.py --collect msgbatch_xxx
    python run_batch.py --status  msgbatch_xxx        ← vérifie sans attendre

  Autres commandes :
    python run_batch.py --dry-run                     ← scan sans rien soumettre
    python run_batch.py --retry-errors                ← resoumet les fichiers en erreur
    python run_batch.py --list-batches                ← liste tous les batches
    python run_batch.py --urgency-only                ← génère le deck urgence
    python run_batch.py --urgency-only --min-priority 5
"""

import argparse
import logging
import sys
from pathlib import Path

from config import PDF_ROOT, LOG_DIR, SUBJECTS_CONFIG
from classifier import PDFClassifier
from main import Pipeline


# ─────────────────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    log_file = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return log_file


# ─────────────────────────────────────────────────────────────────────────────
#  ARGUMENTS
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline PDF → Anki + Obsidian (PCSI) — Mode Batch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── Actions principales (mutuellement exclusives) ──
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--submit", action="store_true",
        help="Phase 1 : soumet les PDFs au batch API"
    )
    actions.add_argument(
        "--collect", metavar="BATCH_ID",
        help="Phase 2 : récupère et traite les résultats d'un batch"
    )
    actions.add_argument(
        "--status", metavar="BATCH_ID",
        help="Vérifie le statut d'un batch sans attendre"
    )
    actions.add_argument(
        "--dry-run", action="store_true",
        help="Scan et classification uniquement, sans appel API"
    )
    actions.add_argument(
        "--retry-errors", action="store_true",
        help="Resoumet un nouveau batch pour les fichiers en erreur"
    )
    actions.add_argument(
        "--list-batches", action="store_true",
        help="Liste tous les batches enregistrés"
    )
    actions.add_argument(
        "--urgency-only", action="store_true",
        help="Génère uniquement le deck Anki urgence"
    )

    # ── Filtres pour --submit ──
    parser.add_argument(
        "--subject",
        choices=list(SUBJECTS_CONFIG.keys()),  # Mathématiques, Physique, Chimie, Informatique, SI
        help="Traite uniquement cette matière (avec --submit)"
    )
    parser.add_argument(
        "--doc-type",
        choices=["cours", "td", "ds", "corrige", "tp"],
        dest="doc_type",
        help="Traite uniquement ce type de document (avec --submit)"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limite le nombre de fichiers (avec --submit, utile pour les tests)"
    )
    parser.add_argument(
        "--pdf-root", type=Path, default=PDF_ROOT,
        help=f"Dossier racine des PDFs (défaut: {PDF_ROOT})"
    )

    # ── Options pour --collect ──
    parser.add_argument(
        "--no-wait", action="store_true",
        help="Avec --collect : retourne immédiatement si le batch n'est pas fini"
    )

    # ── Options pour --urgency-only ──
    parser.add_argument(
        "--min-priority", type=int, default=4, choices=[1, 2, 3, 4, 5],
        help="Priorité minimale pour le deck urgence (défaut: 4)"
    )

    # ── Divers ──
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Logs détaillés (DEBUG)"
    )

    return parser.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run(args):
    log_file = setup_logging(args.verbose)
    logger   = logging.getLogger("run_batch")
    logger.info(f"Logs : {log_file}")

    # ── DRY RUN ──
    if args.dry_run:
        if not args.pdf_root.exists():
            print(f"❌ Dossier introuvable : {args.pdf_root}")
            sys.exit(1)
        scanner = PDFClassifier()
        scan    = scanner.scan_directory(args.pdf_root)
        scanner.print_scan_summary(scan)
        print("Fichiers qui seraient soumis (20 premiers) :")
        for pdf in scan["in_scope"][:20]:
            clf = scanner.classify(pdf)
            print(
                f"  [{clf['doc_type']:<8}] [{clf['subject']:<15}] "
                f"{pdf.name}"
            )
        if len(scan["in_scope"]) > 20:
            print(f"  ... et {len(scan['in_scope']) - 20} autres")
        print(f"\nTotal à traiter : {len(scan['in_scope'])} fichiers")
        return

    # ── LIST BATCHES ──
    if args.list_batches:
        from batch_state import BatchState
        BatchState().print_summary()
        return

    # ── URGENCY ONLY ──
    if args.urgency_only:
        pipeline = Pipeline()
        deck = pipeline.generate_urgency_deck(args.min_priority)
        print(f"\n✅ Deck urgence P{args.min_priority}+ : {deck}\n")
        return

    # ── SUBMIT ──
    if args.submit:
        if not args.pdf_root.exists():
            print(f"❌ Dossier introuvable : {args.pdf_root}")
            print(f"   Configure PDF_ROOT dans config.py ou utilise --pdf-root")
            sys.exit(1)

        pipeline = Pipeline()
        batch_id = pipeline.submit(
            pdf_root        = args.pdf_root,
            subject_filter  = args.subject,
            doc_type_filter = args.doc_type,
            limit           = args.limit,
        )
        if not batch_id:
            print("Aucun fichier à soumettre.")
        return

    # ── COLLECT ──
    if args.collect:
        pipeline = Pipeline()
        pipeline.collect(
            batch_id = args.collect,
            wait     = not args.no_wait,
        )
        return

    # ── STATUS ──
    if args.status:
        pipeline = Pipeline()
        pipeline.status(args.status)
        return

    # ── RETRY ERRORS ──
    if args.retry_errors:
        if not args.pdf_root.exists():
            print(f"❌ Dossier introuvable : {args.pdf_root}")
            sys.exit(1)
        pipeline = Pipeline()
        batch_id = pipeline.submit_retry(args.pdf_root)
        if batch_id:
            print(f"Batch retry soumis : {batch_id}")
        return


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()
    run(args)
