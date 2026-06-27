"""
obsidian_manager.py — Gestionnaire du vault Obsidian.

Architecture APPEND-ONLY :
- new_node      : crée un fichier .md (échoue silencieusement si déjà existant)
- direct_append : colle du Markdown à la fin d'un fichier existant

Le script ne lit JAMAIS le contenu existant pour le passer à l'API.
Zéro risque de dérive sémantique.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from config import OBSIDIAN_VAULT, OBSIDIAN_STRUCTURE

logger = logging.getLogger(__name__)


class ObsidianManager:
    def __init__(self, vault_path: Path = OBSIDIAN_VAULT):
        self.vault = vault_path
        self._ensure_structure()

    # ─────────────────────────────────────────────
    #  INITIALISATION
    # ─────────────────────────────────────────────

    def _ensure_structure(self):
        """Crée l'arborescence du vault si elle n'existe pas."""
        folders = [
            self.vault,
            self.vault / OBSIDIAN_STRUCTURE["concepts"],    # Concepts/
            self.vault / OBSIDIAN_STRUCTURE["theoremes"],   # Théorèmes/
            self.vault / OBSIDIAN_STRUCTURE["methodes"],    # Méthodes/
            self.vault / OBSIDIAN_STRUCTURE["index"],       # _Index/
            self.vault / ".backups",                        # Sauvegardes optionnelles
        ]
        # Crée aussi un sous-dossier par matière dans chaque section
        from config import SUBJECTS_CONFIG
        for subject_cfg in SUBJECTS_CONFIG.values():
            subject_folder = subject_cfg["obsidian_folder"]
            for section in ["concepts", "theoremes", "methodes"]:
                folders.append(
                    self.vault
                    / OBSIDIAN_STRUCTURE[section]
                    / subject_folder
                )
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Vault Obsidian prêt : {self.vault}")

    # ─────────────────────────────────────────────
    #  RÉSOLUTION DES CHEMINS
    # ─────────────────────────────────────────────

    def _folder_key_to_path(self, folder: str) -> Path:
        """
        Convertit un nom de dossier LLM ("Concepts", "Théorèmes", "Méthodes")
        vers le chemin réel dans le vault.
        """
        mapping = {
            "concepts":   OBSIDIAN_STRUCTURE["concepts"],
            "théorèmes":  OBSIDIAN_STRUCTURE["theoremes"],
            "theoremes":  OBSIDIAN_STRUCTURE["theoremes"],
            "méthodes":   OBSIDIAN_STRUCTURE["methodes"],
            "methodes":   OBSIDIAN_STRUCTURE["methodes"],
        }
        key = folder.lower().strip()
        folder_name = mapping.get(key, folder)  # fallback : utilise tel quel
        return self.vault / folder_name

    def _node_path(self, concept_name: str, folder: str, subject: Optional[str] = None) -> Path:
        """
        Retourne le chemin complet du fichier .md pour un concept.
        Le fichier est placé dans vault/<folder>/<subject>/<concept_name>.md
        ou vault/<folder>/<concept_name>.md si pas de subject.
        """
        base = self._folder_key_to_path(folder)
        safe_name = self._sanitize_filename(concept_name)
        if subject:
            from config import SUBJECTS_CONFIG
            subject_folder = SUBJECTS_CONFIG.get(subject, {}).get(
                "obsidian_folder", subject
            )
            node_dir = base / subject_folder
            node_dir.mkdir(parents=True, exist_ok=True)
        else:
            node_dir = base
        return node_dir / f"{safe_name}.md"

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """
        Nettoie un nom de concept pour en faire un nom de fichier valide.
        Conserve les caractères accentués (Obsidian les supporte).
        """
        forbidden = r'\/:*?"<>|'
        result = name
        for ch in forbidden:
            result = result.replace(ch, "-")
        result = result.strip(". ")
        return result[:200]  # limite de longueur

    @staticmethod
    def _fix_latex_delimiters(content: str) -> str:
        """
        Filet de sécurité : convertit les délimiteurs LaTeX non-Obsidian
        en délimiteurs $ / $$ natifs KaTeX.

        Cas traités :
          \\( expr \\)   →  $expr$
          \\[ expr \\]   →  $$\\nexpr\\n$$
          \\\\( etc.     →  idem (backslashes doublés qui ont survécu)
        """
        import re

        # Cas backslashes quadruplés (artefact JSON mal échappé)
        content = content.replace("\\\\(", "\\(").replace("\\\\)", "\\)")
        content = content.replace("\\\\[", "\\[").replace("\\\\]", "\\]")

        # \[ expr \] → $$\nexpr\n$$ (display)
        content = re.sub(
            r"\\\[\s*(.*?)\s*\\\]",
            lambda m: f"$$\n{m.group(1).strip()}\n$$",
            content,
            flags=re.DOTALL,
        )

        # \( expr \) → $expr$ (inline)
        content = re.sub(
            r"\\\(\s*(.*?)\s*\\\)",
            lambda m: f"${m.group(1).strip()}$",
            content,
            flags=re.DOTALL,
        )

        return content

    # ─────────────────────────────────────────────
    #  ÉCRITURE ATOMIQUE
    # ─────────────────────────────────────────────

    @staticmethod
    def _atomic_write(filepath: Path, content: str):
        """
        Écrit dans un fichier temporaire puis déplace atomiquement.
        Évite la corruption si le processus est interrompu.
        """
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=filepath.parent,
            delete=False,
            suffix=".tmp",
        ) as f:
            f.write(content)
            tmp_path = f.name
        os.replace(tmp_path, filepath)

    @staticmethod
    def _atomic_append(filepath: Path, content: str):
        """
        Ajoute du contenu à la fin d'un fichier existant de manière sûre.
        Si le fichier n'existe pas, le crée (cas edge : direct_append sur nœud inconnu).
        """
        if not filepath.exists():
            logger.warning(
                f"direct_append sur un nœud inexistant : {filepath.name}. Création du fichier."
            )
            ObsidianManager._atomic_write(filepath, content.lstrip("\n"))
            return

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(content)

    # ─────────────────────────────────────────────
    #  APPLICATION DES ACTIONS
    # ─────────────────────────────────────────────

    def apply_actions(
        self,
        actions: list[dict],
        subject: str,
        source_file: str,
    ) -> dict:
        """
        Applique une liste d'obsidian_actions dans l'ordre.
        Retourne des stats : {"created": N, "appended": N, "skipped": N, "errors": N}
        """
        stats = {"created": 0, "appended": 0, "skipped": 0, "errors": 0}

        # Index local : concept_name → path, pour résoudre les direct_append
        # dans le même batch sans chercher sur disque
        local_index: dict[str, Path] = {}

        for i, action in enumerate(actions):
            action_type = action.get("action_type", "")
            try:
                if action_type == "new_node":
                    result = self._apply_new_node(action, subject, local_index)
                    if result == "created":
                        stats["created"] += 1
                    else:
                        stats["skipped"] += 1

                elif action_type == "direct_append":
                    result = self._apply_direct_append(action, subject, local_index)
                    if result == "appended":
                        stats["appended"] += 1
                    else:
                        stats["errors"] += 1

                else:
                    logger.warning(f"Action #{i} : type inconnu '{action_type}' — ignorée.")
                    stats["skipped"] += 1

            except Exception as e:
                logger.error(f"Erreur action #{i} ({action_type}) : {e}")
                stats["errors"] += 1

        logger.info(
            f"  Obsidian [{source_file}] → "
            f"{stats['created']} créés, {stats['appended']} appended, "
            f"{stats['skipped']} ignorés, {stats['errors']} erreurs"
        )
        return stats

    def _apply_new_node(
        self, action: dict, subject: str, local_index: dict
    ) -> str:
        """
        Crée un nouveau fichier .md.
        Si le fichier existe déjà → NE l'écrase PAS (append-only) :
          - Log un warning
          - Retourne "skipped"
        Si parent_node spécifié → ajoute ![[concept_name]] à la fin du parent.
        """
        concept_name = action.get("concept_name", "").strip()
        folder       = action.get("folder", "Concepts")
        content      = action.get("content", "")
        parent_node  = action.get("parent_node")  # peut être null/None

        if not concept_name:
            raise ValueError("new_node sans concept_name")
        if not content:
            raise ValueError(f"new_node '{concept_name}' sans content")

        filepath = self._node_path(concept_name, folder, subject)

        # Enregistre dans l'index local immédiatement (même si skip)
        local_index[concept_name] = filepath

        if filepath.exists():
            logger.info(f"  ⏭️  '{concept_name}' existe déjà — skipped (append-only)")
            # Même si skippé, le parent doit quand même pointer vers ce nœud
            if parent_node:
                self._link_to_parent(concept_name, parent_node, subject, local_index)
            return "skipped"

        # Ajoute un frontmatter YAML minimal (utile pour Obsidian Dataview)
        frontmatter = self._build_frontmatter(concept_name, folder, subject)
        full_content = frontmatter + self._fix_latex_delimiters(content)

        self._atomic_write(filepath, full_content)
        logger.info(f"  ✅ Nœud créé : {filepath.relative_to(self.vault)}")

        # Lien depuis le parent
        if parent_node:
            self._link_to_parent(concept_name, parent_node, subject, local_index)

        return "created"

    def _apply_direct_append(
        self, action: dict, subject: str, local_index: dict
    ) -> str:
        """
        Ajoute du contenu Markdown à la fin du nœud cible.
        Cherche d'abord dans l'index local du batch, puis sur disque.
        """
        target_node = action.get("target_node", "").strip()
        content     = action.get("content", "")

        if not target_node:
            raise ValueError("direct_append sans target_node")
        if not content:
            raise ValueError(f"direct_append sur '{target_node}' sans content")

        # Résolution : index local en priorité
        filepath = local_index.get(target_node)

        if filepath is None:
            # Cherche sur disque dans tous les dossiers possibles
            filepath = self._find_node_on_disk(target_node, subject)

        if filepath is None:
            logger.warning(
                f"  ⚠️  direct_append : nœud '{target_node}' introuvable. "
                f"Sera créé comme nœud orphelin."
            )
            # Crée un nœud minimal pour ne pas perdre le contenu
            filepath = self._node_path(target_node, "Concepts", subject)
            orphan_content = f"# {target_node}\n\n> ⚠️ Nœud créé automatiquement par direct_append\n"
            self._atomic_write(filepath, orphan_content)
            local_index[target_node] = filepath

        self._atomic_append(filepath, self._fix_latex_delimiters(content))
        logger.info(f"  ➕ Append : {filepath.name}")
        return "appended"

    def _link_to_parent(
        self,
        concept_name: str,
        parent_node: str,
        subject: str,
        local_index: dict,
    ):
        """
        Ajoute un embed ![[concept_name]] à la fin du fichier parent.
        Cherche le parent dans l'index local puis sur disque.
        """
        parent_path = local_index.get(parent_node)
        if parent_path is None:
            parent_path = self._find_node_on_disk(parent_node, subject)

        if parent_path is None:
            logger.warning(
                f"  ⚠️  Parent '{parent_node}' introuvable pour lier '{concept_name}'."
            )
            return

        embed_line = f"\n\n![[{concept_name}]]"

        # Vérifie que l'embed n'existe pas déjà (idempotence)
        with open(parent_path, "r", encoding="utf-8") as f:
            existing = f.read()
        if f"![[{concept_name}]]" in existing:
            return  # Déjà présent

        self._atomic_append(parent_path, embed_line)
        logger.debug(f"  🔗 Lié : ![[{concept_name}]] → {parent_path.name}")

    def _find_node_on_disk(self, concept_name: str, subject: str) -> Optional[Path]:
        """
        Cherche un fichier .md correspondant à concept_name dans tout le vault.
        Cherche d'abord dans le dossier de la matière, puis partout.
        """
        safe_name = self._sanitize_filename(concept_name)
        filename  = f"{safe_name}.md"

        # Priorité 1 : dossier de la matière
        from config import SUBJECTS_CONFIG
        subject_folder = SUBJECTS_CONFIG.get(subject, {}).get(
            "obsidian_folder", subject
        )
        for section in OBSIDIAN_STRUCTURE.values():
            candidate = self.vault / section / subject_folder / filename
            if candidate.exists():
                return candidate

        # Priorité 2 : recherche globale dans le vault
        for candidate in self.vault.rglob(filename):
            return candidate  # Retourne le premier trouvé

        return None

    # ─────────────────────────────────────────────
    #  FRONTMATTER YAML
    # ─────────────────────────────────────────────

    @staticmethod
    def _build_frontmatter(concept_name: str, folder: str, subject: str) -> str:
        """
        Génère un frontmatter YAML minimal pour Obsidian Dataview.
        Permet de filtrer/requêter les notes par matière, type, etc.
        """
        from datetime import date
        return (
            "---\n"
            f"concept: \"{concept_name}\"\n"
            f"matiere: \"{subject}\"\n"
            f"type: \"{folder}\"\n"
            f"created: {date.today().isoformat()}\n"
            "---\n\n"
        )

    # ─────────────────────────────────────────────
    #  UTILITAIRES
    # ─────────────────────────────────────────────

    def create_subject_index(self, subject: str, chapter: str, source_file: str):
        """
        Met à jour (ou crée) un fichier d'index par matière dans _Index/.
        Liste les chapitres traités avec leur date.
        """
        from config import SUBJECTS_CONFIG
        from datetime import date

        subject_folder = SUBJECTS_CONFIG.get(subject, {}).get(
            "obsidian_folder", subject
        )
        index_path = self.vault / OBSIDIAN_STRUCTURE["index"] / f"{subject_folder}.md"

        entry = f"- [[{chapter}]] — `{source_file}` ({date.today().isoformat()})\n"

        if not index_path.exists():
            header = f"# Index — {subject}\n\n## Chapitres traités\n"
            self._atomic_write(index_path, header + entry)
        else:
            self._atomic_append(index_path, entry)

    def get_vault_stats(self) -> dict:
        """Retourne des statistiques sur le vault."""
        stats = {"total_nodes": 0, "by_folder": {}}
        for section_name, section_folder in OBSIDIAN_STRUCTURE.items():
            folder_path = self.vault / section_folder
            if folder_path.exists():
                count = len(list(folder_path.rglob("*.md")))
                stats["by_folder"][section_folder] = count
                stats["total_nodes"] += count
        return stats
