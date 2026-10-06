"""Shared pixel-grid layout for renderer sheets and recipe estimates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SheetLayout:
    rows: int
    columns: int
    cell_size: int

    @property
    def allocated_cells(self) -> int:
        return self.rows * self.columns

    @property
    def width(self) -> int:
        return self.columns * self.cell_size

    @property
    def height(self) -> int:
        return self.rows * self.cell_size

    @property
    def pixels(self) -> int:
        return self.width * self.height


def calculate_sheet_layout(frames: int, columns: int,
                           cell_size: int) -> SheetLayout:
    """Return the exact padded-grid allocation for a sheet.

    A final partially populated row still occupies every requested column.
    Keep this calculation shared by renderers, resource preflight, and the
    executor's post-allocation check.
    """
    values = (("frames", frames), ("columns", columns),
              ("cell_size", cell_size))
    for name, value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    rows = (frames + columns - 1) // columns
    return SheetLayout(rows=rows, columns=columns, cell_size=cell_size)
