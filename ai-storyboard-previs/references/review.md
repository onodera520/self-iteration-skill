# 抽帧匹配、内容校对与漏镜处理

默认用户视频＋原脚本＋资产图，不需要提示词，不调用 API，不自动修图、补图或重生成。不比较实际与计划时长，不据此判画面失败；聚合另按计划时长执行 15 秒上限。视频实测时长及实际 PTS 只定义检索范围和证据位置。

## 批量匹配与补查

import-video 登记原视频；media.py extract --project/--group 校对视频绑定，抽取均匀帧与切点邻域。脚本无时长也可直接抽帧；抽样密度不是验收标准，稀疏帧不能证明没有漏镜、短暂字幕或错误转场。

一次读完整组的脚本、requirements、资产和候选，批量匹配。每张图片记录中性的 visible_facts、独立的 interpretation 与兼容摘要 observation，按 SHA256 保存复用；同哈希仅在观察遗漏或矛盾时补看。不同帧的状态不能合成同一帧事实。回看原视频取得新信息时追加实际查看范围与观察。

```json
{
  "group_id": "G01", "video_sha256": "CURRENT_VIDEO_SHA256",
  "evidence_file": "evidence/G01/evidence.json",
  "shots": [
    {"shot_id":"S01","status":"matched","observation":"女孩握唯一钥匙，男孩未接触",
     "candidates":[{"path":"ABSOLUTE_EXTRACTED_PATH","time":0.25}]},
    {"shot_id":"S02","status":"uncertain","observation":"当前未定位观察镜头，需要回看",
     "candidates":[]},
    {"shot_id":"S03","status":"matched","observation":"男孩拿稳钥匙，女孩松手",
     "candidates":[{"path":"ABSOLUTE_EXTRACTED_PATH_3","time":4.5}]}
  ]
}
```

storyboard.py map 一次登记整组。候选来自未改动的 evidence.json，实际时间按原镜序严格递增；不能调换脚本编号掩盖乱序。

- **matched**：已定位对应镜头，不代表内容通过。人物、道具或动作轻微错误仍可定位，后续单镜 FAIL。
- **uncertain**：抽帧完全不符、尚未定位或证据不足。先回看原视频/加密抽帧；不直接判漏镜，不批准省图，不触发付费重试。
- **absent**：完整补查原视频确认没有该镜。需 full_rescan: true、空 candidates，以及 `rescan: {"ranges":[[0,6]],"observation":"完整回看 0–6 秒，记录实际出现的镜头和缺失内容"}`。这里 6 必须换成该视频实测终点，多个范围可连续覆盖整份视频，不能留空档或缩短原视频范围。工具检查范围与绑定，实际回看由代理负责。

补查找到对应内容：将新抽帧存新证据目录，更新映射并替换原错误选帧，复查该镜与左右衔接。不把“抽错帧”误报为视频错误。完整补查后仍不能确认内容或时序时继续 uncertain，不伪造 absent。

整组选帧在一次工具调用中顺序登记，复用匹配判断，不逐镜调用 LLM：

```python
from previs import read, save, locked
from storyboard import select_image
with locked(project_path):
    p = read(project_path)
    for selection in read(selections_path):
        select_image(p, project_path, selection)
    save(project_path, p)
```

selection 为 `{"shot_id":"S01","path":"候选路径","source":{"kind":"frame","time":0.25},"reason":"关键状态清楚"}`；缺失或不确定镜头不强选图。匹配与观察不启动费用。

## 一次组级审查，逐镜独立结论

previs.py context 一次输出全组 requirements、event（初分）、planned_duration/duration_source、narrative_plan、review_scope、scene_id/continuity_id、资产及哈希、视频/帧/映射、选帧、左右来源组边界、review_schema: 3、reference_policy_version: 2、context_fingerprint 和 previous_review。一次 LLM 完成全组校对、自然边界、相邻承接、整个合并区间复杂度核对、连续性与取舍依据，一次 previs.py review 保存。禁止逐镜 context/review；旧 storyboard.py 单镜 review 不代替此入口。事件划分以脚本行动目标及承接为准，不随视频错误改变；若发现事件标注有误，先修正完整事件字段并重新取得绑定上下文，再保存审查，不直接复制旧 PASS。有 narrative_plan 时，审查必须填写 grouping_checked: true；其含义是已核对批量剧情依据，不表示画面通过。普通路径仍是整理、匹配、审查三次判断。

