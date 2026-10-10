---
name: ai-storyboard-previs
description: 根据用户的视频、脚本和资产图，抽帧匹配、回看补查并校对内容与连续性，判断保留图、可推导省图和必要漏镜，再聚合相邻分镜，交付带小分镜图的两张 Markdown 表。用于已有视频的分镜校对、聚合规划与参考图取舍；已授权时按证据阈值通过固定 RunningHub 工作流返修一次并独立复审。
---

# 抽帧校对与分镜聚合

输入为视频、完整分镜脚本和资产图。默认仅做抽帧匹配、剧情校对、补查、参考图取舍与相邻聚合，交付图片及两张 Markdown 表。仅在返修阈值满足且用户已授权消耗 RH 币时，执行一次固定工作流返修并独立复审。

可选输入该视频原始生成提示词（粘贴文本或 UTF-8 TXT/MD）。视频登记后用 repair_reference.py 原样保存并绑定来源视频；不要求用户补交，不将提示词当作成片证据或新增审查要求。实际返修时，在同一准备批次对照原提示词、完整脚本和已确认问题，选择相容且有用的视觉细节、排除冲突及重复内容。脚本决定剧情，现有生成规则决定无声、无字幕、镜序、时长和本次画幅；不直接拼接两份长文本。详见 [原视频提示词参考](references/auto-repair.md#原视频提示词参考)。

返修画幅以该次来源视频的实际显示比例为准；与固定导出或项目配置不符时，只覆盖本次请求中的分辨率节点及提示词，不修改固定导出、线上保存的工作流或项目默认画幅。具体支持范围与旧任务恢复见自动返修规则。

返修提示词使用独立的纯视觉视图：原脚本保留对白与 OS/VO，发送给模型的文本只表达已有动作、表情和剧情关系，不含台词原句、说话表演、声音或字幕指令。含此类内容的字段在返修准备中一次转换并绑定来源；无法保留关键剧情时停止。规则与字段见 [受控提示词](references/auto-repair.md#受控提示词)。

## 按阶段读取

先读当前阶段需要的文件，已读且未变的规则直接复用；不提前展开所有链接、历史记录或返修资料。

| 阶段 | 必读资源 | 按需补充 |
| --- | --- | --- |
| 整理与准备 | [项目约定](references/project.md)、[镜头要求](references/shot-requirements.md)、[已有视频模板](assets/imported-project.json) | 首次探测环境读 [执行提效](references/efficiency.md#环境探测与复用)；事实定义不清读 [事实规则](references/facts-and-planner.md) |
| 匹配与审查 | [审查规则](references/review.md)、[精简工作单](references/efficiency.md#工作清单与协调草稿) | FAIL/absent 读 [返修证据字段](references/repair-assessments.md)；确有并行收益且允许子任务时读 [条件并行](references/parallel-review.md) |
| 聚合与交付 | [规划规则](references/planning.md)、项目约定的交付部分、执行提效的收尾部分 | 失败时只读对应恢复说明 |
| 实际返修 | [自动返修](references/auto-repair.md)及本机 runninghub-fixed-workflow 技能 | 触发且有授权后才整理返修资产风格，不预读旧公开模型或修图模式 |

## 默认执行顺序

1. **探测一次、整批整理。** 固定路径找到可用 Python/FFmpeg/FFprobe 就复用，缺组件才安装到稳定缓存目录。先一次路径 preflight，再一次 LLM 处理完整脚本，填写所有镜头的 facts/state_changes/requirements/块级来源、event、duration/duration_source 和 narrative_plan。输入明确提供 Beat 划分时，同批填写每镜 beat；未提供则全脚本视为一个 Beat，不把 event 自动变成 Beat。只写入口状态种子及变化，由 requirements.py 计算完整入口、出口状态。保留 source_script 和每镜 script 原文、镜号、顺序及画幅；同批摘取 shot_design，不新增脚本未给的剧情、机位或硬条件。缺计划时长提出建议并标来源。返修资产风格默认延后准备，原文基线仍立即冻结。
2. **一次准备、全组匹配。** 使用 prepare_imported.py run 串行完成校验、视频登记、基线冻结与稀疏抽帧，不先重复独立 validate。来源组列明视频应覆盖的连续镜头，不等于最终聚合组。一次批量匹配，候选路径、实际时间与 SHA256 来自真实 evidence.json；已看的每帧立即记 observation/visible_facts。MAPPING.json 的 selections 可同时登记选帧，不逐镜 map/select/context。
3. **集中补证。** 对 uncertain、瞬时动作、关键结果、状态冲突和边界疑点，合并时间范围后局部加密或回看。稀疏抽帧不能证明漏镜；absent 必须有完整视频回看或连续全片覆盖记录。找到镜头后替换错误选帧；证据仍不足则内部保留 uncertain，交付写具体缺口。事实按精确哈希复用，解释冲突时重新核对。
4. **一次组级审查。** prepare 同时保存完整上下文、只读精简视图、机械草稿和精简工作单。先读视图中的全部候选、脚本要求、资产、状态及边界；详细绑定按需回查完整上下文。工作单逐镜明确填写检查、判定、identity_reason、取舍和推导理由，逐帧补解释；已有中性事实可显式复用。FAIL/absent 必须补完整返修依据，其他镜头不带空返修表。fill 已包含原完整校验，成功后一次 review 登记；不额外重复 check，不逐镜审查，也不由空字段自动推定 PASS。
5. **一次收尾。** finish_review.py 串行完成预检、规划、机读返修判定、渲染、交付校验及冻结。工具三步聚合：剧情自然初分、相邻合并、短段复核；最终组内再选参考图。成功后核对两表和图片一次，有新问题才重做。冻结后补正使用新目录及关联修订，保留原交付；失败依恢复报告继续，不靠重复运行掩盖失败耗时。

```text
python scripts/prepare_imported.py preflight --script SCRIPT.txt --video INPUT.mp4 --asset A.png
python scripts/prepare_imported.py run PROJECT.json G01 INPUT.mp4 EVIDENCE_DIR --run-dir PREPARE_INTERNAL_DIR
python scripts/storyboard.py map PROJECT.json MAPPING.json
python scripts/review_draft.py prepare PROJECT.json G01 REVIEW_DRAFT.json --context-output CONTEXT.json --view-output REVIEW_VIEW.json --worklist-output WORKLIST.json
python scripts/review_draft.py fill PROJECT.json REVIEW_DRAFT.json WORKLIST.json COMPLETED_REVIEW.json
python scripts/previs.py review PROJECT.json COMPLETED_REVIEW.json
python scripts/finish_review.py PROJECT.json PROFILE.json --output DELIVERY_DIR --run-dir FINISH_INTERNAL_DIR
```

`python` 指已验证的解释器。PROFILE.json 在已有视频模式可为 `{}`。JSON、上下文和工作单均由代理维护，留内部目录，用户无需填写。需要详细可选字段时编辑完整草稿并 check；旧工作单可用 `--legacy-worklist`，原单步入口继续兼容。

## 必须保留的质量边界

- **剧情优先、逐镜独立。** matched 仅表示定位，不等于通过。允许不影响剧情的脸部、服装、姿势、景别及视角差异；人物与行动主体、关键道具、动作结果、空间因果、顺序、必要切镜和用户明确严格要求仍须证据。不检查具体对白逐字、口型、屏幕文字，也不比较视频实测与计划时长。composition 依据已有画面描述与脚本必要信息作规则判断。外观问题沿用剧情影响与本镜证据门槛。
- **省图不删镜。** ai_fill 只是建议、未验证；最终须有同组有效双侧 PASS＋保留图锚点、资产及状态支持，保护首尾和关键剧情变化，不循环借缺镜作为依据。确认漏镜仍使 story 为 FAIL，其他镜头可独立通过。必要漏镜阈值及独立返修阈值见对应规则，不把 uncertain 当必要漏镜或付费重试理由。
- **时长与交付。** 所有脚本镜头，包括漏镜和 ai_fill，计入计划总时长；仅合并同一 Beat 内的相邻镜头，每组4–15秒、≤12镜，<8秒强制复核，8秒不是下限。镜号按原顺序各覆盖一次，组时长及总时长精确守恒，不改原镜时长。短组先尝试调整相邻切分位置；仍无解则标聚合未完成，不能交付为合格分组。超长单镜标需拆分，不擅自缩短。仅两表：分组/镜序/总时长/理由；逐镜含时长、原文描述、小图、检验、处理、推导依据与建议。已有镜头即使建议省图仍显示缩略图和原图；仅确认漏镜且最终批准省图写纯文字“可推导生成”。不输出视频结论表、视频、HTML或内部记录。
- **简洁呈现。** 最终表格和图片不使用“待检查”标签。必要补查后仍证据不足，检验结果写“—”、图片处理写“暂不省图”，问题栏写具体缺口及补查方向；已确认漏镜仍写“视频漏镜”。问题或修改建议优先一句短说明，不重复状态、时长、依据镜号或内部证据；多项独立问题各用短句，不省略关键差异。内部 uncertain/pending、补查、计数及返修规则不变。
- **状态与失效。** 保持来源分级、精确 SHA256/时间/顺序、.lock、review_schema=5/reference_policy_version=5。精简编号只供阅读，完整证据与指纹仍走原校验。新视频整份重匹配审查；局部变化按状态、省图和边界依赖增量复核，不局限左右一镜，不复用失效结论。
- **并行与付费。** 默认串行；只有完整事件可独立核对且收益足够时，最多两个只读任务。同一计算状态、独立草稿、唯一写回；协调复核边界画面和入口/出口状态，最多四个非边界争议及跨任务依赖。付费仍须用户授权；每来源最多一次自动返修、max_retries=1、预算/提交上限与三轮上限不变。submission_unknown 继续查询原任务，不重复提交。更多轮次报告兼容不增加付费额度。

正常单事件路径仍为整理、匹配、审查三次 LLM 判断；工具负责规划及渲染。默认记录各阶段与总墙钟，包含失败、等待和重试；不以机械重放冒充视觉提速，不承诺固定速度或 token 降幅。
