"""拒答题库：题目本身没有可依据的制度，或问的是制度里不存在的条款。

原来的拒答集只有 7 题（2 题无制度 + 5 题语料缺口），跨跑差 1 题就让拒答率跳 0.14，
任何阈值门禁都失去意义。这批题目的标签不需要人工判断：

- ``no_policy_in_corpus``：主题在 13 份已索引制度里 **零命中**（住房公积金、企业年金、
  班车、通勤、外派、高温补贴……），正确答案只能是"没有相关规定"，编造即失败。
- ``nonexistent_clause``：文档存在、主题相关，但问的条款/数额并不存在（如《员工手册》
  第 88 条、《差旅与报销管理制度》第 40 条、投标保证金、认证考试费），用来抓
  "顺着问题编一条规定"的失败模式 —— 比"完全无关"更难。
"""

from __future__ import annotations

from scripts.evaluation.datasets.base import EvalQuestion


def _ref(
    qid: str,
    question: str,
    reason: str,
    split: str,
    note: str,
) -> EvalQuestion:
    return EvalQuestion(
        id=qid,
        question=question,
        ground_truth_answer="当前知识库中没有相关规定，无法给出结论。",
        relevant_contexts=[],
        answerable=False,
        expected_refusal=True,
        metadata={
            "unanswerable_reason": reason,
            "split_hint": split,
            "note": note,
        },
    )


REFUSAL_DATASET: list[EvalQuestion] = [
    # ── 无制度依据（主题在语料里零命中）────────────────────────────────────
    _ref(
        "ref001",
        "公司为员工缴纳的住房公积金缴存比例是多少？",
        "no_policy_in_corpus",
        "dev",
        "语料无住房公积金制度",
    ),
    _ref(
        "ref002",
        "企业年金的个人缴费与公司配比规则是怎样的？",
        "no_policy_in_corpus",
        "test",
        "语料无年金制度",
    ),
    _ref(
        "ref003",
        "员工生育津贴的申领标准和公司补差比例是多少？",
        "no_policy_in_corpus",
        "dev",
        "语料无生育津贴",
    ),
    _ref(
        "ref004",
        "公司是否提供员工通勤班车，班车路线与发车时间如何安排？",
        "no_policy_in_corpus",
        "test",
        "语料无班车",
    ),
    _ref(
        "ref005",
        "员工的托育津贴或子女入托补贴标准是多少？",
        "no_policy_in_corpus",
        "dev",
        "语料无托育条款（托育/入托命中 0）——原题问通讯补贴，审计发现 01 第11条 11.3 已给 200/400 元标准，已作废",
    ),
    _ref(
        "ref006",
        "员工自带办公电脑是否有设备补贴，标准是多少？",
        "no_policy_in_corpus",
        "test",
        "语料无电脑补贴",
    ),
    _ref(
        "ref007",
        "驻外员工的驻外补贴与探亲假是如何规定的？",
        "no_policy_in_corpus",
        "dev",
        "语料无驻外/探亲",
    ),
    _ref(
        "ref008",
        "夏季高温补贴的发放月份和金额标准是多少？",
        "no_policy_in_corpus",
        "test",
        "语料无高温补贴",
    ),
    _ref(
        "ref009",
        "夜班员工的夜班津贴标准与轮班周期如何计算？",
        "no_policy_in_corpus",
        "dev",
        "语料无夜班津贴",
    ),
    _ref(
        "ref010",
        "员工取得残疾人等级鉴定后可享受哪些岗位安置与补贴政策？",
        "no_policy_in_corpus",
        "test",
        "语料无残疾人安置条款（残疾命中 0）——原题问补充医疗，审计发现 01 第11条 11.5 已给出覆盖范围，已作废",
    ),
    _ref(
        "ref011",
        "员工退休返聘的条件与返聘期间的薪酬如何确定？",
        "no_policy_in_corpus",
        "dev",
        "语料无退休返聘",
    ),
    _ref(
        "ref012",
        "员工入住公司宿舍的申请条件与租金标准是什么？",
        "no_policy_in_corpus",
        "test",
        "语料无宿舍/租房",
    ),
    # ── 文档存在但条款/主题不存在（更难的反例）─────────────────────────────
    _ref(
        "ref013",
        "《华远科技集团员工手册》第 88 条规定了什么内容？",
        "nonexistent_clause",
        "test",
        "手册条款远少于 88 条",
    ),
    _ref(
        "ref014",
        "《差旅与报销管理制度》第 40 条对国际航班的舱位等级是怎么规定的？",
        "nonexistent_clause",
        "dev",
        "该制度无第 40 条，也无国际航班条款",
    ),
    _ref(
        "ref015",
        "《企业采购管理与招投标合规审计规范》规定投标保证金比例是百分之几？",
        "nonexistent_clause",
        "test",
        "语料无投标保证金",
    ),
    _ref(
        "ref016",
        "《员工在职进修与专业资格考证补贴办法》是否报销认证培训课程的学费或教材费？",
        "nonexistent_clause",
        "dev",
        "该办法只覆盖考试费（学费/教材/报名费命中 0，培训仅出现在服务期协议名称里）——原题问考试报名费，入索引后已有答案，已改问未被覆盖的支出",
    ),
    _ref(
        "ref017",
        "《商务招待与礼品管理制度》对海外客户来访的接待标准是如何规定的？",
        "nonexistent_clause",
        "test",
        "语料无海外客户条款",
    ),
    _ref(
        "ref018",
        "《智慧园区公约与办公大楼物业管理指南》规定员工名片印制标准是什么？",
        "nonexistent_clause",
        "dev",
        "语料无名片印制",
    ),
    _ref(
        "ref019",
        "《开源软件引入安全审查与合规引入规程》规定引入代码的采购比价流程是什么？",
        "nonexistent_clause",
        "test",
        "语料无采购比价",
    ),
    _ref(
        "ref020",
        "《员工绩效考核评级与年终激励实施细则》规定的股权激励授予数量是多少？",
        "nonexistent_clause",
        "dev",
        "该细则无股份授予数量（仅有 5.1 授予资格与 5.2 四年归属比例）",
    ),
]