优先用可用视频理解能力；否则看切点前后和镜头内部连续帧。复用已有哈希观察，只补充新证据。composition 仅使用“脚本明确 shot_size/关键帧要求 → 已有画面描述 → 满足/违反/证据不足”的规则；不加开放式视觉推理或审美评判。遮挡、画外和特写裁切不等于道具消失。

四项组级 checks 为 shot/continuity/story/subtitles，取 PASS/FAIL/uncertain。检查人物、场景、道具、动作及结果、顺序、必要切镜、字幕和衔接。不检查对白逐字一致、配音文本或对白口型同步，不因这些差异判 FAIL；对白、OS、VO 的剧情含义仍可帮助理解事件，明确画面动作和原有字幕检查不豁免。组级失败不会自动使所有镜头失败；逐镜结论存 shot_reviews。连续性问题须定位受影响镜头，不能一面记录该镜问题一面标 PASS。

以下是单镜结构示例，实际必须按原顺序填满全组及全部边界：

```json
{
  "group_id":"G01","version":1,"video_sha256":"FROM_CONTEXT","context_fingerprint":"FROM_CONTEXT",
  "grouping_checked":true,"review_schema":3,"reference_policy_version":2,
  "checks":{"shot":"PASS","continuity":"PASS","story":"PASS","subtitles":"PASS"},
  "coverage":{"shot_ids":["S01"],"mapping_verified":true,"limitations":[]},
  "evidence":[{"shot_id":"S01","time":0.25,"path":"EXTRACTED_PATH","sha256":"FRAME_SHA256",
               "visible_facts":["可见西装驳领","可见白色圆领内搭","外套表面有湿水反光"],
               "interpretation":"服装结构吻合；反光与雨水相容","observation":"本镜服装结构可见"}],
  "shot_reviews":[{"shot_id":"S01","verdict":"PASS","reason":"脚本内容与衔接满足",
    "identity_scope":[{"asset_id":"A01","aspect":"wardrobe","required":true,"reason":"本镜可见上身服装"},
      {"asset_id":"A01","aspect":"appearance","required":false,"reason":"本例为服装局部特写，不要求画外人脸"}],
    "evidence_times":[0.25],"checks":{"identity":"PASS","scene":"PASS","props":"PASS",
    "composition":"PASS","key_state":"PASS","continuity":"PASS","cleanliness":"PASS"}}],
  "reference_assessments":[{"shot_id":"S01","decision":"anchor","derivable":false,"basis_shot_ids":[],
    "reason":"首次出场与持物基线，需要保留","evidence_times":[0.25]}],
  "asset_comparisons":[{"id":"C01","shot_id":"S01","asset_id":"A01","asset_sha256":"FROM_CONTEXT",
    "aspect":"wardrobe","evidence_refs":[{"path":"EXTRACTED_PATH","sha256":"FRAME_SHA256","time":0.25}],
    "condition_factors":["rain","night lighting","wet reflections"],
    "stable_matches":["西装驳领","白色圆领内搭"],"stable_conflicts":[],"decision":"PASS",
    "unobservable_features":[],"followup":"","basis_shot_ids":[]}],
  "boundary_checks":[],"issues":[],"uncertainties":[]
}
```

shot_reviews 的 verdict：

- PASS：matched、有当前选帧且已包含在同镜 evidence 中、requirements ready、七项检查全 PASS，无本镜未解决问题；相关组边界也通过。即使同组其他镜头失败，本镜仍可独立通过。
- FAIL：已定位且有选帧证据，七项检查至少一项 FAIL，issues 定位本镜。轻微不符也标“该镜需重新生成”，不计必要漏镜。
- uncertain：证据不够，七项 checks 必须齐全，至少一项 uncertain、没有已确认 FAIL；填写 followup、局限和需补查内容，不省图、不计数。有已确认错误时整镜仍为 FAIL，同时保留其他 uncertain 检查。
- absent：必须对应完整补查后的 absent 映射，evidence_times 为空，不得在 evidence 里伪造该镜帧，issues 说明原视频缺失内容。组 story 必须 FAIL；漏镜绝不能 PASS。

整组 PASS 仍要求全部 matched、要求 ready、四项通过、mapping_verified、每镜证据、无未决限制。不要求 actual_shots、各镜区间长度或覆盖时长验收。不可确认的动作/切镜保留 limitations/uncertainties，并使受影响镜头 uncertain；不能为通过而删记录。

## 资产外观判定：逐镜结构证据

先记雨水、夜景、彩色光、曝光、遮挡、运动模糊等干扰，再比服装类别、驳领/拉链、领型、内搭、扣件、长度与轮廓，最后参考颜色、明暗、光泽和纹理。变暗、湿水反光、饱和度变化或“像皮衣”不能单独支持 FAIL。visible_facts 只记可见中性结构；interpretation 单独解释，不在缺乏结构证据时写“皮衣”“换装”“角色不一致”。不增加 confidence 分数。

