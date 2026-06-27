"""
classifier.py — Classification des PDFs.

Stratégie en deux passes :
1. Heuristique locale (nom de fichier + chemin) → rapide, gratuit
2. API Claude Haiku (si heuristique insuffisante) → fiable, très peu coûteux

Permet de filtrer les fichiers hors-scope AVANT d'envoyer quoi que ce soit
à l'API principale (Opus), ce qui évite de gaspiller du budget sur des
fichiers Allemand, organisation, etc.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from config import IGNORED_SUBJECTS, SUBJECTS_CONFIG, DOC_TYPES

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  HEURISTIQUES LOCALES
# ─────────────────────────────────────────────────────────────────────────────

# Patterns sur le nom de fichier (insensible à la casse)
_CORRIGE_PATTERNS = re.compile(
    r"corr(ig[eé]?)?|_corr[_\.]|correction|solution|CORR", re.IGNORECASE
)
_DS_PATTERNS = re.compile(
    r"\bds\b|\bdevoir\b|\bcontr[oô]le\b|\binterro\b|\bexamen\b", re.IGNORECASE
)
_TD_PATTERNS = re.compile(
    r"\btd\b|\bexo\b|\bexercice\b|\bprobleme\b|\bfeuille\b|\bdm\b", re.IGNORECASE
)
_TP_PATTERNS = re.compile(
    r"\btp\b|\btravaux.pratiques\b|\bmanip\b|\bprotocole\b", re.IGNORECASE
)
_COURS_PATTERNS = re.compile(
    r"\bcours\b|\bpoly\b|\bchapitre\b|\bch\d+\b|\bfiche\b|\blecon\b|\bmagistral\b",
    re.IGNORECASE,
)

# Patterns sur le chemin complet (dossier parent)
_PATH_CORRIGE = re.compile(r"corrig[eé]|correction|solutions?", re.IGNORECASE)
_PATH_DS      = re.compile(r"\bD\.?S\.?\b|devoirs?\s+surveill", re.IGNORECASE)
_PATH_TD      = re.compile(r"\bT\.?D\.?\b|travaux\s+dirig", re.IGNORECASE)
_PATH_TP      = re.compile(r"T\.P|TP\d+|travaux[\s_]pratiq", re.IGNORECASE)
_PATH_COURS   = re.compile(r"\bcours\b|\bch\d+\b", re.IGNORECASE)


class PDFClassifier:
    def __init__(self, api_client=None):
        """
        api_client : instance de APIClient. Si None, seule l'heuristique locale
        est utilisée (utile pour les tests).
        """
        self._api = api_client
        self._cache: dict[str, dict] = {}  # chemin → résultat, évite les doubles appels

    # ─────────────────────────────────────────────
    #  POINT D'ENTRÉE PRINCIPAL
    # ─────────────────────────────────────────────

    def classify(self, pdf_path: Path) -> dict:
        """
        Classifie un PDF. Retourne un dict :
        {
          "subject":    "Mathématiques|...|Hors-scope",
          "doc_type":   "cours|td|ds|corrige|tp|hors_scope",
          "chapter":    "Nom du chapitre",
          "confidence": 0.0-1.0,
          "method":     "heuristic|api"
        }
        """
        key = str(pdf_path)
        if key in self._cache:
            return self._cache[key]

        # Passe 1 : heuristique locale
        result = self._heuristic_classify(pdf_path)

        # Passe 2 : API si confiance insuffisante et client disponible
        if result["confidence"] < 0.75 and self._api is not None:
            logger.debug(
                f"Heuristique insuffisante ({result['confidence']:.2f}) "
                f"pour {pdf_path.name} → appel API Haiku"
            )
            try:
                from prompts import CLASSIFIER_SYSTEM
                api_result = self._api.classify_pdf(pdf_path, CLASSIFIER_SYSTEM)
                api_result["method"] = "api"
                result = api_result
            except Exception as e:
                logger.warning(
                    f"Échec classification API pour {pdf_path.name}: {e}. "
                    f"Utilisation de l'heuristique."
                )

        self._cache[key] = result
        return result

    def is_in_scope(self, pdf_path: Path) -> bool:
        """Retourne True si le fichier doit être traité par le pipeline."""
        result = self.classify(pdf_path)
        return (
            result["subject"] != "Hors-scope"
            and result["doc_type"] != "hors_scope"
        )

    # ─────────────────────────────────────────────
    #  HEURISTIQUE LOCALE
    # ─────────────────────────────────────────────

    def _heuristic_classify(self, pdf_path: Path) -> dict:
        """
        Classification basée sur le chemin et le nom de fichier uniquement.
        Rapide et gratuite — couvre ~80% des cas avec la structure PCSI.
        """
        path_str = str(pdf_path)
        name     = pdf_path.stem  # nom sans extension

        # ── Détection matière ──
        subject, subject_conf = self._detect_subject(path_str)

        # Si hors-scope, inutile d'analyser le type : on court-circuite
        if subject == "Hors-scope":
            return {
                "subject":    "Hors-scope",
                "doc_type":   "hors_scope",
                "chapter":    pdf_path.stem,
                "confidence": round(subject_conf, 2),
                "method":     "heuristic",
            }

        # ── Détection type de document ──
        doc_type, type_conf = self._detect_doc_type(name, path_str)

        # ── Extraction chapitre ──
        chapter = self._extract_chapter(pdf_path)

        # Confiance globale = min des deux composantes
        confidence = min(subject_conf, type_conf)

        result = {
            "subject":    subject,
            "doc_type":   doc_type,
            "chapter":    chapter,
            "confidence": round(confidence, 2),
            "method":     "heuristic",
        }
        logger.debug(
            f"Heuristique {pdf_path.name}: {subject}/{doc_type} "
            f"(conf={confidence:.2f})"
        )
        return result

    def _detect_subject(self, path_str: str) -> tuple[str, float]:
        """
        Détecte la matière depuis le chemin.
        Retourne (subject, confidence).
        """
        path_lower = path_str.lower()

        # Hors-scope en priorité
        for ignored in IGNORED_SUBJECTS:
            if ignored.lower() in path_lower:
                return "Hors-scope", 0.95

        # Fichiers d'organisation générale
        hors_scope_patterns = [
            "organisation", "calendrier", "emploi du temps", "colloscope",
            "trombinoscope", "liste mail", "planning", "modalit", "conférence",
            "handbook", "conductivit", "points méthode", "méthode de travail",
            "culture_confiture", "origami",
        ]
        for pattern in hors_scope_patterns:
            if pattern in path_lower:
                return "Hors-scope", 0.90

        # Matières scientifiques
        subject_map = {
            "Mathématiques": ["mathématiques", "maths", "math"],
            "Physique":       ["physique", "phys"],
            "Chimie":         ["chimie", "chim"],
            "Informatique":   ["informatique", "info"],
            "SI":             ["\\si\\", "sciences de l'ingénieur", "\\si "],
        }
        for subject, keywords in subject_map.items():
            for kw in keywords:
                if kw in path_lower:
                    return subject, 0.90

        # Détection SI par le nom du dossier exact (cas courant : dossier "SI")
        parts = path_lower.replace("\\", "/").split("/")
        if "si" in parts:
            return "SI", 0.88

        return "Hors-scope", 0.50  # Incertain → basse confiance

    def _detect_doc_type(self, name: str, path_str: str) -> tuple[str, float]:
        """
        Détecte le type de document depuis le nom de fichier et le chemin.
        Retourne (doc_type, confidence).
        Le chemin complet est utilisé pour les cas où le type est dans le dossier parent.
        """
        # Priorité 1 : corrigé (préfixe sur nom ET chemin)
        if _CORRIGE_PATTERNS.search(name) or _PATH_CORRIGE.search(path_str):
            return "corrige", 0.92

        # Priorité 2 : DS (souvent dans un dossier "D.S")
        if _DS_PATTERNS.search(name) or _PATH_DS.search(path_str):
            return "ds", 0.88

        # Priorité 3 : TP — cherche dans chemin complet (dossier parent "T.P" courant)
        if _TP_PATTERNS.search(name) or _PATH_TP.search(path_str):
            return "tp", 0.88

        # Priorité 4 : TD
        if _TD_PATTERNS.search(name) or _PATH_TD.search(path_str):
            return "td", 0.88

        # Priorité 5 : Cours
        if _COURS_PATTERNS.search(name) or _PATH_COURS.search(path_str):
            return "cours", 0.85

        # Patterns numériques (ex: "1_Logique", "14_Derivabilite") → cours
        if re.match(r"^\d+[_\-]", name):
            return "cours", 0.78

        return "cours", 0.45  # Fallback incertain → l'API confirmera

    @staticmethod
    def _extract_chapter(pdf_path: Path) -> str:
        """
        Extrait un nom de chapitre lisible depuis le chemin.
        Essaie d'utiliser le nom du dossier parent puis le nom du fichier.
        """
        # Dossier parent (souvent le chapitre dans la structure PCSI)
        parent_name = pdf_path.parent.name

        # Nettoie les préfixes numériques et underscores
        chapter = re.sub(r"^(Ch\d+\s*[_:]?\s*|TD\d+\s*[_:]?\s*|\d+[_\-])", "", parent_name)
        chapter = chapter.replace("_", " ").strip()

        # Si le dossier parent est trop générique (ex: "Cours"), utilise le nom du fichier
        generic_parents = {"cours", "td", "tp", "ds", "d.s", "t.d", "t.p", "corrigé"}
        if chapter.lower() in generic_parents or not chapter:
            stem = pdf_path.stem
            chapter = re.sub(r"^[\d_\-]+", "", stem).replace("_", " ").strip()
            chapter = re.sub(r"\s+(CORR|corrige|correction).*$", "", chapter, flags=re.IGNORECASE)

        return chapter or pdf_path.stem

    # ─────────────────────────────────────────────
    #  SCAN DU DOSSIER SOURCE
    # ─────────────────────────────────────────────

    def scan_directory(self, root: Path) -> dict:
        """
        Scanne récursivement un dossier et classifie tous les PDFs.
        Retourne un résumé et la liste des fichiers par catégorie.
        """
        all_pdfs = sorted(root.rglob("*.pdf"))
        logger.info(f"Scan de {root} : {len(all_pdfs)} PDFs trouvés")

        results = {
            "in_scope":   [],   # à traiter
            "out_scope":  [],   # ignorés
            "by_subject": {},   # subject → list of paths
            "by_type":    {},   # doc_type → list of paths
            "total":      len(all_pdfs),
        }

        for pdf in all_pdfs:
            classification = self.classify(pdf)
            subject  = classification["subject"]
            doc_type = classification["doc_type"]

            if subject == "Hors-scope" or doc_type == "hors_scope":
                results["out_scope"].append(pdf)
            else:
                results["in_scope"].append(pdf)
                results["by_subject"].setdefault(subject, []).append(pdf)
                results["by_type"].setdefault(doc_type, []).append(pdf)

        logger.info(
            f"Scan terminé : {len(results['in_scope'])} à traiter, "
            f"{len(results['out_scope'])} ignorés"
        )
        return results

    def print_scan_summary(self, scan_results: dict):
        """Affiche un résumé lisible du scan."""
        print("\n" + "═" * 55)
        print("SCAN DES PDFs")
        print("═" * 55)
        print(f"  Total PDFs trouvés : {scan_results['total']}")
        print(f"  À traiter          : {len(scan_results['in_scope'])}")
        print(f"  Hors-scope ignorés : {len(scan_results['out_scope'])}")
        print()
        print("  Par matière :")
        for subject, files in sorted(scan_results["by_subject"].items()):
            print(f"    {subject:<20} : {len(files):>3} fichiers")
        print()
        print("  Par type de document :")
        for doc_type, files in sorted(scan_results["by_type"].items()):
            print(f"    {doc_type:<15} : {len(files):>3} fichiers")
        print("═" * 55 + "\n")
