---
name: ai-storyboard-previs
description: 一次批量看图，校对用户已按脚本排序配对的分镜参考图，立即交付逐镜报告与全部原图；达阈值后优先导出整批新视频提示词，对白内容不参与提示词保真检查。默认不登记视频、不抽帧、不重新匹配、不放大复看、不拼接原资产。
---

# 分镜图校对

默认流程：**登记输入并出总览 → 一次填写审查表 → submit 立即交付**。保留脚本、原资产、分组、省图及返修阈值；用户不填写内部 JSON。默认不依赖 FFmpeg。旧视频任务才读 [历史接口](references/project.md)。

## 新任务

记录开始时间。用户指定的 case 目录就是 DELIVERY，只放报告、images/ 和触发后的提示词。新目录或已存在的空目录均可；有文件的旧交付另选目录。只读本入口，定位用户提供的脚本、图片、原资产、分组及原提示词，直接登记：

```text
python scripts/review_storyboards.py start SCRIPT.txt --images-dir IMAGES_DIR --asset character=CHARACTER.png --asset scene=SCENE.png --asset prop=PROP.png --groups GROUPS.txt --original-prompt PROMPT.txt --delivery DELIVERY
```

每个用户原资产重复一次 `--asset 种类=路径`，种类为 character/scene/prop，不假设示例中的三个资产都存在。无分组或原提示词就省略相应参数。路径含空格时引用整个参数。`--images-dir` 只接受与脚本明确对应的 `1.png`、`S01.png`、`镜头1.png` 等纯镜号文件名，按数值绑定，拒绝缺号、重复号和额外编号；其他已确定的顺序使用 `--images IMAGES.json` 有序路径或 shot_id/path 列表，不猜匹配。分组支持 JSON 镜号数组或 `shot1：1、2、3` 行；其他格式明确整理成列表后传入。原提示词只登记路径，达阈值才读取。

start 自动提取原文、时长、图片对应、资产 ID、原分组与来源指纹；内部文件自动放在 DELIVERY 同级 `.storyboard-internal/本次任务/`，或显式指定独立 `--run-dir`。成功后立即批量显示返回的 pages，每9张一页；同次读取返回的 **REVIEW.json**，它含逐镜原文和待填字段。此时不先读模板、规划、返修或源码，不先写完整 requirements。

**这就是本轮唯一一次看图。** 实际观察与判断逐页保存到同一 REVIEW.json，不用聊天摘要代替；不另外填写 OBSERVATIONS、INPUT 或 WORKLIST，也不为机械转换编写临时 build/judge 脚本。原文、顺序、时长、路径、资产与分组字段保持工具生成值。只填写：

- 根 `defaults.scene_id/continuity_id/intent`：明确共享的场景、连续段及三个布尔标记 critical_result/narrative_turn/required_cut；不共用的镜头在该行覆盖，不能自动假定全批相同。
- 每镜 `asset_ids`（引用表内 A01 等 ID）、`purpose`（简短剧情目的）、`phase`、`must_have`（具体可见要求）、`visible_facts`、`verdict`、`match_level`、`findings`、`unresolved`。`phase=entry/action/exit` 同时用于参考阶段和目标阶段；无法确定实际阶段则填 unknown，并另加 `keyframe_phase` 明确脚本计划阶段。参考画面描述默认机械复用 must_have，不用抽象 purpose；确有额外阶段要求或 must_have 为空时，另填具体 `keyframe_description`。
- 根 `grouping_checked=true`，`reviewed_groups` 保留三组；无额外限制或资产对照时保留空数组。

purpose、阶段、必要内容及关键性仍逐镜按脚本和画面判断。程序机械展开 required_result、requirements 与版本4工作单；默认 provenance 指向同镜原脚本，其他依据需在该镜显式填写 `provenance`。完整动作结果不强制每张参考图都是终态，普通景别／姿势不升级为硬要求。显式状态建模、资产对照或提出省图时按需读 [字段速查](references/fields.md)，使用保留的 [原 prepare/complete 接口](references/storyboard-images.md)；不将整镜剧情写成 static 状态，不为消除报错编造变化。

**不再次显示已看图片，不显示或生成原资产拼图**。事实存在不代表 PASS。来源改变使旧判断失效，另建审查；资产路径和指纹继续用于失效核验及提示词。

