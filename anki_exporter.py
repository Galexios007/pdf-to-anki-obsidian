"""
anki_exporter.py — Export des flashcards vers des fichiers CSV importables dans Anki.

Format CSV Anki :
- Séparateur : tabulation (\t)
- Colonnes : Question, Réponse, Tags, Source, Priorité, Deck
- Encodage : UTF-8 avec BOM (requis par Anki sur Windows)
- Un fichier CSV par matière, accumulé au fil du traitement

Import dans Anki :
1. Fichier → Importer
2. Sélectionner le CSV
3. Type de note : "Basic" (ou "Basic (et carte inversée)" selon préférence)
4. Champ 1 → Question, Champ 2 → Réponse
5. Cocher "Autoriser les doublons HTML" pour le LaTeX
"""

import csv
import logging
from pathlib import Path
from typing import Optional

from config import ANKI_OUTPUT, SUBJECTS_CONFIG, PRIORITY_LABELS

logger = logging.getLogger(__name__)

# En-têtes du CSV Anki
ANKI_HEADERS = ["Question", "Réponse", "Tags", "Source", "Priorité", "Deck", "PrioritéNum"]


class AnkiExporter:
    def __init__(self, output_dir: Path = ANKI_OUTPUT):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Buffer en mémoire : subject → list of rows
        self._buffers: dict[str, list[dict]] = {}

    # ─────────────────────────────────────────────
    #  VALIDATION D'UNE FLASHCARD
    # ─────────────────────────────────────────────

    @staticmethod
    def _validate_card(card: dict) -> Optional[str]:
        """
        Valide une flashcard. Retourne None si valide, sinon le message d'erreur.
        """
        if not card.get("question", "").strip():
            return "Question vide"
        if not card.get("answer", "").strip():
            return "Réponse vide"
        priority = card.get("priority")
        if not isinstance(priority, int) or priority not in range(1, 6):
            return f"Priorité invalide : {priority!r} (attendu 1-5)"
        tags = card.get("tags", [])
        if not isinstance(tags, list):
            return f"Tags invalides : {tags!r} (attendu une liste)"
        return None

    # ─────────────────────────────────────────────
    #  NORMALISATION DES TAGS
    # ─────────────────────────────────────────────

    @staticmethod
    def _format_tags(tags: list, subject: str) -> str:
        """
        Formate les tags pour Anki.
        - Séparés par des espaces (format natif Anki)
        - Espaces internes remplacés par _ (Anki n'accepte pas les espaces dans un tag)
        - Dédupliqués, ordre préservé
        """
        # S'assure que les tags de base sont présents
        base_tags = SUBJECTS_CONFIG.get(subject, {}).get("tags_base", ["PCSI"])
        all_tags = list(dict.fromkeys(base_tags + [str(t) for t in tags]))

        # Nettoie chaque tag
        cleaned = []
        seen = set()
        for tag in all_tags:
            clean = tag.strip().replace(" ", "_").replace("\t", "_")
            if clean and clean not in seen:
                cleaned.append(clean)
                seen.add(clean)
        return " ".join(cleaned)

    # ─────────────────────────────────────────────
    #  AJOUT DE CARTES AU BUFFER
    # ─────────────────────────────────────────────

    def add_flashcards(self, flashcards: list[dict], subject: str) -> dict:
        """
        Ajoute des flashcards au buffer de la matière.
        Retourne des stats : {"added": N, "skipped": N}
        """
        stats = {"added": 0, "skipped": 0}

        if subject not in self._buffers:
            self._buffers[subject] = []

        deck = SUBJECTS_CONFIG.get(subject, {}).get("anki_deck", f"PCSI::{subject}")

        for card in flashcards:
            error = self._validate_card(card)
            if error:
                logger.warning(f"Carte ignorée ({error}) : {str(card)[:100]}")
                stats["skipped"] += 1
                continue

            priority_num = card["priority"]
            priority_label = PRIORITY_LABELS.get(priority_num, str(priority_num))

            row = {
                "Question":     card["question"].strip(),
                "Réponse":      card["answer"].strip(),
                "Tags":         self._format_tags(card.get("tags", []), subject),
                "Source":       card.get("source", ""),
                "Priorité":     priority_label,
                "Deck":         deck,
                "PrioritéNum":  priority_num,
            }
            self._buffers[subject].append(row)
            stats["added"] += 1

        logger.info(
            f"  Anki [{subject}] → {stats['added']} cartes ajoutées, "
            f"{stats['skipped']} ignorées"
        )
        return stats

    # ─────────────────────────────────────────────
    #  FLUSH VERS FICHIERS CSV
    # ─────────────────────────────────────────────

    def flush_to_csv(self) -> dict[str, Path]:
        """
        Écrit tous les buffers en mémoire vers des fichiers CSV.
        Retourne un dict subject → chemin du fichier généré.
        Peut être appelé plusieurs fois (append si le fichier existe).
        """
        output_paths = {}

        for subject, rows in self._buffers.items():
            if not rows:
                continue

            safe_subject = subject.replace(" ", "_")
            csv_path = self.output_dir / f"Anki_{safe_subject}.csv"

            # Détermine si le fichier existe déjà (pour l'en-tête)
            file_exists = csv_path.exists()

            with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=ANKI_HEADERS,
                    delimiter="\t",
                    quoting=csv.QUOTE_MINIMAL,
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerows(rows)

            logger.info(
                f"  📁 CSV Anki : {csv_path.name} "
                f"({len(rows)} nouvelles cartes)"
            )
            output_paths[subject] = csv_path

        # Vide les buffers après flush
        total = sum(len(r) for r in self._buffers.values())
        self._buffers = {}
        logger.info(f"  ✅ Flush Anki terminé : {total} cartes écrites")
        return output_paths

    # ─────────────────────────────────────────────
    #  EXPORT D'UN DECK "URGENCE" FILTRÉ
    # ─────────────────────────────────────────────

    def generate_urgency_deck(self, min_priority: int = 4) -> Path:
        """
        Génère un CSV consolidé contenant uniquement les cartes de haute priorité
        (toutes matières confondues). Utile pour les révisions de dernière minute.
        """
        urgency_path = self.output_dir / f"Anki_URGENCE_P{min_priority}plus.csv"

        # Collecte depuis tous les CSV existants
        all_rows = []
        for subject in SUBJECTS_CONFIG:
            safe_subject = subject.replace(" ", "_")
            csv_path = self.output_dir / f"Anki_{safe_subject}.csv"
            if not csv_path.exists():
                continue
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    try:
                        if int(row.get("PrioritéNum", 0)) >= min_priority:
                            all_rows.append(row)
                    except (ValueError, TypeError):
                        continue

        if not all_rows:
            logger.warning("Aucune carte de haute priorité trouvée.")
            return urgency_path

        with open(urgency_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=ANKI_HEADERS,
                delimiter="\t",
                quoting=csv.QUOTE_MINIMAL,
            )
            writer.writeheader()
            writer.writerows(all_rows)

        logger.info(
            f"  🔴 Deck urgence généré : {urgency_path.name} "
            f"({len(all_rows)} cartes P{min_priority}+)"
        )
        return urgency_path

    # ─────────────────────────────────────────────
    #  STATS
    # ─────────────────────────────────────────────

    def get_total_cards_on_disk(self) -> dict[str, int]:
        """Compte les cartes déjà persistées sur disque par matière."""
        counts = {}
        for subject in SUBJECTS_CONFIG:
            safe_subject = subject.replace(" ", "_")
            csv_path = self.output_dir / f"Anki_{safe_subject}.csv"
            if not csv_path.exists():
                counts[subject] = 0
                continue
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                # -1 pour l'en-tête
                counts[subject] = max(0, sum(1 for _ in f) - 1)
        return counts
