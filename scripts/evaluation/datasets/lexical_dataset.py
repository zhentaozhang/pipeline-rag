"""编号类题库（30 题）：条款号 / 子条款号 / 职级代号 / 多解条款号。

与 employee_dataset 的差别：这些题的**题面本身**含精确 token（第9条、9.1、M3、B类城市），
考的是"精确项能不能被检索到并排到前面"，而不是语义改写能力。

gold 一律是 chunk_id（确定性），多解题用 gold_mode="any_of"。
`relevant_contexts` 保留为原文片段，供旧的 bigram 口径并排对比。
"""

from scripts.evaluation.datasets.base import EvalQuestion

LEXICAL_DATASET: list[EvalQuestion] = [
    # ── clause_doc：问"第N条的主题"（答案就是章节标题，确定性强）────────────
    EvalQuestion(
        id="lex001",
        question="《华远科技集团差旅与报销管理制度》第9条的主题是什么？",
        ground_truth_answer="住宿费用限额。",
        relevant_contexts=["第9条 住宿费用限额"],
        relevant_chunk_ids=["2111417685869854735"],
        metadata={"question_kind": "lexical", "lexical_subtype": "clause_doc", "split_hint": "dev"},
    ),
    EvalQuestion(
        id="lex002",
        question="《商务招待与礼品管理制度》第7条的主题是什么？",
        ground_truth_answer="礼品标准。",
        relevant_contexts=["第7条 礼品标准"],
        relevant_chunk_ids=["2111417690164822022"],
        metadata={"question_kind": "lexical", "lexical_subtype": "clause_doc", "split_hint": "dev"},
    ),
    EvalQuestion(
        id="lex003",
        question="《华远科技集团员工手册》第5条的主题是什么？",
        ground_truth_answer="试用期规定。",
        relevant_contexts=["第5条 试用期规定"],
        relevant_chunk_ids=["2111417690865270789"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_doc",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex004",
        question="《华远科技集团差旅与报销管理制度》第6条的主题是什么？",
        ground_truth_answer="高铁/动车（乘坐座席标准）。",
        relevant_contexts=["第6条 高铁/动车"],
        relevant_chunk_ids=["2111417685869854732"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_doc",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex005",
        question="《商务招待与礼品管理制度》第9条的主题是什么？",
        ground_truth_answer="会议接待标准。",
        relevant_contexts=["第9条 会议接待标准"],
        relevant_chunk_ids=["2111417690164822024"],
        metadata={"question_kind": "lexical", "lexical_subtype": "clause_doc", "split_hint": "dev"},
    ),
    # ── clause_sub：问"第N条 N.M 的具体规定"（答案是数字/规则）──────────────
    EvalQuestion(
        id="lex006",
        question="差旅报销制度 9.1 里，总监级及以上人员在 A 类城市的每日住宿上限是多少？",
        ground_truth_answer="800元/晚（含税）。",
        relevant_contexts=["800元/晚", "每日住宿上限（含税）"],
        relevant_chunk_ids=["2111417685869854735"],
        metadata={"question_kind": "lexical", "lexical_subtype": "clause_sub", "split_hint": "dev"},
    ),
    EvalQuestion(
        id="lex007",
        question="差旅报销制度 9.2 对同性别两人同行的住宿有什么要求？",
        ground_truth_answer="须合住一间（总监级及以上除外），按较高职级一方的标准执行。",
        relevant_contexts=["同性别2人同行须合住一间", "按较高职级一方的标准执行"],
        relevant_chunk_ids=["2111417685869854735"],
        metadata={"question_kind": "lexical", "lexical_subtype": "clause_sub", "split_hint": "dev"},
    ),
    EvalQuestion(
        id="lex008",
        question="差旅报销制度 8.1 规定的市内交通费包干标准是多少？",
        ground_truth_answer="每人每天80元包干使用，无需发票。",
        relevant_contexts=["市内交通费每人每天80元包干使用"],
        relevant_chunk_ids=["2111417685869854734"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_sub",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex009",
        question="差旅报销制度 7.1 规定的自驾报销标准是多少？",
        ground_truth_answer="1.2元/公里（含油费、过路费、车辆损耗）。",
        relevant_contexts=["1.2元/公里"],
        relevant_chunk_ids=["2111417685869854733"],
        metadata={"question_kind": "lexical", "lexical_subtype": "clause_sub", "split_hint": "dev"},
    ),
    EvalQuestion(
        id="lex010",
        question="差旅报销制度 5.1 里，经理级人员乘坐飞机的单程票价上限是多少？",
        ground_truth_answer="经济舱，单程票价不超过2500元。",
        relevant_contexts=["经理级（M3）：经济舱，单程票价不超过2500元"],
        relevant_chunk_ids=["2111417685869854731"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_sub",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex011",
        question="差旅报销制度 6.2 里，员工级在什么情况下可以申请一等座？",
        ground_truth_answer="行程超过4小时且无直达高铁时，须在出差申请中注明。",
        relevant_contexts=["行程超过4小时且无直达高铁"],
        relevant_chunk_ids=["2111417685869854732"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_sub",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex012",
        question="商务招待制度 4.1 里，一线城市普通商务招待的人均餐饮标准上限是多少？",
        ground_truth_answer="人均不超过300元（不含酒水）。",
        relevant_contexts=["一线城市：人均不超过300元"],
        relevant_chunk_ids=["2111417690164822019"],
        metadata={"question_kind": "lexical", "lexical_subtype": "clause_sub", "split_hint": "dev"},
    ),
    EvalQuestion(
        id="lex013",
        question="商务招待制度 4.2 里，二线城市重要商务招待的人均餐饮标准上限是多少？",
        ground_truth_answer="人均不超过400元（不含酒水）。",
        relevant_contexts=["二线城市：人均不超过400元"],
        relevant_chunk_ids=["2111417690164822019"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_sub",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex014",
        question="商务招待与礼品管理制度 7.1 规定的常规礼品单价上限是多少？",
        ground_truth_answer="单价不超过200元。",
        relevant_contexts=["常规礼品", "单价不超过200元"],
        relevant_chunk_ids=["2111417690164822022"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_sub",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex015",
        question="员工手册 5.2 规定的试用期薪酬比例是多少？",
        ground_truth_answer="为转正薪酬的80%，且不低于当地最低工资标准。",
        relevant_contexts=["试用期薪酬为转正薪酬的80%"],
        relevant_chunk_ids=["2111417690865270789"],
        metadata={"question_kind": "lexical", "lexical_subtype": "clause_sub", "split_hint": "dev"},
    ),
    # ── clause_grade：题面含职级代号 + 城市类别（精确闭集）──────────────────
    EvalQuestion(
        id="lex016",
        question="差旅报销制度第9条里，总监级及以上（M4+）在 A 类城市的住宿上限是多少？",
        ground_truth_answer="800元/晚。",
        relevant_contexts=["总监级及以上（M4+） | 800元/晚"],
        relevant_chunk_ids=["2111417685869854735"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "dev",
        },
    ),
    EvalQuestion(
        id="lex017",
        question="差旅报销制度第9条里，经理级（M3）在 C 类城市的住宿上限是多少？",
        ground_truth_answer="400元/晚。",
        relevant_contexts=["经理级（M3）", "400元/晚"],
        relevant_chunk_ids=["2111417685869854735"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex018",
        question="差旅报销制度第9条里，员工级（P1-P7/M1-M2）在 B 类城市的住宿上限是多少？",
        ground_truth_answer="350元/晚。",
        relevant_contexts=["员工级（P1-P7/M1-M2）", "350元/晚"],
        relevant_chunk_ids=["2111417685869854735"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex019",
        question="差旅报销制度第9条里，总监级及以上（M4+）在 D 类城市的住宿上限是多少？",
        ground_truth_answer="300美元/晚。",
        relevant_contexts=["300美元/晚"],
        relevant_chunk_ids=["2111417685869854735"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "dev",
        },
    ),
    EvalQuestion(
        id="lex020",
        question="差旅报销制度第5条里，总监级及以上（M4+）乘坐飞机的单程票价上限是多少？",
        ground_truth_answer="可乘坐商务舱/头等舱，单程票价不超过3000元。",
        relevant_contexts=["总监级及以上（M4+）：可乘坐商务舱/头等舱，单程票价不超过3000元"],
        relevant_chunk_ids=["2111417685869854731"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "dev",
        },
    ),
    EvalQuestion(
        id="lex021",
        question="差旅报销制度第5条里，员工级（P1-P7/M1-M2）乘坐飞机的单程票价上限是多少？",
        ground_truth_answer="经济舱，单程票价不超过1500元。",
        relevant_contexts=["员工级（P1-P7/M1-M2）：经济舱，单程票价不超过1500元"],
        relevant_chunk_ids=["2111417685869854731"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex022",
        question="差旅报销制度第6条里，经理级（M3）乘坐高铁的座席标准是什么？",
        ground_truth_answer="一等座。",
        relevant_contexts=["经理级（M3）：一等座"],
        relevant_chunk_ids=["2111417685869854732"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "dev",
        },
    ),
    EvalQuestion(
        id="lex023",
        question="差旅报销制度第6条里，员工级（P1-P7/M1-M2）乘坐高铁的座席标准是什么？",
        ground_truth_answer="二等座。",
        relevant_contexts=["员工级（P1-P7/M1-M2）：二等座"],
        relevant_chunk_ids=["2111417685869854732"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex024",
        question="员工手册第7条里，弹性工时制适用于哪个序列和职级？",
        ground_truth_answer="仅限研发序列 P6 及以上员工，核心工作时间 10:00-16:00。",
        relevant_contexts=["仅限研发序列P6及以上员工", "核心工作时间为10:00-16:00"],
        relevant_chunk_ids=["2111417690865270791"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex025",
        question="员工手册第4条里，竞业限制协议适用于哪些岗位？",
        ground_truth_answer="仅限 P6+/M3+ 岗位。",
        relevant_contexts=["竞业限制协议（仅限P6+/M3+岗位）"],
        relevant_chunk_ids=["2111417690865270788"],
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_grade",
            "split_hint": "test",
        },
    ),
    # ── clause_ambiguous：同一个"第N条"在多份制度里含义不同（any_of）────────
    EvalQuestion(
        id="lex026",
        question="“第3条”在员工手册、差旅制度、商务招待制度里分别规定什么？",
        ground_truth_answer="员工手册=名词定义；差旅制度=城市分类标准；商务招待制度=基本原则。",
        relevant_contexts=["第3条 名词定义", "第3条 城市分类标准", "第3条 基本原则"],
        relevant_chunk_ids=[
            "2111417690865270787",
            "2111417685869854729",
            "2111417690164822018",
        ],
        gold_mode="any_of",
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_ambiguous",
            "split_hint": "dev",
        },
    ),
    EvalQuestion(
        id="lex027",
        question="“第6条”在员工手册、差旅制度、商务招待制度里分别规定什么？",
        ground_truth_answer="员工手册=劳动合同管理；差旅制度=高铁/动车；商务招待制度=餐饮招待审批权限。",
        relevant_contexts=["第6条 劳动合同管理", "第6条 高铁/动车", "第6条 餐饮招待审批权限"],
        relevant_chunk_ids=[
            "2111417690865270790",
            "2111417685869854732",
            "2111417690164822021",
        ],
        gold_mode="any_of",
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_ambiguous",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex028",
        question="“第7条”在员工手册、差旅制度、商务招待制度里分别规定什么？",
        ground_truth_answer="员工手册=工作时间；差旅制度=自驾车；商务招待制度=礼品标准。",
        relevant_contexts=["第7条 工作时间", "第7条 自驾车", "第7条 礼品标准"],
        relevant_chunk_ids=[
            "2111417690865270791",
            "2111417685869854733",
            "2111417690164822022",
        ],
        gold_mode="any_of",
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_ambiguous",
            "split_hint": "dev",
        },
    ),
    EvalQuestion(
        id="lex029",
        question="“第9条”在员工手册、差旅制度、商务招待制度里分别规定什么？",
        ground_truth_answer="员工手册=加班管理；差旅制度=住宿费用限额；商务招待制度=会议接待标准。",
        relevant_contexts=["第9条 加班管理", "第9条 住宿费用限额", "第9条 会议接待标准"],
        relevant_chunk_ids=[
            "2111417690865270800",
            "2111417685869854735",
            "2111417690164822024",
        ],
        gold_mode="any_of",
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_ambiguous",
            "split_hint": "test",
        },
    ),
    EvalQuestion(
        id="lex030",
        question="“第12条”在员工手册、差旅制度、商务招待制度里分别规定什么？",
        ground_truth_answer="员工手册=办公行为规范；差旅制度=报销基本原则；商务招待制度=违规行为。",
        relevant_contexts=["第12条 办公行为规范", "第12条 报销基本原则", "第12条 违规行为"],
        relevant_chunk_ids=[
            "2111417690865270803",
            "2111417685869854738",
            "2111417690164822027",
        ],
        gold_mode="any_of",
        metadata={
            "question_kind": "lexical",
            "lexical_subtype": "clause_ambiguous",
            "split_hint": "dev",
        },
    ),
]
