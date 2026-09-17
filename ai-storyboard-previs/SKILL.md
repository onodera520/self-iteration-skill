---
name: ai-storyboard-previs
description: 根据用户的视频、脚本和资产图，抽帧匹配、回看补查并校对内容与连续性，判断保留图、可推导省图和必要漏镜，再聚合相邻分镜，交付带小分镜图的两张 Markdown 表。用于已有视频的分镜校对、聚合规划与参考图取舍，不调用 API。
---

# 抽帧校对与分镜聚合

默认输入：**视频＋脚本＋资产图**。

默认链路：**抽帧匹配 → 画面校对 → 必要时回看并替换抽帧 → 保留或可推导省图 → 相邻聚合 → 图片＋Markdown 两张表**。不调用 API，重新生成仅提供建议。按脚本计划时长聚合，每组不超过 15 秒、12 镜；实际时间戳只用于寻找镜头和定位问题。不比较实际与计划时长，不检查具体对白逐字一致、配音文本或口型同步；对白/OS/VO 的剧情含义、明确画面动作及字幕仍在相应审查范围内。

## 默认执行流程

1. **一次整理完整输入**：读 [项目约定](references/project.md)、[镜头要求](references/shot-requirements.md)。一次 LLM 调用填写全部镜头的 facts/state_changes/requirements/块级 provenance 、event（初步事件编号、说明、来源）、duration/duration_source 与 narrative_plan（自然边界、相邻承接及整段复杂度依据）。代理只写入口状态种子与 state_changes，requirements.py 计算完整入口、出口状态。不逐镜提取，不用视频错误画面改写脚本。保留原镜号、顺序、剧情及画幅；脚本给定时长原值保留；缺时长先按动作和剧情提出建议并注明来源，不冒充原值或实测值。旧项目可先抽帧审查，交付新版聚合前须补齐计划时长和剧情依据。
2. **登记已有视频并抽帧**：设置 workflow: video_evidence、video_source: imported。一份视频对应一个来源组，列出它应覆盖的连续脚本镜头；来源组不等于最终聚合。import-video 保存文件哈希与实测时长，独立于付费任务。资产仅本地核对。media.py extract 提取均匀采样、切点前后及内部连续帧，不依赖脚本时长。
3. **一次批量匹配**：按 [审查规则](references/review.md) 整组对应脚本，记录候选、实际时间、SHA256 和 observation。matched 只表示已定位；完全不符或抽不到先 uncertain，回看原视频或加密抽帧。找到后替换错误候选；完整补查仍无对应画面才 absent，记录覆盖整个原视频的补查范围及观察。稀疏帧不能单独证明漏镜。
4. **一次组级审查与推导评估**：previs.py context 一次读取全组要求、资产、候选、选帧及左右组边界。一次 LLM 同时核对自然边界、相邻承接和整个合并区间的生成复杂度（grouping_checked: true），判断并填写整组 shot_reviews、reference_assessments、四项总检查、证据和问题；一次 review 登记，禁止逐镜 context/review。逐镜独立通过，同组失败不扩散。composition 只按脚本明确景别、关键帧要求和已有画面描述作规则比较。无法确认的动作或切镜标待检查。每图观察按哈希保存复用，不为后续步骤重复看图。
5. **按问题处理**：已定位且剧情、动作或明确要求轻微不符标“该镜需重新生成”，列差异和建议。确认漏镜后判断推导：有检验通过的前后保留镜头和资产支持且不违反锚点保护，可标“视频漏镜；可推导省图，未验证”；无法推导且必要则标“必要漏镜，需补生成”；证据或推导仍不确定标待检查。缺失镜头不能互为依据，也不能标检验通过。重选帧只重看该镜及左右衔接，复用其他观察、按新指纹登记完整组。替换整份视频则整份重新匹配审查并复查左右来源组边界。
6. **规则聚合并交付**：运行 [审查后规划](references/planning.md)，先按剧情自然初分，再强制检查相邻段合并，最后复核小于 8 秒的短段；承接更强侧优先，同等条件优先前组。每组计划总时长 ≤15 秒、镜数 ≤12，不能仅凭两两可合并推断整段复杂度。event 不是最终硬边界，景别、即时反应和短 OS/VO 不自动拆组。确定最终组后再选择参考图；同场景可拆组，跨场景的连续行动可同组，保护首尾、首次出场、关键状态、空间变化及必要锚点，保留原镜序和必要切镜。独立保存 aggregation，不改来源组和实际时间映射。每份视频仅统计必要漏镜；默认 bad_num ≥ 2 且占应覆盖镜头数 ≥ 20% 才建议重新生成该视频。轻微错误、可推导漏镜、待检查不计数。
7. **最终仅图片＋MD**：render 为非省图镜头在本地生成 240×168 小分镜图及缺图文字卡，图下标镜号。MD 固定两张表：分组表含总时长，逐镜表含镜头计划时长。建议时长逐镜标“建议”，所属组总时长标“含建议值”。单镜超过 15 秒标“需拆分或调整计划时长”，不缩短、不删镜、不冒称合格方案。所有最终批准 ai_fill 的镜头，小分镜图栏只写“可推导生成”，不复制原帧、不生成图片或图片链接；图片处理写“建议省图，未验证”，检验结果仍区分通过与漏镜。其他缺图卡标“必要漏镜”或“待检查”；逐镜展示检验、图片处理、推导依据及修改建议。**不输出视频结论表**。达到漏镜阈值，仅在两表下用一句话建议重新生成对应视频；未达到则仅逐镜列建议。格式见 [项目约定](references/project.md)。不交付视频、HTML、JSON 或内部审查记录。

