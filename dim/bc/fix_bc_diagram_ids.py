"""
fix_bc_diagram_ids.py
----------------------
Run this after every re-export of bc_diagram.svg from draw.io.

WHY THIS EXISTS
----------------
The "Apply BC Rules" wizard (businesscontinuity/templates/businesscontinuity/
apply_bc_rules.html) loads bc_diagram.svg and live-updates the 9 result boxes
(rules A-I) as the user edits their action text. To find each box, the JS
looks up a FIXED element id per letter (SVG_CELL_MAP in that template):

    A -> rB_text   D -> rE_text   G -> rH_text
    B -> rC_text   E -> rF_text   H -> rI_text
    C -> rD_text   F -> rG_text   I -> rJ_text

(The B..J offset is historical — the wizard's JS depends on exactly these
values, so don't "fix" the naming without updating SVG_CELL_MAP too.)

Every time you re-export the diagram from draw.io, it assigns brand new
random ids (e.g. "VaasQkKRO-dtZ1R5eqLz-12") to every shape, which breaks the
lookup above — the boxes render but stay empty, because the JS can't find
them anymore.

WHAT THIS SCRIPT DOES
----------------------
1. Finds the 9 single-letter boxes (A-I) anywhere in the file, by their
   visible text.
2. For each letter, finds its neighboring empty "text" box using geometry
   only (the empty rounded rectangle immediately to the right of the
   letter, same y, no text of its own) — no assumption about ids or
   grouping, so it works regardless of how you organized the drawing.
3. Renames that neighboring box's id to the fixed value the wizard expects,
   both in the rendered SVG (`data-cell-id="..."`) and in the embedded
   draw.io model (`content="...&lt;mxCell id=..."`), so the file stays
   editable in draw.io afterwards.
4. Refuses to write anything unless all 9 letters were found unambiguously
   (exactly one candidate box per letter) — you'll get a clear error
   instead of a half-fixed file.

USAGE
------
    python fix_bc_diagram_ids.py
        Fixes bc_diagram.svg in this same folder, in place.
        A backup of the previous content is written to bc_diagram.svg.bak.

    python fix_bc_diagram_ids.py path\\to\\other_export.svg
        Fixes a specific file in place (still makes a .bak).

    python fix_bc_diagram_ids.py path\\to\\other_export.svg -o fixed.svg
        Writes the result to a new file instead of overwriting the input
        (no backup needed in this mode).

    python fix_bc_diagram_ids.py --dry-run
        Only prints what it would rename, writes nothing.

Exit code is 0 on success, 1 if anything couldn't be resolved safely.
"""

import argparse
import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# letter -> id the wizard's JS expects (SVG_CELL_MAP in apply_bc_rules.html)
LETTER_TO_TARGET_ID = {
    "A": "rB_text",
    "B": "rC_text",
    "C": "rD_text",
    "D": "rE_text",
    "E": "rF_text",
    "F": "rG_text",
    "G": "rH_text",
    "H": "rI_text",
    "I": "rJ_text",
}

X_TOLERANCE = 8   # px — how far a text box's left edge may drift from (letter.x + letter.width)
Y_TOLERANCE = 6   # px — how far a text box's top edge may drift from the letter's top
MIN_TEXT_BOX_WIDTH = 80  # px — filters out other small chips that aren't the description box

