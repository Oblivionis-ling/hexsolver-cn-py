from __future__ import annotations

import unittest

from hexsolver_cn.models import (
    Board,
    Cell,
    CellVisualType,
    ClueType,
    LineFamily,
    RowClue,
)
from hexsolver_cn.reason_interaction import (
    ReasonReferenceKind,
    RowReferenceKey,
    parse_reason_references,
)


def make_reference_board() -> Board:
    coords = [(index, 0) for index in range(8)]
    cells = {
        coord: Cell(
            cell_id=index,
            coord=coord,
            center=(float(coord[0] * 48), 0.0),
            visual_type=CellVisualType.HIDDEN,
        )
        for index, coord in enumerate(coords, start=1)
    }
    rows = [
        RowClue(
            line_id=line_id,
            family=family,
            line_key=index,
            coords=list(coords[start : start + length]),
            anchor=(0.0, float(index * 40)),
            clue_text=str(index + 1),
            clue_type=ClueType.COUNT,
            clue_number=index + 1,
        )
        for index, (line_id, family, start, length) in enumerate(
            (
                ("H2", LineFamily.HORIZONTAL, 0, 4),
                ("R6", LineFamily.DOWN_RIGHT, 1, 5),
                ("L4", LineFamily.DOWN_LEFT, 2, 6),
            )
        )
    ]
    return Board(
        image_path="",
        image_size=(640, 360),
        cells=cells,
        row_clues=rows,
        origin=(0.0, 0.0),
        basis_a=(48.0, 0.0),
        basis_b=(24.0, 42.0),
        ring_threshold=20.0,
    )


class ReasonReferenceParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.board = make_reference_board()

    def test_single_coordinate_is_linked_to_one_board_cell(self) -> None:
        text = "结论：格子 (4, 0) 必须判蓝。"

        references = parse_reason_references(text, self.board)

        self.assertEqual(1, len(references))
        self.assertIs(references[0].kind, ReasonReferenceKind.CELLS)
        self.assertEqual(((4, 0),), references[0].coords)
        self.assertEqual("(4, 0)", references[0].label)

    def test_long_coordinate_array_is_one_group_not_competing_links(self) -> None:
        coords_text = "[(0, 0)、(1, 0)、(2, 0)、(3, 0)、(4, 0)、(5, 0)、(6, 0)、(7, 0)]"
        text = f"未知格 8 个 {coords_text}。"

        references = parse_reason_references(text, self.board)

        self.assertEqual(1, len(references))
        self.assertEqual(coords_text, references[0].label)
        self.assertEqual(tuple((index, 0) for index in range(8)), references[0].coords)

    def test_all_three_row_families_resolve_to_exact_row_and_cells(self) -> None:
        text = "；".join(f"条件：{row.display_name()}" for row in self.board.row_clues)

        references = parse_reason_references(text, self.board)

        self.assertEqual(3, len(references))
        self.assertEqual(
            {
                RowReferenceKey("H2", LineFamily.HORIZONTAL, 4),
                RowReferenceKey("R6", LineFamily.DOWN_RIGHT, 5),
                RowReferenceKey("L4", LineFamily.DOWN_LEFT, 6),
            },
            {reference.row_key for reference in references},
        )
        self.assertTrue(all(reference.kind is ReasonReferenceKind.ROW for reference in references))
        self.assertTrue(all(reference.coords for reference in references))

    def test_coordinates_missing_from_board_are_ignored_safely(self) -> None:
        text = "差集为 [(1, 0)、(99, -99)]，另看格子 (88, 88)。"

        references = parse_reason_references(text, self.board)

        self.assertEqual(1, len(references))
        self.assertEqual(((1, 0),), references[0].coords)
        self.assertEqual("[(1, 0)、(99, -99)]", references[0].label)


if __name__ == "__main__":
    unittest.main()
