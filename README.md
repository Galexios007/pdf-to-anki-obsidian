# PDF → Anki + Obsidian (PCSI)

Pipeline d'ingestion automatisée de cours PCSI scanné vers :
- 🃏 **Flashcards Anki** (CSV importable, LaTeX rendu via MathJax)
- 🔗 **Graphe de connaissances Obsidian** (notes atomiques, liens embed, KaTeX)

Propulsé par l'**API Batch Anthropic** (Claude Sonnet) — asynchrone, -50% sur les tokens.

---

## Installation

```bash
git clone https://github.com/ton-user/pdf-to-anki-obsidian
cd pdf-to-anki-obsidian
pip install -r requirements.txt
```

## Configuration (2 minutes)

**1. Copie le fichier d'environnement :**

```bash
cp .env.example .env
```

**2. Renseigne ta clé API dans `.env` :**

```env
ANTHROPIC_API_KEY=sk-ant-...
```
> Obtenir une clé sur [console.anthropic.com](https://console.anthropic.com)

**3. Ajuste les chemins dans `config.py` si nécessaire :**

```python
PDF_ROOT       = Path("./cours_pcsi")     # ← tes PDFs ici
OBSIDIAN_VAULT = Path("./obsidian_vault") # ← vault généré ici
ANKI_OUTPUT    = Path("./anki_output")    # ← CSV Anki ici
```

---

## Workflow en deux phases

Le pipeline utilise l'**API Batch Anthropic** : tu soumets, tu fermes le terminal,
tu récupères 15 min à 2h plus tard. Zéro timeout réseau, -50% sur le coût.

### Phase 1 — Soumettre

```bash
# Scan sans rien soumettre (recommandé en premier)
python run_batch.py --dry-run

# Test sur 5 fichiers d'une matière
python run_batch.py --submit --subject Mathématiques --limit 5

# Soumettre une matière complète
python run_batch.py --submit --subject Mathématiques
python run_batch.py --submit --subject Physique
python run_batch.py --submit --subject SI

# Tout soumettre d'un coup
python run_batch.py --submit
```

La commande affiche un `batch_id` de la forme `msgbatch_xxx`. **Note-le.**

### Phase 2 — Récupérer (15 min à 2h plus tard)

```bash
# Vérifier si c'est prêt (sans bloquer)
python run_batch.py --status msgbatch_xxx

# Récupérer et traiter les résultats (attend si pas encore fini)
python run_batch.py --collect msgbatch_xxx

# Récupérer sans attendre (retourne si pas encore terminé)
python run_batch.py --collect msgbatch_xxx --no-wait
```

### Autres commandes

```bash
# Liste tous les batches soumis
python run_batch.py --list-batches

# Resoumettre les fichiers en erreur
python run_batch.py --retry-errors

# Générer le deck urgence manuellement (cartes priorité ≥ 4)
python run_batch.py --urgency-only
python run_batch.py --urgency-only --min-priority 5

# Nettoyer les espaces LaTeX parasites dans le vault
python repair.py
python repair.py --dry-run   # aperçu sans modification
```

---

## Import dans Anki

1. Ouvre Anki → **Fichier → Importer**
2. Sélectionne `anki_output/Anki_Mathématiques.csv`
3. Type de note : **Basic**
4. Séparateur : **Tabulation**
5. Colonne 1 → **Recto**, Colonne 2 → **Verso**
6. Coche **Autoriser les doublons HTML** (pour le LaTeX)
7. Répète pour chaque matière

Pour le rendu LaTeX dans Anki : installe le plugin **[AnkiMathJax](https://ankiweb.net/shared/info/1312543825)**
ou active le rendu LaTeX natif dans les paramètres du type de note.

---

## Structure du vault Obsidian généré

```
obsidian_vault/
├── Concepts/
│   ├── Mathématiques/
│   │   ├── Dérivabilité.md
│   │   ├── Continuité.md
│   │   └── ...
│   ├── Physique/
│   ├── Chimie/
│   ├── Informatique/
│   └── SI/
├── Théorèmes/
│   └── Mathématiques/
│       ├── Théorème de Rolle.md
│       └── ...
├── Méthodes/
│   └── Mathématiques/
│       ├── Méthode — Variation de la constante.md
│       └── ...
└── _Index/
    ├── Mathématiques.md
    ├── Physique.md
    └── ...
```

Les théorèmes sont automatiquement **embeddés** dans leur nœud parent via
`![[Théorème de Rolle]]` — le contenu s'affiche inline dans Obsidian.

---

## Architecture du code

```
run_batch.py           ← CLI  (--submit / --collect / --status / ...)
    │
    └── main.py        ← Orchestrateur Pipeline
            │
            ├── classifier.py       ← Heuristique locale (nom fichier + chemin)
            ├── batch_client.py     ← API Batch Anthropic (submit + collect)
            ├── batch_state.py      ← Persistance batch_ids (batch_state.json)
            ├── pipeline_state.py   ← Checkpoint par fichier (pipeline_state.json)
            ├── prompts.py          ← System prompts (COURS_SYSTEM, TD_SYSTEM)
            ├── anki_exporter.py    ← Buffer mémoire + CSV par matière
            └── obsidian_manager.py ← Actions append-only sur le vault

repair.py              ← Utilitaire post-traitement (espaces LaTeX)
api_client.py          ← Client synchrone (non utilisé en batch, usage futur)

utils/
├── arborescence.py    ← Affiche l'arborescence d'un dossier
├── comptage.py        ← Compte pages PDF + estimation coût API
└── convert_to_pdf.py  ← Convertit .docx/.pptx en PDF (LibreOffice)
```

### Pourquoi le mode Batch ?

| | API synchrone | API Batch |
|---|---|---|
| Timeout | ⚠️ ~3 min (PDFs lourds) | ✅ Aucun |
| Coût | 100% | **50%** |
| Rate limit | Oui | Non |
| Résilience | Nulle | ✅ Continue si terminal fermé |

---

## Coûts estimés

Avec **Claude Sonnet 4** en mode Batch (~$1.50/MTok input, ~$7.50/MTok output) :

| Document | Pages | Estimation |
|---|---|---|
| Cours (20 pages) | ~20 | ~$0.08 |
| TD (3 pages) | ~3 | ~$0.01 |
| 100 PDFs (cours + TDs) | ~1 500 | ~$4–8 |

> Estime ton budget avant de lancer : `python utils/comptage.py ./cours_pcsi`

Pour réduire encore les coûts : passe `MODEL_MAIN = "claude-haiku-4-5-20251001"` dans `config.py`
(moins précis sur le LaTeX complexe).

---

## Matières supportées

| Matière | Deck Anki | Dossier Obsidian |
|---|---|---|
| Mathématiques | `PCSI::Mathématiques` | `Mathématiques/` |
| Physique | `PCSI::Physique` | `Physique/` |
| Chimie | `PCSI::Chimie` | `Chimie/` |
| Informatique | `PCSI::Informatique` | `Informatique/` |
| SI | `PCSI::SI` | `SI/` |

Ajouter une matière : édite `SUBJECTS_CONFIG` dans `config.py`.

---

## Troubleshooting

**`ANTHROPIC_API_KEY manquante`**
→ Vérifie que ton `.env` existe et contient la bonne clé.
→ Ou exporte manuellement : `export ANTHROPIC_API_KEY='sk-ant-...'`

**JSON invalide retourné par l'API**
→ Le fichier log (dans `logs/`) contient les 500 premiers caractères de la réponse brute.
→ Relance avec `--retry-errors` (les troncatures seront soumises avec plus de tokens).

**Nœud Obsidian non créé**
→ Vérifie que `OBSIDIAN_VAULT` pointe vers le bon dossier dans `config.py`.
→ Vérifie les logs — les nœuds déjà existants sont ignorés (append-only).

**Classification incorrecte**
→ Lance `--dry-run` pour auditer avant soumission.
→ Pour forcer le retraitement d'un fichier : supprime son entrée de `pipeline_state.json`.

**Espaces parasites dans le LaTeX Obsidian**
→ Lance `python repair.py` pour nettoyer le vault en une passe.
