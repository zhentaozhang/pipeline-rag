"""评测题库合并：85 道自然语言 + 30 道编号类。"""

from scripts.evaluation.datasets.employee_dataset import EMPLOYEE_DATASET
from scripts.evaluation.datasets.lexical_dataset import LEXICAL_DATASET

ALL_QUESTIONS = [*EMPLOYEE_DATASET, *LEXICAL_DATASET]
