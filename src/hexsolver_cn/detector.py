from __future__ import annotations

import math
import os
import re
import statistics
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .models import Board, Cell, CellVisualType, ClueType, Coord, LineFamily, OCRObservation, RowClue
from .ocr import OCRResult, RapidOCRBoxEngine, TemplateOCR


class DetectionError(RuntimeError):
    pass


class HexImageDetector:
    def __init__(self, asset_dir: str) -> None:
        self.template_ocr = TemplateOCR(os.path.join(asset_dir, "ocr_patterns"))
        self.rapid_ocr = RapidOCRBoxEngine()

    def detect_board(self, image_path: str) -> Board:
        bgr = cv2.imread(image_path)
        if bgr is None:
            raise DetectionError("无法读取截图文件。")

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        logs: List[str] = []

        observations = self.rapid_ocr.recognize_image(bgr)
        logs.append(f"整图 OCR 检测到 {len(observations)} 个文本框。")

        orange_centers, component_shape = self._detect_orange_centers(hsv)
        if len(orange_centers) < 30:
            raise DetectionError("橙色未知格识别失败，无法建立六边形网格。")
        logs.append(f"检测到 {len(orange_centers)} 个橙色未知格。")

        origin, basis_a, basis_b = self._estimate_lattice(orange_centers)
        logs.append(
            "网格步长估计完成："
            f"水平步长 {basis_a[0]:.2f}，斜向步长 ({basis_b[0]:.2f}, {basis_b[1]:.2f})。"
        )

        coords = self._assign_orange_coords(orange_centers, origin, basis_a, basis_b)
        min_q = min(coord[0] for coord in coords) - 2
        max_q = max(coord[0] for coord in coords) + 2
        min_r = min(coord[1] for coord in coords) - 2
        max_r = max(coord[1] for coord in coords) + 2

        radius = self._estimate_cell_radius(component_shape, basis_b)
        ring_threshold = 120.0

        cells: Dict[Coord, Cell] = {}
        next_id = 1
        for q in range(min_q, max_q + 1):
            for r in range(min_r, max_r + 1):
                x, y = self._pixel_for_coord(origin, basis_a, basis_b, (q, r))
                if not self._patch_inside(rgb, x, y, radius + 4):
                    continue
                visual_type, _ring_mean = self._classify_position(rgb, hsv, x, y, radius)
                if visual_type == CellVisualType.OUTSIDE:
                    continue

                cell = Cell(
                    cell_id=next_id,
                    coord=(q, r),
                    center=(x, y),
                    visual_type=visual_type,
                )
                next_id += 1

                cells[(q, r)] = cell

        if not cells:
            raise DetectionError("没有识别到可用棋盘格。")

        for cell in cells.values():
            if cell.visual_type not in {CellVisualType.BLUE, CellVisualType.BLACK}:
                continue
            clue_result = self._recognize_cell_clue(rgb, observations, cell, cells, radius)
            parsed = self.template_ocr.parse_clue(clue_result.text)
            cell.clue_text = parsed.text
            cell.clue_type = parsed.clue_type
            cell.clue_number = parsed.number
            cell.ocr_text = clue_result.text
            cell.ocr_source = clue_result.variant
            cell.ocr_score = clue_result.score if clue_result.text else None
            cell.ocr_box = clue_result.box

        row_clues = self._build_row_clues(cells, basis_a, basis_b)
        row_ocr_count, row_autofill_count = self._populate_row_clue_ocr(
            rgb,
            observations,
            row_clues,
            basis_a,
            basis_b,
            cells,
        )
        remaining_blue, remaining_ocr_text, remaining_ocr_source, remaining_ocr_score = self._detect_remaining_blue(
            rgb,
            observations,
            cells,
            basis_a,
            basis_b,
        )

        logs.append(f"总共建立 {len(cells)} 个棋盘位置，其中 {len(row_clues)} 条行线索。")
        logs.append(f"自动识别到 {row_ocr_count} 条行线索，其中高置信度自动填入 {row_autofill_count} 条。")
        if remaining_ocr_text:
            if remaining_blue is not None:
                logs.append(f"自动识别 REMAINING = {remaining_blue}（来源：{remaining_ocr_source}）。")
            else:
                logs.append(f"检测到疑似 REMAINING 文本：{remaining_ocr_text}（来源：{remaining_ocr_source}），请人工确认。")

        return Board(
            image_path=image_path,
            image_size=(rgb.shape[1], rgb.shape[0]),
            cells=cells,
            row_clues=row_clues,
            origin=origin,
            basis_a=basis_a,
            basis_b=basis_b,
            ring_threshold=ring_threshold,
            logs=logs,
            remaining_blue=remaining_blue,
            remaining_ocr_text=remaining_ocr_text,
            remaining_ocr_source=remaining_ocr_source,
            remaining_ocr_score=remaining_ocr_score,
            ocr_observations=observations,
        )

    def parse_clue_text(self, text: str) -> Tuple[str, ClueType, Optional[int]]:
        parsed = self.template_ocr.parse_clue(text)
        return parsed.text, parsed.clue_type, parsed.number

    def row_candidate_texts(self, row: RowClue) -> List[str]:
        return self.template_ocr.build_candidates(
            min(max(len(row.coords), 1), 40),
            allow_patterns=True,
            allow_unknown=False,
        )

    def cell_candidate_texts(self, board: Board, cell: Cell) -> List[str]:
        if cell.visual_type == CellVisualType.BLACK:
            max_value = max(0, len(self._neighbor_coords(board.cells, cell.coord)))
            return self.template_ocr.build_candidates(max_value, allow_patterns=True, allow_unknown=True)
        max_value = max(0, len(self._area_coords(board.cells, cell.coord)))
        return self.template_ocr.build_candidates(max_value, allow_patterns=False, allow_unknown=True)

    def match_row_observation(self, row: RowClue, observation_text: str) -> OCRResult:
        return self.rapid_ocr.match_candidates(observation_text, self.row_candidate_texts(row))

    def match_cell_observation(self, board: Board, cell: Cell, observation_text: str) -> OCRResult:
        return self.rapid_ocr.match_candidates(observation_text, self.cell_candidate_texts(board, cell))

    def parse_remaining_text(self, text: str) -> Optional[int]:
        fragments = self._extract_digit_fragments(text)
        if not fragments:
            return None
        return int(max(fragments, key=lambda item: (len(item), item)))

    def _detect_orange_centers(
        self,
        hsv: np.ndarray,
    ) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        mask = cv2.inRange(hsv, (5, 110, 140), (35, 255, 255))
        count, _labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)

        components: List[Tuple[int, int, int, np.ndarray]] = []
        for idx in range(1, count):
            width = int(stats[idx, cv2.CC_STAT_WIDTH])
            height = int(stats[idx, cv2.CC_STAT_HEIGHT])
            area = int(stats[idx, cv2.CC_STAT_AREA])
            if width < 12 or height < 12 or area < 80:
                continue
            components.append((width, height, area, centers[idx]))

        if len(components) < 30:
            return np.zeros((0, 2), dtype=float), (0.0, 0.0, 0.0)

        areas = np.array([area for _width, _height, area, _center in components], dtype=float)
        area_cutoff = max(200.0, float(np.percentile(areas, 60)) * 0.65)
        seed = [component for component in components if component[2] >= area_cutoff]
        if len(seed) < 30:
            seed = sorted(components, key=lambda item: item[2], reverse=True)[: min(220, len(components))]

        median_w = float(statistics.median(component[0] for component in seed))
        median_h = float(statistics.median(component[1] for component in seed))
        median_a = float(statistics.median(component[2] for component in seed))

        selected = [
            component[3]
            for component in components
            if 0.60 <= component[0] / max(median_w, 1.0) <= 1.45
            and 0.60 <= component[1] / max(median_h, 1.0) <= 1.45
            and 0.55 <= component[2] / max(median_a, 1.0) <= 1.65
        ]
        if len(selected) < 30:
            selected = [component[3] for component in seed]

        return np.array(selected, dtype=float), (median_w, median_h, median_a)

    def _estimate_lattice(
        self,
        orange_centers: np.ndarray,
    ) -> Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]:
        nearest_distances: List[float] = []
        for idx, point in enumerate(orange_centers):
            best = float("inf")
            for other_index, other in enumerate(orange_centers):
                if idx == other_index:
                    continue
                dist = math.hypot(float(other[0] - point[0]), float(other[1] - point[1]))
                if dist < best:
                    best = dist
            if best < float("inf"):
                nearest_distances.append(best)

        if not nearest_distances:
            raise DetectionError("无法从橙色格子推断网格步长。")

        diagonal_distance = statistics.median(nearest_distances)
        pairs: List[Tuple[float, float, float]] = []
        for idx, point in enumerate(orange_centers):
            for other in orange_centers[idx + 1 :]:
                dx = float(other[0] - point[0])
                dy = float(other[1] - point[1])
                dist = math.hypot(dx, dy)
                if not (diagonal_distance * 0.82 <= dist <= diagonal_distance * 1.22):
                    continue
                if abs(dx) < diagonal_distance * 0.18 or abs(dy) < diagonal_distance * 0.18:
                    continue
                pairs.append((abs(dx), abs(dy), dist))

        if not pairs:
            raise DetectionError("无法从橙色格子推断网格步长。")

        dx = float(statistics.median(item[0] for item in pairs))
        dy = float(statistics.median(item[1] for item in pairs))
        basis_a = (dx * 2.0, 0.0)
        basis_b = (dx, dy)

        top_index = min(range(len(orange_centers)), key=lambda index: (orange_centers[index][1], orange_centers[index][0]))
        origin = tuple(float(value) for value in orange_centers[top_index])
        return origin, basis_a, basis_b

    def _assign_orange_coords(
        self,
        orange_centers: np.ndarray,
        origin: Tuple[float, float],
        basis_a: Tuple[float, float],
        basis_b: Tuple[float, float],
    ) -> List[Coord]:
        matrix = np.column_stack([basis_a, basis_b])
        inverse = np.linalg.inv(matrix)
        coords: List[Coord] = []
        origin_vec = np.array(origin, dtype=float)
        for point in orange_centers:
            qr = inverse.dot(point - origin_vec)
            coords.append(tuple(int(round(value)) for value in qr))
        return coords

    @staticmethod
    def _pixel_for_coord(
        origin: Tuple[float, float],
        basis_a: Tuple[float, float],
        basis_b: Tuple[float, float],
        coord: Coord,
    ) -> Tuple[float, float]:
        q, r = coord
        x = origin[0] + q * basis_a[0] + r * basis_b[0]
        y = origin[1] + q * basis_a[1] + r * basis_b[1]
        return x, y

    def _estimate_cell_radius(
        self,
        component_shape: Tuple[float, float, float],
        basis_b: Tuple[float, float],
    ) -> int:
        median_w, median_h, _median_a = component_shape
        diagonal = math.hypot(*basis_b)
        return max(
            14,
            int(round(max(median_w, median_h) * 0.40)),
            int(round(diagonal * 0.40)),
        )

    @staticmethod
    def _patch_inside(rgb: np.ndarray, x: float, y: float, radius: int) -> bool:
        xi = int(round(x))
        yi = int(round(y))
        return (
            xi - radius >= 0
            and yi - radius >= 0
            and xi + radius < rgb.shape[1]
            and yi + radius < rgb.shape[0]
        )

    def _classify_position(
        self,
        rgb: np.ndarray,
        hsv: np.ndarray,
        x: float,
        y: float,
        radius: int,
    ) -> Tuple[CellVisualType, float]:
        xi = int(round(x))
        yi = int(round(y))
        patch_rgb = rgb[yi - radius : yi + radius + 1, xi - radius : xi + radius + 1]
        patch_hsv = hsv[yi - radius : yi + radius + 1, xi - radius : xi + radius + 1]
        yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
        dist = np.sqrt(xx**2 + yy**2)
        disk = dist <= max(8.0, radius * 0.58)
        ring = (dist >= max(10.0, radius * 0.72)) & (dist <= radius * 0.98)

        white_dist = np.linalg.norm(patch_rgb.astype(np.int16) - 255, axis=2)
        ring_mean = float(white_dist[ring].mean())
        if ring_mean < 110:
            return CellVisualType.OUTSIDE, ring_mean

        h_mean = float(patch_hsv[:, :, 0][disk].mean())
        s_mean = float(patch_hsv[:, :, 1][disk].mean())
        v_mean = float(patch_hsv[:, :, 2][disk].mean())

        if 5 <= h_mean <= 35 and s_mean > 110 and v_mean > 145:
            return CellVisualType.HIDDEN, ring_mean
        if 70 <= h_mean <= 140 and s_mean > 70 and v_mean > 110:
            return CellVisualType.BLUE, ring_mean
        if v_mean < 130 or (v_mean < 165 and s_mean > 35):
            return CellVisualType.BLACK, ring_mean
        return CellVisualType.GREY, ring_mean

    @staticmethod
    def _crop_for_text(rgb: np.ndarray, x: float, y: float, radius: int) -> np.ndarray:
        xi = int(round(x))
        yi = int(round(y))
        text_radius = max(12, int(round(radius * 0.90)))
        return rgb[
            yi - text_radius : yi + text_radius + 1,
            xi - text_radius : xi + text_radius + 1,
        ]

    def _recognize_cell_clue(
        self,
        rgb: np.ndarray,
        observations: Sequence[OCRObservation],
        cell: Cell,
        cells: Dict[Coord, Cell],
        radius: int,
    ) -> OCRResult:
        if cell.visual_type == CellVisualType.BLACK:
            max_value = max(0, len(self._neighbor_coords(cells, cell.coord)))
            candidate_texts = self.template_ocr.build_candidates(max_value, allow_patterns=True, allow_unknown=True)
        else:
            max_value = max(0, len(self._area_coords(cells, cell.coord)))
            candidate_texts = self.template_ocr.build_candidates(max_value, allow_patterns=False, allow_unknown=True)

        crop = self._crop_for_text(rgb, cell.center[0], cell.center[1], radius)
        best = self.template_ocr.recognize_best(crop, candidate_texts=candidate_texts, score_cutoff=125.0)
        if best.text:
            best.variant = "template-cell"

        x_tol = radius * 1.35
        y_tol = radius * 1.15
        nearby = self._find_nearby_observations(observations, cell.center, x_tol, y_tol)
        for observation in nearby:
            candidate = self._candidate_from_observation(rgb, observation, candidate_texts)
            if candidate.text and self._prefer_candidate(candidate, best):
                best = candidate

        return best if best.text else OCRResult()

    def _candidate_from_observation(
        self,
        rgb: np.ndarray,
        observation: OCRObservation,
        candidate_texts: Sequence[str],
    ) -> OCRResult:
        best = self.rapid_ocr.match_candidates(observation.text, candidate_texts)
        if best.text:
            best.score = best.score + (1.0 - min(observation.score, 1.0)) * 35.0
            best.variant = "rapid-box"
            best.box = observation.box

        crop = self._crop_from_box(rgb, observation.box, pad=5)
        refined = self.template_ocr.recognize_best(crop, candidate_texts=candidate_texts, score_cutoff=125.0)
        if refined.text:
            refined.variant = "template-box"
            refined.box = observation.box

        if refined.text and (not best.text or self._prefer_candidate(refined, best)):
            return refined
        return best

    def _populate_row_clue_ocr(
        self,
        rgb: np.ndarray,
        observations: Sequence[OCRObservation],
        row_clues: List[RowClue],
        basis_a: Tuple[float, float],
        basis_b: Tuple[float, float],
        cells: Dict[Coord, Cell],
    ) -> Tuple[int, int]:
        crop_width = int(round(max(84.0, abs(basis_a[0]) * 1.35)))
        crop_height = int(round(max(42.0, abs(basis_b[1]) * 1.95)))
        board_box = self._cells_bounding_box(cells.values())
        assigned = self._assign_row_observations(observations, row_clues, board_box, basis_a, basis_b)

        recognized = 0
        autofilled = 0
        for row in row_clues:
            candidate_texts = self.row_candidate_texts(row)
            best = assigned.get(row.line_id, OCRResult())
            template_result = self._recognize_row_from_anchor(
                rgb,
                row,
                crop_width,
                crop_height,
                candidate_texts,
            )
            if template_result.text and self._prefer_candidate(template_result, best):
                best = template_result

            if not best.text:
                continue

            row.ocr_text = best.text
            row.ocr_score = float(best.score)
            row.ocr_source = best.variant
            row.ocr_box = best.box
            recognized += 1
            if best.score <= 64.0:
                parsed = self.template_ocr.parse_clue(best.text)
                if parsed.clue_type != ClueType.NONE:
                    row.clue_text = parsed.text
                    row.clue_type = parsed.clue_type
                    row.clue_number = parsed.number
                    autofilled += 1

        return recognized, autofilled

    def _detect_remaining_blue(
        self,
        rgb: np.ndarray,
        observations: Sequence[OCRObservation],
        cells: Dict[Coord, Cell],
        basis_a: Tuple[float, float],
        basis_b: Tuple[float, float],
    ) -> Tuple[Optional[int], str, str, Optional[float]]:
        board_box = self._cells_bounding_box(cell for cell in cells.values() if cell.is_playable)
        label_obs = [
            observation
            for observation in observations
            if self._looks_like_remaining_label(observation.text)
        ]

        digit_candidates: List[Tuple[str, OCRObservation]] = []
        for observation in observations:
            if observation.box[1] > board_box[1] + abs(basis_b[1]) * 0.55:
                continue
            for digits in self._extract_digit_fragments(observation.text):
                digit_candidates.append((digits, observation))

        best_candidate: Optional[Tuple[str, OCRObservation]] = None
        best_metric = float("inf")
        for digits, observation in digit_candidates:
            metric = (1.0 - min(observation.score, 1.0)) * 45.0
            metric += max(0.0, (board_box[2] - observation.box[0]) / max(abs(basis_a[0]), 1.0)) * 12.0
            metric += max(0.0, (observation.box[1] - board_box[1]) / max(abs(basis_b[1]), 1.0)) * 8.0
            if self._looks_like_remaining_label(observation.text):
                metric -= 18.0

            label_distance = self._nearest_label_distance(observation.center, label_obs)
            if label_distance is not None:
                metric += label_distance * 0.05
            else:
                metric += 28.0

            if metric < best_metric:
                best_metric = metric
                best_candidate = (digits, observation)

        if best_candidate is not None:
            digits, observation = best_candidate
            if best_metric <= 30.0:
                return int(digits), digits, "rapid-image", best_metric
            return None, digits, "rapid-image", best_metric

        center_x = board_box[2] - abs(basis_a[0]) * 0.30
        center_y = board_box[1] - abs(basis_b[1]) * 1.15
        candidate_texts = self.template_ocr.build_candidates(200, allow_patterns=False, allow_unknown=False)
        crop = self._crop_rect(
            rgb,
            center_x,
            center_y,
            int(round(max(110.0, abs(basis_a[0]) * 1.45))),
            int(round(max(44.0, abs(basis_b[1]) * 1.80))),
        )
        result = self.template_ocr.recognize_best(crop, candidate_texts=candidate_texts, score_cutoff=120.0)
        if result.text and result.text.isdigit():
            if result.score <= 82.0:
                return int(result.text), result.text, "template-remaining", result.score
            return None, result.text, "template-remaining", result.score
        return None, "", "", None

    def _assign_row_observations(
        self,
        observations: Sequence[OCRObservation],
        row_clues: Sequence[RowClue],
        board_box: Tuple[float, float, float, float],
        basis_a: Tuple[float, float],
        basis_b: Tuple[float, float],
    ) -> Dict[str, OCRResult]:
        global_candidates = self.template_ocr.build_candidates(40, allow_patterns=True, allow_unknown=False)
        max_distance = max(abs(basis_a[0]) * 1.85, abs(basis_b[1]) * 2.80, 220.0)
        options: List[Tuple[float, int, str, str, Tuple[float, float, float, float]]] = []

        for observation_index, observation in enumerate(observations):
            matched = self.rapid_ocr.match_candidates(observation.text, global_candidates)
            if not matched.text:
                continue
            parsed = self.template_ocr.parse_clue(matched.text)
            if parsed.clue_type == ClueType.NONE or parsed.number is None:
                continue

            for row in row_clues:
                if parsed.number > len(row.coords):
                    continue
                distance = self._distance(row.anchor, observation.center)
                if distance > max_distance:
                    continue
                score = matched.score + (1.0 - min(observation.score, 1.0)) * 18.0 + distance * 0.22
                options.append((score, observation_index, row.line_id, matched.text, observation.box))

        options.sort(key=lambda item: item[0])
        used_observations: set[int] = set()
        used_rows: set[str] = set()
        assigned: Dict[str, OCRResult] = {}
        for score, observation_index, row_id, text, box in options:
            if observation_index in used_observations or row_id in used_rows:
                continue
            used_observations.add(observation_index)
            used_rows.add(row_id)
            assigned[row_id] = OCRResult(
                text=text,
                score=float(score),
                variant="rapid-assigned",
                box=box,
            )
        return assigned

    def _recognize_row_from_anchor(
        self,
        rgb: np.ndarray,
        row: RowClue,
        crop_width: int,
        crop_height: int,
        candidate_texts: Sequence[str],
    ) -> OCRResult:
        crop = self._crop_rect(rgb, row.anchor[0], row.anchor[1], crop_width, crop_height)
        best = OCRResult()
        for angle in self._row_rotation_angles(row.family):
            rotated = crop if angle == 0 else self._rotate_image(crop, angle)
            candidate = self.template_ocr.recognize_best(
                rotated,
                candidate_texts=candidate_texts,
                score_cutoff=72.0,
            )
            if not candidate.text:
                continue
            candidate.variant = f"template-anchor-{angle:+d}"
            if self._prefer_candidate(candidate, best):
                best = candidate
        return best

    def _find_nearby_observations(
        self,
        observations: Sequence[OCRObservation],
        center: Tuple[float, float],
        x_tol: float,
        y_tol: float,
    ) -> List[OCRObservation]:
        nearby: List[OCRObservation] = []
        cx, cy = center
        for observation in observations:
            ox, oy = observation.center
            if abs(ox - cx) <= x_tol and abs(oy - cy) <= y_tol:
                nearby.append(observation)
        return nearby

    def _observations_for_row(
        self,
        observations: Sequence[OCRObservation],
        row: RowClue,
        basis_a: Tuple[float, float],
        basis_b: Tuple[float, float],
        board_box: Tuple[float, float, float, float],
    ) -> List[OCRObservation]:
        x_tol = max(abs(basis_a[0]) * 0.95, 54.0)
        y_tol = max(abs(basis_b[1]) * 1.05, 32.0)
        candidates = []
        for observation in observations:
            ox, oy = observation.center
            if abs(ox - row.anchor[0]) > x_tol or abs(oy - row.anchor[1]) > y_tol:
                continue
            if self._box_inside_board(observation.box, board_box, padding=abs(basis_b[1]) * 0.12):
                continue
            candidates.append(observation)
        return candidates

    @staticmethod
    def _distance(left: Tuple[float, float], right: Tuple[float, float]) -> float:
        return math.hypot(left[0] - right[0], left[1] - right[1])

    @staticmethod
    def _row_rotation_angles(family: LineFamily) -> List[int]:
        if family == LineFamily.HORIZONTAL:
            return [0]
        if family == LineFamily.DOWN_RIGHT:
            return [-60, 0, 60]
        return [60, 0, -60]

    @staticmethod
    def _prefer_candidate(candidate: OCRResult, current: OCRResult) -> bool:
        if not candidate.text:
            return False
        if not current.text:
            return True
        return candidate.score + 0.5 < current.score

    @staticmethod
    def _rotate_image(rgb: np.ndarray, angle: int) -> np.ndarray:
        height, width = rgb.shape[:2]
        center = (width / 2.0, height / 2.0)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        cosine = abs(matrix[0, 0])
        sine = abs(matrix[0, 1])
        bound_w = int((height * sine) + (width * cosine))
        bound_h = int((height * cosine) + (width * sine))
        matrix[0, 2] += bound_w / 2.0 - center[0]
        matrix[1, 2] += bound_h / 2.0 - center[1]
        return cv2.warpAffine(rgb, matrix, (bound_w, bound_h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))

    @staticmethod
    def _extract_digit_fragments(text: str) -> List[str]:
        direct = re.findall(r"\d+", text)
        if direct:
            return direct
        compact = text.replace(" ", "")
        if len(compact) > 4:
            return []
        mapped = (
            compact.replace("O", "0")
            .replace("o", "0")
            .replace("I", "1")
            .replace("l", "1")
            .replace("|", "1")
            .replace("S", "5")
            .replace("s", "5")
            .replace("B", "8")
        )
        return re.findall(r"\d+", mapped)

    @staticmethod
    def _crop_rect(rgb: np.ndarray, cx: float, cy: float, width: int, height: int) -> np.ndarray:
        half_w = width // 2
        half_h = height // 2
        x0 = max(0, int(round(cx)) - half_w)
        y0 = max(0, int(round(cy)) - half_h)
        x1 = min(rgb.shape[1], x0 + width)
        y1 = min(rgb.shape[0], y0 + height)
        return rgb[y0:y1, x0:x1]

    @staticmethod
    def _crop_from_box(rgb: np.ndarray, box: Tuple[float, float, float, float], pad: int = 4) -> np.ndarray:
        x0, y0, x1, y1 = box
        left = max(0, int(round(x0)) - pad)
        top = max(0, int(round(y0)) - pad)
        right = min(rgb.shape[1], int(round(x1)) + pad)
        bottom = min(rgb.shape[0], int(round(y1)) + pad)
        return rgb[top:bottom, left:right]

    @staticmethod
    def _cells_bounding_box(cells: Iterable[Cell]) -> Tuple[float, float, float, float]:
        items = list(cells)
        xs = [cell.center[0] for cell in items]
        ys = [cell.center[1] for cell in items]
        return min(xs), min(ys), max(xs), max(ys)

    @staticmethod
    def _box_inside_board(
        box: Tuple[float, float, float, float],
        board_box: Tuple[float, float, float, float],
        padding: float = 0.0,
    ) -> bool:
        x0, y0, x1, y1 = box
        bx0, by0, bx1, by1 = board_box
        return x0 >= bx0 - padding and y0 >= by0 - padding and x1 <= bx1 + padding and y1 <= by1 + padding

    def _nearest_label_distance(
        self,
        center: Tuple[float, float],
        labels: Sequence[OCRObservation],
    ) -> Optional[float]:
        if not labels:
            return None
        return min(self._distance(center, label.center) for label in labels)

    @staticmethod
    def _looks_like_remaining_label(text: str) -> bool:
        lowered = text.upper().replace(" ", "")
        return "REMAIN" in lowered or "剩余" in text

    def _build_row_clues(
        self,
        cells: Dict[Coord, Cell],
        basis_a: Tuple[float, float],
        basis_b: Tuple[float, float],
    ) -> List[RowClue]:
        playable = [cell for cell in cells.values() if cell.is_playable]
        grouped: List[RowClue] = []

        line_id = 1
        for family in (LineFamily.HORIZONTAL, LineFamily.DOWN_RIGHT, LineFamily.DOWN_LEFT):
            groups: Dict[int, List[Cell]] = {}
            for cell in playable:
                q, r = cell.coord
                if family == LineFamily.HORIZONTAL:
                    key = r
                elif family == LineFamily.DOWN_RIGHT:
                    key = q
                else:
                    key = q + r
                groups.setdefault(key, []).append(cell)

            for key in sorted(groups):
                members = groups[key]
                ordered = self._sort_line_members(family, members)
                anchor = self._line_anchor(family, ordered, basis_a, basis_b)
                grouped.append(
                    RowClue(
                        line_id=f"L{line_id:03d}",
                        family=family,
                        line_key=key,
                        coords=[member.coord for member in ordered],
                        anchor=anchor,
                    )
                )
                line_id += 1

        return grouped

    @staticmethod
    def _sort_line_members(family: LineFamily, members: List[Cell]) -> List[Cell]:
        if family == LineFamily.HORIZONTAL:
            return sorted(members, key=lambda cell: (cell.center[0], cell.center[1]))
        return sorted(members, key=lambda cell: (cell.center[1], cell.center[0]))

    @staticmethod
    def _line_anchor(
        family: LineFamily,
        ordered: List[Cell],
        basis_a: Tuple[float, float],
        basis_b: Tuple[float, float],
    ) -> Tuple[float, float]:
        first = ordered[0].center
        last = ordered[-1].center
        if family == LineFamily.HORIZONTAL:
            return (first[0] - basis_b[0] * 0.58, first[1] - basis_b[1] * 1.02)
        if family == LineFamily.DOWN_RIGHT:
            return (first[0] - basis_a[0] * 0.64, first[1] + basis_b[1] * 0.12)
        return (last[0] + basis_b[0] * 0.54, last[1] - basis_b[1] * 0.20)

    @staticmethod
    def _neighbor_coords(cells: Dict[Coord, Cell], coord: Coord) -> List[Coord]:
        q, r = coord
        coords: List[Coord] = []
        for dq, dr in ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0)):
            target = (q + dq, r + dr)
            cell = cells.get(target)
            if cell is not None and cell.is_playable:
                coords.append(target)
        return coords

    @staticmethod
    def _area_coords(cells: Dict[Coord, Cell], coord: Coord) -> List[Coord]:
        q, r = coord
        coords: List[Coord] = []
        for dq in range(-2, 3):
            for dr in range(-2, 3):
                if dq == 0 and dr == 0:
                    continue
                ds = -dq - dr
                if max(abs(dq), abs(dr), abs(ds)) > 2:
                    continue
                target = (q + dq, r + dr)
                cell = cells.get(target)
                if cell is not None and cell.is_playable:
                    coords.append(target)
        return coords