每个非 absent 镜头的 identity_scope 对其 asset_ids 中每个人物分别列 wardrobe（服装）与 appearance（人物外观），填写 required 和 reason。required 表示本镜需要审查该方面，不能因为看不清就设为 false；required:false 仅用于脚本不要求且本镜不适用的方面，例如手部特写的画外人脸。被排除方面不生成 PASS 比较记录；identity 全部不适用时的 PASS 仅表示没有适用的身份检查，不声称验证完整人物身份。服装 PASS 不替代必要的人物外观判断。

asset_comparisons 每个“镜头＋资产＋方面”一条，示例字段均必填。aspect 为 wardrobe/appearance（对应 identity）、prop（对应 props）或 scene（对应 scene）。asset_sha256 取当前 context，evidence_refs 必须引用本镜 evidence 中的 path/sha256/精确 time，同时列在该镜 evidence_times 中。帧经当前抽帧集合绑定到当前视频；来源资产、视频、脚本与观察通过 context_fingerprint 一同绑定。

| decision | 必须满足 |
| --- | --- |
| PASS | 当前资产、本镜有效帧及时间，非空 stable_matches，没有 stable_conflicts 或必要不可见特征 |
| FAIL | 当前资产、本镜有效帧及时间，非空 stable_conflicts，并有对应 issue |
| uncertain | unobservable_features 明确必要的不可见结构，followup 写出需要补查的角度/帧；不能同时声称已有确定冲突 |

stable_conflicts 每项为 `{"feature":"领型与扣件","expected":"资产西装驳领及纽扣","observed":"清晰立领和非对称拉链","environment_exclusion":"光照和湿水不能将驳领纽扣变成立领拉链"}`。颜色、反光不能冒充结构冲突。缺少资产或本镜有效证据时，不允许资产 PASS/FAIL；未知先补证。identity 检查按适用比较归并：任一 FAIL 则 FAIL，否则有 uncertain 则 uncertain，否则 PASS。其他七项检查与问题独立保留。

资产差异问题不论写在 identity、props、continuity 或其他检查下，都必须填 asset_ids 与 asset_comparison_ids。多镜问题中的每个镜头、每个相关资产都要有各自的 FAIL 比较和 issue 时间范围内的证据；禁止将一镜推断扩散到全组，或用更换检查项逃避门槛。工具校验结构、哈希、绑定和结论组合，无法证明视觉描述真实或自动识别被故意错标的自然语言问题。

清晰邻镜可以帮助解释雨水与照明，记入 basis_shot_ids；引用镜须有同资产同方面、独立可见的 PASS 比较，不能循环解释或借用 FAIL。邻镜不能代替本镜可见事实，必要结构仍不清楚时保留 uncertain。背面、远景不自动 uncertain：本镜所需轮廓、袖口等若清楚仍可判断。新证据推翻旧解释时，更新受影响镜头与相关衔接，保留无关问题。以清晰驳领、白色内搭纠正早先“黑亮所以是皮衣”的解释，不把邻镜结构写进本镜 visible_facts。

上述字段在原有全组匹配和审查内完成，不增加逐镜 LLM 往返。对同一 SHA256 的有效事实复用；新规则要求补全或发现矛盾时才重看。雨夜西装结构吻合→PASS、明确机车夹克结构冲突→FAIL、必要结构不可见→uncertain 是行为回归；合成记录仅验证门槛，真实视觉验收另记范围。

## 可推导省图：判据与决策表

统一使用“可推导省图”，内部值仍为 ai_fill。三个字段分别回答不同问题，不互相覆盖：mapping.status 的 matched/uncertain/absent 表示是否定位；shot_reviews.verdict 表示画面检验结论；reference_assessments.decision 表示参考图取舍候选。matched 不等于 PASS，ai_fill 不等于视频有该镜，pending 本身不等于漏镜。沿用现有字段，不另建 present/absent 二值状态。

reference_assessments 按镜顺序填 decision、reason、derivable、basis_shot_ids、evidence_times。有图评估复用 shot_reviews 的同镜 evidence_times；确认漏镜则留空，引用完整补查及依据镜，不能伪造本镜证据。

在同一次组级审查中，按下列条件判断可推导性，复用已保存的观察，不另作逐镜 LLM 调用：

