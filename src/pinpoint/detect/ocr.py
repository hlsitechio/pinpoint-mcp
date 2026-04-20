"""Détection d'éléments par OCR Tesseract. Marche sur n'importe quelle image
(web, desktop, Citrix, RDP) — pas besoin d'accès au DOM.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image
import pytesseract


@dataclass
class TextMatch:
    """Un match OCR avec sa bounding box et sa confiance."""

    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float  # 0-100, donné par Tesseract

    def to_rect_annotation(self, color: str = "#FF1744", thickness: int = 4) -> dict:
        return {
            "type": "rect",
            "x": self.x,
            "y": self.y,
            "w": self.width,
            "h": self.height,
            "color": color,
            "thickness": thickness,
        }

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


class OCRDetector:
    """Wrapper Tesseract pour trouver du texte dans des images."""

    def __init__(self, lang: str = "eng+fra", min_confidence: float = 60.0):
        """
        Args:
            lang: codes langue Tesseract (ex 'eng', 'fra', 'eng+fra' pour multi)
            min_confidence: seuil de confiance Tesseract pour filtrer le bruit
        """
        self.lang = lang
        self.min_confidence = min_confidence

    def find_text(
        self,
        image_path: str | Path,
        query: str,
        case_sensitive: bool = False,
        partial_match: bool = True,
    ) -> list[TextMatch]:
        """Trouve toutes les occurrences d'un texte dans l'image.

        Args:
            image_path: chemin vers le screenshot
            query: texte recherché (ex: "Approve scopes", "Soumettre")
            case_sensitive: matching sensible à la casse
            partial_match: True = matche si query est un sous-string du mot OCR
        """
        img = Image.open(image_path)
        # image_to_data retourne dict avec text/conf/left/top/width/height par mot
        data = pytesseract.image_to_data(
            img,
            lang=self.lang,
            output_type=pytesseract.Output.DICT,
        )

        if not case_sensitive:
            query_norm = query.lower()
        else:
            query_norm = query

        matches: list[TextMatch] = []
        n = len(data["text"])

        # Étape 1: matcher par mot individuel
        word_matches: list[int] = []
        for i in range(n):
            word = data["text"][i].strip()
            if not word:
                continue
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                continue
            if conf < self.min_confidence:
                continue

            word_norm = word if case_sensitive else word.lower()
            if (partial_match and query_norm in word_norm) or word_norm == query_norm:
                word_matches.append(i)

        # Étape 2: pour les queries multi-mots, regrouper les mots adjacents
        # qui composent la query complète sur la même ligne
        query_words = query_norm.split()
        if len(query_words) > 1:
            multi_matches = self._find_multiword_matches(data, query_words, case_sensitive)
            for match in multi_matches:
                matches.append(match)
        else:
            for i in word_matches:
                matches.append(
                    TextMatch(
                        text=data["text"][i],
                        x=data["left"][i],
                        y=data["top"][i],
                        width=data["width"][i],
                        height=data["height"][i],
                        confidence=float(data["conf"][i]),
                    )
                )

        return matches

    def _find_multiword_matches(
        self,
        data: dict,
        query_words: list[str],
        case_sensitive: bool,
    ) -> list[TextMatch]:
        """Trouve des séquences de mots adjacents qui matchent la query."""
        matches: list[TextMatch] = []
        n = len(data["text"])

        for i in range(n):
            # Vérifier qu'on a assez de mots restants
            if i + len(query_words) > n:
                break

            # Extraire les mots candidats (sur la même ligne idéalement)
            candidate_indices = []
            for j in range(i, min(i + len(query_words) * 2, n)):
                word = data["text"][j].strip()
                if word:
                    candidate_indices.append(j)
                if len(candidate_indices) == len(query_words):
                    break

            if len(candidate_indices) != len(query_words):
                continue

            # Vérifier que tous matchent dans l'ordre
            all_match = True
            for k, idx in enumerate(candidate_indices):
                word = data["text"][idx].strip()
                word_norm = word if case_sensitive else word.lower()
                if query_words[k] not in word_norm:
                    all_match = False
                    break

            if not all_match:
                continue

            # Vérifier que ce sont sur la même ligne (block_num + line_num identiques)
            same_line = all(
                data["block_num"][candidate_indices[0]] == data["block_num"][idx]
                and data["line_num"][candidate_indices[0]] == data["line_num"][idx]
                for idx in candidate_indices
            )
            if not same_line:
                continue

            # Calculer la bbox englobante
            xs = [data["left"][idx] for idx in candidate_indices]
            ys = [data["top"][idx] for idx in candidate_indices]
            rights = [data["left"][idx] + data["width"][idx] for idx in candidate_indices]
            bottoms = [data["top"][idx] + data["height"][idx] for idx in candidate_indices]

            avg_conf = sum(
                float(data["conf"][idx]) for idx in candidate_indices
            ) / len(candidate_indices)

            matches.append(
                TextMatch(
                    text=" ".join(data["text"][idx] for idx in candidate_indices),
                    x=min(xs),
                    y=min(ys),
                    width=max(rights) - min(xs),
                    height=max(bottoms) - min(ys),
                    confidence=avg_conf,
                )
            )

        return matches

    def list_all_text(self, image_path: str | Path) -> list[TextMatch]:
        """Retourne tous les textes détectés (utile pour debug ou listing)."""
        img = Image.open(image_path)
        data = pytesseract.image_to_data(
            img,
            lang=self.lang,
            output_type=pytesseract.Output.DICT,
        )
        results = []
        for i in range(len(data["text"])):
            word = data["text"][i].strip()
            if not word:
                continue
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                continue
            if conf < self.min_confidence:
                continue
            results.append(
                TextMatch(
                    text=word,
                    x=data["left"][i],
                    y=data["top"][i],
                    width=data["width"][i],
                    height=data["height"][i],
                    confidence=conf,
                )
            )
        return results
