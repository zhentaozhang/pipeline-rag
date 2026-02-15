import re
from collections import defaultdict
from typing import NamedTuple

from app.document.structure.models import DocumentStructureLogicalLine
from app.document.structure.patterns import INLINE_EXPLICIT_STEP_BOUNDARY_PATTERN


class LineContext(NamedTuple):
    previous_non_blank: DocumentStructureLogicalLine | None
    next_non_blank: DocumentStructureLogicalLine | None
    blank_before: bool
    blank_after: bool


def build_logical_lines(parsed_text: str) -> list[DocumentStructureLogicalLine]:
    raw_lines = (parsed_text or "").split("\n")
    logical_lines = []
    logical_line_no = 1
    for index, raw_line in enumerate(raw_lines):
        raw_line = raw_line or ""
        segments = _split_inline_segments(raw_line)
        if not segments:
            logical_lines.append(
                DocumentStructureLogicalLine(
                    line_no=logical_line_no,
                    raw_line_index=index + 1,
                    segment_index=1,
                    indent_level=0,
                    raw_text=raw_line,
                    normalized_text=safe_text(raw_line),
                )
            )
            logical_line_no += 1
            continue

        for segment_index, segment in enumerate(segments):
            logical_lines.append(
                DocumentStructureLogicalLine(
                    line_no=logical_line_no,
                    raw_line_index=index + 1,
                    segment_index=segment_index + 1,
                    indent_level=count_indent_level(segment),
                    raw_text=segment,
                    normalized_text=safe_text(segment),
                )
            )
            logical_line_no += 1
    return logical_lines


def _split_inline_segments(raw_line: str) -> list[str]:
    if not raw_line or not raw_line.strip():
        return []
    trimmed = raw_line.strip()
    if trimmed.startswith(("#", "|", ">")) or re.match(r"^[:\-\s|]+$", trimmed):
        return [raw_line]

    boundaries = [0]
    for m in INLINE_EXPLICIT_STEP_BOUNDARY_PATTERN.finditer(raw_line):
        if m.start() > 0:
            boundaries.append(m.start())

    if len(boundaries) == 1:
        return [raw_line]

    segments = []
    for index in range(len(boundaries)):
        start = boundaries[index]
        end = len(raw_line) if index == len(boundaries) - 1 else boundaries[index + 1]
        segment = raw_line[start:end].strip()
        if segment:
            segments.append(segment)
    return segments or [raw_line]


def count_indent_level(text: str) -> int:
    if not text:
        return 0
    indent = 0
    for char in text:
        if char == " ":
            indent += 1
        elif char == "\t":
            indent += 4
        else:
            break
    return indent


def build_line_frequency(logical_lines: list[DocumentStructureLogicalLine]) -> dict[str, int]:
    freq = defaultdict(int)
    for ll in logical_lines:
        if ll.normalized_text:
            freq[ll.normalized_text] += 1
    return dict(freq)


def build_context(
    logical_lines: list[DocumentStructureLogicalLine], current_index: int
) -> LineContext:
    prev_non_blank = None
    blank_before = False
    for i in range(current_index - 1, -1, -1):
        cand = logical_lines[i]
        if not cand.normalized_text:
            blank_before = True
        else:
            prev_non_blank = cand
            break

    next_non_blank = None
    blank_after = False
    for i in range(current_index + 1, len(logical_lines)):
        cand = logical_lines[i]
        if not cand.normalized_text:
            blank_after = True
        else:
            next_non_blank = cand
            break

    return LineContext(prev_non_blank, next_non_blank, blank_before, blank_after)


def safe_text(text: str) -> str:
    return (text or "").strip()
