from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
from rapidocr import RapidOCR

from .models import ClueType, OCRObservation


VALID_PATTERN = re.compile(r"^(\?|\{?\d+\}?|-\d+-)$")


@dataclass
class ParsedClue:
    text: str
    clue_type: ClueType
    number: Optional[int]


@dataclass
class OCRResult:
    text: str = ""
    score: float = float("inf")
    variant: str = ""
    box: Optional[Tuple[float, float, float, float]] = None


class RapidOCRBoxEngine:
    def __init__(self) -> None:
        self.engine: Optional[RapidOCR] = None

    def recognize_image(self, bgr: np.ndarray) -> List[OCRObservation]:
        engine = self._get_engine()
        output = engine(bgr)
        observations: List[OCRObservation] = []
        for text, score, box in zip(output.txts, output.scores, output.boxes):
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            observations.append(
                OCRObservation(
                    text=str(text).strip(),
                    score=float(score),
                    box=(min(xs), min(ys), max(xs), max(ys)),
                )
            )
        return observations

    def match_candidates(self, text: str, candidate_texts: Iterable[str]) -> OCRResult:
        normalized = self.normalize_text(text)
        if not normalized:
            return OCRResult()

        best_candidate = ""
        best_score = 0.0
        for candidate in dict.fromkeys(candidate_texts):
            ratio = self._candidate_similarity(normalized, candidate)
            if ratio > best_score:
                best_candidate = candidate
                best_score = ratio

        if not best_candidate or best_score < 0.55:
            return OCRResult()
        return OCRResult(text=best_candidate, score=(1.0 - best_score) * 100.0, variant="rapidocr")

    @staticmethod
    def normalize_text(text: str) -> str:
        text = text.strip()
        replacements = {
            " ": "",
            "（": "(",
            "）": ")",
            "【": "[",
            "】": "]",
            "—": "-",
            "－": "-",
            "一": "-",
            "_": "-",
            "l": "1",
            "I": "1",
            "|": "1",
            "O": "0",
            "o": "0",
            "D": "0",
            "S": "5",
            "s": "5",
            "B": "8",
            "G": "6",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)

        normalized_chars: List[str] = []
        for char in text:
            if char in {"(", "[", "C", "c"}:
                normalized_chars.append("{")
            elif char in {")", "]"}:
                normalized_chars.append("}")
            elif char.isdigit() or char in {"{", "}", "-", "?"}:
                normalized_chars.append(char)
        return "".join(normalized_chars)

    def _get_engine(self) -> RapidOCR:
        if self.engine is None:
            rapid_logger = logging.getLogger("RapidOCR")
            rapid_logger.setLevel(logging.CRITICAL)
            rapid_logger.propagate = False
            for handler in rapid_logger.handlers:
                handler.setLevel(logging.CRITICAL)
            try:
                from rapidocr.utils.log import logger as packaged_logger

                packaged_logger.setLevel(logging.CRITICAL)
                for handler in packaged_logger.handlers:
                    handler.setLevel(logging.CRITICAL)
            except Exception:
                pass
            self.engine = RapidOCR()
        return self.engine

    def _candidate_similarity(self, observed: str, candidate: str) -> float:
        if observed == candidate:
            return 1.0
        direct = SequenceMatcher(None, observed, candidate).ratio()
        if len(observed) != len(candidate):
            return direct * 0.9

        score = 0.0
        for observed_char, candidate_char in zip(observed, candidate):
            if observed_char == candidate_char:
                score += 1.0
            elif observed_char in self._confusions(candidate_char):
                score += 0.65
        return max(direct, score / max(len(candidate), 1))

    @staticmethod
    def _confusions(candidate_char: str) -> set[str]:
        mapping = {
            "0": {"O", "o", "D", "0"},
            "1": {"1", "I", "l", "|"},
            "2": {"2", "Z", "z"},
            "3": {"3", "E", "e"},
            "5": {"5", "S", "s"},
            "6": {"6", "G"},
            "8": {"8", "B"},
            "{": {"{", "(", "[", "C", "c"},
            "}": {"}", ")", "]"},
            "-": {"-", "_", "—", "－", "一"},
        }
        return mapping.get(candidate_char, {candidate_char})


