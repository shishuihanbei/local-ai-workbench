/* 用户端 · 工作台模板、定时任务、工作台抽屉；末尾 bindEvents() / boot() | 原 app.js 第 3928–5189 行 */
"use strict";
  /* ---------------------------------------------------------------- 工作台 */
  const WB_STATUS = {
    ok: ["已完成", "ok"], error: ["失败", "error"], running: ["执行中", "running"],
    skipped: ["条件未满足", "idle"], budget: ["超出预算", "idle"], stopped: ["已停止", "idle"],
  };

  const WB_QUICK_DEFAULT = [
    { label: "写总结", text: "帮我写一份本周工作总结，包含进度、问题和下周计划", format: "" },
    { label: "做 Word", text: "写一份《二次方程》教学计划，包含教学目标、重难点、教学过程和作业，排版准确", format: "docx" },
    { label: "做表格", text: "把下面的数据整理成 Excel 表格，字段清晰，适合直接汇报：", format: "xlsx" },
    { label: "做 PPT", text: "帮我整理一份 10 页以内的 PPT 大纲和每页要点：", format: "pptx" },
  ];

  const WELCOME_QUICK_DEFAULT = [
    { label: "阅读并总结", text: "把下面的文档总结成 5 条要点，标出关键结论和待办：", format: "", desc: "上传 PDF / Word，提炼结论", icon: "file", tone: "blue" },
    { label: "行业动态", text: "联网整理今天的 AI 行业重要动态，输出 5 条，每条附来源链接", format: "", desc: "联网检索，附来源链接", icon: "globe", tone: "purple" },
    { label: "文档生成", text: "把下面的内容整理成一份 Word 文档，结构清晰、可直接使用：", format: "docx", desc: "直接生成 Word / Excel / PPT", icon: "file", tone: "amber" },
    { label: "数据分析", text: "把下面的数据整理成 Excel 表格，字段清晰，适合直接汇报：", format: "xlsx", desc: "整理字段，生成 Excel", icon: "chart", tone: "green" },
  ];

  const WB_PLUGINS = [
    { id: "web", name: "联网检索", desc: "发送前搜索网页，给出来源链接", icon: "search" },
    { id: "kb", name: "知识库检索", desc: "回答前先查本机和个人知识库", icon: "book" },
    { id: "docgen", name: "文档生成", desc: "把结果直接输出成可下载文件", icon: "file" },
  ];

  let WB_TEMPLATES = [
    {
      id: "teacher", icon: "🎓", tone: "blue", name: "教师工作台",
      desc: "教案、练习题、家长通知和课堂总结，一站准备。",
      welcome: "老师，今天有什么教学任务需要帮忙？",
      welcomeSub: "写教案、出练习、做课件、分析学情，选一个开始；也可以直接告诉我年级和课题。",
      skill: "plan", skills: ["plan", "doc_qa", "polish", "summary"], plugins: ["kb", "docgen"],
      quick: [
        { label: "课件生成", text: "围绕《二次方程》生成一份 10 页课件大纲，每页包含标题、讲解要点、例题和课堂互动，输出 PPT", format: "pptx" },
        { label: "编写教案", text: "写一份《二次方程》教学计划，包含教学目标、重难点、教学过程和作业，排版准确", format: "docx" },
        { label: "出题组卷", text: "围绕《二次方程》出 20 道分层练习题，分为基础、提高、拓展三组，附带答案，整理成试卷", format: "docx" },
        { label: "学情分析", text: "根据下面的测验成绩和课堂表现，分析班级掌握情况，按知识点列出薄弱项和分层辅导建议：", format: "docx" },
        { label: "优化课件", text: "帮我优化下面这份课件的结构和表达，按导入、讲解、练习、总结四段重排，并指出可以加入的互动环节：", format: "" },
        { label: "教学视频脚本", text: "把《二次方程》的 5 分钟教学微课写成视频脚本，包含镜头、旁白、字幕和板书", format: "docx" },
        { label: "互动课件", text: "设计一套《二次方程》互动课堂活动，包含提问、分组任务、即时反馈和收尾检测，输出 PPT 大纲", format: "pptx" },
        { label: "家长通知", text: "写一则家长通知，说明本周学习重点、作业安排和需要家长配合的事项", format: "" },
      ],
    },
    {
      id: "finance", icon: "💰", tone: "gold", name: "金融投研工作台",
      desc: "行业动态、公司公告和研报摘要，按你的关注范围整理。",
      welcome: "今天想先看行业、公司，还是财报？",
      welcomeSub: "联网简报、公告摘要、研报提纲和数据表，都可以直接生成文件。",
      skill: "summary", skills: ["summary", "plan", "doc_qa"], plugins: ["web", "docgen"],
      quick: [
        { label: "行业简报", text: "联网整理今天的 AI 行业重要动态，输出 5 条，每条附来源链接，不做投资建议", format: "" },
        { label: "公告摘要", text: "把下面的公司公告整理成 5 条要点，标出对经营可能的影响，不做投资建议：", format: "docx" },
        { label: "研报提纲", text: "围绕以下行业写一份研报提纲，包含行业现状、竞争格局、风险和关键指标：", format: "docx" },
        { label: "财报解读", text: "解读下面这份财报，列出收入、利润、现金流和风险点，用普通人能理解的语言，不做投资建议：", format: "docx" },
        { label: "估值速览", text: "根据下面的公司财务数据，整理 PE、PB、PS 等估值指标和同业对比，注明数据来源，不做投资建议：", format: "xlsx" },
        { label: "数据表", text: "把下面的财务数据整理成 Excel，包含同比、环比和占比，字段清晰：", format: "xlsx" },
        { label: "事件追踪", text: "联网梳理过去 7 天与【公司或行业】相关的重要事件，按时间排序，附来源链接，不做投资建议", format: "" },
        { label: "路演提纲", text: "写一份 10 分钟路演提纲，包含投资逻辑、市场、竞争、财务和风险，不做投资建议", format: "docx" },
      ],
    },
    {
      id: "marketing", icon: "📣", tone: "pink", name: "营销工作台",
      desc: "活动方案、卖点提炼、投放复盘和竞品观察。",
      welcome: "今天要推什么产品，还是复盘哪场活动？",
      welcomeSub: "从活动方案到竞品对比、投放复盘，先把目标和素材告诉我。",
      skill: "plan", skills: ["plan", "polish", "summary"], plugins: ["web", "docgen"],
      quick: [
        { label: "活动方案", text: "为下面的产品写一份 7 天促销活动方案，包含目标、节奏、渠道和预算", format: "docx" },
        { label: "卖点提炼", text: "根据下面的产品资料，提炼 6 个用户能一眼理解的卖点，并给出对应文案", format: "" },
        { label: "竞品对比", text: "把下面几个竞品整理成对比表，从价格、功能、渠道和口碑四方面比较", format: "xlsx" },
        { label: "投放复盘", text: "根据下面的投放数据，写一份复盘，指出有效渠道、浪费点和下一步调整", format: "docx" },
        { label: "内容日历", text: "为下面品牌制定 30 天内容日历，按平台和主题排期，输出 Excel", format: "xlsx" },
        { label: "用户画像", text: "根据下面的数据和描述，整理目标用户画像：需求、场景、痛点、决策因素和触达渠道", format: "docx" },
        { label: "广告文案", text: "为下面产品写 5 组广告文案，分别适合信息流、搜索、朋友圈、短视频和电商详情页", format: "" },
        { label: "达人简报", text: "整理一份达人合作 brief，包含目标、受众、内容方向、交付要求和禁用表达", format: "docx" },
      ],
    },
    {
      id: "design", icon: "🎨", tone: "orange", name: "创意设计工作台",
      desc: "创意方向、配色说明、分镜和设计说明，先把想法说清。",
      welcome: "先聊创意方向，还是直接出分镜和设计说明？",
      welcomeSub: "把品牌、受众和想要的感觉说清楚，我来拆成可执行的方案。",
      skill: "plan", skills: ["plan", "polish"], plugins: [],
      quick: [
        { label: "创意方向", text: "为下面的品牌写 3 个视觉创意方向，分别说明关键词、色彩、构图和适用场景", format: "" },
        { label: "配色方案", text: "为下面这个页面设计 3 套配色方案，给出色值、使用比例和视觉效果说明", format: "" },
        { label: "分镜脚本", text: "把下面的 30 秒广告创意拆成 6 个分镜，包含画面、字幕和节奏", format: "docx" },
        { label: "设计说明", text: "根据下面的设计稿，写一段给客户看的说明，解释设计思路和每个元素的作用", format: "docx" },
        { label: "Logo 概念", text: "为下面品牌设计 3 个 Logo 概念，说明图形、字体、色彩和适用场景", format: "" },
        { label: "海报文案", text: "为下面活动写 3 套海报文案，包含主标题、副标题、行动号召和版式建议", format: "docx" },
        { label: "视觉规范", text: "把下面的品牌视觉整理成一份基础规范，包含色彩、字体、间距、图片风格和禁用示例", format: "docx" },
        { label: "评审清单", text: "根据下面的设计稿，列一份 10 条视觉评审清单，逐条指出问题和修改建议", format: "" },
      ],
    },
    {
      id: "writing", icon: "📚", tone: "violet", name: "写作工作台",
      desc: "长文提纲、改稿、标题和素材整理，先把结构搭稳。",
      welcome: "今天想写长文、改稿，还是先把结构搭出来？",
      welcomeSub: "提纲、润色、标题和素材整理，都可以从一句话开始。",
      skill: "polish", skills: ["polish", "plan", "summary"], plugins: ["docgen"],
      quick: [
        { label: "长文提纲", text: "围绕下面的主题写一份长文提纲，分 4 个部分，每部分列出核心观点和例子", format: "docx" },
        { label: "润色改写", text: "把下面这段文字改得更清楚、更有节奏，保留原意，不要加空洞套话：", format: "" },
        { label: "起标题", text: "根据下面的文章内容，起 10 个不同风格的标题，并说明各自适合的平台", format: "" },
        { label: "素材整理", text: "把下面这些零散素材整理成可用的写作素材库，按主题分类并标注出处", format: "docx" },
        { label: "人物小传", text: "根据下面素材写一篇 800 字人物小传，按时间线和关键事件组织，避免空洞评价：", format: "docx" },
        { label: "故事大纲", text: "把下面的设定扩写成三幕故事大纲，包含人物目标、冲突、转折和结局：", format: "docx" },
        { label: "文风模仿", text: "分析下面样文的句式、节奏和用词，再用同样风格改写我给出的段落：", format: "" },
        { label: "投稿检查", text: "按下面平台的投稿要求检查这篇文章，列出不符合项和修改建议：", format: "" },
      ],
    },
    {
      id: "formal", icon: "📄", tone: "gray", name: "正式材料工作台",
      desc: "通知、总结、汇报和请示，先明确对象、目的和口径。",
      welcome: "这份材料是通知、汇报，还是请示？",
      welcomeSub: "告诉我对象、目的和口径，我按正式格式起草。",
      skill: "polish", skills: ["polish", "plan", "summary"], plugins: ["docgen"],
      quick: [
        { label: "写通知", text: "写一则正式通知，说明事项、时间、地点、参加人员和注意事项", format: "docx" },
        { label: "写汇报", text: "写一份工作汇报，包含进展、数据、问题和下一步安排，语气正式", format: "docx" },
        { label: "写请示", text: "写一份请示，说明背景、请示事项、依据和拟办意见，格式规范", format: "docx" },
        { label: "改材料", text: "把下面的材料改得更符合正式公文口径，保留事实，删掉口语和重复", format: "" },
        { label: "会议纪要", text: "根据下面会议记录整理正式会议纪要，包含时间、参会人、议题、决定和待办", format: "docx" },
        { label: "工作总结", text: "写一份年度工作总结，包含完成情况、数据、问题和明年计划", format: "docx" },
        { label: "讲话稿", text: "为下面场合写 5 分钟讲话稿，语气正式，结构清楚", format: "docx" },
        { label: "公文校对", text: "按公文规范校对下面的材料，标出格式、称谓、数字和逻辑问题", format: "" },
      ],
    },
    {
      id: "media", icon: "🚀", tone: "cyan", name: "新媒体创作工作台",
      desc: "选题、脚本、口播和平台文案，按平台节奏来写。",
      welcome: "今天做选题、短视频，还是直播？",
      welcomeSub: "按平台节奏写脚本、口播和文案，也可以做数据复盘。",
      skill: "plan", skills: ["plan", "polish", "summary"], plugins: ["web", "docgen"],
      quick: [
        { label: "选题清单", text: "围绕下面这个账号定位，给出 20 个近期可做的选题，标注适合的平台和形式", format: "docx" },
        { label: "短视频脚本", text: "把下面的选题写成 45 秒短视频脚本，包含开场钩子、正文和结尾引导", format: "docx" },
        { label: "口播稿", text: "把下面的文章改成 90 秒口播稿，短句、好读、有节奏", format: "" },
        { label: "平台文案", text: "为下面这条内容写 3 版平台文案，分别适合小红书、公众号和视频号", format: "" },
        { label: "直播流程", text: "为下面主题设计 60 分钟直播流程，包含暖场、讲解、互动、转化和收尾", format: "xlsx" },
        { label: "封面标题", text: "为下面视频起 10 个封面标题，控制在 12 字内，并标注适合的平台", format: "" },
        { label: "评论回复", text: "为下面视频写 10 条评论区互动回复，覆盖咨询、质疑和好评", format: "" },
        { label: "数据复盘", text: "根据下面的播放和互动数据写复盘，指出开头、留存和转化的问题", format: "docx" },
      ],
    },
    {
      id: "doctor", icon: "🩺", tone: "teal", name: "医生工作台",
      desc: "健康科普、随访提醒和患者宣教材料，注意表述严谨。",
      welcome: "今天要写科普、患者宣教，还是整理门诊记录？",
      welcomeSub: "涉及诊疗的内容会保持严谨，并提示不能替代就诊。",
      skill: "summary", skills: ["summary", "doc_qa", "polish"], plugins: ["kb", "docgen"],
      quick: [
        { label: "健康科普", text: "写一篇面向普通人的健康科普，主题是高血压日常管理，语言通俗，注明不能替代就诊", format: "" },
        { label: "患者宣教", text: "把下面的注意事项整理成一页患者宣教材料，分点清楚，避免专业术语堆叠", format: "docx" },
        { label: "随访提醒", text: "写一则随访提醒，说明复诊时间、需要携带的资料和日常监测事项", format: "" },
        { label: "门诊记录", text: "把下面的门诊记录整理成规范格式，包含主诉、现病史、处理和随访计划", format: "docx" },
        { label: "用药说明", text: "把下面的用药信息整理成患者能看懂的单页说明，包含用法、注意事项和需要就医的情况，注明不能替代医嘱", format: "docx" },
        { label: "检查解读", text: "用通俗语言解释下面检查报告的关键指标和常见意义，提示需要复诊的情况，不给出诊断：", format: "" },
        { label: "科室培训", text: "围绕下面主题做一份科室培训 PPT 大纲，包含指南要点、流程和注意事项", format: "pptx" },
        { label: "科普问答", text: "围绕下面疾病整理 10 个患者最常问的问题和回答，语言通俗，避免绝对化", format: "docx" },
      ],
    },
    {
      id: "game", icon: "🎮", tone: "indigo", name: "游戏制作工作台",
      desc: "玩法拆解、关卡设计、数值表和项目排期。",
      welcome: "先拆玩法，还是排关卡和数值？",
      welcomeSub: "从核心循环到版本计划，把设计和排期一起理清。",
      skill: "plan", skills: ["plan", "summary"], plugins: ["docgen"],
      quick: [
        { label: "玩法拆解", text: "拆解下面这款游戏的核心循环，说明目标、反馈、成长和留存点", format: "" },
        { label: "关卡设计", text: "为下面这个玩法设计 5 个递进关卡，写明目标、障碍、奖励和难度变化", format: "docx" },
        { label: "数值表", text: "把下面的成长设定整理成 Excel 数值表，包含等级、消耗、产出和节奏", format: "xlsx" },
        { label: "项目排期", text: "把下面的开发内容排成 8 周计划，标出里程碑、依赖和风险", format: "xlsx" },
        { label: "剧情框架", text: "为下面这款游戏写世界观和主线剧情框架，包含冲突、章节和关键节点", format: "docx" },
        { label: "角色设定", text: "设计 5 个核心角色，包含定位、能力、成长和关系", format: "docx" },
        { label: "测试清单", text: "为下面玩法列测试清单，包含功能、边界、性能、兼容和回归项", format: "xlsx" },
        { label: "上线计划", text: "把下面版本内容排成上线计划，包含灰度、监控、回滚和公告", format: "xlsx" },
      ],
    },
  ];

  const WB_TASK_RECOS = [
    {
      id: "price-watch", title: "商品价格监控",
      desc: "持续追踪心仪商品到手价，达到目标价时提醒",
      prompt: "联网查询我关注的商品当前到手价，和我设定的目标价对比。如果达到或低于目标价，直接提醒我并给出购买链接；没达到就简述差距。商品名称和目标价：",
      frequency: "daily", time_of_day: "09:00", weekdays: [1], web_enabled: true,
    },
    {
      id: "weekend", title: "周末好去处",
      desc: "结合天气和本地活动，为你提供周末出行建议",
      prompt: "联网查一下本周末的天气和本地活动，给我 3 个适合周末出行的去处，说明距离、花费、适合人群和预约提醒。",
      frequency: "weekly", time_of_day: "18:00", weekdays: [5], web_enabled: true,
    },
    {
      id: "trivia", title: "学点小知识",
      desc: "每天一个趣味小问答，拓展知识面",
      prompt: "每天讲一个有趣的冷知识，先用一句话抛出问题，再给出答案和简短解释，控制在 200 字以内。",
      frequency: "daily", time_of_day: "08:00", weekdays: [1], web_enabled: false,
    },
    {
      id: "english", title: "每日英语单词",
      desc: "每天 5 个实用单词，带例句和记忆技巧",
      prompt: "每天给我 5 个实用英语单词，附音标、中文释义、一个例句和一个记忆技巧，难度适中。",
      frequency: "daily", time_of_day: "07:30", weekdays: [1], web_enabled: false,
    },
    {
      id: "stock-watch", title: "股价监控",
      desc: "收盘后整理关注股票走势和公开消息，不做投资建议",
      prompt: "联网整理我关注股票今天的收盘表现和公开消息，列出涨跌、成交量和 3 条可能相关的新闻，只做事实整理，不做投资建议。股票代码：",
      frequency: "daily", time_of_day: "15:30", weekdays: [1, 2, 3, 4, 5], web_enabled: true,
    },
    {
      id: "competitor", title: "竞品动态调研",
      desc: "定期跟进竞品动作，整理变化和影响",
      prompt: "联网检索我所在行业的竞品最近动态，整理产品更新、价格变化、营销动作和渠道变化，按重要性排序。行业和竞品名单：",
      frequency: "weekly", time_of_day: "09:00", weekdays: [1], web_enabled: true,
    },
    {
      id: "news", title: "每日新闻推送",
      desc: "汇总行业重要动态，按优先级排序",
      prompt: "联网汇总今天 AI 行业的重要新闻，挑 5 条，按重要性排序，每条附来源链接和一句影响判断。",
      frequency: "daily", time_of_day: "08:00", weekdays: [1], web_enabled: true,
    },
    {
      id: "weekly-summary", title: "每周工作总结",
      desc: "每周五整理本周进展、问题和下周计划",
      prompt: "根据本周聊天记录和下面补充的事项，写一份周工作总结，包含已完成、遇到的问题和下周计划。",
      frequency: "weekly", time_of_day: "17:30", weekdays: [5], web_enabled: false,
    },
  ];

  function wbShort(kind) {
    return ({ docx: "W", xlsx: "X", pptx: "P", pdf: "PDF", md: "MD", txt: "TXT" })[kind] || "F";
  }

  function wbFormatLabel(kind) {
    return OUT_FORMATS[kind] || String(kind || "文件").toUpperCase();
  }

  function wbTemplatesAll() {
    return WB_TEMPLATES.concat((S.wbCustom || []).map((t) => ({
      id: `custom-${t.id}`, dbId: t.id, custom: true, tone: "custom",
      icon: t.icon || "🧩", name: t.name || "我的工作台",
      desc: t.desc || t.description || "", quick: Array.isArray(t.quick) ? t.quick : [],
      skills: Array.isArray(t.skills) && t.skills.length ? t.skills : (t.skill_id ? [t.skill_id] : []),
      skillNames: Array.isArray(t.skill_names) ? t.skill_names : [],
      plugins: Array.isArray(t.plugins) ? t.plugins : [],
    })));
  }

  function wbSkillsOf(t) {
    if (!t) return [];
    if (Array.isArray(t.skills) && t.skills.length) return t.skills;
    return t.skill ? [t.skill] : [];
  }

  function wbSkillNamesOf(t) {
    return wbSkillsOf(t).map((id, i) => {
      const known = (S.skills || []).find((s) => s.id === id);
      return (known && known.name) || (t && (t.skillNames || t.skill_names) && (t.skillNames || t.skill_names)[i]) || id;
    });
  }

  function wbSkillName(id) {
    if (!id) return "";
    return ((S.skills || []).find((s) => s.id === id) || {}).name || id;
  }

  function wbPluginName(id) {
    return (WB_PLUGINS.find((p) => p.id === id) || {}).name || id;
  }

  function wbTemplateOf(id = S.wbTemplate) {
    return wbTemplatesAll().find((t) => t.id === id) || null;
  }

  function renderWbHero() {
    const tpl = wbTemplateOf();
    const kicker = $("#wbHeroKicker");
    const title = $("#wbHeroTitle");
    const sub = $("#wbHeroSub");
    const browse = $("#wbHeroBrowse");
    const custom = $("#wbHeroCustom");
    const share = $("#wbHeroShare");
    const exit = $("#wbHeroExit");
    const caps = $("#wbHeroCaps");
    const art = $("#wbHeroArt");
    if (!kicker || !title || !sub) return;
    $("#wbHero").classList.toggle("active", !!tpl);
    if (exit) exit.hidden = !tpl;
    if (art) {
      art.innerHTML = tpl
        ? `<span class="wb-hero-emoji">${esc(tpl.icon || "🧩")}</span><span class="wb-hero-emoji-ring"></span>`
        : `<span class="wb-art-card a">◧</span><span class="wb-art-card b">▤</span><span class="wb-art-orb">✦</span>`;
    }
    if (tpl) {
      kicker.textContent = `正在使用 · ${tpl.name}`;
      title.textContent = tpl.welcome || `${tpl.name}已就绪`;
      sub.textContent = tpl.welcomeSub || tpl.desc;
      if (browse) browse.innerHTML = "换一个模板 <span>›</span>";
    } else {
      kicker.textContent = "定制专属工作台";
      title.textContent = "轻松开工，从一组常用任务开始";
      sub.textContent = "选一个模板，快捷提示和定时任务都会跟着换。";
      if (browse) browse.innerHTML = "浏览推荐 <span>›</span>";
    }
    if (caps) {
      const skills = wbSkillsOf(tpl);
      const names = wbSkillNamesOf(tpl);
      const plugins = tpl ? (tpl.plugins || []).map(wbPluginName) : [];
      caps.hidden = !skills.length && !plugins.length;
      caps.innerHTML = [
        ...skills.map((sid, i) => {
          const on = S.skill && S.skill.id === sid;
          return `<button type="button" class="wb-cap-skill ${on ? "on" : ""}" data-wb-hero-skill="${esc(sid)}" title="使用「${esc(names[i])}」">技能 · ${esc(names[i])}</button>`;
        }),
        plugins.length ? `<span class="wb-cap-plugin">插件 · ${esc(plugins.join(" / "))}</span>` : "",
      ].join("");
    }
    if (custom) custom.innerHTML = tpl ? (tpl.custom ? "✎ 编辑当前" : "+ 自定义这套") : "+ 自定义工作台";
    if (share) share.hidden = !tpl;
  }

  function renderWbQuick() {
    const box = $("#wbQuick");
    if (!box) return;
    const tpl = wbTemplateOf();
    const items = tpl ? tpl.quick : WB_QUICK_DEFAULT;
    $("#wbQuickTitle").textContent = tpl ? `${tpl.name} · 快捷开始` : "快捷开始";
    box.innerHTML = items.map((x) => `
      <button type="button" data-wb-prompt="${esc(x.text)}" data-wb-format="${esc(x.format || "")}">${esc(x.label)}</button>`).join("");
  }

  function wbTemplateMeta(t) {
    const names = wbSkillNamesOf(t);
    const plugins = (t.plugins || []).map(wbPluginName);
    if (!names.length && !plugins.length) return "";
    return `<span class="wb-template-meta">
      ${names.length ? `<i class="skill" title="${esc(names.join(" / "))}">技能 · ${esc(names.join(" / "))}</i>` : ""}
      ${plugins.length ? `<i class="plugin">插件 · ${esc(plugins.join(" / "))}</i>` : ""}
    </span>`;
  }

  function wbTemplateCard(t) {
    const active = t.id === S.wbTemplate;
    return `<div class="wb-template ${active ? "active" : ""} ${t.custom ? "custom" : ""}" data-wb-template-card="${esc(t.id)}">
      <button type="button" class="wb-template-main" data-wb-template="${esc(t.id)}" aria-pressed="${active ? "true" : "false"}">
        <span class="wb-template-icon ${esc(t.tone)}">${esc(t.icon)}</span>
        <span class="wb-template-copy">
          <b>${esc(t.name)}${t.custom ? `<em>自建</em>` : ""}</b>
          <small>${esc(t.desc || "还没有说明，点「自定义」补充。")}</small>
          ${wbTemplateMeta(t)}
        </span>
      </button>
      <div class="wb-template-actions">
        <button type="button" class="wb-template-use ${active ? "on" : ""}" data-wb-template-use="${esc(t.id)}">${active ? "使用中" : "使用"}</button>
        <button type="button" class="wb-template-tool" data-wb-template-edit="${esc(t.id)}" title="${t.custom ? "编辑" : "自定义"}这套工作台">
          <svg><use href="#i-edit"/></svg><span>${t.custom ? "编辑" : "自定义"}</span>
        </button>
        <button type="button" class="wb-template-tool" data-wb-template-share="${esc(t.id)}" title="分享这套工作台">
          <svg><use href="#i-share"/></svg><span>分享</span>
        </button>
      </div>
    </div>`;
  }

  function renderWbTemplates() {
    const box = $("#wbTemplateGrid");
    const mine = $("#wbMyTemplateGrid");
    const mineSection = $("#wbMyTemplateSection");
    const custom = wbTemplatesAll().filter((t) => t.custom);
    if (mineSection) mineSection.hidden = custom.length === 0;
    if (mine) mine.innerHTML = custom.map(wbTemplateCard).join("");
    if (!box) return;
    box.innerHTML = WB_TEMPLATES.map(wbTemplateCard).join("");
    renderActiveWb();
  }

  function renderWbTaskRecos() {
    const box = $("#wbTaskReco");
    if (!box) return;
    box.innerHTML = WB_TASK_RECOS.map((t) => `
      <button type="button" class="wb-reco-task" data-wb-task-preset="${esc(t.id)}">
        <span class="wb-reco-main"><b>${esc(t.title)}</b><small>${esc(t.desc)}</small></span>
        <span class="wb-reco-plus" aria-hidden="true">+</span>
      </button>`).join("");
  }

  async function loadWbCustomTemplates() {
    try {
      const d = await api("/api/workbench/templates");
      S.wbCustom = (d.items || []).map((t) => ({
        id: t.id, name: t.name, icon: t.icon || "🧩",
        desc: t.description || "", quick: Array.isArray(t.quick) ? t.quick : [],
        skills: Array.isArray(t.skills) ? t.skills : (t.skill_id ? [t.skill_id] : []),
        skill_names: Array.isArray(t.skill_names) ? t.skill_names : [],
        skill_id: t.skill_id || "",
        plugins: Array.isArray(t.plugins) ? t.plugins : [],
      }));
    } catch {
      S.wbCustom = S.wbCustom || [];
    }
  }

  async function importSharedWbTemplate() {
    let raw = "";
    try { raw = localStorage.getItem("wb_shared_import") || ""; } catch {}
    if (!raw) return;
    let data = null;
    try { data = JSON.parse(raw); } catch {}
    if (!data || !data.name || !Array.isArray(data.quick) || !data.quick.length) {
      try { localStorage.removeItem("wb_shared_import"); } catch {}
      return;
    }
    try {
      const saved = await api("/api/workbench/templates", {
        method: "POST",
        body: {
          name: String(data.name).slice(0, 40),
          icon: String(data.icon || "🧩").slice(0, 8),
          description: String(data.description || "").slice(0, 200),
          quick: data.quick,
          skills: Array.isArray(data.skills) ? data.skills : [],
          skill_id: String(data.skill_id || "").slice(0, 80),
          plugins: Array.isArray(data.plugins) ? data.plugins : [],
        },
      });
      try { localStorage.removeItem("wb_shared_import"); } catch {}
      await loadWbCustomTemplates();
      applyWbTemplate(`custom-${saved.id}`);
      toast(`已导入分享的工作台「${saved.name}」`);
    } catch (e) {
      // 未登录或网络失败时保留待导入数据，登录后会再次尝试。
    }
  }

  async function loadActiveWb() {
    try {
      const d = await api("/api/workbench/active");
      S.wbTemplate = d.key || "";
    } catch {
      S.wbTemplate = "";
    }
  }

  async function persistActiveWb(key) {
    try {
      await api("/api/workbench/active", { method: "PUT", body: { key } });
    } catch {}
  }

  function renderActiveWb() {
    const box = $("#sideActiveWb");
    if (!box) return;
    const tpl = wbTemplateOf();
    box.hidden = !tpl;
    if (!tpl) return;
    $("#sideActiveWbIcon").textContent = tpl.icon || "🧩";
    $("#sideActiveWbName").textContent = tpl.name;
  }

  async function initWbRecommendations() {
    await loadActiveWb();
    await loadWbCustomTemplates();
    await importSharedWbTemplate();
    if (!wbTemplateOf()) S.wbTemplate = "";
    const current = wbTemplateOf();
    if (current) applyWbCapabilities(current);
    renderWbHero();
    renderWbTemplates();
    renderWbQuick();
    renderWbTaskRecos();
    renderActiveWb();
    updateWelcome();
  }

  function applyWbCapabilities(tpl) {
    if (!tpl) return;
    const firstSkill = wbSkillsOf(tpl)[0] || "";
    setSkill(firstSkill || null);
    const plugins = tpl.plugins || [];
    setWeb(plugins.includes("web"));
    const useKb = plugins.includes("kb");
    S.prefs = { ...(S.prefs || PREF_DEFAULT), useKb };
    savePrefs({ useKb });
    if ($("#setKb")) $("#setKb").checked = useKb;
    renderWbCaps();
  }

  function applyWbTemplate(id) {
    const tpl = wbTemplateOf(id);
    if (!tpl) return;
    S.wbTemplate = tpl.id;
    persistActiveWb(tpl.id);
    applyWbCapabilities(tpl);
    renderWbHero();
    renderWbTemplates();
    renderWbQuick();
    renderActiveWb();
    renderWelcomeHome();
    toast(`已套用「${tpl.name}」`);
  }

  function openWbHome(id) {
    const tpl = wbTemplateOf(id);
    if (!tpl) return;
    applyWbTemplate(tpl.id);
    closeWorkbench();
    newChat(false);
    applyWbCapabilities(tpl);
    updateWelcome();
    renderActiveWb();
    setTimeout(() => $("#messageInput").focus(), 80);
  }

  function closeActiveWb() {
    if (!S.wbTemplate) return;
    S.wbTemplate = "";
    persistActiveWb("");
    setSkill(null);
    setWeb(false);
    S.prefs = { ...(S.prefs || PREF_DEFAULT), useKb: false };
    savePrefs({ useKb: false });
    if ($("#setKb")) $("#setKb").checked = false;
    renderWbHero();
    renderWbTemplates();
    renderWbQuick();
    renderWbCaps();
    renderActiveWb();
    updateWelcome();
    toast("已关闭当前工作台");
  }

  function wbQuickEditorRows(items = []) {
    const rows = Array.from({ length: Math.max(4, items.length) }, (_, i) => items[i] || { label: "", text: "", format: "" });
    const formats = [["", "直接回答"], ["docx", "Word"], ["xlsx", "Excel"], ["pptx", "PPT"], ["pdf", "PDF"]];
    return rows.map((q, i) => `
      <div class="wb-edit-quick" data-wb-q="${i}">
        <div class="wb-edit-quick-head">
          <input class="wb-q-label" maxlength="20" placeholder="按钮名称，例如：写方案" value="${collabEsc(q.label || "")}">
          <select class="wb-q-format">${formats.map(([v, label]) => `<option value="${v}" ${String(q.format || "") === v ? "selected" : ""}>${label}</option>`).join("")}</select>
        </div>
        <textarea class="wb-q-text" rows="2" maxlength="600" placeholder="点这个按钮后，自动填进输入框的内容">${collabEsc(q.text || "")}</textarea>
      </div>`).join("");
  }

  function openWbTemplateEditor(template = null, builtin = false) {
    const icons = ["🎓", "💰", "📣", "🎨", "📚", "📄", "🚀", "🩺", "🎮", "🧩"];
    const initial = template || {
      name: "", icon: "🧩", desc: "", skills: [], plugins: [],
      quick: [{ label: "", text: "", format: "" }],
    };
    const isCustom = !!(template && template.custom);
    const initialSkills = wbSkillsOf(initial);
    const skillPicks = (S.skills || []).map((s) => `
      <label class="wb-skill-pick"><input type="checkbox" data-wb-tpl-skill="${collabEsc(s.id)}" ${initialSkills.includes(s.id) ? "checked" : ""}>
        <span>${collabEsc(s.name)}</span><small>${collabEsc(s.hint || "")}</small></label>`).join("");
    const pluginPicks = WB_PLUGINS.map((p) => `
      <label class="wb-plugin-pick"><input type="checkbox" data-wb-tpl-plugin="${p.id}" ${(initial.plugins || []).includes(p.id) ? "checked" : ""}>
        <span>${collabEsc(p.name)}</span></label>`).join("");
    openCollab(isCustom ? "编辑工作台" : (builtin ? "自定义这套工作台" : "新建工作台"), `
      <div class="wb-editor-note">${builtin ? "保存后会生成一份属于你的副本，原始推荐模板不会变。" : "名称、图标、说明、技能、插件和快捷按钮都可以自己定。"}</div>
      <div class="wb-editor-top">
        <label class="collab-field wb-icon-field"><span>图标</span><input id="wbtplIcon" maxlength="8" value="${collabEsc(initial.icon || "🧩")}"></label>
        <label class="collab-field"><span>工作台名称</span><input id="wbtplName" maxlength="40" placeholder="例如：内容运营工作台" value="${collabEsc(initial.name || "")}"></label>
      </div>
      <div class="wb-emoji-row">${icons.map((x) => `<button type="button" data-wb-emoji="${x}">${x}</button>`).join("")}</div>
      <label class="collab-field"><span>一句话说明</span><input id="wbtplDesc" maxlength="200" placeholder="这个工作台主要帮你做什么" value="${collabEsc(initial.desc || "")}"></label>
      <div class="wb-editor-caps">
        <div class="collab-field"><span>包含技能</span><div class="wb-skill-picks">${skillPicks}</div></div>
        <div class="collab-field"><span>默认插件</span><div class="wb-plugin-picks">${pluginPicks}</div></div>
        <div class="wb-editor-note">技能可以多选，至少选一个；套用后默认使用第一个，其余技能在工作台顶部可随时切换。插件会随工作台自动打开。</div>
      </div>
      <div class="wb-editor-sub"><b>快捷按钮</b><span>最多填 8 个，至少填 1 个；留空的会自动忽略。</span></div>
      <div class="wb-edit-quicks">${wbQuickEditorRows(initial.quick || [])}</div>
      <div class="wb-editor-actions">
        <button class="btn primary sm" type="button" id="wbtplSave">保存并套用</button>
        <button class="btn ghost sm" type="button" id="wbtplCancel">取消</button>
        ${isCustom ? `<button class="wb-editor-danger" type="button" id="wbtplDelete">删除这个工作台</button>` : ""}
      </div>`);
    $("#collabModal").classList.add("over-wb");
    $$("[data-wb-emoji]").forEach((btn) => btn.addEventListener("click", () => {
      $("#wbtplIcon").value = btn.dataset.wbEmoji;
    }));
    $("#wbtplCancel").addEventListener("click", closeCollab);
    $("#wbtplSave").addEventListener("click", () => saveWbTemplateEditor(isCustom ? template.dbId : null));
    if ($("#wbtplDelete")) {
      $("#wbtplDelete").addEventListener("click", () => deleteWbTemplate(template));
    }
    setTimeout(() => $("#wbtplName").focus(), 60);
  }

  async function saveWbTemplateEditor(editId = null) {
    const name = $("#wbtplName").value.trim();
    const icon = $("#wbtplIcon").value.trim() || "🧩";
    const description = $("#wbtplDesc").value.trim();
    const quick = $$(".wb-edit-quick").map((row) => ({
      label: $(".wb-q-label", row).value.trim(),
      text: $(".wb-q-text", row).value.trim(),
      format: $(".wb-q-format", row).value,
    })).filter((q) => q.label || q.text);
    if (!name) return toast("先给工作台起个名字");
    if (!quick.length) return toast("至少填一个快捷按钮");
    if (quick.some((q) => !q.label || !q.text)) return toast("每个快捷按钮都要有名称和提示词");
    if (quick.length > 8) return toast("快捷按钮最多 8 个");
    const pickedSkills = $$("[data-wb-tpl-skill]:checked").map((x) => x.dataset.wbTplSkill);
    if (!pickedSkills.length) return toast("至少选择一个技能");
    const body = {
      name, icon, description, quick,
      skills: pickedSkills,
      skill_id: pickedSkills[0] || "",
      plugins: $$("[data-wb-tpl-plugin]:checked").map((x) => x.dataset.wbTplPlugin),
    };
    try {
      const saved = editId
        ? await api(`/api/workbench/templates/${editId}`, { method: "PUT", body })
        : await api("/api/workbench/templates", { method: "POST", body });
      await loadWbCustomTemplates();
      applyWbTemplate(`custom-${saved.id}`);
      closeCollab();
      toast(editId ? `「${saved.name}」已保存` : `「${saved.name}」已创建并套用`);
    } catch (e) {
      toast(e.message || "保存失败");
    }
  }

  async function deleteWbTemplate(template) {
    if (!template || !template.dbId) return;
    if (!window.confirm(`确定删除「${template.name}」？这个操作不能撤销。`)) return;
    try {
      await api(`/api/workbench/templates/${template.dbId}`, { method: "DELETE" });
      if (S.wbTemplate === template.id) {
        S.wbTemplate = "";
        persistActiveWb("");
      }
      await loadWbCustomTemplates();
      renderWbHero(); renderWbTemplates(); renderWbQuick(); renderActiveWb();
      closeCollab();
      toast("工作台已删除");
    } catch (e) {
      toast(e.message || "删除失败");
    }
  }

  function openWbShareDialog(template) {
    if (!template) return;
    openCollab("分享工作台", `
      <div class="wb-share-preview">
        <span class="wb-template-icon ${collabEsc(template.tone || "custom")}">${collabEsc(template.icon || "🧩")}</span>
        <div><b>${collabEsc(template.name)}</b><small>${collabEsc(template.desc || "包含一组快捷开始按钮")}</small>${wbTemplateMeta(template)}</div>
      </div>
      <div class="collab-field"><span>链接有效期</span>
        <select id="wbShareDays"><option value="7">7 天</option><option value="30" selected>30 天</option><option value="0">永久有效</option></select>
      </div>
      <div class="collab-row"><button class="btn primary sm" type="button" id="wbDoShare">生成分享链接</button></div>
      <div class="collab-result" id="wbShareResult" hidden></div>
      <div class="wb-editor-note">收到链接的人可以直接查看这套工作台，并一键导入成自己的自定义工作台。</div>`);
    $("#collabModal").classList.add("over-wb");
    $("#wbDoShare").addEventListener("click", async () => {
      const days = Number($("#wbShareDays").value || 0);
      try {
        const d = await api("/api/workbench/shares", {
          method: "POST",
          body: {
            name: template.name, icon: template.icon || "🧩",
            description: template.desc || "", quick: template.quick,
            skill_id: template.skill || "", plugins: template.plugins || [],
            expires_days: days,
          },
        });
        const url = location.origin + (d.url || `/wb/${d.token}`);
        const box = $("#wbShareResult");
        box.hidden = false;
        box.innerHTML = `<div>链接已生成，可直接发给同事：</div>
          <div style="margin-top:6px"><a href="${collabEsc(url)}" target="_blank" rel="noreferrer">${collabEsc(url)}</a></div>
          <div class="collab-row" style="margin-top:8px"><button class="btn ghost sm" type="button" id="wbCopyShare" data-url="${collabEsc(url)}">复制链接</button></div>`;
        $("#wbCopyShare").addEventListener("click", async () => {
          try { await navigator.clipboard.writeText(url); toast("链接已复制"); }
          catch { toast("复制失败，请手动选中链接"); }
        });
      } catch (e) {
        toast(e.message || "生成分享链接失败");
      }
    });
  }


  function renderWbCaps() {
    const skillGrid = $("#wbSkillGrid");
    const pluginGrid = $("#wbPluginGrid");
    if (!skillGrid || !pluginGrid) return;
    const activeSkill = S.skill ? S.skill.id : "";
    const skills = S.skills || [];
    $("#wbCapSkillState").textContent = S.skill ? `当前 · ${S.skill.name}` : "当前不使用技能";
    skillGrid.innerHTML = `
      <button type="button" class="wb-skill-card ${!S.skill ? "active" : ""}" data-wb-skill="none">
        <span class="wb-skill-icon none"><svg><use href="#i-spark"/></svg></span>
        <span class="wb-skill-copy"><b>不使用技能</b><small>按普通对话发送</small></span>
        <span class="wb-skill-state">${!S.skill ? "使用中" : "选择"}</span>
      </button>` + skills.map((s) => {
        const icon = SKILL_ICONS[s.icon] || "i-spark";
        const on = activeSkill === s.id;
        return `<button type="button" class="wb-skill-card ${on ? "active" : ""}" data-wb-skill="${esc(s.id)}">
          <span class="wb-skill-icon"><svg><use href="#${icon}"/></svg></span>
          <span class="wb-skill-copy"><b>${esc(s.name)}</b><small>${esc(s.hint || "按这个方向回答")}</small></span>
          <span class="wb-skill-state">${on ? "使用中" : "选择"}</span>
        </button>`;
      }).join("");
    const webOn = !!S.web;
    const kbOn = !!(S.prefs && S.prefs.useKb);
    const fmt = OUT_FORMATS[S.outputFormat] || "";
    const pluginLabels = [webOn ? "联网" : "", kbOn ? "知识库" : "", fmt ? fmt : ""].filter(Boolean);
    if ($("#wbCapSummary")) {
      $("#wbCapSummary").innerHTML = `
        <span class="${S.skill ? "" : "muted"}">技能 · ${esc(S.skill ? S.skill.name : "普通对话")}</span>
        <span class="${pluginLabels.length ? "" : "muted"}">插件 · ${esc(pluginLabels.join(" / ") || "未开启")}</span>`;
    }
    pluginGrid.innerHTML = `
      <div class="wb-plugin-card ${webOn ? "on" : ""}">
        <span class="wb-plugin-icon"><svg><use href="#i-search"/></svg></span>
        <div class="wb-plugin-copy"><b>联网检索</b><small>发送前搜索网页，附来源链接</small></div>
        <label class="wb-mini-switch"><input type="checkbox" data-wb-plugin-toggle="web" ${webOn ? "checked" : ""}><span></span></label>
      </div>
      <div class="wb-plugin-card ${kbOn ? "on" : ""}">
        <span class="wb-plugin-icon"><svg><use href="#i-book"/></svg></span>
        <div class="wb-plugin-copy"><b>知识库检索</b><small>回答前先查本机和个人知识库</small></div>
        <label class="wb-mini-switch"><input type="checkbox" data-wb-plugin-toggle="kb" ${kbOn ? "checked" : ""}><span></span></label>
      </div>
      <div class="wb-plugin-card ${fmt ? "on" : ""}">
        <span class="wb-plugin-icon"><svg><use href="#i-file"/></svg></span>
        <div class="wb-plugin-copy"><b>文档生成</b><small>${fmt ? `当前输出：${esc(fmt)}` : "选格式后直接生成可下载文件"}</small></div>
        <select class="wb-plugin-format" data-wb-plugin-format>
          <option value="">只在对话里回答</option>
          ${Object.entries(OUT_FORMATS).map(([v, label]) => `<option value="${v}" ${S.outputFormat === v ? "selected" : ""}>${label}</option>`).join("")}
        </select>
      </div>`;
    $("#wbCapNote").textContent = "套用工作台会按模板自动切换，手动选择只影响接下来的对话。";
  }


  function setWorkbenchBadge(n) {
    const badge = $("#workbenchBadge");
    if (!badge) return;
    const count = Math.max(0, Number(n) || 0);
    badge.hidden = count <= 0;
    badge.textContent = count > 9 ? "9+" : String(count);
  }

  function closeWorkbench() {
    $("#workbenchDrawer").hidden = true;
  }

  function openWorkbench(tab = "overview") {
    if (!S.user) return showAuth();
    if (!frontOn("workbench")) return;
    closeSettings?.();
    $("#workbenchDrawer").hidden = false;
    setWorkbenchBadge(0);
    setWbTab(tab);
    loadWorkbench().catch((e) => toast(e.message));
    if (window.innerWidth <= 900) closeSidebar();
  }

  function setWbTab(tab) {
    let target = ["overview", "tasks", "files", "caps"].includes(tab) ? tab : "overview";
    const need = { tasks: "schedule", files: "files", caps: "skills" }[target];
    if (need && !frontOn(need)) target = "overview";
    S.wbTab = target;
    const head = {
      overview: ["WORKBENCH", "工作台", "任务、文件、最近对话，都在这里。"],
      tasks: ["SCHEDULE", "定时任务", "按你的时间自动开工，结果会留在会话里。"],
      caps: ["CAPABILITIES", "技能与插件", "选好回答方式和插件能力，下一条消息立即生效。"],
      files: ["FILES", "生成文件", "这里保存所有真实生成的文件，可直接下载。"],
    }[target];
    if ($("#wbHeadKicker")) $("#wbHeadKicker").textContent = head[0];
    if ($("#workbenchTitle")) $("#workbenchTitle").textContent = head[1];
    if ($("#wbHeadSub")) $("#wbHeadSub").textContent = head[2];
    $$("#wbTabs button").forEach((b) => b.classList.toggle("active", b.dataset.wtab === target));
    $$(".wb-pane").forEach((p) => {
      const on = p.id === `wpanel-${target}`;
      p.hidden = !on;
      p.classList.toggle("active", on);
    });
    if (target === "tasks") loadWbTasks().catch(() => {});
    if (target === "files") loadWbFiles().catch(() => {});
    if (target === "caps") renderWbCaps();
  }

  function renderWbOverview(ov) {
    S.wbOverview = ov || {};
    const counts = (ov && ov.counts) || {};
    $("#wbStatConv").textContent = String(counts.conversations || 0);
    $("#wbStatFiles").textContent = String(counts.files || 0);
    $("#wbStatTasks").textContent = String(counts.tasks || 0);
    $("#wbStatRuns").textContent = String(counts.runs_24h || 0);

    const upcoming = (ov && ov.upcoming) || [];
    $("#wbUpcoming").innerHTML = upcoming.length ? upcoming.map((t) => `
      <button type="button" class="wb-item" data-wb-task-open="${t.id}">
        <span class="wb-ico">${t.frequency === "once" ? "1" : "↻"}</span>
        <span class="wb-main"><b>${esc(t.title)}</b><small>${esc(t.schedule)}${t.trigger_mode === "event" ? "" : ` · 下次 ${esc(t.next_run_text || "待计算")}`}</small></span>
        <span class="wb-go">›</span>
      </button>`).join("") : `<div class="wb-empty">还没有启用的定时任务</div>`;

    renderWbFiles((ov && ov.files) || [], $("#wbRecentFiles"), true);

    const chats = (ov && ov.conversations) || [];
    $("#wbRecentChats").innerHTML = chats.length ? chats.map((c) => `
      <button type="button" class="wb-item" data-wb-conv="${c.id}">
        <span class="wb-ico">AI</span>
        <span class="wb-main"><b>${esc(c.title || "未命名对话")}</b><small>${esc(fmtTime(c.updated_at))}</small></span>
        <span class="wb-go">›</span>
      </button>`).join("") : `<div class="wb-empty">还没有对话</div>`;
  }

  function renderWbFiles(items, box, compact = false) {
    if (!box) return;
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) {
      box.innerHTML = `<div class="wb-empty">还没有生成文件。聊天时选择 Word / Excel / PPT / PDF 等格式，文件会出现在这里。</div>`;
      return;
    }
    box.innerHTML = rows.map((f) => {
      const expiry = fileExpiry(f);
      const extra = expiry.text ? ` · <span class="file-expiry">${esc(expiry.text)}</span>` : "";
      const action = expiry.download
        ? `<span class="file-actions">
             <button type="button" class="file-act" data-preview-file="${esc(f.id)}" data-file-name="${esc(f.name)}">
               <svg><use href="#i-file"/></svg>预览</button>
             <a class="btn ghost sm" href="/api/files/generated/${f.id}" download="${esc(f.name)}">下载</a>
           </span>`
        : `<span class="badge ${expiry.state === "cleaned" ? "bad" : "warn"}">${esc(expiry.badge)}</span>`;
      return `<div class="wb-file-row ${expiry.state}" title="${esc(expiry.title)}">
        <span class="wb-ico">${wbShort(f.kind)}</span>
        <div class="wb-main"><b>${esc(f.name)}</b><small>${esc(wbFormatLabel(f.kind))} · ${esc(fmtBytes(f.size))} · ${esc(fmtTime(f.created_at))}${extra}</small></div>
        ${action}
      </div>`;
    }).join("");
  }

  async function loadWbFiles() {
    const d = await api("/api/files/generated?limit=100");
    renderWbFiles(d.items || [], $("#wbFileList"));
    const policy = $("#wbFilePolicy");
    if (policy) policy.textContent = `默认保留 ${Number(d.days) || 30} 天，到期后自动删除`;
    const notice = $("#wbFileNotice");
    if (notice) {
      const soon = Number(d.expiring_soon) || 0;
      notice.hidden = !soon;
      if (soon) {
        notice.innerHTML = `<svg><use href="#i-clock"/></svg><span>有 <b>${soon}</b> 个文件将在 ${Number(d.warn_days) || 3} 天内到期并被自动删除，请及时下载。</span>`;
      }
    }
  }

  function wbTaskStatus(task) {
    const status = String(task.last_status || "");
    if (status === "running") return WB_STATUS.running;
    if (status === "error") return WB_STATUS.error;
    if (status === "ok") return WB_STATUS.ok;
    return ["未运行", "idle"];
  }

  function wbVerdictTag(task) {
    const run = task.last_run || null;
    const verdict = String((run && run.verdict) || task.last_verdict || "");
    if (!verdict) return "";
    const map = {
      ok: ["自检通过", "ok"],
      weak: ["结论偏弱", "warn"],
      failed: ["自检未通过", "error"],
      skipped: ["条件未满足", "idle"],
      budget: ["超出预算", "warn"],
    };
    const [label, cls] = map[verdict] || ["自检完成", "ok"];
    const attempts = Number((run && run.attempts) || 0);
    return `<span class="wb-verdict ${cls}">${label}${attempts > 1 ? ` · ${attempts} 轮` : ""}</span>`;
  }

  const WB_STEP_ICONS = { ok: "✓", error: "✕", skip: "–", retry: "↻", running: "…" };

  function renderWbSteps(run) {
    const steps = (run && run.steps) || [];
    if (!steps.length) return "";
    const rows = steps.map((s) => {
      const icon = WB_STEP_ICONS[String(s.status || "ok")] || "·";
      const dur = Number(s.dur_ms || 0);
      return `<li class="wb-step ${esc(String(s.status || "ok"))}">
        <span class="wb-step-icon">${icon}</span>
        <b>${esc(String(s.title || s.step || ""))}</b>
        ${dur ? `<small>${dur} ms</small>` : ""}
        ${s.detail ? `<p>${esc(String(s.detail))}</p>` : ""}
      </li>`;
    }).join("");
    return `<details class="wb-steps"><summary>执行步骤（${steps.length}）</summary><ol>${rows}</ol></details>`;
  }

  function renderWbTasks() {
    const box = $("#wbTaskList");
    if (!box) return;
    const items = S.wbTasks || [];
    if (!items.length) {
      box.innerHTML = `<div class="wb-empty">还没有定时任务。点上方「新建任务」，可以让模型每天、每周或某个时间自动生成一份结果。</div>`;
      return;
    }
    box.innerHTML = items.map((t) => {
      const [statusText, statusClass] = wbTaskStatus(t);
      const result = String(t.last_result || "").trim();
      const fmt = t.output_format ? wbFormatLabel(t.output_format) : "";
      const next = !t.enabled ? "已暂停" : (t.trigger_mode === "event" ? "等待事件" : (t.next_run_text || "待计算"));
      return `<div class="wb-task ${t.enabled ? "" : "off"}" data-wb-task-card="${t.id}">
        <div class="wb-task-top">
          <div><b>${esc(t.title)}</b><small>${esc(t.schedule)}</small></div>
          <span class="wb-status ${statusClass}">${statusText}</span>
        </div>
        <div class="wb-task-meta">
          <span>下次：${esc(next)}</span>
          <span>上次：${esc(t.last_run_text || "未运行")}</span>
          ${fmt ? `<span>输出：${esc(fmt)}</span>` : ""}
          ${t.web_enabled ? "<span>联网</span>" : ""}
          ${t.trigger_mode && t.trigger_mode !== "schedule" ? `<span class="wb-trigger">${esc(t.trigger_text)}</span>` : ""}
          ${t.notify_channel === "webhook" ? "<span>Webhook 投递</span>" : ""}
          ${wbVerdictTag(t)}
        </div>
        ${result ? `<div class="wb-task-result">${esc(result.length > 240 ? result.slice(0, 240) + "…" : result)}</div>` : ""}
        ${renderWbSteps(t.last_run)}
        ${t.memory ? `<details class="wb-memory"><summary>任务档案</summary><pre>${esc(t.memory)}</pre></details>` : ""}
        <div class="wb-task-actions">
          <button class="btn ghost sm" data-wb-run-task="${t.id}" ${t.last_status === "running" ? "disabled" : ""}>立即执行</button>
          ${t.last_conversation_id ? `<button class="btn ghost sm" data-wb-task-conv="${t.last_conversation_id}">打开结果</button>` : ""}
          <button class="btn ghost sm" data-wb-edit-task="${t.id}">编辑</button>
          <button class="btn ghost sm danger" data-wb-del-task="${t.id}">删除</button>
          <label class="switch" title="${t.enabled ? "暂停" : "启用"}"><input type="checkbox" data-wb-toggle="${t.id}" ${t.enabled ? "checked" : ""}><span></span></label>
        </div>
      </div>`;
    }).join("");
  }

  async function loadWbTasks() {
    const d = await api("/api/workbench/tasks");
    S.wbTasks = d.items || [];
    renderWbTasks();
  }

  async function loadWorkbench() {
    const [ov, tasks] = await Promise.all([
      api("/api/workbench/overview"),
      api("/api/workbench/tasks"),
    ]);
    S.wbTasks = tasks.items || [];
    renderWbOverview(ov);
    renderWbTasks();
    S.wbLoadedAt = Date.now();
    const latest = ((ov && ov.runs) || []).reduce((m, r) => Math.max(m, Number(r.id || 0)), 0);
    if (!S.wbLastRunId || latest < S.wbLastRunId) S.wbLastRunId = latest;
  }

  function wbDatetimeLocal(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function fillWbModelOptions(task = null) {
    const model = $("#wbTaskModel");
    if (model) {
      const ready = (S.models || []).filter((m) => modelRunnable(m) || m.key === (task && task.model));
      model.innerHTML = `<option value="">自动选择</option>` + ready.map((m) =>
        `<option value="${esc(m.key)}">${esc(m.label || m.key)}</option>`).join("");
      model.value = (task && task.model) || "";
    }
    const agent = $("#wbTaskAgent");
    if (agent) {
      agent.innerHTML = `<option value="">通用助手</option>` + (S.agents || []).map((a) =>
        `<option value="${a.id}">${esc(a.avatar || "🤖")} ${esc(a.name)}</option>`).join("");
      agent.value = task && task.agent_id ? String(task.agent_id) : "";
    }
  }

  function updateWbFreqFields() {
    const mode = $("#wbTaskTrigger").value;
    $("#wbTaskEventWrap").hidden = mode !== "event";
    $("#wbTaskCondWrap").hidden = mode !== "condition";
    $("#wbTaskNotifyWrap").hidden = $("#wbTaskNotify").value !== "webhook";
    $("#wbTaskScheduleGrid").hidden = mode === "event";
    if ($("#wbTaskWeekdays")) $("#wbTaskWeekdays").hidden = mode === "event";
    if (mode === "event") return;
    const freq = $("#wbTaskFreq").value;
    $("#wbTaskOnceWrap").hidden = freq !== "once";
    $("#wbTaskTimeWrap").hidden = freq === "once";
    $("#wbTaskWeekdays").hidden = freq !== "weekly";
    $("#wbTaskMonthWrap").hidden = freq !== "monthly";
  }

  function fillWbEventOptions() {
    const box = $("#wbTaskEvent");
    if (!box || box.dataset.ready === "1") return;
    api("/api/workbench/events").then((d) => {
      const items = d.items || [];
      box.innerHTML = items.map((x) => `<option value="${esc(x.key)}">${esc(x.label)}</option>`).join("");
      box.dataset.ready = "1";
    }).catch(() => {});
  }

  function openWbTaskForm(task = null, preset = null) {
    const seed = task || preset || {};
    S.wbEditingTask = task ? task.id : null;
    $("#wbTaskFormTitle").textContent = task ? "编辑定时任务" : "新建定时任务";
    $("#wbTaskTitle").value = seed.title || "";
    $("#wbTaskPrompt").value = seed.prompt || "";
    $("#wbTaskGoal").value = seed.goal || "";
    $("#wbTaskFreq").value = seed.frequency || "once";
    $("#wbTaskTime").value = seed.time_of_day || "09:00";
    $("#wbTaskMonthDay").value = String(seed.day_of_month || new Date().getDate());
    const when = new Date(Date.now() + 60 * 60 * 1000);
    when.setMinutes(Math.ceil(when.getMinutes() / 5) * 5, 0, 0);
    const savedAt = task && task.run_at ? new Date(Number(task.run_at) * 1000) : null;
    const savedFuture = savedAt && savedAt.getTime() > Date.now() + 60 * 1000;
    $("#wbTaskRunAt").value = task && task.frequency === "once" && savedFuture
      ? wbDatetimeLocal(savedAt)
      : wbDatetimeLocal(when);
    const wanted = seed.frequency === "weekly" ? (seed.weekdays || []) : [];
    $$("#wbTaskWeekdays input").forEach((x) => {
      x.checked = wanted.includes(Number(x.value));
    });
    if (seed.frequency === "weekly" && !wanted.length) {
      const first = $("#wbTaskWeekdays input");
      if (first) first.checked = true;
    }
    fillWbModelOptions(task);
    $("#wbTaskFormat").value = seed.output_format || "";
    $("#wbTaskWeb").checked = !!seed.web_enabled;
    fillWbEventOptions();
    $("#wbTaskTrigger").value = seed.trigger_mode || "schedule";
    $("#wbTaskEvent").value = seed.event_key || "";
    $("#wbTaskEventFilter").value = seed.event_filter || "";
    $("#wbTaskCondition").value = seed.condition || "";
    $("#wbTaskNotify").value = seed.notify_channel || "";
    $("#wbTaskNotifyUrl").value = seed.notify_url || "";
    $("#wbTaskNotifyFormat").value = seed.notify_format || "json";
    $("#wbTaskNotifyOn").value = seed.notify_on || "ok";
    $("#wbTaskHint").textContent = task
      ? (task.frequency === "once" && !savedFuture
        ? "这个一次性任务已经结束；要再执行一次，请选一个将来的时间，或改成每天/每周。"
        : "修改后从下一次计划时间开始生效。")
      : (preset ? "来自推荐模板，可以改时间、模型和输出格式再保存。" : "任务会在本机运行，结果进入最近对话。");
    updateWbFreqFields();
    $("#wbTaskForm").hidden = false;
    $("#wbTaskForm").scrollIntoView({ block: "start", behavior: "smooth" });
    setTimeout(() => $("#wbTaskTitle").focus(), 80);
  }

  function closeWbTaskForm() {
    S.wbEditingTask = null;
    $("#wbTaskForm").hidden = true;
  }

  async function saveWbTask() {
    const title = $("#wbTaskTitle").value.trim();
    const prompt = $("#wbTaskPrompt").value.trim();
    if (!title) return toast("任务名称不能为空");
    if (!prompt) return toast("要执行的内容不能为空");
    const mode = $("#wbTaskTrigger").value;
    const eventKey = $("#wbTaskEvent").value;
    const condition = $("#wbTaskCondition").value.trim();
    if (mode === "event" && !eventKey) return toast("请选择事件类型");
    if (mode === "condition" && condition.length < 4) return toast("请写清判断条件");
    const notifyChannel = $("#wbTaskNotify").value;
    const notifyUrl = $("#wbTaskNotifyUrl").value.trim();
    if (notifyChannel === "webhook" && !/^https?:\/\/\S+$/.test(notifyUrl)) {
      return toast("Webhook 地址需要是完整的 http/https 链接");
    }
    const frequency = $("#wbTaskFreq").value;
    const runAt = $("#wbTaskRunAt").value;
    if (mode !== "event" && frequency === "once" && !runAt) return toast("请选择执行时间");
    const weekdays = $$("#wbTaskWeekdays input:checked").map((x) => Number(x.value));
    if (mode !== "event" && frequency === "weekly" && !weekdays.length) return toast("请至少选择一天");
    const editing = S.wbEditingTask ? (S.wbTasks || []).find((t) => t.id === S.wbEditingTask) : null;
    const body = {
      title,
      prompt,
      goal: $("#wbTaskGoal").value.trim(),
      trigger_mode: mode,
      event_key: mode === "event" ? eventKey : "",
      event_filter: $("#wbTaskEventFilter").value.trim(),
      condition: mode === "condition" ? condition : "",
      notify_channel: notifyChannel,
      notify_url: notifyChannel === "webhook" ? notifyUrl : "",
      notify_format: $("#wbTaskNotifyFormat").value || "json",
      notify_on: $("#wbTaskNotifyOn").value || "ok",
      frequency,
      time_of_day: $("#wbTaskTime").value || "09:00",
      weekdays,
      day_of_month: Number($("#wbTaskMonthDay").value || 1),
      run_at: frequency === "once" ? runAt : null,
      model: $("#wbTaskModel").value || null,
      agent_id: Number($("#wbTaskAgent").value || 0) || null,
      output_format: $("#wbTaskFormat").value || null,
      web_enabled: $("#wbTaskWeb").checked,
      enabled: editing ? !!editing.enabled : true,
    };
    const btn = $("#wbTaskSave");
    btn.disabled = true;
    try {
      if (S.wbEditingTask) {
        await api(`/api/workbench/tasks/${S.wbEditingTask}`, { method: "PUT", body });
      } else {
        await api("/api/workbench/tasks", { method: "POST", body });
      }
      toast(S.wbEditingTask ? "任务已更新" : "定时任务已创建");
      closeWbTaskForm();
      await loadWorkbench();
      setWbTab("tasks");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  }

  async function runWbTask(id, btn) {
    btn.disabled = true;
    try {
      await api(`/api/workbench/tasks/${id}/run`, { method: "POST", body: {} });
      toast("任务已开始执行，完成后会进入最近对话");
      const deadline = Date.now() + 10 * 60 * 1000;
      const tick = async () => {
        try { await loadWbTasks(); } catch {}
        const task = (S.wbTasks || []).find((t) => Number(t.id) === Number(id));
        if (!task || task.last_status !== "running") {
          if (btn.isConnected) btn.disabled = false;
          if (task) toast(task.last_status === "ok"
            ? `任务完成：${task.last_result || "已生成结果"}`
            : `任务失败：${task.last_result || "请查看运行记录"}`);
          loadConversations().catch(() => {});
          return;
        }
        if (Date.now() < deadline) setTimeout(tick, 3000);
        else if (btn.isConnected) btn.disabled = false;
      };
      setTimeout(tick, 4000);
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
    }
  }

  async function toggleWbTask(id, enabled) {
    try {
      await api(`/api/workbench/tasks/${id}`, { method: "PATCH", body: { enabled } });
      toast(enabled ? "任务已启用" : "任务已暂停");
      await loadWorkbench();
      setWbTab("tasks");
    } catch (e) {
      toast(e.message);
      await loadWbTasks().catch(() => {});
    }
  }

  async function deleteWbTask(id, btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.textContent = "再点一次删除";
      setTimeout(() => {
        if (btn.isConnected) {
          btn.dataset.armed = "";
          btn.textContent = "删除";
        }
      }, 3200);
      return;
    }
    try {
      await api(`/api/workbench/tasks/${id}`, { method: "DELETE" });
      toast("任务已删除");
      await loadWorkbench();
      setWbTab("tasks");
    } catch (e) {
      toast(e.message);
    }
  }

  function useWbPrompt(button) {
    const prompt = button.dataset.wbPrompt || "";
    const fmt = button.dataset.wbFormat || "";
    closeWorkbench();
    newChat(false);
    if (fmt) setOutputFormat(fmt, true);
    $("#messageInput").value = prompt;
    autoResizeInput();
    $("#messageInput").focus();
    toast(fmt ? `已填入提示词，并选择 ${OUT_FORMATS[fmt]}` : "已填入提示词");
  }

  async function pollWorkbench() {
    if (!S.user || !$("#appView") || $("#appView").hidden) return;
    try {
      const ov = await api("/api/workbench/overview");
      const runs = (ov && ov.runs) || [];
      const seen = S.wbRunStatuses || {};
      const changed = runs.filter((r) => seen[r.id] && seen[r.id] !== r.status && r.status !== "running");
      S.wbRunStatuses = runs.reduce((m, r) => { m[r.id] = r.status; return m; }, {});
      const latest = runs.reduce((m, r) => Math.max(m, Number(r.id || 0)), 0);
      if (!S.wbLastRunId) S.wbLastRunId = latest;
      else if (latest > S.wbLastRunId) S.wbLastRunId = latest;
      if (changed.length) {
        const done = changed[0];
        toast(done.status === "ok"
          ? `定时任务完成：${done.summary || "已生成结果"}`
          : `定时任务失败：${done.error || "请到工作台查看"}`);
        if ($("#workbenchDrawer").hidden) {
          const current = Number(($("#workbenchBadge").textContent || "0").replace("+", "")) || 0;
          setWorkbenchBadge(current + changed.filter((r) => r.status === "ok").length);
        }
        loadConversations().catch(() => {});
      }
      if (!$("#workbenchDrawer").hidden) {
        if (S.wbTab === "overview") renderWbOverview(ov);
        else if (S.wbTab === "tasks") loadWbTasks().catch(() => {});
        else if (S.wbTab === "files") loadWbFiles().catch(() => {});
      }
    } catch {}
  }

  if ($("#workbenchBtn")) $("#workbenchBtn").addEventListener("click", () => openWorkbench());
  if ($("#sideActiveWbOpen")) $("#sideActiveWbOpen").addEventListener("click", () => openWorkbench());
  if ($("#sideActiveWbClose")) $("#sideActiveWbClose").addEventListener("click", (ev) => {
    ev.stopPropagation();
    closeActiveWb();
  });
  if ($("#capsBtn")) $("#capsBtn").addEventListener("click", () => openWorkbench("caps"));
  if ($("#wbTabs")) {
    $("#wbTabs").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-wtab]");
      if (btn) setWbTab(btn.dataset.wtab);
    });
  }
  $$("[data-close-workbench]").forEach((el) => el.addEventListener("click", closeWorkbench));
  if ($("#wbNewTask")) $("#wbNewTask").addEventListener("click", () => openWbTaskForm());
  if ($("#wbTaskCancel")) $("#wbTaskCancel").addEventListener("click", closeWbTaskForm);
  if ($("#wbTaskSave")) $("#wbTaskSave").addEventListener("click", saveWbTask);
  if ($("#wbTaskFreq")) $("#wbTaskFreq").addEventListener("change", updateWbFreqFields);
  ["#wbTaskTrigger", "#wbTaskNotify"].forEach((sel) => {
    if ($(sel)) $(sel).addEventListener("change", updateWbFreqFields);
  });
  if ($("#wbRefreshFiles")) $("#wbRefreshFiles").addEventListener("click", () => loadWbFiles().catch((e) => toast(e.message)));
  if ($("#wbNewChat")) $("#wbNewChat").addEventListener("click", () => { closeWorkbench(); newChat(); });
  if ($("#wbHeroBrowse")) $("#wbHeroBrowse").addEventListener("click", () => {
    $("#wbTemplateSection").scrollIntoView({ block: "start", behavior: "smooth" });
  });
  if ($("#wbNewTemplate")) $("#wbNewTemplate").addEventListener("click", () => openWbTemplateEditor(null, false));
  if ($("#wbHeroCustom")) $("#wbHeroCustom").addEventListener("click", () => {
    const tpl = wbTemplateOf();
    if (tpl && tpl.custom) openWbTemplateEditor(tpl, false);
    else if (tpl) openWbTemplateEditor(tpl, true);
    else openWbTemplateEditor(null, false);
  });
  if ($("#wbHeroShare")) $("#wbHeroShare").addEventListener("click", () => {
    const tpl = wbTemplateOf();
    if (tpl) openWbShareDialog(tpl);
  });
  if ($("#wbHeroExit")) $("#wbHeroExit").addEventListener("click", closeActiveWb);

  document.addEventListener("change", (ev) => {
    if (ev.target && ev.target.dataset && ev.target.dataset.wbToggle) {
      toggleWbTask(Number(ev.target.dataset.wbToggle), ev.target.checked);
      return;
    }
    if (ev.target && ev.target.dataset && ev.target.dataset.wbPluginToggle) {
      const id = ev.target.dataset.wbPluginToggle;
      if (id === "web") setWeb(ev.target.checked);
      if (id === "kb") {
        savePrefs({ useKb: ev.target.checked });
        if ($("#setKb")) $("#setKb").checked = ev.target.checked;
      }
      renderWbCaps();
      return;
    }
    if (ev.target && ev.target.dataset && ev.target.dataset.wbPluginFormat !== undefined) {
      setOutputFormat(ev.target.value);
      renderWbCaps();
    }
  });

  document.addEventListener("click", async (ev) => {
    const close = ev.target.closest("[data-close-workbench]");
    if (close) { closeWorkbench(); return; }
    const goTab = ev.target.closest("[data-wtab-go]");
    if (goTab) { setWbTab(goTab.dataset.wtabGo); return; }
    const wbSkill = ev.target.closest("[data-wb-skill]");
    if (wbSkill) {
      setSkill(wbSkill.dataset.wbSkill);
      renderWbCaps();
      renderWbHero();
      toast(S.skill ? `已选择技能「${S.skill.name}」` : "已切换为普通对话");
      return;
    }
    const heroSkill = ev.target.closest("[data-wb-hero-skill]");
    if (heroSkill) {
      setSkill(heroSkill.dataset.wbHeroSkill);
      renderWbCaps();
      renderWbHero();
      toast(`已切换到「${S.skill ? S.skill.name : "普通对话"}」`);
      return;
    }
    const tplUse = ev.target.closest("[data-wb-template-use]");
    if (tplUse) { openWbHome(tplUse.dataset.wbTemplateUse); return; }
    const tplEdit = ev.target.closest("[data-wb-template-edit]");
    if (tplEdit) {
      const tpl = wbTemplateOf(tplEdit.dataset.wbTemplateEdit);
      if (tpl) openWbTemplateEditor(tpl, !tpl.custom);
      return;
    }
    const tplShare = ev.target.closest("[data-wb-template-share]");
    if (tplShare) {
      const tpl = wbTemplateOf(tplShare.dataset.wbTemplateShare);
      if (tpl) openWbShareDialog(tpl);
      return;
    }
    const useTpl = ev.target.closest("[data-wb-template]");
    if (useTpl) { openWbHome(useTpl.dataset.wbTemplate); return; }
    const preset = ev.target.closest("[data-wb-task-preset]");
    if (preset) {
      const tpl = WB_TASK_RECOS.find((x) => x.id === preset.dataset.wbTaskPreset);
      if (tpl) {
        setWbTab("tasks");
        openWbTaskForm(null, tpl);
      }
      return;
    }
    const quick = ev.target.closest("[data-wb-prompt]");
    if (quick) { useWbPrompt(quick); return; }
    const conv = ev.target.closest("[data-wb-conv]");
    if (conv) {
      closeWorkbench();
      await openConversation(Number(conv.dataset.wbConv)).catch((e) => toast(e.message));
      return;
    }
    const taskOpen = ev.target.closest("[data-wb-task-open]");
    if (taskOpen) {
      setWbTab("tasks");
      const card = document.querySelector(`[data-wb-task-card="${taskOpen.dataset.wbTaskOpen}"]`);
      if (card) card.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
    const run = ev.target.closest("[data-wb-run-task]");
    if (run) { await runWbTask(Number(run.dataset.wbRunTask), run); return; }
    const edit = ev.target.closest("[data-wb-edit-task]");
    if (edit) {
      const task = (S.wbTasks || []).find((t) => t.id === Number(edit.dataset.wbEditTask));
      setWbTab("tasks");
      if (task) openWbTaskForm(task);
      return;
    }
    const taskConv = ev.target.closest("[data-wb-task-conv]");
    if (taskConv) {
      closeWorkbench();
      await openConversation(Number(taskConv.dataset.wbTaskConv)).catch((e) => toast(e.message));
      return;
    }
    const del = ev.target.closest("[data-wb-del-task]");
    if (del) { await deleteWbTask(Number(del.dataset.wbDelTask), del); return; }
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !$("#workbenchDrawer").hidden) closeWorkbench();
  });

  bindEvents();
  boot();
