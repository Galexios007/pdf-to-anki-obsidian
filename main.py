"""
main.py — Orchestrateur du pipeline batch.

Deux phases distinctes :
  Phase 1 — submit(pdf_root) :
    Scanne les PDFs, classifie localement, construit les jobs,
    soumet le batch Anthropic, sauvegarde le batch_id et sort.

  Phase 2 — collect(batch_id) :
    Attend la fin du batch (ou reprend un batch existant),
    puis pour chaque résultat : exporte Anki et applique les actions Obsidian.

Le terminal peut être fermé entre les deux phases.
"""

import logging
from pathlib import Path

from config import MAX_TOKENS_RESPONSE, MAX_TOKENS_LARGE
from batch_client import BatchClient
from batch_state import BatchState
from anki_exporter import AnkiExporter
from classifier import PDFClassifier
from obsidian_manager import ObsidianManager
from pipeline_state import PipelineState
from prompts import COURS_SYSTEM, TD_SYSTEM

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  UTILITAIRES PARTAGÉS
# ─────────────────────────────────────────────

def build_custom_id(pdf_path: Path, subject: str) -> str:
    """
    Construit un custom_id unique et lisible pour l'API Batch.
    Format : <Matiere>__<NomFichierSansExt>__<hash4>
    Limité à 64 caractères (contrainte API).
    Le hash de 4 chars sur le chemin complet garantit l'unicité
    même si deux fichiers ont un nom très similaire après nettoyage.
    """
    import hashlib
    subject_short = subject.replace("é", "e").replace("è", "e").replace("ê", "e") \
                           .replace("à", "a").replace("â", "a").replace("ù", "u") \
                           .replace("û", "u").replace("î", "i").replace("ô", "o") \
                           .replace(" ", "")[:10]
    stem = pdf_path.stem
    # Nettoyage : retire accents et caractères non-ASCII
    import unicodedata
    stem_ascii = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem_clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem_ascii)
    # Hash court sur le chemin absolu pour garantir l'unicité
    path_hash = hashlib.md5(str(pdf_path).encode()).hexdigest()[:6]
    raw = f"{subject_short}__{stem_clean[:44]}__{path_hash}"
    return raw[:64]


def select_prompt(doc_type: str) -> str:
    if doc_type == "cours":
        return COURS_SYSTEM
    elif doc_type in ("td", "ds", "corrige", "tp"):
        return TD_SYSTEM
    else:
        logger.warning(f"doc_type inconnu '{doc_type}', utilisation du prompt TD.")
        return TD_SYSTEM


def validate_extraction(extracted: dict, label: str):
    """Validation minimale du JSON retourné par l'API."""
    if not isinstance(extracted, dict):
        raise ValueError(f"Réponse non-dict pour {label}")
    missing = [k for k in ("metadata", "flashcards", "obsidian_actions") if k not in extracted]
    if missing:
        raise ValueError(f"Clés manquantes {missing} pour {label}")
    if not isinstance(extracted["flashcards"], list):
        raise ValueError(f"'flashcards' n'est pas une liste pour {label}")
    if not isinstance(extracted["obsidian_actions"], list):
        raise ValueError(f"'obsidian_actions' n'est pas une liste pour {label}")


# ─────────────────────────────────────────────
#  PIPELINE
# ─────────────────────────────────────────────

