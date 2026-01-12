from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
# autoescape=False: 所有模板是 LLM prompt（非 HTML），不需要 HTML 转义
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False)
