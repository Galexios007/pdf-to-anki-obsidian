"""
batch_state.py — Persistance des batch_ids et état des jobs soumis.

Fichier JSON séparé du pipeline_state.json : on garde une trace de
chaque batch soumis pour pouvoir le retrouver même si le terminal
est fermé entre la soumission et la collecte.

Format :
{
  "batches": {
    "msgbatch_xxx": {
      "submitted_at": "2025-01-15T14:00:00",
      "batch_type": "extraction|classification",
      "status": "submitted|ended|collected|failed",
      "jobs": {
        "custom_id": {
          "pdf_path": "chemin/absolu/fichier.pdf",
          "subject":  "Mathématiques",
          "doc_type": "cours",
          "chapter":  "Dérivabilité",
          "collected": false
        }
      }
    }
  }
}
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import STATE_FILE

logger = logging.getLogger(__name__)

BATCH_STATE_FILE = STATE_FILE.parent / "batch_state.json"


class BatchState:
    def __init__(self, state_file: Path = BATCH_STATE_FILE):
        self.state_file = state_file
        self._state = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"batches": {}}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    # ─────────────────────────────────────────────
    #  ENREGISTREMENT D'UN BATCH SOUMIS
    # ─────────────────────────────────────────────

    def register_batch(
        self,
        batch_id: str,
        batch_type: str,
        jobs: list[dict],
    ):
        """
        Enregistre un batch fraîchement soumis avec tous ses jobs.

        jobs : liste de dicts avec au minimum :
          - custom_id, pdf_path, subject, doc_type, chapter
        """
        jobs_dict = {}
        for job in jobs:
            cid = job["custom_id"]
            jobs_dict[cid] = {
                "pdf_path":  str(job["pdf_path"]),
                "subject":   job.get("subject", ""),
                "doc_type":  job.get("doc_type", ""),
                "chapter":   job.get("chapter", ""),
                "collected": False,
            }

        self._state["batches"][batch_id] = {
            "submitted_at": datetime.now().isoformat(),
            "batch_type":   batch_type,
            "status":       "submitted",
            "jobs":         jobs_dict,
        }
        self._save()
        logger.info(f"Batch {batch_id} enregistré ({len(jobs_dict)} jobs).")

    # ─────────────────────────────────────────────
    #  MISE À JOUR DU STATUT
    # ─────────────────────────────────────────────

    def mark_batch_ended(self, batch_id: str):
        if batch_id in self._state["batches"]:
            self._state["batches"][batch_id]["status"] = "ended"
            self._save()

    def mark_batch_collected(self, batch_id: str):
        if batch_id in self._state["batches"]:
            self._state["batches"][batch_id]["status"] = "collected"
            self._state["batches"][batch_id]["collected_at"] = datetime.now().isoformat()
            self._save()

    def mark_job_collected(self, batch_id: str, custom_id: str):
        try:
            self._state["batches"][batch_id]["jobs"][custom_id]["collected"] = True
            self._save()
        except KeyError:
            pass

    # ─────────────────────────────────────────────
    #  LECTURE
    # ─────────────────────────────────────────────

    def get_pending_batches(self) -> list[str]:
        """Retourne les batch_ids soumis mais pas encore collectés."""
        return [
            bid
            for bid, bdata in self._state["batches"].items()
            if bdata["status"] in ("submitted", "ended")
        ]

    def get_job(self, batch_id: str, custom_id: str) -> dict:
        return self._state["batches"][batch_id]["jobs"].get(custom_id, {})

    def get_all_jobs(self, batch_id: str) -> dict:
        return self._state["batches"].get(batch_id, {}).get("jobs", {})

    def get_batch_info(self, batch_id: str) -> dict:
        return self._state["batches"].get(batch_id, {})

    def list_batches(self) -> list[dict]:
        """Retourne un résumé de tous les batches enregistrés."""
        summary = []
        for bid, bdata in self._state["batches"].items():
            jobs = bdata.get("jobs", {})
            collected = sum(1 for j in jobs.values() if j.get("collected"))
            summary.append({
                "batch_id":     bid,
                "type":         bdata.get("batch_type"),
                "status":       bdata.get("status"),
                "submitted_at": bdata.get("submitted_at"),
                "total_jobs":   len(jobs),
                "collected":    collected,
            })
        return sorted(summary, key=lambda x: x["submitted_at"], reverse=True)

    def print_summary(self):
        print("\n" + "═" * 60)
        print("BATCHES ENREGISTRÉS")
        print("═" * 60)
        for b in self.list_batches():
            print(
                f"  {b['batch_id']}\n"
                f"    Type    : {b['type']}\n"
                f"    Statut  : {b['status']}\n"
                f"    Soumis  : {b['submitted_at'][:19]}\n"
                f"    Jobs    : {b['collected']}/{b['total_jobs']} collectés\n"
            )
        print("═" * 60 + "\n")