## 同一次观察的判断标准

三组一起判断：**主体内容**（人物、场景、关键道具）；**状态承接**（当前阶段及相邻可见连续性）；**参考可用性**（必要内容的构图可见性及严重损坏）。仍逐镜判断，不能用同页其他镜头替代证据。跨页连续性复用已保存的相邻观察，不重开前页末镜。

三级放宽是同一次判断的尺度，不是三轮看图：

1. 核心主体及必要关系成立，允许景别／拍摄角度差异；拍摄角度不等于角色朝向。
2. 核心主体及必要关系成立，允许合理动作阶段／光影差异。
3. **全部剧情必需元素成立**，允许非关键细节差异；不以多数相似抵消关键错误，不选取另一帧。

按脚本校对，不另设外观或拍法必须严格一致的通用规则：

- **动作可读即可通过。** 核心主体、动作姿态及作用对象的关系足够识别且无矛盾时，允许局部模糊、遮挡和道具细节不清，不要求工具轮廓、精确接触点或完整运动同时清楚。例如敲锣关系可辨，木槌局部模糊仍可 PASS；只有铜锣可见而击打关系无法辨认，不能据此通过。
- **局部画外可通过。** 核心动作／表演已可读，道具或脚下支撑物仅被裁在画外且无可见矛盾，可以 PASS。例如高举奖杯但奖杯在上方画外、站在木箱上但脚下出框；不把画外内容写成已看见。
- **核心表演被构图排除则 FAIL。** 所选合理阶段仍须呈现本镜核心动作准备、动作关系或表演线索。脚本要求展扇及得意、神秘的眼神，画面却只有背影，脸、手与扇均不可见，应记 composition 普通错误，不能仅记 uncertain，也不能凭“之后可能转身或展扇”放行；不自动认定角色朝向错误。
- **朝向错误不通过。** 脚本明确角色面向／背向哪里，画面却明确相反，直接 FAIL。按脚本参照物判断，不将机位、反打或单纯视线变化当成角色转向；脚本未写不猜方向。

直接符合记 match_level=0，按上述等级通过记1–3。脚本人物、可见关键道具／持物状态、角色明确朝向或剧情状态有矛盾，或构图明确排除了核心表演，任何等级都不能通过：直接 FAIL 并记录具体修正。先排除上述可通过情形与明确错误，只有现有画面仍不足以判断符合或矛盾、必要关系或阶段确实无法确定时才记 uncertain，说明无法确认什么后直接交付，**不放大、不安排复查、不计返修阈值**。单图不能证明完整运动不构成错误或疑点；动作前参考图不强求终态。剧情相关对白帮助理解，默认不核对文字、配音或口型。

REVIEW 的 verdict 明确覆盖上述三组，程序展开版本4工作单的七项记录、问题和返修依据。通过镜不另写理由；错误只在 findings 写一次；疑点只在 unresolved 写一次，不重复写 reason／issues／repair_assessments。省图的双侧依据不能由 PASS 自动推导；严重损坏的特殊证据才按需读 [返修证据](references/repair-assessments.md)。旧工作单版本1／2／3兼容；空字段不代表通过。

每镜 `verdict=PASS/FAIL/uncertain`，PASS 的 `match_level=0–3`，其他 null。普通错误 findings 项为 `{check,script_quote,actual,fix,kind:"ordinary",affects_story:true或false,preserves_script:true}`；script_quote 必须逐字来自同镜原文。关键错误 kind 使用 missing_key_node/wrong_actor/broken_causality/wrong_transfer_result/explicit_key_requirement，另填 `affects_story=true` 及具体 `impact`，不能仅因外观或拍法不同归为关键。check 只能 identity/scene/props/composition/key_state/continuity/cleanliness；疑点 unresolved 项为 `{check,reason}`。没有错误／疑点保留空数组。

## 立即交付

有用户分组就采用，没有才按需读 [规划规则](references/planning.md) 自动分组。省图只在合法组内使用双侧 PASS 且保留的锚点，记录依据和理由；FAIL／uncertain 暂不省图，全部脚本镜头和原图保留。无需省图的通过镜保留原图。

```text
python scripts/review_storyboards.py submit SESSION.json
```