1. **依据有效**：仅 PASS 或完整补查确认 absent 的镜头进入推导判断。basis_shot_ids 是同来源组中顺序正确、前后夹住该镜的两个已有镜头；两者各自 PASS、有当前有效选帧且 decision: anchor，相关资产图存在。缺失镜头和其他 ai_fill 不可充当依据，禁止循环推导或降级为单侧锚点。
2. **状态可以承接**：读取 requirements.py 计算的完整 entry_state/exit_state 及原 state_changes，说明前锚点如何提供入口条件、该镜出口如何衔接后锚点。代理只填写入口种子和状态变化，不重写完整入口/出口。无关键变化是筛选条件，不是充分证明；非关键动作可有变化，但其过程与结果必须能说明。不能把后镜状态倒灌到前镜。
3. **没有必须独立约束的信息**：核对 purpose、keyframe、must_have/must_not_have 与剧情。人物首次出场、新的关键属性、关键道具或空间状态变化、关键反应/决定、叙事转折及动作结果须保护；资产库已有该人物不代表其首次出场可省。即使状态不变，揭示钥匙刻字的特写、必须可见的反应或独特空间关系也可能需要保留。
4. **画面要求可由依据补足**：reason 简述“依据镜号及可见内容 → 本镜入口/动作/出口如何承接 → 为什么没有必须独立呈现的新信息”。例如前后均提供同场人物与持物基线，本镜只是无关键变化的观察，可提出候选；不能仅写“状态相同”“同组”或“AI 能生成”。景别只按脚本明确要求比较，不增加审美判断。

derivable 为三值：true 表示上述依据与语义条件均满足，可提出候选；false 表示明确无法可靠推导或已知必须保留独立图，说明原因；null 表示证据或判断不足，说明缺什么，不能把未知写成 false。必要首尾及用户锁定锚点也不能因可推导而省去。

| 逐镜 verdict | derivable | 审查 decision | 含义及后续 |
| --- | --- | --- | --- |
| PASS | true | ai_fill | 可推导省图候选，交最终规划检查锚点约束 |
| PASS | false / null | anchor | 保留已通过图片；null 仅表示推导未定，不撤销画面通过 |
| absent | true | ai_fill | 可推导省图候选；保留漏镜结论，注明未验证 |
| absent | false | pending | 必要漏镜，需补生成 |
| absent | null | pending | 推导待检查，不因未知计入必要漏镜 |
| FAIL / uncertain | 任意 | pending | 不批准省图；分别建议修正或先补证据 |

表中 decision 是**审查候选**，不是最终省图批准。planner 在确定 ≤15 秒、≤12 镜的最终聚合后，再检查组首尾、关键锚点和同组双侧依据；候选成为新组首尾、依据被分到其他组等情况必须保留。硬约束优先于候选 true：有合格图则保留；确认缺失且必须保留则为必要漏镜。null 仍为待检查，不计必要漏镜；若审查已确认必须独立保留，应写明依据并填 false，不能用 null 掩盖已知必要条件。分组通过也不能把 FAIL/absent 升为 PASS。

所有可推导省图均为“建议，未验证”。原视频该镜 PASS 只证明原画面符合脚本，不证明省去独立参考图后仍能生成。风险/信心不是验证状态，本轮不新增 confidence/risk 或“已验证”字段，不启动专项生成。工具检查字段组合、依据资格、指纹和硬约束；可重建性的语义判断由上述批量审查承担，不能把工具校验通过当作生成实证。

已有视频 context 的 reference_policy_version 纳入指纹。review_schema=3 与 reference_policy_version=2 均进入指纹；旧审查与依赖它的聚合失效，不能改版本号后直接复用。有效抽帧、映射和哈希可继续使用；旧自由文字 observation 不能自动转换成新版比较证据，须按新判据补充事实并完成组级复核。

boundary_checks 按 context.boundaries 原顺序填 `{"shot_id":"S00","verdict":"PASS","observation":"本组首镜与前组末镜持物衔接"}`。PASS 需邻镜 matched 证据和 ready 要求；FAIL/uncertain 反映到 continuity 和本组受影响边缘镜。其他镜头可以独立通过。

FAIL/absent 的 issues 必填 id、shot_ids、time_range、severity、problem、expected、actual、evidence、repair_target、fix，以及 asset_ids 和 asset_comparison_ids（非资产问题两者均填空数组）。severity 为 low/medium/high/critical；默认 repair_target: video_shot，证据未定用 unresolved 并保持 uncertain。time_range 只是定位/回看范围。建议针对具体错误，不自动修图或重生成。

## 漏镜统计、失效与停止