class TemplateOCR:
    def __init__(self, pattern_dir: str) -> None:
        self.patterns = self._load_patterns(pattern_dir)
        self._candidate_cache: Dict[Tuple[str, ...], Dict[str, np.ndarray]] = {}
        self._compose_cache: Dict[str, np.ndarray] = {}

    @staticmethod
    def _normalize_char(key: str) -> str:
        if key == "Q":
            return "?"
        return key

    def _load_patterns(self, pattern_dir: str) -> Dict[str, np.ndarray]:
        patterns: Dict[str, np.ndarray] = {}
        for name in sorted(os.listdir(pattern_dir)):
            if not name.lower().endswith(".png"):
                continue
            key = name[len("pattern_") : -4]
            key = self._normalize_char(key)
            image = cv2.imread(os.path.join(pattern_dir, name), cv2.IMREAD_GRAYSCALE)
            _, binary = cv2.threshold(image, 160, 255, cv2.THRESH_BINARY)
            patterns[key] = binary
        return patterns

    def parse_clue(self, text: str) -> ParsedClue:
        text = text.strip()
        if not text:
            return ParsedClue("", ClueType.NONE, None)
        if text == "?":
            return ParsedClue(text, ClueType.UNKNOWN, None)
        if text.startswith("{") and text.endswith("}") and text[1:-1].isdigit():
            return ParsedClue(text, ClueType.CONSECUTIVE, int(text[1:-1]))
        if text.startswith("-") and text.endswith("-") and text[1:-1].isdigit():
            return ParsedClue(text, ClueType.NONCONSECUTIVE, int(text[1:-1]))
        if text.isdigit():
            return ParsedClue(text, ClueType.COUNT, int(text))
        return ParsedClue("", ClueType.NONE, None)

    def build_candidates(
        self,
        max_value: int,
        *,
        allow_patterns: bool = True,
        allow_unknown: bool = False,
    ) -> List[str]:
        max_value = max(0, max_value)
        candidates: List[str] = []
        if allow_unknown:
            candidates.append("?")
        for value in range(max_value + 1):
            plain = str(value)
            candidates.append(plain)
            if allow_patterns:
                candidates.append("{" + plain + "}")
                candidates.append("-" + plain + "-")
        return candidates

    def recognize_text(self, crop_rgb: np.ndarray) -> str:
        result = self.recognize_best(
            crop_rgb,
            candidate_texts=self.build_candidates(40, allow_patterns=True, allow_unknown=True),
        )
        return result.text

    def recognize_best(
        self,
        crop_rgb: np.ndarray,
        *,
        candidate_texts: Optional[Iterable[str]] = None,
        score_cutoff: float = 92.0,
    ) -> OCRResult:
        if crop_rgb.size == 0:
            return OCRResult()

        gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
        candidate_map = self._candidate_map(candidate_texts)
        best = OCRResult()

        for variant_name, binary in self._binary_variants(gray):
            bbox = self._bounding_box(binary)
            if bbox is None:
                continue
            x, y, w, h = bbox
            roi = binary[y : y + h, x : x + w]
            text, score = self._match_whole_candidate(roi, candidate_map)
            if text and score < best.score:
                best = OCRResult(text=text, score=score, variant=variant_name)

        if best.score > score_cutoff:
            return OCRResult(score=best.score)
        return best

    def _candidate_map(self, candidate_texts: Optional[Iterable[str]]) -> Dict[str, np.ndarray]:
        if candidate_texts is None:
            candidate_texts = self.build_candidates(40, allow_patterns=True, allow_unknown=True)
        key = tuple(dict.fromkeys(candidate_texts))
        cached = self._candidate_cache.get(key)
        if cached is not None:
            return cached

        mapping: Dict[str, np.ndarray] = {}
        for text in key:
            if not text:
                continue
            mapping[text] = self._compose_text(text)
        self._candidate_cache[key] = mapping
        return mapping

    def _compose_text(self, text: str) -> np.ndarray:
        cached = self._compose_cache.get(text)
        if cached is not None:
            return cached

        if text in self.patterns:
            self._compose_cache[text] = self.patterns[text]
            return self.patterns[text]

        parts = [self.patterns[token] for token in text]
        height = max(part.shape[0] for part in parts)
        padded_parts = []
        for part in parts:
            top = (height - part.shape[0]) // 2
            bottom = height - part.shape[0] - top
            padded_parts.append(cv2.copyMakeBorder(part, top, bottom, 0, 0, cv2.BORDER_CONSTANT, value=0))

        gap = np.zeros((height, 2), dtype=np.uint8)
        image = padded_parts[0]
        for part in padded_parts[1:]:
            image = np.concatenate([image, gap, part], axis=1)
        self._compose_cache[text] = image
        return image

    @staticmethod
    def _binary_variants(gray: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        variants: List[Tuple[str, np.ndarray]] = []
        for threshold in (100, 130, 160, 190, 220):
            for suffix, mode in (("light", cv2.THRESH_BINARY), ("dark", cv2.THRESH_BINARY_INV)):
                _, binary = cv2.threshold(gray, threshold, 255, mode)
                opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
                variants.append((f"{suffix}-{threshold}", opened))

        for suffix, mode in (("light-otsu", cv2.THRESH_BINARY), ("dark-otsu", cv2.THRESH_BINARY_INV)):
            _, binary = cv2.threshold(gray, 0, 255, mode | cv2.THRESH_OTSU)
            opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            variants.append((suffix, opened))
        return variants

    def _match_whole_candidate(
        self,
        roi: np.ndarray,
        candidate_map: Dict[str, np.ndarray],
    ) -> Tuple[str, float]:
        best_key = ""
        best_score = float("inf")
        for key, template in candidate_map.items():
            candidate = self._normalize_for_compare(roi, template.shape[1], template.shape[0])
            template_norm = self._normalize_for_compare(template, template.shape[1], template.shape[0])
            diff = np.mean(np.abs(candidate.astype(np.float32) - template_norm.astype(np.float32)))
            aspect_penalty = abs((roi.shape[1] / max(roi.shape[0], 1)) - (template.shape[1] / max(template.shape[0], 1))) * 8.0
            score = diff + aspect_penalty
            if score < best_score:
                best_score = score
                best_key = key
        return best_key, best_score

    @staticmethod
    def _bounding_box(binary: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        ys, xs = np.where(binary > 0)
        if xs.size < 10:
            return None
        x0, x1 = xs.min(), xs.max()
        y0, y1 = ys.min(), ys.max()
        return int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)

    @staticmethod
    def _normalize_for_compare(image: np.ndarray, width: int, height: int) -> np.ndarray:
        src_h, src_w = image.shape[:2]
        scale = min(width / max(src_w, 1), height / max(src_h, 1))
        resized = cv2.resize(
            image,
            (max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        canvas = np.zeros((height, width), dtype=np.uint8)
        x = (width - resized.shape[1]) // 2
        y = (height - resized.shape[0]) // 2
        canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
        return canvas