submit 自动展开输入及观察、复用首看拼图、填入工作单并调用一次 prepare/complete；核验整批、规划、判阈值、渲染及冻结仍由原校验器完成。返回 project 与提示词续接路径。未达阈值成功后立即交付，达到阈值则优先完成下述新提示词导出，再结束交付。不重看报告或图片，不手动重复同一校验。字段预检失败只修 REVIEW 对应项后提交；已有内部准备时按返回记录恢复。输出 01_分镜图审查.md 和 images/：标题、镜头数直接接原九列表，不附流程说明或分组诊断；脚本计划时长，通过只写“符合脚本”，待核查“—／暂不省图”，无漏镜或补帧条目。

阈值：关键剧情错误一镜，或严重画面损坏一镜，或普通明确错误至少两镜且占整批≥20%；2/10触发、2/11不触发。待核查、输入问题、分组和省图不改变分母。**达到阈值后，下一优先事项就是导出整批新视频提示词**，报告冻结后立即继续。只读 FINISH.view 指向的 **PROMPT.work.view.json**，复用其中 `submission_template`，一次填 preparation、必要 edits 和四组具体结论后保存为 PROMPT.work.json；无需再打开空 work 文件。视图已含全部镜头、原资产路径、来源与规则；资产风格须来自用户原资产，未看过的原资产原图按需同批显示，不生成资产拼图。存在原提示词时按 `reference_instructions` 填写：selections 的每项含 shot_id/source_quote/script_quote/visual_text，excluded 的每项含 source_quote/reason，两数组至少一条实际记录；兼容性总说明不能替代采纳或排除，均由代理判断。

随后执行一次 `repair_quality.py finish PROJECT.json G01 PROMPT.work.json --output case/G01_新视频提示词.md`。finish 先集中预检筛选字段和逐字引文；报错只按具体字段及同一视图的填写说明修复后重试，不为字段缺项通读源码或重做审查。指纹、资产 SHA、对应关系和未改正文由工具维护；四组仍覆盖全部九项检查，不自动批准空字段。focus_shot_ids 只是提示额外来源，全部镜头仍同批核对。历史任务无 work 文件或需特殊诊断时才查 [提示词编排](references/prompt-quality.md)及 [提示词规则](references/auto-repair.md)。

提示词只核对**可见剧情保真**：保留脚本已有的人物、动作、表情、位置、道具关系、镜序和必要切镜。**对白文字及其含义不参与提示词保真或时长检查，也不要求把对白独有信息转成画面，不能以其无法无声表达为由停止导出。** 去除说话表演、声音和新增文字指令，不为承接对白发明动作、人物、道具或事件；内部 preserves_story／story_basis 也只确认已有可见内容。finish 导出全部镜头，每镜1秒、静音、无说话口型、无新增文字，保留原资产。**画幅自动采用整批分镜图中数量最多的显示画幅；数量并列取原镜序中最先出现者，不询问确认。** 按每镜对应图计数，同一比例的不同分辨率合并，不按像素面积、时长、分组或通过数加权，不裁图；仅用户另有明确指定时才使用目标画幅。导出后再结束交付，由用户自行生成；用户明确只要报告时按其要求执行。

## 中断恢复

实际观察与判断逐页落盘。新入口摘要保留 SESSION.json 绝对路径、阶段、下一步；提交前读取 REVIEW，只继续未完整填写的镜头，不重开已记录的图片。提交后使用 prepare/RUN.json 和原 resume 接口恢复。uncertain 留在报告，不排复查；未落盘且无法确认的判断保留待核查，不能凭摘要 PASS。已 complete 只读 finish/FINISH.view.json：below_threshold 直接交付，其他状态优先按 prompt_work／prompt_work_view／prompt_output 续接导出。complete 的 status 只表示报告完成，不表示提示词已交付。不重复 prepare／complete。

图片、脚本、资产、要求或分组变化使相关结论失效，另存新审查，旧交付冻结。workflow=storyboard_images，source.kind=provided，无视频时间戳。历史项目未设置新策略时保留原上下文与交付兼容。计时以首次读技能前实际 UTC 为起点，以 submit 返回 ended_at、finish 输出 Export completed at (UTC) 为阶段终点；不能等下一轮模型调用再读时钟作为导出完成时间。计时／调优才读 [执行提效](references/efficiency.md)，程序耗时不能冒充模型端到端耗时。