统一称“可推导省图”（内部 ai_fill），只省独立参考图，不删脚本镜头。按 [推导判据与决策表](references/review.md#可推导省图判据与决策表) 在原有组级审查中判断；状态无变化不等于可以省图，须有有效双侧锚点、资产及具体叙事承接依据。审查输出候选，最终规划再执行组首尾和关键锚点保护。漏镜、待检查及 ai_fill 均计入计划总时长。已有画面可读或缺图可推导，均不证明后续生成一定成功；省图统一标建议/未验证。审查证据不足先补查；仍不足就保留待检查并结束，不强行给通过结论。

事实来源分级、SHA256、.lock 和观察复用规则保持。旧生成模式的 max_retries=1、budget_cny/max_submissions、三轮上限与 submission_unknown 恢复逻辑不变；仅在用户另外要求生成时读 [生成与恢复](references/generation.md)。默认不进入付费、独立修图或补图入口。不实现 CLIP，不并发。

资产对比以人物、行动及剧情能否正确理解为准，允许不影响剧情的脸部、服装颜色、材质与款式偏差；明确要求严格一致的特征仍须满足。按 [剧情优先的资产审查](references/review.md#资产外观判定剧情优先) 填每镜 identity_reason，普通通过复用可见事实与帧证据，不强制逐人填写 wardrobe＋appearance。仅剧情相关外观要求/问题填写详细 asset_comparisons；FAIL/uncertain 必须说明具体剧情要求及影响。保留本镜证据、逐镜问题绑定和事实/解释分离。review_schema=4、reference_policy_version=3 进入指纹，旧审查及聚合需复核，不能直接升级。正常仍为三次判断与一次组 context/review。

## 工具入口

Python 3.10+、Pillow、FFmpeg/FFprobe。内部项目和记录由代理维护，用户不必填 JSON。已有视频模式 PROFILE.json 可写 `{}`，不使用模型配置中的时长、图片数量或成本限制；新版聚合固定执行计划时长 ≤15 秒及每组 ≤12 镜。

```text
python scripts/previs.py validate PROJECT.json
python scripts/previs.py import-video PROJECT.json G01 INPUT.mp4
python scripts/media.py extract INPUT.mp4 EVIDENCE_DIR --project PROJECT.json --group G01
python scripts/storyboard.py map PROJECT.json MAPPING.json
python scripts/storyboard.py select PROJECT.json SELECTION.json
python scripts/previs.py context PROJECT.json G01
python scripts/previs.py review PROJECT.json GROUP_REVIEW.json
python scripts/planner.py PROJECT.json PROFILE.json --post-review --output AGGREGATION.json
python scripts/previs.py render PROJECT.json DELIVERY_DIR
```

整组选帧可在一次工具调用中顺序登记数组，见审查规则。正常三镜路径仍为 3 次 LLM 判断：完整提取、批量匹配、组级校对与取舍。登记、抽帧、规划、渲染为工具操作。此为调用设计，不是实测耗时；补证时审查质量优先。
