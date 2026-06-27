"""
api_client.py — Wrapper robuste pour l'API Anthropic.
Gère : retry exponentiel, rate limiting, logging, validation JSON.
"""

import json
import time
import base64
import logging
from pathlib import Path
from typing import Optional

import anthropic

from config import (
    ANTHROPIC_API_KEY, MODEL_MAIN, MODEL_CLASSIFIER,
    MAX_TOKENS_RESPONSE, REQUEST_DELAY, MAX_RETRIES
)

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY manquante. "
                "Lance : export ANTHROPIC_API_KEY='sk-ant-...'"
            )
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._last_request_time = 0.0

    # ─────────────────────────────────────────────
    #  RATE LIMITING
    # ─────────────────────────────────────────────

    def _wait_rate_limit(self):
        """Assure un délai minimum entre les requêtes."""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    # ─────────────────────────────────────────────
    #  ENCODAGE PDF
    # ─────────────────────────────────────────────

    @staticmethod
    def encode_pdf(pdf_path: Path) -> str:
        """Encode un PDF en base64 pour l'envoi à l'API."""
        with open(pdf_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    # ─────────────────────────────────────────────
    #  REQUÊTE PRINCIPALE AVEC RETRY
    # ─────────────────────────────────────────────

    def _call_api(
        self,
        system_prompt: str,
        messages: list,
        model: str,
        max_tokens: int = MAX_TOKENS_RESPONSE,
    ) -> str:
        """
        Appelle l'API Claude avec retry exponentiel.
        Retourne le texte brut de la réponse.
        """
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            self._wait_rate_limit()
            try:
                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=0,
                    system=system_prompt,
                    messages=messages,
                )
                # Concatène tous les blocs texte
                text = "".join(
                    block.text
                    for block in response.content
                    if hasattr(block, "text")
                )
                return text.strip()

            except anthropic.RateLimitError as e:
                wait = 60 * attempt
                logger.warning(
                    f"Rate limit atteint (tentative {attempt}/{MAX_RETRIES}). "
                    f"Attente {wait}s..."
                )
                time.sleep(wait)
                last_error = e

            except anthropic.APIStatusError as e:
                if e.status_code == 529:  # Overloaded
                    wait = 30 * attempt
                    logger.warning(f"API surchargée. Attente {wait}s...")
                    time.sleep(wait)
                    last_error = e
                else:
                    logger.error(f"Erreur API {e.status_code}: {e.message}")
                    raise

            except anthropic.APIConnectionError as e:
                wait = 10 * attempt
                logger.warning(f"Erreur connexion. Attente {wait}s...")
                time.sleep(wait)
                last_error = e

        raise RuntimeError(
            f"Échec après {MAX_RETRIES} tentatives. Dernière erreur: {last_error}"
        )

    # ─────────────────────────────────────────────
    #  EXTRACTION JSON ROBUSTE
    # ─────────────────────────────────────────────

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """
        Tente de parser du JSON depuis la réponse brute.
        Gère les cas où Claude ajoute du texte parasite malgré les instructions.
        """
        # Tentative directe
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # Cherche un bloc JSON entre accolades
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw_text[start:end])
            except json.JSONDecodeError:
                pass

        # Dernier recours : nettoie les backticks markdown
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Impossible de parser le JSON de la réponse API.\n"
                f"Erreur: {e}\n"
                f"Début de la réponse: {raw_text[:500]}"
            )

    # ─────────────────────────────────────────────
    #  API PUBLIQUE : CLASSIFY
    # ─────────────────────────────────────────────

    def classify_pdf(self, pdf_path: Path, system_prompt: str) -> dict:
        """
        Classifie un PDF (matière, type de document, chapitre).
        Utilise le modèle léger Haiku pour économiser du budget.
        """
        logger.info(f"Classification de {pdf_path.name}...")

        pdf_b64 = self.encode_pdf(pdf_path)
        messages = [
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
                    {
                        "type": "text",
                        "text": f"Classifie ce document. Nom du fichier : {pdf_path.name}",
                    },
                ],
            }
        ]

        raw = self._call_api(
            system_prompt=system_prompt,
            messages=messages,
            model=MODEL_CLASSIFIER,
            max_tokens=300,
        )
        result = self._extract_json(raw)
        logger.info(
            f"  → {result.get('subject')} / {result.get('doc_type')} "
            f"(confiance: {result.get('confidence', '?')})"
        )
        return result

    # ─────────────────────────────────────────────
    #  API PUBLIQUE : EXTRACT
    # ─────────────────────────────────────────────

    def extract_from_pdf(
        self,
        pdf_path: Path,
        system_prompt: str,
        extra_context: Optional[str] = None,
    ) -> dict:
        """
        Extraction principale : envoie le PDF à Claude et retourne le JSON parsé.
        extra_context : texte additionnel ajouté au message utilisateur (non utilisé ici,
        réservé pour usage futur).
        """
        logger.info(f"Extraction de {pdf_path.name}...")

        pdf_b64 = self.encode_pdf(pdf_path)

        user_text = (
            f"Analyse ce document et génère les flashcards et nœuds Obsidian demandés.\n"
            f"Nom du fichier source : {pdf_path.name}"
        )
        if extra_context:
            user_text += f"\n\nContexte supplémentaire :\n{extra_context}"

        messages = [
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
        ]

        raw = self._call_api(
            system_prompt=system_prompt,
            messages=messages,
            model=MODEL_MAIN,
        )
        result = self._extract_json(raw)
        logger.info(
            f"  → {len(result.get('flashcards', []))} flashcards, "
            f"{len(result.get('obsidian_nodes', []))} nœuds Obsidian"
        )
        return result

    # ─────────────────────────────────────────────
    #  API PUBLIQUE : FUSION NŒUD OBSIDIAN
    # ─────────────────────────────────────────────

    def append_to_obsidian_node(
        self,
        existing_content: str,
        new_content: str,
        system_prompt: str,
    ) -> str:
        """
        Demande à Claude d'AJOUTER du nouveau contenu à une note existante
        sans jamais réécrire l'existant.
        Retourne le Markdown complet mis à jour.
        """
        messages = [
            {
                "role": "user",
                "content": (
                    f"<existing_note>\n{existing_content}\n</existing_note>\n\n"
                    f"<new_content>\n{new_content}\n</new_content>\n\n"
                    "Retourne le fichier Markdown complet avec les ajouts intégrés."
                ),
            }
        ]

        return self._call_api(
            system_prompt=system_prompt,
            messages=messages,
            model=MODEL_MAIN,
            max_tokens=4000,
        )
