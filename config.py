"""
config.py — Configuration centrale du pipeline PDF → Anki/Obsidian

Modifie ce fichier selon ton environnement, OU définis des variables
d'environnement (recommandé pour la clé API).

Priorité de configuration :
  1. Variable d'environnement (ex: export ANTHROPIC_API_KEY=...)
  2. Fichier .env à la racine du projet (copie .env.example → .env)
  3. Valeur par défaut ci-dessous
"""

import os
from pathlib import Path

# Support optionnel de python-dotenv (pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Pas de .env — variables d'environnement système uniquement

# ─────────────────────────────────────────────
#  CHEMINS
# ─────────────────────────────────────────────

# Racine de ton dossier de cours (ex: /Users/toi/Documents/cours)
PDF_ROOT = Path(os.environ.get("PDF_ROOT", "./cours_pcsi"))

# Vault Obsidian cible (sera créé s'il n'existe pas)
OBSIDIAN_VAULT = Path(os.environ.get("OBSIDIAN_VAULT", "./obsidian_vault"))

# Dossier de sortie des CSV Anki
ANKI_OUTPUT = Path(os.environ.get("ANKI_OUTPUT", "./anki_output"))

# Fichier de checkpoint (pour reprendre après un plantage)
STATE_FILE = Path(os.environ.get("STATE_FILE", "./pipeline_state.json"))

# Dossier de logs
LOG_DIR = Path(os.environ.get("LOG_DIR", "./logs"))

# ─────────────────────────────────────────────
#  API CLAUDE
# ─────────────────────────────────────────────

# Clé API — NE JAMAIS mettre une vraie clé ici.
# Définis ANTHROPIC_API_KEY dans ton .env ou en variable d'environnement.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Modèle utilisé pour l'extraction principale
MODEL_MAIN = "claude-sonnet-4-6"

# Modèle léger pour la classification des PDFs (moins cher)
MODEL_CLASSIFIER = "claude-haiku-4-5-20251001"

# Tokens max pour une réponse d'extraction standard
MAX_TOKENS_RESPONSE = 16000

# Tokens max pour les cours très denses (retry après troncature détectée)
MAX_TOKENS_LARGE = 24000

# Délai entre les requêtes (secondes) — utilisé en mode synchrone uniquement
REQUEST_DELAY = 3.0

# Nombre de tentatives en cas d'échec API
MAX_RETRIES = 3

# ─────────────────────────────────────────────
#  MATIÈRES TRAITÉES (les autres sont ignorées)
# ─────────────────────────────────────────────

SUBJECTS_CONFIG = {
    "Mathématiques": {
        "anki_deck": "PCSI::Mathématiques",
        "obsidian_folder": "Mathématiques",
        "tags_base": ["PCSI", "Mathématiques"],
        "keywords": ["math", "mathématiques", "logique", "arithmétique",
                     "polynôme", "matrice", "intégration", "dérivabilité",
                     "série", "suite", "espace vectoriel", "déterminant"],
    },
    "Physique": {
        "anki_deck": "PCSI::Physique",
        "obsidian_folder": "Physique",
        "tags_base": ["PCSI", "Physique"],
        "keywords": ["physique", "mécanique", "optique", "électricité",
                     "thermodynamique", "oscillateur", "ondes", "circuit"],
    },
    "Chimie": {
        "anki_deck": "PCSI::Chimie",
        "obsidian_folder": "Chimie",
        "tags_base": ["PCSI", "Chimie"],
        "keywords": ["chimie", "réaction", "équilibre", "acide", "base",
                     "oxydation", "réduction", "cinétique", "thermochimie",
                     "orbitale", "molécule", "liaisons"],
    },
    "Informatique": {
        "anki_deck": "PCSI::Informatique",
        "obsidian_folder": "Informatique",
        "tags_base": ["PCSI", "Informatique"],
        "keywords": ["info", "informatique", "algorithme", "python",
                     "récursivité", "dictionnaire", "liste", "tri", "complexité"],
    },
    "SI": {
        "anki_deck": "PCSI::SI",
        "obsidian_folder": "SI",
        "tags_base": ["PCSI", "SI"],
        "keywords": ["si", "sciences de l'ingénieur", "mécanique", "cinématique",
                     "dynamique", "automatique", "asservissement", "solide",
                     "modélisation", "torseur", "chapitre"],
    },
}

# Dossiers/matières à ignorer complètement
IGNORED_SUBJECTS = ["Allemand", "Anglais", "Espagnol", "Français", "Général"]

# ─────────────────────────────────────────────
#  TYPES DE DOCUMENTS
# ─────────────────────────────────────────────

DOC_TYPES = {
    "COURS":      "cours",       # Cours principal → extraction complète
    "TD":         "td",          # TD → extraction méthodes + astuces
    "DS":         "ds",          # DS/Devoir → extraction méthodes + pièges
    "CORRIGE":    "corrige",     # Corrigé → extraction méthodes uniquement
    "TP":         "tp",          # TP → extraction protocoles + méthodes
    "HORS_SCOPE": "hors_scope",  # Ignoré
}

# ─────────────────────────────────────────────
#  OBSIDIAN
# ─────────────────────────────────────────────

# Structure du vault généré
OBSIDIAN_STRUCTURE = {
    "concepts":    "Concepts",    # Nœuds conceptuels principaux
    "theoremes":   "Théorèmes",   # Théorèmes importants (nœuds séparés)
    "methodes":    "Méthodes",    # Méthodes de résolution
    "index":       "_Index",      # Index par matière/chapitre
}

# Taille max indicative d'un nœud avant d'externaliser en sous-nœud (en caractères)
NODE_SOFT_LIMIT = 3000

# ─────────────────────────────────────────────
#  ANKI
# ─────────────────────────────────────────────

# Priorités : 5 = concours certain, 1 = détail
PRIORITY_LABELS = {
    5: "🔴 Fondamental",
    4: "🟠 Important",
    3: "🟡 Utile",
    2: "🟢 Secondaire",
    1: "⚪ Détail",
}

# Tags Anki de type de carte
CARD_TYPES = ["Définition", "Théorème", "Méthode", "Démonstration",
              "Exercice", "PiègeClassique", "Astuce", "Propriété"]
