from scripts.evaluation.datasets.combined import ALL_QUESTIONS
from scripts.evaluation.datasets.employee_dataset import EMPLOYEE_DATASET as EMPLOYEE_DATASET
from scripts.evaluation.datasets.seed_data import SEED_DATASET

# 量化能力：默认使用与当前知识库（员工手册）匹配的数据集，评估分数才有意义；
# 如需旧版 FastMCP 主题数据可显式传参。默认集 = 85 道自然语言 + 30 道编号类，
# 只要自然语言那 85 道时用 `--subset emp`。
DEFAULT_DATASET = ALL_QUESTIONS


def load_dataset(seed: bool = False) -> list:
    """加载评估数据集。seed=True 返回历史 FastMCP 主题集，否则返回合并题库"""
    if seed:
        return SEED_DATASET
    return ALL_QUESTIONS
