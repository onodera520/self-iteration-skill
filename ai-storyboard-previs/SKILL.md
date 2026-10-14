---
name: ai-storyboard-previs
description: 一次批量看图，校对用户已按脚本排序配对的分镜参考图，立即交付逐镜报告与全部原图；达阈值后导出整批新视频提示词。默认不登记视频、不抽帧、不重新匹配、不放大复看、不拼接原资产。
---

# 分镜图校对

默认流程：**用户输入 → 每张分镜判断一次 → complete 立即交付**。保留脚本、原资产、分组、省图及返修阈值；用户不填写内部 JSON。默认不依赖 FFmpeg。旧视频任务才读 [历史接口](references/project.md)。

## 新任务

记录开始时间。用户指定的 case 目录就是 DELIVERY，只放报告、images/ 和触发后的提示词。新目录或已存在的空目录均可，不删除空目录；有文件的旧交付另选目录。所有 INPUT、PROJECT、拼图、工作单与运行记录放在其同级 `.storyboard-internal/本次任务/` 下，**不要在 DELIVERY 内创建 internal、_internal 或 case 工作子目录**；内部文件保留供恢复，不打包进交付。只读本入口，定位脚本和用户已确定的图片顺序，执行：

```text
python scripts/prepare_storyboards.py overview SCRIPT.txt --images IMAGES.json --output FIRST_LOOK_INTERNAL --delivery DELIVERY
```

IMAGES.json 是有序路径列表或 shot_id/path 项；相对路径以该 JSON 为基准。支持“镜头N／【时长】【镜头设计】【镜头内容】”脚本。其他格式先明确对应关系，不猜编号。此时不读模板、规划、返修或源码，不先写完整 requirements。成功后立即批量显示 pages 拼图，每9张一页、原始尺寸，不在显示前插入字段整理。已有准备任务直接恢复。

**这就是本轮唯一一次看图。** 同次记录对应脚本、可见事实、阶段和初步判断；将实际事实保存到返回的 OBSERVATIONS.json，不用聊天摘要代替。复制 input_draft 为新 INPUT，按下面的字段约定集中补齐；正常任务不另读接口、模板或源码。完整动作结果不强制每张参考图都是终态，普通景别／姿势不升级为硬要求。

INPUT 保留草稿的 title/source_script/id/script/image/duration/duration_source，不重新抄写原文；assets 填用户原资产的 `{id,kind:character/scene/prop,path,description}`，路径用绝对路径，原分组存 `input_shot_groups=[[镜号,…],…]`。每镜只补 `scene_id`、`continuity_id`、`asset_ids`、`required_result`（简短剧情目的）及：

```json
{"intent":{"critical_result":false,"narrative_turn":false,"required_cut":false},"requirements":{"status":"ready","keyframe":{"phase":"entry","description":"本镜参考图所处阶段"},"must_have":["本镜剧情必需内容"],"provenance":[{"field":"purpose,keyframe,must_have","status":"script","source":"对应脚本出处"}]}}
```

这是字段形状示例，三个 intent 标记、阶段和必要内容须按本镜实际判断；phase 只能 entry/action/exit，来源 status 只能 observed/user_provided/script/assumed/unknown。普通保留图任务**不填 facts、state_changes、entry_state 或 inherits_from 来重复复述脚本**；仅明确建模状态或提出省图时才按需读 [字段速查](references/fields.md) 补真实状态依据。不要把整镜剧情段落写成同一实体的 static 属性，也不要为消除报错编造状态变化。可见事实只在 OBSERVATIONS/WORKLIST 保存一次。

```text
python scripts/prepare_storyboards.py prepare PROJECT.json --input INTERNAL/INPUT.json --reuse-overviews FIRST_LOOK_INTERNAL --run-dir PREPARE_INTERNAL --output DELIVERY --concise
```

prepare 自动校验来源、复用未变拼图与首看事实，并生成工作单。事实存在不代表 PASS。按原脚本填完 WORKLIST，复用首看判断；**不再次显示已看图片，不显示或生成原资产拼图**。若首看来源改变，旧观察不复用，变化的图片才需要重新判断。资产路径和指纹继续保存，用于失效核验、省图和提示词。

## 同一次观察的判断标准

三组一起判断：**主体内容**（人物、场景、关键道具）；**状态承接**（当前阶段及相邻可见连续性）；**参考可用性**（必要内容的构图可见性及严重损坏）。仍逐镜判断，不能用同页其他镜头替代证据。跨页连续性复用已保存的相邻观察，不重开前页末镜。

三级放宽是同一次判断的尺度，不是三轮看图：

1. 核心主体及必要关系成立，允许景别／拍摄角度差异；拍摄角度不等于角色朝向。
2. 核心主体及必要关系成立，允许合理动作阶段／光影差异。
3. **全部剧情必需元素成立**，允许非关键细节差异；不以多数相似抵消关键错误，不选取另一帧。

