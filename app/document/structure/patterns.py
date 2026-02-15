import re

MARKDOWN_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")
DECIMAL_HEADING_PATTERN = re.compile(r"^(\d+(?:\.\d+)+)\s*[、.]?\s*(.+)$")
SINGLE_LEVEL_DIGIT_PATTERN = re.compile(r"^(\d+)\s*[、.]\s*(.+)$")
CHAPTER_PATTERN = re.compile(r"^(第([一二三四五六七八九十百\d]+)[章节条部分])\s*(.+)$")
APPENDIX_PATTERN = re.compile(r"^(附录\s*([A-Za-z一二三四五六七八九十百\d]+))(?:\s+(.+))?$")
CHINESE_OUTLINE_PATTERN = re.compile(r"^([一二三四五六七八九十百]+)[、.]\s*(.+)$")
EXPLICIT_STEP_PATTERN = re.compile(
    r"^(?:第\s*([0-9一二三四五六七八九十百]+)\s*步|步骤\s*([0-9一二三四五六七八九十百]+))\s*[:：、.]?\s*(.+)$"
)
BULLET_PATTERN = re.compile(r"^([-*+•])\s+(.+)$")
CHECKBOX_PATTERN = re.compile(r"^\[(?: |x|X)]\s+(.+)$")
PAGE_NOISE_PATTERN = re.compile(r"^(?:第\s*\d+\s*页|Page\s*\d+|\d+\s*/\s*\d+)$", re.IGNORECASE)
COPYRIGHT_NOISE_PATTERN = re.compile(
    r".*(?:版权所有|未经授权|内部使用|copyright|all rights reserved|保密).*", re.IGNORECASE
)
VERSION_FOOTER_PATTERN = re.compile(
    r".*(?:\bV\d+(?:\.\d+)*\b|版本|修订|Rev\.?\s*\d+).*", re.IGNORECASE
)
INLINE_EXPLICIT_STEP_BOUNDARY_PATTERN = re.compile(
    r"(?=(?:第\s*[0-9一二三四五六七八九十百]+\s*步|步骤\s*[0-9一二三四五六七八九十百]+)\s*[:：、.])"
)
TABLE_SPLIT_PATTERN = re.compile(r"\|")