审查后规划只计“确认缺失且无法省去的必要镜头”为 bad_num，每份输入视频各计一次。默认至少 2 镜且占该视频应覆盖镜头数至少 20% 才给重新生成建议。2/10 触发；2/11 与 1/3 不触发。轻微错误、可推导漏镜及待检查不计数，不变更脚本覆盖范围规避阈值。

输出仅两表，阈值触发时在两表下加一句建议，不生成视频结论表。可推导漏镜仍标“视频漏镜；可推导省图，未验证”。省图不代表原视频完整，也不删脚本位置。

重选单镜帧：重看该镜及左右衔接，复用其他有效观察，以完整组结构重登记新指纹。替换整份视频：整份重新抽帧、匹配和审查，左右来源组只补查接壤边界并复用内部观察。脚本/资产/视频/依据图片/映射变更均使相关旧结论失效。previous_review 只供复用观察，不直接复制过期 PASS。

证据不足先补查；仍无法确认则交付待检查并停止。默认没有生成重试。旧生成模式仅在另外获得用户生成指令后按 [生成恢复规则](generation.md) 处理：确认 FAIL 才登记 repair，再改提示词或拆组；三轮上限、预算、提交数、max_retries=1、.lock、submission_unknown 查询原任务逻辑不变，uncertain 不触发付费重试。

## 三镜验收与调用数

S01 女孩持钥匙；S02 同场景观察无关键变化；S03 钥匙交接完成。若脚本未给时长，一次整理时可分别建议 3、2、3 秒并记 inference 来源；总时长 8 秒（含建议值），不是实测时长。

| LLM 判断 | 一次输入 | 一次输出 | 后续工具 |
|---|---|---|---|
| 1 完整提取 | 完整脚本、资产、输入视频信息 | 三镜 facts/state_changes/requirements/块级来源、event、时长来源、narrative_plan | 状态计算、校验、登记视频、抽帧 |
| 2 全组匹配 | 三镜要求、全部候选及实际时间 | 三镜映射、哈希观察、选帧理由 | map、顺序 select、一次组 context |
| 3 全组校对与推导 | context、已存观察、连续帧/视频 | 三镜独立结论、四项总检查、证据、取舍、边界及 grouping_checked | 一次组 review、规则规划、两表渲染 |

正常路径由“3 提取＋1 匹配＋3 审查”的 7 次 LLM 判断合并为 3 次；旧逐镜 context/review 共 6 次工具往返变为一次组 context＋一次组 review 共 2 次。工具抽帧、登记和渲染另计。此为调用设计，不是实测耗时；补查如实增加判断，质量优先。

正常 S01/S03 保留，S02 可推导省图且标建议/未验证。模拟 S02 漏镜时先补查，确认 absent 后若前后通过且满足推导/硬规则，可给省图建议但仍保留漏镜结论；若必要或不确定则分别计数或待检查。测试覆盖轻微错误、重新抽帧纠正、混合结果、来源失效、阈值、无时长可审查但聚合待规划、建议时长及剧情三步合并；合成颜色视频只验证实际抽帧/PTS，模拟语义判断不当作真实视觉验收。

## 借鉴来源与边界

审查设计参考 [Reviewer-skill，固定提交 4c9dc937](https://github.com/onodera520/Reviewer-skill/tree/4c9dc937de3a51379928df91b2795d431c79861f)，具体采用：

| 原文件 | 本技能采用的思想 |
|---|---|
| [story-preview.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/story-preview.md) | 创作意图、关键结果与可容忍变化 |
| [continuity-review.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/continuity-review.md) | 同实体、可见性、正确基线与授权变化；状态账本 |
| [animatic-review.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/animatic-review.md) | 参考图角色、逐镜动态与序列检查、疑点补证 |
| [verdict-policy.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/verdict-policy.md) | 严重程度与修复对象分开；不确定不等于重做 |
| [generator-compatibility.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/references/generator-compatibility.md) | 生成分组不等于叙事场景 |
| [prepare_animatic.py](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/scripts/prepare_animatic.py) | 实际 PTS、镜头内部与切点邻域抽帧 |
| [story-preview-rubric.md](https://github.com/onodera520/Reviewer-skill/blob/4c9dc937de3a51379928df91b2795d431c79861f/evals/story-preview-rubric.md) | 用正反例检查审查行为而非仅测试格式 |

代码独立实现，不复制其整个技能。采用其状态基线、可见证据与局部修复思想，用于视频内容与连续性审查、候选匹配及有实证依据的省图建议；以源脚本而非生成提示词作为最高叙事依据。模拟案例只验证流程与记录，不宣称真实视频理解已被证明。