按脚本校对，不另设外观或拍法必须严格一致的通用规则。**画外可通过：**角色动作／姿态与脚本相符，道具或脚下支撑物被构图裁在画外，且没有可见矛盾，可以 PASS，不仅因未入画而记 uncertain。例如高举奖杯但奖杯在画面上方、站在木箱上但木箱在画面下方；不把画外内容写成已看见。**朝向错误不通过：**脚本已明确角色面向／背向哪里，画面却明确相反，直接 FAIL；不能以剧情仍可理解放行。朝向按脚本参照物判断，不将机位、反打或单纯视线变化当成角色转向；脚本未写不猜方向。

直接符合记 match_level=0，按上述等级通过记1–3。脚本人物、可见关键道具／持物状态、角色明确朝向或剧情状态有矛盾，任何等级都不能通过：直接 FAIL 并记录具体修正。单张图不能证明完整运动，不因此判错。除上述可接受的画外裁切外，必要信息看不清或阶段无法确定：uncertain，说明无法确认什么后直接交付，**不放大、不安排复查、不计返修阈值**。动作前参考图不强求动作后的结果；剧情相关对白帮助理解，默认不核对文字、配音或口型。

新任务用版本4简短 WORKLIST：verdict 明确覆盖上述三组，每镜填阶段和 match_level，复用首看事实。通过镜不另写理由；错误只在 findings 写一次脚本引文、可见矛盾、修改意见和种类；疑点只在 unresolved 写一次。程序展开七项记录、问题和返修依据，不重复写 reason／issues／repair_assessments。省图仍另填双侧 reference 依据及理由，不能由 PASS 自动推导；关键错误或严重损坏的额外证据按需读 [返修证据](references/repair-assessments.md)。版本1／2／3兼容；空字段不代表通过。

保留 WORKLIST 的结构／指纹，根字段 `reviewed_groups` 保留三组并核对 `grouping_checked=true`；每镜填写 `verdict=PASS/FAIL/uncertain`、`reference_phase=entry/action/exit/unknown`，PASS 的 `match_level=0–3`，其他 null。普通错误 findings 项为 `{check,script_quote,actual,fix,kind:"ordinary",affects_story:true或false,preserves_script:true}`，script_quote 必须逐字来自同镜原文。check 只能 identity/scene/props/composition/key_state/continuity/cleanliness；疑点 unresolved 项为 `{check,reason}`。没有错误／疑点保留空数组；不建议省图时不加 reference。默认 asset_comparisons=[]。上述足够完成普通任务，特殊证据才查扩展字段。

## 立即交付

有用户分组就采用，没有才按需读 [规划规则](references/planning.md) 自动分组。省图只在合法组内使用双侧 PASS 且保留的锚点，记录依据和理由；FAIL／uncertain 暂不省图，全部脚本镜头和原图保留。无需省图的通过镜保留原图。

```text
python scripts/prepare_storyboards.py complete PROJECT.json PREPARE_INTERNAL/WORKLIST.json --output DELIVERY --run-dir FINISH_INTERNAL
```

complete 一次展开记录、核验整批、规划、判阈值、渲染并冻结；成功立即交付，不重看报告或图片，不手动重复同一校验。失败只修对应字段。输出 01_分镜图审查.md 和 images/：标题、镜头数直接接原九列表，不附流程说明或分组诊断；脚本计划时长，通过只写“符合脚本”，待核查“—／暂不省图”，无漏镜或补帧条目。命令细节才读 [图片接口](references/storyboard-images.md)。

阈值：关键剧情错误一镜，或严重画面损坏一镜，或普通明确错误至少两镜且占整批≥20%；2/10触发、2/11不触发。待核查、输入问题、分组和省图不改变分母。只有触发才读 [提示词编排](references/prompt-quality.md)、[提示词规则](references/auto-repair.md)及 PROMPT.view.json，读取原生成提示词；九项提示词核对在同一次阅读中按四组完成，不属于普通看图环节。缺项集中补齐，不重做有效审查。finish 导出全部镜头的新视频提示词，每镜1秒、静音、保留资产及剧情；共同画幅沿用，混用先确定目标，不自动裁图。到交付停止，由用户自行生成。

## 中断恢复

实际观察与判断逐页落盘。摘要保留 RUN.json 绝对路径、阶段、下一步。压缩后读 RUN.json，执行 resume PROJECT.json PREPARE_INTERNAL；需定位才加 --page 或 --shots。只继续未记录／不完整项目，已存事实直接复用；uncertain 留在报告，不排复查。未落盘且无法确认的判断保留待核查，不能凭摘要 PASS。已 complete 只读 FINISH.view.json 接着交付，不重复 prepare／complete。

图片、脚本、资产、要求或分组变化使相关结论失效，另存新审查，旧交付冻结。workflow=storyboard_images，source.kind=provided，无视频时间戳。历史项目未设置新策略时保留原上下文与交付兼容。计时／调优才读 [执行提效](references/efficiency.md)，程序耗时不能冒充模型端到端耗时。
