from scripts.evaluation.datasets.employee_dataset import EMPLOYEE_DATASET
from scripts.evaluation.datasets.seed_data import SEED_DATASET

# 量化能力：默认使用与当前知识库（员工手册）匹配的数据集，评估分数才有意义；
# 如需旧版 FastMCP 主题数据可显式传参。
DEFAULT_DATASET = EMPLOYEE_DATASET


def load_dataset(seed: bool = False) -> list:
    """加载评估数据集。seed=True 返回历史 FastMCP 主题集，否则返回员工手册集"""
    return SEED_DATASET if seed else EMPLOYEE_DATASET
