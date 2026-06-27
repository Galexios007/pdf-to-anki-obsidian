"""
batch_client.py — Gestion de l'API Batch Anthropic.

Workflow en deux phases séparées :
  Phase 1 (submit_batch)  : encode tous les PDFs, construit les requêtes,
                             soumet un batch, sauvegarde le batch_id.
  Phase 2 (collect_batch) : interroge le statut, télécharge les résultats
                             quand le batch est terminé, retourne un dict
                             custom_id → résultat JSON parsé.

Avantages vs requêtes synchrones :
  - Pas de timeout réseau (traitement async côté Anthropic)
  - 50% moins cher sur tokens entrée ET sortie
  - Pas de rate-limit par requête
  - Jusqu'à 10 000 requêtes par batch
"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    MODEL_MAIN,
    MODEL_CLASSIFIER,
    MAX_TOKENS_RESPONSE,
    MAX_TOKENS_LARGE,
)

logger = logging.getLogger(__name__)

# Délai entre deux polls de statut (secondes)
POLL_INTERVAL = 60


class BatchClient:
    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY manquante.\n"
                "Windows : set ANTHROPIC_API_KEY=sk-ant-...\n"
                "Mac/Linux : export ANTHROPIC_API_KEY=sk-ant-..."
            )
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ─────────────────────────────────────────────
    #  ENCODAGE PDF
    # ─────────────────────────────────────────────

    @staticmethod
    def encode_pdf(pdf_path: Path) -> str:
        with open(pdf_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    # ─────────────────────────────────────────────
    #  EXTRACTION JSON ROBUSTE
    # ─────────────────────────────────────────────

    @staticmethod
    def extract_json(raw_text: str) -> dict:
        """Parse du JSON depuis une réponse brute, tolère le texte parasite."""
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass
        start = raw_text.find("{")
        end   = raw_text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw_text[start:end])
            except json.JSONDecodeError:
                pass
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"JSON non parseable.\nErreur: {e}\nDébut: {raw_text[:300]}"
            )

    # ─────────────────────────────────────────────
    #  CONSTRUCTION D'UNE REQUÊTE BATCH
    # ─────────────────────────────────────────────

    def _build_request(
        self,
        custom_id: str,
        pdf_path: Path,
        system_prompt: str,
        model: str,
        max_tokens: int,
        user_text: str,
    ) -> dict:
        """Construit un objet requête au format Batch API."""
        pdf_b64 = self.encode_pdf(pdf_path)
        return {
            "custom_id": custom_id,
            "params": {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_b64,
                                },
                            },
                            {"type": "text", "text": user_text},
                        ],
                    }
                ],
            },
        }

    # ─────────────────────────────────────────────
    #  PHASE 1 : SOUMISSION
    # ─────────────────────────────────────────────

    def submit_extraction_batch(
        self,
        jobs: list[dict],
        max_tokens: int = None,
    ) -> str:
        """
        Soumet un batch d'extraction.

        jobs : liste de dicts avec les clés :
          - pdf_path    : Path
          - custom_id   : str
          - system_prompt : str
          - doc_type    : str

        max_tokens : override du MAX_TOKENS_RESPONSE (utilise MAX_TOKENS_LARGE pour les retry)
        Retourne le batch_id Anthropic (str).
        """
        if max_tokens is None:
            max_tokens = MAX_TOKENS_RESPONSE
        requests = []
        skipped  = 0

        for job in jobs:
            pdf_path = job["pdf_path"]
            if not pdf_path.exists():
                logger.warning(f"  ⚠️  Fichier introuvable : {pdf_path} — ignoré")
                skipped += 1
                continue

            size_mb = pdf_path.stat().st_size / (1024 * 1024)
            if size_mb > 32:
                logger.warning(
                    f"  ⚠️  {pdf_path.name} trop lourd ({size_mb:.1f} MB > 32 MB) — ignoré"
                )
                skipped += 1
                continue

            user_text = (
                f"Analyse ce document et génère les flashcards et actions Obsidian demandées.\n"
                f"Nom du fichier source : {pdf_path.name}\n"
                f"Type de document : {job.get('doc_type', 'inconnu')}"
            )

            req = self._build_request(
                custom_id   = job["custom_id"],
                pdf_path    = pdf_path,
                system_prompt = job["system_prompt"],
                model       = MODEL_MAIN,
                max_tokens  = max_tokens,
                user_text   = user_text,
            )
            requests.append(req)

        if not requests:
            raise ValueError("Aucune requête valide à soumettre.")

        logger.info(
            f"Soumission du batch : {len(requests)} requêtes "
            f"({skipped} ignorées)..."
        )

        batch = self.client.messages.batches.create(requests=requests)
        batch_id = batch.id

        logger.info(f"  ✅ Batch soumis : {batch_id}")
        logger.info(f"  Statut initial : {batch.processing_status}")
        return batch_id

    def submit_classifier_batch(self, jobs: list[dict]) -> str:
        """
        Soumet un batch de classification (modèle Haiku, réponses courtes).

        jobs : liste de dicts avec :
          - pdf_path  : Path
          - custom_id : str
          - system_prompt : str
        """
        requests = []
        for job in jobs:
            pdf_path = job["pdf_path"]
            if not pdf_path.exists():
                continue
            req = self._build_request(
                custom_id     = job["custom_id"],
                pdf_path      = pdf_path,
                system_prompt = job["system_prompt"],
                model         = MODEL_CLASSIFIER,
                max_tokens    = 300,
                user_text     = f"Classifie ce document. Nom : {pdf_path.name}",
            )
            requests.append(req)

        if not requests:
            raise ValueError("Aucune requête de classification à soumettre.")

        batch = self.client.messages.batches.create(requests=requests)
        logger.info(f"  ✅ Batch classification soumis : {batch.id} ({len(requests)} fichiers)")
        return batch.id

    # ─────────────────────────────────────────────
    #  PHASE 2 : POLLING ET COLLECTE
    # ─────────────────────────────────────────────

    def wait_and_collect(
        self,
        batch_id: str,
        poll_interval: int = POLL_INTERVAL,
        timeout_hours: float = 24.0,
    ) -> dict[str, dict]:
        """
        Attend la fin d'un batch puis collecte et parse tous les résultats.

        Retourne un dict : custom_id → résultat parsé
          - Si succès   : {"status": "success", "data": <dict JSON>}
          - Si erreur   : {"status": "error", "error": <str>}
        """
        logger.info(f"Attente du batch {batch_id}...")
        timeout_secs = timeout_hours * 3600
        start = time.time()

        while True:
            elapsed = time.time() - start
            if elapsed > timeout_secs:
                raise TimeoutError(
                    f"Batch {batch_id} non terminé après {timeout_hours}h."
                )

            batch = self.client.messages.batches.retrieve(batch_id)
            status = batch.processing_status

            counts = batch.request_counts
            logger.info(
                f"  [{batch_id}] {status} — "
                f"processing:{counts.processing} / "
                f"succeeded:{counts.succeeded} / "
                f"errored:{counts.errored} / "
                f"canceled:{counts.canceled} "
                f"(écoulé: {int(elapsed//60)}m)"
            )

            if status == "ended":
                break

            time.sleep(poll_interval)

        # Collecte des résultats
        logger.info(f"Batch terminé. Collecte des résultats...")
        results: dict[str, dict] = {}

        for result in self.client.messages.batches.results(batch_id):
            custom_id = result.custom_id
            if result.result.type == "succeeded":
                message    = result.result.message
                stop_reason = getattr(message, "stop_reason", None)

                # Extrait le texte de la réponse
                raw_text = "".join(
                    block.text
                    for block in message.content
                    if hasattr(block, "text")
                ).strip()

                # Détection de troncature : stop_reason == "max_tokens"
                # OU JSON invalide avec une string non fermée
                is_truncated = (stop_reason == "max_tokens")

                try:
                    parsed = self.extract_json(raw_text)
                    results[custom_id] = {"status": "success", "data": parsed}
                    if is_truncated:
                        # Parsing a réussi malgré max_tokens — peut-être tronqué
                        # mais récupérable. On log un warning.
                        logger.warning(
                            f"  ⚠️  {custom_id} : stop_reason=max_tokens mais JSON parseable. "
                            f"Résultat potentiellement incomplet."
                        )
                except ValueError as e:
                    error_str = str(e)
                    # Distingue troncature vs JSON vraiment malformé
                    truncation_hints = [
                        "Unterminated string",
                        "Expecting ',' delimiter",
                        "Expecting ':' delimiter",
                        "Expecting value",
                    ]
                    is_truncation_error = is_truncated or any(
                        hint in error_str for hint in truncation_hints
                    )
                    logger.error(
                        f"  ❌ JSON {'tronqué' if is_truncation_error else 'invalide'} "
                        f"pour {custom_id}: {error_str[:200]}"
                    )
                    results[custom_id] = {
                        "status": "error",
                        "error": f"JSON parse error: {e}",
                        "truncated": is_truncation_error,  # flag pour le retry
                        "raw": raw_text[:500],
                    }
            elif result.result.type == "errored":
                err = result.result.error
                logger.error(f"  ❌ Erreur API pour {custom_id}: {err}")
                results[custom_id] = {
                    "status": "error",
                    "error": str(err),
                }
            else:
                # expired, canceled
                results[custom_id] = {
                    "status": result.result.type,
                    "error": f"Résultat de type inattendu : {result.result.type}",
                }

        succeeded = sum(1 for r in results.values() if r["status"] == "success")
        failed    = len(results) - succeeded
        logger.info(
            f"Collecte terminée : {succeeded} succès, {failed} échecs "
            f"sur {len(results)} requêtes"
        )
        return results

    def get_batch_status(self, batch_id: str) -> dict:
        """Retourne le statut courant d'un batch sans bloquer."""
        batch = self.client.messages.batches.retrieve(batch_id)
        return {
            "id":     batch.id,
            "status": batch.processing_status,
            "counts": {
                "processing": batch.request_counts.processing,
                "succeeded":  batch.request_counts.succeeded,
                "errored":    batch.request_counts.errored,
                "canceled":   batch.request_counts.canceled,
            },
        }

    def cancel_batch(self, batch_id: str):
        """Annule un batch en cours."""
        self.client.messages.batches.cancel(batch_id)
        logger.info(f"Batch {batch_id} annulé.")