class Pipeline:
    def __init__(self):
        logger.info("Initialisation du pipeline...")
        self.batch_client = BatchClient()
        self.classifier   = PDFClassifier()   # heuristique locale uniquement
        self.obsidian     = ObsidianManager()
        self.anki         = AnkiExporter()
        self.state        = PipelineState()
        self.batch_state  = BatchState()
        logger.info("Pipeline prêt.")

    # ═══════════════════════════════════════════════
    #  PHASE 1 : SOUMISSION
    # ═══════════════════════════════════════════════

    def submit(
        self,
        pdf_root: Path,
        subject_filter: str = None,
        doc_type_filter: str = None,
        limit: int = None,
    ) -> str:
        """
        Scanne pdf_root, classifie les PDFs localement,
        soumet un batch Anthropic et retourne le batch_id.
        """
        # ── Scan et classification locale ──
        logger.info(f"Scan de {pdf_root}...")
        scan = self.classifier.scan_directory(pdf_root)
        self.classifier.print_scan_summary(scan)

        files = scan["in_scope"]

        if subject_filter:
            files = scan["by_subject"].get(subject_filter, [])
            logger.info(f"Filtre matière : {subject_filter} → {len(files)} fichiers")

        if doc_type_filter:
            files = [
                f for f in files
                if self.classifier.classify(f).get("doc_type") == doc_type_filter
            ]
            logger.info(f"Filtre type : {doc_type_filter} → {len(files)} fichiers")

        # Exclut les déjà traités avec succès
        files = [f for f in files if not self.state.is_processed(f)]
        logger.info(f"Non encore traités : {len(files)} fichiers")

        if limit:
            files = files[:limit]
            logger.info(f"Limite appliquée : {limit} fichiers")

        if not files:
            logger.info("Aucun fichier à soumettre.")
            return ""

        # ── Construction des jobs ──
        jobs = []
        for pdf_path in files:
            clf      = self.classifier.classify(pdf_path)
            subject  = clf["subject"]
            doc_type = clf["doc_type"]
            chapter  = clf["chapter"]

            jobs.append({
                "custom_id":     build_custom_id(pdf_path, subject),
                "pdf_path":      pdf_path,
                "subject":       subject,
                "doc_type":      doc_type,
                "chapter":       chapter,
                "system_prompt": select_prompt(doc_type),
            })

        # ── Soumission ──
        logger.info(f"\nSoumission de {len(jobs)} requêtes au batch API...")
        batch_id = self.batch_client.submit_extraction_batch(jobs)

        # ── Persistance ──
        self.batch_state.register_batch(batch_id, "extraction", jobs)

        print(f"\n{'═'*60}")
        print(f"✅ BATCH SOUMIS : {batch_id}")
        print(f"   {len(jobs)} fichiers en cours de traitement.")
        print(f"   Durée estimée : 15 min à 2h selon la charge Anthropic.")
        print(f"\n   Commandes utiles :")
        print(f"   python run_batch.py --status {batch_id}")
        print(f"   python run_batch.py --collect {batch_id}")
        print(f"{'═'*60}\n")

        return batch_id

    # ═══════════════════════════════════════════════
    #  PHASE 2 : COLLECTE
    # ═══════════════════════════════════════════════

    def collect(self, batch_id: str, wait: bool = True) -> dict:
        """
        Attend la fin du batch puis traite chaque résultat :
        - Export CSV Anki
        - Actions Obsidian (new_node / direct_append)
        - Checkpoint par fichier

        wait=False : retourne immédiatement si le batch n'est pas terminé.
        """
        # ── Vérification statut si non-bloquant ──
        if not wait:
            status_info = self.batch_client.get_batch_status(batch_id)
            if status_info["status"] != "ended":
                logger.info(
                    f"Batch {batch_id} pas encore terminé "
                    f"(statut: {status_info['status']})."
                )
                return {"status": "pending"}

        # ── Attente + collecte API ──
        raw_results = self.batch_client.wait_and_collect(batch_id)
        self.batch_state.mark_batch_ended(batch_id)

        # ── Métadonnées des jobs ──
        jobs_meta = self.batch_state.get_all_jobs(batch_id)

        # ── Traitement résultat par résultat ──
        stats = {
            "success": 0, "error": 0,
            "total_flashcards": 0, "total_nodes": 0,
        }

        for custom_id, result in raw_results.items():
            job_meta = jobs_meta.get(custom_id, {})
            pdf_path = Path(job_meta.get("pdf_path", custom_id))
            subject  = job_meta.get("subject", "Mathématiques")
            doc_type = job_meta.get("doc_type", "cours")
            chapter  = job_meta.get("chapter", "")

            if result["status"] != "success":
                error_msg  = result.get("error", "Erreur API inconnue")
                truncated  = result.get("truncated", False)
                logger.error(f"❌ {pdf_path.name}: {error_msg[:120]}")
                self.state.mark_error(pdf_path, error_msg, truncated=truncated)
                stats["error"] += 1
                continue

            extracted = result["data"]

            try:
                validate_extraction(extracted, custom_id)

                # Assure la cohérence du subject
                extracted.setdefault("metadata", {})
                if not extracted["metadata"].get("subject"):
                    extracted["metadata"]["subject"] = subject

                # ── Export Anki ──
                flashcards = extracted.get("flashcards", [])
                anki_stats = self.anki.add_flashcards(flashcards, subject)
                fc_added   = anki_stats["added"]
                stats["total_flashcards"] += fc_added

                # ── Actions Obsidian ──
                actions  = extracted.get("obsidian_actions", [])
                n_nodes  = 0
                if actions:
                    obs_stats = self.obsidian.apply_actions(
                        actions=actions,
                        subject=subject,
                        source_file=pdf_path.name,
                    )
                    n_nodes = obs_stats["created"] + obs_stats["appended"]
                    stats["total_nodes"] += n_nodes

                # ── Index Obsidian ──
                self.obsidian.create_subject_index(subject, chapter, pdf_path.name)

                # ── Checkpoint ──
                self.state.mark_success(
                    pdf_path=pdf_path,
                    subject=subject,
                    doc_type=doc_type,
                    chapter=chapter,
                    flashcards_count=fc_added,
                    nodes_count=n_nodes,
                )
                self.batch_state.mark_job_collected(batch_id, custom_id)
                stats["success"] += 1
                logger.info(
                    f"✅ {pdf_path.name:<40} "
                    f"{fc_added:>3} cartes | {n_nodes:>2} nœuds"
                )

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(f"❌ Traitement de {custom_id}: {error_msg}")
                self.state.mark_error(pdf_path, error_msg)
                stats["error"] += 1

        # ── Flush CSV Anki ──
        self.anki.flush_to_csv()

        # ── Deck urgence automatique ──
        urgency_path = self.anki.generate_urgency_deck(min_priority=4)

        # ── Marque le batch collecté ──
        self.batch_state.mark_batch_collected(batch_id)

        # ── Résumé console ──
        print(f"\n{'═'*60}")
        print(f"COLLECTE TERMINÉE — {batch_id}")
        print(f"{'═'*60}")
        print(f"  ✅ Succès          : {stats['success']}")
        print(f"  ❌ Erreurs         : {stats['error']}")
        print(f"  🃏 Flashcards Anki : {stats['total_flashcards']}")
        print(f"  🔗 Nœuds Obsidian  : {stats['total_nodes']}")
        print(f"  🔴 Deck urgence    : {urgency_path}")
        print(f"{'═'*60}\n")

        if stats["error"] > 0:
            print(f"  ⚠️  {stats['error']} erreur(s) — relance avec :")
            print(f"  python run_batch.py --retry-errors\n")

        self.print_final_stats()
        return stats

    # ═══════════════════════════════════════════════
    #  STATUT
    # ═══════════════════════════════════════════════

    def status(self, batch_id: str):
        info      = self.batch_client.get_batch_status(batch_id)
        meta      = self.batch_state.get_batch_info(batch_id)
        jobs      = meta.get("jobs", {})
        collected = sum(1 for j in jobs.values() if j.get("collected"))

        print(f"\n{'═'*55}")
        print(f"STATUT : {batch_id}")
        print(f"{'═'*55}")
        print(f"  Statut API   : {info['status']}")
        print(f"  Processing   : {info['counts']['processing']}")
        print(f"  Succeeded    : {info['counts']['succeeded']}")
        print(f"  Errored      : {info['counts']['errored']}")
        print(f"  Collectés    : {collected}/{len(jobs)}")
        if meta.get("submitted_at"):
            print(f"  Soumis le    : {meta['submitted_at'][:19]}")
        print(f"{'═'*55}")

        if info["status"] == "ended":
            print(f"\n→ Prêt : python run_batch.py --collect {batch_id}\n")
        else:
            print(f"\n→ Pas encore terminé. Réessaie dans quelques minutes.\n")

    # ─────────────────────────────────────────────
    #  RETRY DES ERREURS
    # ─────────────────────────────────────────────

    def submit_retry(self, pdf_root: Path) -> str:
        """
        Soumet un nouveau batch pour les PDFs en erreur dans le checkpoint.
        Les erreurs de troncature JSON sont soumises avec MAX_TOKENS_LARGE.
        """
        error_entries = self.state.get_errors_with_details()
        if not error_entries:
            logger.info("Aucune erreur à retraiter.")
            return ""

        logger.info(f"Retry de {len(error_entries)} fichiers en erreur...")
        self.state.reset_errors()

        jobs_normal  = []  # max_tokens standard
        jobs_large   = []  # max_tokens augmenté (troncatures)

        for entry in error_entries:
            pdf_path = Path(entry["path"])
            if not pdf_path.exists():
                logger.warning(f"  ⚠️  Introuvable : {pdf_path}")
                continue
            clf = self.classifier.classify(pdf_path)
            job = {
                "custom_id":     build_custom_id(pdf_path, clf["subject"]),
                "pdf_path":      pdf_path,
                "subject":       clf["subject"],
                "doc_type":      clf["doc_type"],
                "chapter":       clf["chapter"],
                "system_prompt": select_prompt(clf["doc_type"]),
            }
            if entry.get("truncated"):
                jobs_large.append(job)
                logger.info(f"  📄 [LARGE] {pdf_path.name}")
            else:
                jobs_normal.append(job)
                logger.info(f"  📄 [NORMAL] {pdf_path.name}")

        submitted = []

        if jobs_normal:
            bid = self.batch_client.submit_extraction_batch(
                jobs_normal, max_tokens=MAX_TOKENS_RESPONSE
            )
            self.batch_state.register_batch(bid, "extraction_retry", jobs_normal)
            submitted.append((bid, len(jobs_normal), "standard"))

        if jobs_large:
            bid = self.batch_client.submit_extraction_batch(
                jobs_large, max_tokens=MAX_TOKENS_LARGE
            )
            self.batch_state.register_batch(bid, "extraction_retry_large", jobs_large)
            submitted.append((bid, len(jobs_large), "large tokens"))

        print(f"\n{'═'*60}")
        for bid, count, mode in submitted:
            print(f"✅ Batch retry soumis ({mode}) : {bid} ({count} fichiers)")
            print(f"   python run_batch.py --collect {bid}")
        print(f"{'═'*60}\n")

        return submitted[0][0] if submitted else ""

    # ─────────────────────────────────────────────
    #  STATS FINALES
    # ─────────────────────────────────────────────

    def generate_urgency_deck(self, min_priority: int = 4) -> Path:
        return self.anki.generate_urgency_deck(min_priority)

    def print_final_stats(self):
        self.state.print_summary()
        vault_stats = self.obsidian.get_vault_stats()
        anki_counts = self.anki.get_total_cards_on_disk()

        print("VAULT OBSIDIAN")
        print("═" * 50)
        for folder, count in vault_stats["by_folder"].items():
            print(f"  {folder:<25} : {count:>4} nœuds")
        print(f"  {'TOTAL':<25} : {vault_stats['total_nodes']:>4} nœuds")
        print()
        print("CARTES ANKI SUR DISQUE")
        print("═" * 50)
        for subject, count in sorted(anki_counts.items()):
            print(f"  {subject:<20} : {count:>5} cartes")
        print("═" * 50 + "\n")
