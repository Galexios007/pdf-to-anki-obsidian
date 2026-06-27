"""
pipeline_state.py — Checkpoint et reprise après plantage.
Enregistre chaque PDF traité avec succès pour ne jamais le retraiter.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import STATE_FILE

logger = logging.getLogger(__name__)


class PipelineState:
    """
    Gère l'état persistant du pipeline.
    Format du fichier state :
    {
      "processed": {
        "chemin/relatif/fichier.pdf": {
          "status": "success|error|skipped",
          "subject": "Mathématiques",
          "doc_type": "cours",
          "chapter": "Dérivabilité",
          "flashcards_count": 32,
          "nodes_count": 8,
          "processed_at": "2025-01-15T14:23:00",
          "error": null  // ou message d'erreur
        }
      },
      "stats": {
        "total_processed": 0,
        "total_flashcards": 0,
        "total_nodes": 0,
        "total_errors": 0,
        "started_at": "...",
        "last_updated": "..."
      }
    }
    """

    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self._state = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(
                f"État chargé : {len(state.get('processed', {}))} fichiers déjà traités."
            )
            return state
        return {
            "processed": {},
            "stats": {
                "total_processed": 0,
                "total_flashcards": 0,
                "total_nodes": 0,
                "total_errors": 0,
                "started_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
            },
        }

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state["stats"]["last_updated"] = datetime.now().isoformat()
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    def is_processed(self, pdf_path: Path) -> bool:
        """Retourne True si le PDF a déjà été traité avec succès."""
        key = str(pdf_path)
        entry = self._state["processed"].get(key)
        return entry is not None and entry.get("status") == "success"

    def mark_success(
        self,
        pdf_path: Path,
        subject: str,
        doc_type: str,
        chapter: str,
        flashcards_count: int,
        nodes_count: int,
    ):
        key = str(pdf_path)
        self._state["processed"][key] = {
            "status": "success",
            "subject": subject,
            "doc_type": doc_type,
            "chapter": chapter,
            "flashcards_count": flashcards_count,
            "nodes_count": nodes_count,
            "processed_at": datetime.now().isoformat(),
            "error": None,
        }
        stats = self._state["stats"]
        stats["total_processed"] += 1
        stats["total_flashcards"] += flashcards_count
        stats["total_nodes"] += nodes_count
        self._save()
        logger.info(
            f"✅ {pdf_path.name} → {flashcards_count} cartes, {nodes_count} nœuds"
        )

    def mark_error(self, pdf_path: Path, error: str, truncated: bool = False):
        key = str(pdf_path)
        self._state["processed"][key] = {
            "status":    "error",
            "processed_at": datetime.now().isoformat(),
            "error":     error,
            "truncated": truncated,  # True si la réponse a été coupée par max_tokens
        }
        self._state["stats"]["total_errors"] += 1
        self._save()
        flag = " [TRONQUÉ]" if truncated else ""
        logger.error(f"❌ {pdf_path.name}{flag} → ERREUR: {error[:120]}")

    def mark_skipped(self, pdf_path: Path, reason: str):
        key = str(pdf_path)
        self._state["processed"][key] = {
            "status": "skipped",
            "reason": reason,
            "processed_at": datetime.now().isoformat(),
        }
        self._save()
        logger.info(f"⏭️  {pdf_path.name} → Ignoré ({reason})")

    def get_stats(self) -> dict:
        return self._state["stats"]

    def get_errors(self) -> list:
        """Retourne la liste des chemins des PDFs en erreur."""
        return [
            path
            for path, entry in self._state["processed"].items()
            if entry.get("status") == "error"
        ]

    def get_errors_with_details(self) -> list[dict]:
        """
        Retourne les PDFs en erreur avec leurs métadonnées complètes.
        Chaque entrée : {"path": str, "error": str, "truncated": bool}
        """
        return [
            {
                "path":      path,
                "error":     entry.get("error", ""),
                "truncated": entry.get("truncated", False),
            }
            for path, entry in self._state["processed"].items()
            if entry.get("status") == "error"
        ]

    def reset_errors(self):
        """Remet les PDFs en erreur en état 'non traité' pour les relancer."""
        keys_to_delete = [
            key for key, entry in self._state["processed"].items()
            if entry.get("status") == "error"
        ]
        for key in keys_to_delete:
            del self._state["processed"][key]
        self._state["stats"]["total_errors"] = 0
        self._save()
        logger.info(f"{len(keys_to_delete)} erreurs réinitialisées.")

    def print_summary(self):
        stats = self._state["stats"]
        errors = self.get_errors()
        print("\n" + "═" * 50)
        print("RÉSUMÉ DU PIPELINE")
        print("═" * 50)
        print(f"  PDFs traités avec succès : {stats['total_processed']}")
        print(f"  Total flashcards générées : {stats['total_flashcards']}")
        print(f"  Total nœuds Obsidian : {stats['total_nodes']}")
        print(f"  Erreurs : {stats['total_errors']}")
        if errors:
            print(f"\n  ⚠️  PDFs en erreur ({len(errors)}) :")
            for e in errors:
                print(f"    - {e}")
        print("═" * 50 + "\n")
