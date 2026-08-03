# ABOUTME: One sheet laying a row of references over a row of results, so an
# ABOUTME: asset and the thing it was drawn from can be read in one glance.


def grid_size(columns, rows, cell, spacing):
    """The pixel size of a sheet holding `columns` x `rows` cells.

    Spacing is a GUTTER counted one more time than the cells it separates, so
    the gap between two cells is one spacing wide and the sheet's own border is
    the same — the arithmetic the packer uses, and the reason a sheet built here
    reads like the sheets the dataset is packed into.
    """
    return (cell * columns + spacing * (columns + 1),
            cell * rows + spacing * (rows + 1))


def cell_origin(column, row, cell, spacing):
    """Top-left of one cell: every column sits past its own cells and one more
    gutter than that."""
    return (spacing + column * (cell + spacing),
            spacing + row * (cell + spacing))


def fit_box(width, height, cell):
    """`width` x `height` scaled to fit inside a square cell, aspect kept, and
    the offset that centres it there.

    Fitted rather than stretched because these rows are read as a comparison: a
    reference squashed to a different aspect than the result beside it is the
    one distortion that would make the sheet lie about what changed.
    """
    if width <= 0 or height <= 0:
        return 0, 0, 0, 0
    scale = min(cell / width, cell / height)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    return new_w, new_h, (cell - new_w) // 2, (cell - new_h) // 2


def auto_cell(sizes, fallback=512):
    """The cell size a sheet should use for these images: the largest edge among
    them, so nothing is upscaled into softness and the biggest one is shown at
    its own resolution."""
    edges = [max(int(w), int(h)) for w, h in sizes if w and h]
    return max(edges) if edges else fallback


def compose_rows(rows, cell, spacing, background):
    """Rows of PIL images laid out as a grid, returned as one RGB image.

    A short row keeps its empty cells rather than closing up: column alignment
    IS the sheet's argument — the result belongs under the reference it came
    from — and a row that closed up would silently pair each result with the
    wrong reference.
    """
    from PIL import Image
    columns = max((len(r) for r in rows), default=0)
    if not columns or not rows:
        raise ValueError("nothing to lay out — both rows are empty")
    width, height = grid_size(columns, len(rows), cell, spacing)
    sheet = Image.new("RGB", (width, height), background)
    for row_index, row in enumerate(rows):
        for column, image in enumerate(row):
            if image is None:
                continue
            new_w, new_h, dx, dy = fit_box(image.width, image.height, cell)
            if not new_w or not new_h:
                continue
            x, y = cell_origin(column, row_index, cell, spacing)
            sheet.paste(image.convert("RGB").resize((new_w, new_h),
                                                    Image.LANCZOS),
                        (x + dx, y + dy))
    return sheet