CELL_RE = re.compile(r'<g data-cell-id="([^"]+)">(.*?)</g></g>', re.S)
RECT_RE = re.compile(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"')
TEXT_RE = re.compile(r'<text[^>]*>([^<]*)</text>')


class Cell:
    def __init__(self, cell_id, x, y, w, h, text):
        self.cell_id = cell_id
        self.x, self.y, self.w, self.h = x, y, w, h
        self.text = text

    def __repr__(self):
        return f"Cell({self.cell_id!r}, x={self.x}, y={self.y}, w={self.w}, h={self.h}, text={self.text!r})"


def parse_cells(raw_svg: str) -> list[Cell]:
    cells = []
    for cell_id, body in CELL_RE.findall(raw_svg):
        rect_m = RECT_RE.search(body)
        if not rect_m:
            continue  # edges and other non-rect shapes aren't candidates here
        x, y, w, h = (float(v) for v in rect_m.groups())
        text_matches = TEXT_RE.findall(body)
        text = text_matches[-1].strip() if text_matches else ""
        cells.append(Cell(cell_id, x, y, w, h, text))
    return cells


def find_letter_cells(cells: list[Cell]) -> dict:
    """Returns {letter: Cell}. Raises with a clear message if a letter is missing or duplicated."""
    by_letter = {}
    for cell in cells:
        if cell.text in LETTER_TO_TARGET_ID:
            by_letter.setdefault(cell.text, []).append(cell)

    errors = []
    result = {}
    for letter in LETTER_TO_TARGET_ID:
        matches = by_letter.get(letter, [])
        if not matches:
            errors.append(f"  - Letter '{letter}': no box found with that exact text.")
        elif len(matches) > 1:
            ids = ", ".join(c.cell_id for c in matches)
            errors.append(f"  - Letter '{letter}': found in {len(matches)} boxes ({ids}) — ambiguous.")
        else:
            result[letter] = matches[0]

    if errors:
        raise ValueError(
            "Could not uniquely identify all 9 letter boxes (A-I):\n" + "\n".join(errors)
        )
    return result


def find_text_box(letter_cell: Cell, cells: list[Cell]) -> Cell:
    """Finds the empty description box that sits immediately right of a letter box."""
    target_x = letter_cell.x + letter_cell.w
    candidates = [
        c for c in cells
        if c.text == ""
        and c.w >= MIN_TEXT_BOX_WIDTH
        and abs(c.y - letter_cell.y) <= Y_TOLERANCE
        and abs(c.x - target_x) <= X_TOLERANCE
    ]
    if not candidates:
        raise ValueError(
            f"No empty text box found next to letter '{letter_cell.text}' "
            f"(box at x={letter_cell.x}, y={letter_cell.y}). "
            f"Expected an empty box starting around x={target_x:.0f}, y={letter_cell.y:.0f}."
        )
    if len(candidates) > 1:
        ids = ", ".join(c.cell_id for c in candidates)
        raise ValueError(
            f"Multiple empty boxes found next to letter '{letter_cell.text}' ({ids}) — ambiguous."
        )
    return candidates[0]


def build_rename_map(raw_svg: str) -> dict:
    """Returns {old_id: new_id} for the 9 description boxes, or raises ValueError."""
    cells = parse_cells(raw_svg)
    letter_cells = find_letter_cells(cells)

    rename_map = {}
    problems = []
    for letter, target_id in LETTER_TO_TARGET_ID.items():
        try:
            text_box = find_text_box(letter_cells[letter], cells)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if text_box.cell_id != target_id:
            rename_map[text_box.cell_id] = target_id

    if problems:
        raise ValueError("Could not map every letter to a text box:\n" + "\n".join(f"  - {p}" for p in problems))

    # Safety: never let a rename collide with an id that's staying untouched.
    all_ids = {c.cell_id for c in cells}
    for old_id, new_id in rename_map.items():
        if new_id in all_ids and new_id not in rename_map:
            raise ValueError(f"Target id '{new_id}' already exists on another cell — refusing to overwrite it.")

    return rename_map


def apply_rename_map(raw_svg: str, rename_map: dict) -> str:
    for old_id, new_id in rename_map.items():
        raw_svg = raw_svg.replace(f'"{old_id}"', f'"{new_id}"')
        raw_svg = raw_svg.replace(f'&quot;{old_id}&quot;', f'&quot;{new_id}&quot;')
    return raw_svg


def validate(raw_svg: str) -> None:
    """Well-formedness + sanity checks. Raises ValueError on any problem."""
    try:
        ET.fromstring(raw_svg)
    except ET.ParseError as exc:
        raise ValueError(f"Resulting SVG is not well-formed XML: {exc}") from exc

    content_m = re.search(r'content="([^"]*)"', raw_svg)
    if content_m:
        try:
            ET.fromstring(html.unescape(content_m.group(1)))
        except ET.ParseError as exc:
            raise ValueError(f"Embedded draw.io model is not well-formed XML: {exc}") from exc

    ids = re.findall(r'data-cell-id="([^"]+)"', raw_svg)
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"Duplicate cell ids after renaming: {sorted(dupes)}")

    missing = [tid for tid in LETTER_TO_TARGET_ID.values() if f'data-cell-id="{tid}"' not in raw_svg]
    if missing:
        raise ValueError(f"Expected ids missing after renaming: {missing}")


def main():
    parser = argparse.ArgumentParser(description="Fix bc_diagram.svg cell ids after a draw.io export.")
    parser.add_argument(
        "input", nargs="?", default=None,
        help="Path to the SVG to fix (default: bc_diagram.svg next to this script).",
    )
    parser.add_argument("-o", "--output", default=None, help="Write to this path instead of overwriting the input.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the planned renames, write nothing.")
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else Path(__file__).parent / "bc_diagram.svg"
    if not input_path.exists():
        print(f"error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    raw_svg = input_path.read_text(encoding="utf-8")

    try:
        rename_map = build_rename_map(raw_svg)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not rename_map:
        print("Nothing to do - all 9 ids already match what the wizard expects.")
        return

    print("Planned renames:")
    letter_by_target = {v: k for k, v in LETTER_TO_TARGET_ID.items()}
    for old_id, new_id in rename_map.items():
        print(f"  [{letter_by_target[new_id]}] {old_id}  ->  {new_id}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    fixed_svg = apply_rename_map(raw_svg, rename_map)

    try:
        validate(fixed_svg)
    except ValueError as exc:
        print(f"error: fix produced an invalid file, nothing was written: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = input_path
        backup_path = input_path.with_suffix(input_path.suffix + ".bak")
        backup_path.write_text(raw_svg, encoding="utf-8")
        print(f"Backup written to {backup_path}")

    out_path.write_text(fixed_svg, encoding="utf-8")
    print(f"Fixed file written to {out_path}")


if __name__ == "__main__":
    main()
