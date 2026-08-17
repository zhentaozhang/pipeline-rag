"""员工手册基准数据集（量化能力：与当前知识库匹配的评估问题集）

来源：demo_docs/employee_handbook/ 四份真实制度文档（2026-08 实测环境已上传）。
每问含：问题、标准答案（文档条款）、应检出的上下文片段（relevant_contexts，
用于 Recall@K / context_recall 判定）。

用法：评估 runner 默认使用本数据集（与当前知识库匹配，分数有意义）。
"""

from scripts.evaluation.datasets.base import EvalQuestion

EMPLOYEE_DATASET: list[EvalQuestion] = [
    # ═══ 01 员工手册 ═══
    EvalQuestion(
        id="emp001",
        question="试用期时长是如何根据劳动合同期限确定的？",
        ground_truth_answer=(
            "合同期限3个月以上不满1年试用期1个月；1年以上不满3年为2个月；"
            "3年以上或无固定期限为6个月。"
        ),
        relevant_contexts=["合同期限3个月以上不满1年：试用期1个月", "合同期限3年以上或无固定期限：试用期6个月"],
    ),
    EvalQuestion(
        id="emp002",
        question="试用期转正的条件是什么？",
        ground_truth_answer=(
            "考核评分≥70分且无重大违规违纪记录；未达标者可延长试用期1个月（仅一次）或协商解除。"
        ),
        relevant_contexts=["转正条件：考核评分≥70分，无重大违规违纪记录"],
    ),
    EvalQuestion(
        id="emp003",
        question="员工主动辞职需要提前多久通知？",
        ground_truth_answer="正式员工提前30天书面通知；试用期提前3天。",
        relevant_contexts=["员工主动辞职须提前30天书面通知（试用期提前3天）"],
    ),
    EvalQuestion(
        id="emp004",
        question="试用期薪酬如何计算？",
        ground_truth_answer="为转正薪酬的80%，且不低于当地最低工资标准。",
        relevant_contexts=["试用期薪酬为转正薪酬的80%，不低于当地最低工资标准"],
    ),
    EvalQuestion(
        id="emp005",
        question="员工手册的核心价值观包括哪些？",
        ground_truth_answer="客户至上、创新驱动、务实高效、诚信合规。",
        relevant_contexts=["客户至上", "创新驱动", "务实高效", "诚信合规"],
    ),
    # ═══ 02 差旅报销 ═══
    EvalQuestion(
        id="emp006",
        question="A 类城市经理级的每日住宿标准是多少？",
        ground_truth_answer="经理级（M3）在 A 类城市住宿上限为 600 元/晚。",
        relevant_contexts=["经理级（M3）", "600元/晚"],
    ),
    EvalQuestion(
        id="emp007",
        question="员工级在 C 类城市的住宿标准是多少？",
        ground_truth_answer="员工级（P1-P7/M1-M2）在 C 类城市住宿上限 280 元/晚。",
        relevant_contexts=["员工级（P1-P7/M1-M2）", "280元/晚"],
    ),
    EvalQuestion(
        id="emp008",
        question="自驾出差的报销标准是多少？",
        ground_truth_answer="自驾报销标准为 1.2 元/公里（含油费、过路费、车辆损耗）。",
        relevant_contexts=["自驾报销标准：1.2元/公里"],
    ),
    EvalQuestion(
        id="emp009",
        question="出差住宿超标如何处理？",
        ground_truth_answer="需按超标特批流程申请审批，否则超出部分不予报销。",
        relevant_contexts=["超标特批"],
    ),
    EvalQuestion(
        id="emp010",
        question="差旅费用的城市分为哪几类？",
        ground_truth_answer="按消费水平分为 A/B/C/D 四类，A 类为北上广深等一线城市。",
        relevant_contexts=["A类", "B类", "C类", "D类"],
    ),
    # ═══ 03 信息安全 ═══
    EvalQuestion(
        id="emp011",
        question="数据安全等级是如何划分的？",
        ground_truth_answer="分为 L1 公开、L2 内部、L3 敏感、L4 绝密四级。",
        relevant_contexts=["L1 公开", "L2 内部", "L3 敏感", "L4 绝密"],
    ),
    EvalQuestion(
        id="emp012",
        question="薪酬数据属于哪个安全等级？",
        ground_truth_answer="L3 敏感（仅限授权人员访问，含薪酬数据、财务报表、合同文本等）。",
        relevant_contexts=["L3 敏感", "薪酬数据"],
    ),
    EvalQuestion(
        id="emp013",
        question="员工入职时须签署什么文件？",
        ground_truth_answer="数据保密承诺书。",
        relevant_contexts=["入职时须签署数据保密承诺书"],
    ),
    EvalQuestion(
        id="emp014",
        question="L4 绝密数据包含哪些内容？",
        ground_truth_answer="战略规划、并购方案、核心算法源码、未公开专利等，仅极少数核心人员可访问。",
        relevant_contexts=["L4 绝密", "战略规划", "核心算法源码"],
    ),
    EvalQuestion(
        id="emp015",
        question="信息安全管理规范依据哪些法律法规制定？",
        ground_truth_answer="网络安全法、数据安全法、个人信息保护法及 GB/T 相关标准。",
        relevant_contexts=["《中华人民共和国网络安全法》", "《中华人民共和国数据安全法》", "《中华人民共和国个人信息保护法》"],
    ),
    # ═══ 04 商务招待 ═══
    EvalQuestion(
        id="emp016",
        question="商务餐饮招待的基本原则是什么？",
        ground_truth_answer="禁止公款吃喝，招待须有明确的商务目的和事前审批。",
        relevant_contexts=["禁止公款吃喝", "事前审批"],
    ),
    EvalQuestion(
        id="emp017",
        question="单次餐饮招待总额不超过多少由部门负责人审批？",
        ground_truth_answer="单次总额不超过 2000 元由部门负责人审批。",
        relevant_contexts=["单次总额不超过2000元：部门负责人审批"],
    ),
    EvalQuestion(
        id="emp018",
        question="商务招待陪同人数超标如何处理？",
        ground_truth_answer="超标人数须在报销时附书面说明，由事业部负责人审批。",
        relevant_contexts=["超标人数须在报销时附书面说明", "事业部负责人审批"],
    ),
    EvalQuestion(
        id="emp019",
        question="商务招待制度适用于哪些活动？",
        ground_truth_answer="餐饮招待、礼品赠送、会议接待等商务活动。",
        relevant_contexts=["餐饮招待", "礼品赠送", "会议接待"],
    ),
    EvalQuestion(
        id="emp020",
        question="商务礼品赠送有什么限制？",
        ground_truth_answer="礼品须符合制度标准并有事前审批，禁止赠送现金或超出规定的贵重礼品。",
        relevant_contexts=["礼品赠送"],
    ),

    # ═══ 21-30 复杂问题补盲（016 轮 E 项：比较/否定/多跳/数值/流程）═══
    EvalQuestion(
        id="emp021",
        question="连续请 8 天事假需要谁审批？",
        ground_truth_answer="事假超过7天须由事业部负责人审批（≤3天直属上级；3-7天部门负责人；>7天事业部负责人）。",
        relevant_contexts=[">7天 → 事业部负责人审批", "3-7天 → 部门负责人审批"],
    ),
    EvalQuestion(
        id="emp022",
        question="事假和病假的审批权限有什么区别？",
        ground_truth_answer=(
            "事假按天数分层审批（≤3天直属上级/3-7天部门负责人/>7天事业部负责人）；"
            "病假需提供二级及以上医院证明，审批路径按制度规定执行，两者申请条件不同。"
        ),
        relevant_contexts=["事假", "病假", "二级及以上医院"],
    ),
    EvalQuestion(
        id="emp023",
        question="试用期最长可以签多久？",
        ground_truth_answer="6个月（合同期限3年以上或无固定期限的，试用期最长6个月）。",
        relevant_contexts=["合同期限3年以上或无固定期限：试用期6个月"],
    ),
    EvalQuestion(
        id="emp024",
        question="未休的年假最多可以跨年结转几天？",
        ground_truth_answer="最多结转5天，超出部分按日工资300%补偿。",
        relevant_contexts=["未休年假可跨年结转最多5天", "超出部分按日工资300%补偿"],
    ),
    EvalQuestion(
        id="emp025",
        question="单次违纪扣款的金额上限是多少？",
        ground_truth_answer="单次违纪扣款不超过当月工资的20%，且扣款后不低于当地最低工资标准。",
        relevant_contexts=["单次违纪扣款不超过当月工资的20%", "不低于当地最低工资标准"],
    ),
    EvalQuestion(
        id="emp026",
        question="信息安全事件处置的初步研判要求多长时间内完成？",
        ground_truth_answer="初步研判要求在15分钟内完成（安全值班工程师确认事件真实性并初判等级）。",
        relevant_contexts=["初步研判（15分钟内）"],
    ),
    EvalQuestion(
        id="emp027",
        question="信息安全事件处置流程分哪几步？",
        ground_truth_answer="第1步初步研判（15分钟内）；第2步上报对应处置团队；第3步应急处置（网络隔离等）；后续包含调查与恢复等步骤。",
        relevant_contexts=["初步研判（15分钟内）", "第3步：应急处置", "网络隔离"],
    ),
    EvalQuestion(
        id="emp028",
        question="P6 级别研发员工的核心工作时间是几点到几点？",
        ground_truth_answer="弹性工时制仅限研发序列P6及以上员工，核心工作时间为10:00-16:00，须保证每日在岗满8小时。",
        relevant_contexts=["弹性工时制", "P6及以上", "核心工作时间为10:00-16:00"],
    ),
    EvalQuestion(
        id="emp029",
        question="员工每天需要在考勤系统打卡几次？",
        ground_truth_answer="每日须在考勤系统打卡2次（上班+下班），缺卡可在当月处理。",
        relevant_contexts=["每日须在考勤系统打卡2次", "上班+下班"],
    ),
    EvalQuestion(
        id="emp030",
        question="集团内部接待的人均餐饮标准是多少？",
        ground_truth_answer=(
            "集团内部接待（兄弟公司来访、总部检查）工作餐人均不超过80元，不适用酒水；"
            "会议用餐参照第4条（普通商务招待一线城市300元/重要商务招待一线城市600元）。"
        ),
        relevant_contexts=["集团内部接待", "工作餐：人均不超过80元", "不适用酒水"],
    ),
]
