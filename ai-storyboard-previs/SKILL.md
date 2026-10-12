---
name: ai-storyboard-previs
description: 根据用户的视频、脚本、资产图及可选 Shot 分组，抽帧匹配、回看补查并校对内容与连续性，在指定或自动分组内判断保留图、可推导省图和必要漏镜，交付图片和一张逐镜 Markdown 表。用于已有视频的分镜校对、聚合规划与参考图取舍；达到返修阈值时输出新视频提示词，供用户自行生成。
---

# 抽帧校对与分镜聚合

输入为视频、完整分镜脚本和资产图，可选提供 Shot 分组和原视频提示词。先做抽帧匹配、剧情校对、补查，在指定或自动分组内判断参考图取舍，交付图片及一张逐镜 Markdown 表。达到现有返修阈值时，完成受控提示词准备，另交付新视频提示词，然后停止。提示词只按“资产对应 → 逐镜脚本 → 固定预演要求 → 资产风格”排列，保留每镜必须／不得出现；不加标题、参数表、资产路径、代码块或内部返修说明。默认不调用生成 API，不上传资产、不提交或查询生成任务、不下载或复审返修视频；原先的一次自动付费授权不再适用于此默认流程。用户自行生成后交回新视频，再独立审查。

用户 Shot 分组接受表格、文字（如 `A01：S01–S03；A02：S04–S06`）或 JSON，存为独立 `input_shot_groups`，不替换视频来源组或审查批次。有输入就固定采用，跳过自动初分、相邻合并和短段复核，不要求这些步骤专用的 event/narrative_plan。用 grouping.py 一次收集覆盖、顺序、相邻性、4–15秒、12镜、Beat 和跨视频证据边界冲突；仅提示，不静默改组或退回自动分组。画面审查继续，受冲突影响的省图暂不批准；冲突不能成为画面 FAIL、必要漏镜或返修理由。无输入时沿用自动分组。具体字段与导入命令见 [分组约定](references/planning.md#用户输入-shot-分组)。

可选输入该视频原始生成提示词（粘贴文本或 UTF-8 TXT/MD）。视频登记后用 repair_reference.py 原样保存并绑定来源视频；不要求用户补交，不将提示词当作成片证据或新增审查要求。准备新提示词时，在同一批次对照原提示词、完整脚本和已确认问题，选择相容且有用的视觉细节、排除冲突及重复内容。脚本决定剧情，现有生成规则决定无声、无字幕、镜序、时长和本次画幅；不直接拼接两份长文本。详见 [原视频提示词参考](references/auto-repair.md#原视频提示词参考)。

新视频提示词的画幅以该次来源视频的实际显示比例为准，不修改项目默认画幅。旧固定工作流的请求级覆盖及恢复规则仍保留，但不在默认流程执行。具体支持范围见提示词规则。

返修提示词使用独立的纯视觉视图：原脚本保留对白与 OS/VO，发送给模型的文本只表达已有动作、表情和剧情关系，不含台词原句、说话表演、声音或字幕指令。含此类内容的字段在返修准备中一次转换并绑定来源；无法保留关键剧情时停止。规则与字段见 [受控提示词](references/auto-repair.md#受控提示词)。

## 按阶段读取

先读当前阶段需要的文件，已读且未变的规则直接复用；不提前展开所有链接、历史记录或返修资料。

| 阶段 | 必读资源 | 按需补充 |
| --- | --- | --- |
| 整理与准备 | [项目约定](references/project.md)、[镜头要求](references/shot-requirements.md)、[已有视频模板](assets/imported-project.json) | 首次探测环境读 [执行提效](references/efficiency.md#环境探测与复用)；事实定义不清读 [事实规则](references/facts-and-planner.md) |
| 匹配与审查 | [审查规则](references/review.md)、[精简工作单](references/efficiency.md#工作清单与协调草稿) | FAIL/absent 读 [返修证据字段](references/repair-assessments.md)；确有并行收益且允许子任务时读 [条件并行](references/parallel-review.md) |
| 聚合与交付 | [规划规则](references/planning.md)、项目约定的交付部分、执行提效的收尾部分 | 失败时只读对应恢复说明 |
| 阈值触发后提示词交付 | [提示词与历史任务](references/auto-repair.md) | 达阈值才整理返修资产风格及纯视觉转换；纯文本导出不需要 RunningHub 技能、密钥或付费额度 |

## 默认执行顺序

1. **探测一次、整批整理。** 固定路径找到可用 Python/FFmpeg/FFprobe 就复用，缺组件才安装到稳定缓存目录。先一次路径 preflight，再一次 LLM 处理完整脚本，填写所有镜头的 facts/state_changes/requirements/块级来源及 duration/duration_source。有 Shot 分组就同批导入并集中报告冲突；无输入分组才填写 event 和 narrative_plan。输入明确提供 Beat 划分时，同批填写每镜 beat；未提供则全脚本视为一个 Beat，不把 event 自动变成 Beat。只写入口状态种子及变化，由 requirements.py 计算完整入口、出口状态。保留 source_script 和每镜 script 原文、镜号、顺序及画幅；同批摘取 shot_design，不新增脚本未给的剧情、机位或硬条件。缺计划时长提出建议并标来源。返修资产风格默认延后准备，原文基线仍立即冻结。
2. **一次准备、全组匹配。** 使用 prepare_imported.py run 串行完成校验、视频登记、基线冻结与稀疏抽帧，不先重复独立 validate。来源组列明视频应覆盖的连续镜头，不等于最终聚合组。prepare-map 生成当前证据的帧编号视图和匹配工作单；一次批量填写镜号、帧号、匹配状态、单帧 observation/visible_facts 及选帧理由。map --view 恢复真实路径、实际时间和 SHA256，在原校验及同一锁内登记映射和选帧；证据变化后拒绝旧编号。不逐镜 map/select/context，也不由工具判断画面。
3. **集中补证。** 对 uncertain、瞬时动作、关键结果、状态冲突和边界疑点，合并时间范围后局部加密或回看。稀疏抽帧不能证明漏镜；absent 必须有完整视频回看或连续全片覆盖记录。找到镜头后替换错误选帧；证据仍不足则内部保留 uncertain，交付写具体缺口。事实按精确哈希复用，解释冲突时重新核对。
4. **一次组级审查。** prepare 同时保存完整上下文、只读精简视图、机械草稿和精简工作单。小组读完整视图；大组用 read --index 后按事件或镜号分段读取，保留所选镜头全部候选、要求、完整计算状态、邻镜及边界，明确列出本次未读内容。读取范围不缩小审查范围，全部必要证据读完后仍一次填写完整组；详细绑定按需回查完整上下文。工作单逐镜明确填写检查、判定、identity_reason、取舍和推导理由，逐帧补解释；已有中性事实可显式复用。FAIL/absent 必须补完整返修依据，其他镜头不带空返修表。fill 已包含原完整校验，成功后一次 review 登记；不额外重复 check，不逐镜审查，也不由空字段自动推定 PASS。
5. **一次收尾。** finish_review.py 串行完成预检、规划、机读返修判定、渲染、交付校验及冻结。有输入分组时固定采用，只在无冲突组内批准省图；否则工具依次完成剧情自然初分、相邻合并、短段复核。最终组内再选参考图。成功后核对逐镜表和图片一次，有新问题才重做。达到阈值的来源，在同一准备批次补齐资产风格、纯视觉转换及可选原提示词筛选，重新 decide 后用 export-prompt 导出 Markdown，并停止。提示词另放新目录，不修改冻结交付。未触发不强制输出新提示词；准备受阻说明缺项，不伪造提示词。冻结后补正使用新目录及关联修订，保留原交付；失败依恢复报告继续。

```text
python scripts/prepare_imported.py preflight --script SCRIPT.txt --video INPUT.mp4 --asset A.png
python scripts/grouping.py PROJECT.json SHOT_GROUPS.md --apply
python scripts/prepare_imported.py run PROJECT.json G01 INPUT.mp4 EVIDENCE_DIR --run-dir PREPARE_INTERNAL_DIR
python scripts/storyboard.py prepare-map PROJECT.json EVIDENCE_DIR/evidence.json --group G01 --output MATCH_VIEW.json --worklist-output MATCH_WORKLIST.json
# 阅读 MATCH_VIEW.json，整批填写 MATCH_WORKLIST.json 后：
python scripts/storyboard.py map PROJECT.json MATCH_WORKLIST.json --view MATCH_VIEW.json
python scripts/review_draft.py prepare PROJECT.json G01 REVIEW_DRAFT.json --context-output CONTEXT.json --view-output REVIEW_VIEW.json --worklist-output WORKLIST.json
# 仅大视图需要分段；小组直接读取 REVIEW_VIEW.json：
python scripts/review_draft.py read PROJECT.json REVIEW_VIEW.json --index
python scripts/review_draft.py read PROJECT.json REVIEW_VIEW.json --event E01
# 无事件字段或需指定范围时改用 --shots S01 S02；继续读完其余必要内容后填写整个 WORKLIST.json。
python scripts/review_draft.py fill PROJECT.json REVIEW_DRAFT.json WORKLIST.json COMPLETED_REVIEW.json
python scripts/previs.py review PROJECT.json COMPLETED_REVIEW.json
python scripts/finish_review.py PROJECT.json PROFILE.json --output DELIVERY_DIR --run-dir FINISH_INTERNAL_DIR
# 仅达到阈值且完成提示词准备后：
python scripts/repair_cycle.py decide PROJECT.json G01
python scripts/repair_cycle.py export-prompt PROJECT.json G01 --output PROMPT_DELIVERY_DIR/G01_新视频提示词.md
```

`python` 指已验证的解释器。只有提供了 Shot 分组才运行 grouping.py 导入行；省略 --apply 可只检查。PROFILE.json 在已有视频模式可为 `{}`。JSON、上下文和工作单均由代理维护，留内部目录，用户无需填写。多来源逐份判断和导出，不按 Shot 数增加生成任务。需要详细可选字段时编辑完整草稿并 check；旧工作单可用 `--legacy-worklist`，原单步入口继续兼容。

## 必须保留的质量边界

- **剧情优先、逐镜独立。** matched 仅表示定位，不等于通过。允许不影响剧情的脸部、服装、姿势、景别及视角差异；人物与行动主体、关键道具、动作结果、空间因果、顺序、必要切镜和用户明确严格要求仍须证据。不检查具体对白逐字、口型、屏幕文字，也不比较视频实测与计划时长。composition 依据已有画面描述与脚本必要信息作规则判断。外观问题沿用剧情影响与本镜证据门槛。
- **省图与返修分开。** ai_fill 只是建议、未验证，不删镜；最终须有同组有效双侧 PASS＋保留图锚点、资产及状态支持，保护首尾和关键剧情变化，不循环借缺镜作为依据。确认漏镜仍使 story 为 FAIL，其他镜头可独立通过。关键剧情问题或严重画面损坏有充分证据时 1 镜触发；普通影响剧情的错误与确认漏镜按原镜号去重，至少 2 镜且占来源视频全部应覆盖镜头 ≥20% 触发。影响剧情的可推导漏镜也计入，不等待省图判定；纯表演细节、允许的差异和 uncertain 不计入，先补证。达阈值只导出新提示词；证据字段见 [返修证据](references/repair-assessments.md)，bad_num 仍仅统计必要漏图。
- **时长与交付。** 所有脚本镜头，包括漏镜和 ai_fill，计入计划总时长；合格组为同一 Beat 内相邻镜头，每组4–15秒、≤12镜。镜号按原顺序各覆盖一次，时长精确守恒。自动分组才执行 <8秒短段复核及合法切分重排；输入分组有冲突只提示，不擅改时长或分组。超长单镜提示需拆分，不擅自缩短。仅一张逐镜表：分组、原镜号、镜头时长、脚本描述、小分镜图、检验结果、图片处理、推导依据镜号、问题或修改建议。已有镜头即使建议省图仍显示缩略图和原图；仅确认漏镜且最终批准省图写纯文字“可推导生成”。不输出分组表、视频结论表、视频、HTML或内部记录。
- **简洁呈现。** 最终表格和图片不使用“待检查”标签。必要补查后仍证据不足，检验结果写“—”、图片处理写“暂不省图”，问题栏写具体缺口及补查方向；已确认漏镜仍写“视频漏镜”。问题或修改建议优先一句短说明，不重复状态、时长、依据镜号或内部证据；多项独立问题各用短句，不省略关键差异。内部 uncertain/pending、补查、计数及返修规则不变。
- **状态与失效。** 保持来源分级、精确 SHA256/时间/顺序、.lock、review_schema=5/reference_policy_version=5。编号只用于阅读及机械复原绑定，不替代视觉判断；素材或上下文变化后拒绝旧视图，完整证据与指纹仍走原校验。新视频整份重匹配审查；局部变化按状态、省图和边界依赖增量复核，不局限左右一镜，不复用失效结论。
- **并行与执行。** 默认串行；只有完整事件可独立核对且收益足够时，最多两个只读任务。同一计算状态、独立草稿、唯一写回；协调复核边界画面和入口/出口状态，最多四个非边界争议及跨任务依赖。默认到提示词交付停止，不自动进入旧 submit/resume/install/repaired 流程。文本导出不占提交额度，也不受 API 密钥、固定工作流安装或支付预算阻挡。旧任务、预算/提交上限、max_retries=1、.lock、三轮上限保持；仅另行明确要求执行或恢复时使用历史入口，submission_unknown 只恢复原任务，不重复提交。

正常单事件路径仍为整理、匹配、审查三次 LLM 判断；工具负责规划及渲染。默认记录各阶段与总墙钟，包含失败、等待和重试；不以机械重放冒充视觉提速，不承诺固定速度或 token 降幅。
