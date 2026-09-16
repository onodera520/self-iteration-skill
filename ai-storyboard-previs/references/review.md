# 抽帧匹配、内容校对与漏镜处理

默认用户视频＋原脚本＋资产图，不需要提示词，不调用 API，不自动修图、补图或重生成。不审查镜头时长；视频实测时长及实际 PTS 只定义检索范围和证据位置。

## 批量匹配与补查

import-video 登记原视频；media.py extract --project/--group 校对视频绑定，抽取均匀帧与切点邻域。脚本无时长也可直接抽帧；抽样密度不是验收标准，稀疏帧不能证明没有漏镜、短暂字幕或错误转场。

一次读完整组的脚本、requirements、资产和候选，批量匹配。每张图片的可见 observation 按 SHA256 保存复用；同哈希仅在观察遗漏或矛盾时补看。不同帧的状态不能合成同一帧事实。回看原视频取得新信息时追加实际查看范围与观察。

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

previs.py context 一次输出全组 requirements、event（新项目）、scene_id/continuity_id、资产及哈希、视频/帧/映射、选帧、左右来源组边界、review_schema: 2、context_fingerprint 和 previous_review。一次 LLM 完成全组校对、事件划分核对、连续性与取舍依据，一次 previs.py review 保存。禁止逐镜 context/review；旧 storyboard.py 单镜 review 不代替此入口。事件划分以脚本行动目标及承接为准，不随视频错误改变；若发现事件标注有误，先修正完整事件字段并重新取得绑定上下文，再保存审查，不直接复制旧 PASS。普通路径仍是整理、匹配、审查三次判断。

优先用可用视频理解能力；否则看切点前后和镜头内部连续帧。复用已有哈希观察，只补充新证据。composition 仅使用“脚本明确 shot_size/关键帧要求 → 已有画面描述 → 满足/违反/证据不足”的规则；不加开放式视觉推理或审美评判。遮挡、画外和特写裁切不等于道具消失。

四项组级 checks 为 shot/continuity/story/subtitles，取 PASS/FAIL/uncertain。检查人物、场景、道具、动作及结果、顺序、必要切镜、字幕和衔接。组级失败不会自动使所有镜头失败；逐镜结论存 shot_reviews。连续性问题须定位受影响镜头，不能一面记录该镜问题一面标 PASS。

以下是单镜结构示例，实际必须按原顺序填满全组及全部边界：

```json
{
  "group_id":"G01","version":1,"video_sha256":"FROM_CONTEXT","context_fingerprint":"FROM_CONTEXT",
  "checks":{"shot":"PASS","continuity":"PASS","story":"PASS","subtitles":"PASS"},
  "coverage":{"shot_ids":["S01"],"mapping_verified":true,"limitations":[]},
  "evidence":[{"shot_id":"S01","time":0.25,"path":"EXTRACTED_PATH","sha256":"FRAME_SHA256",
               "observation":"可见人物、道具及状态；写明已查看的连续动作证据"}],
  "shot_reviews":[{"shot_id":"S01","verdict":"PASS","reason":"脚本内容与衔接满足",
    "evidence_times":[0.25],"checks":{"identity":"PASS","scene":"PASS","props":"PASS",
    "composition":"PASS","key_state":"PASS","continuity":"PASS","cleanliness":"PASS"}}],
  "reference_assessments":[{"shot_id":"S01","decision":"anchor","derivable":false,"basis_shot_ids":[],
    "reason":"首次出场与持物基线，需要保留","evidence_times":[0.25]}],
  "boundary_checks":[],"issues":[],"uncertainties":[]
}
```

shot_reviews 的 verdict：

- PASS：matched、有当前选帧且已包含在同镜 evidence 中、requirements ready、七项检查全 PASS，无本镜未解决问题；相关组边界也通过。即使同组其他镜头失败，本镜仍可独立通过。
- FAIL：已定位且有选帧证据，七项检查至少一项 FAIL，issues 定位本镜。轻微不符也标“该镜需重新生成”，不计必要漏镜。
- uncertain：证据不够，列局限和需补查内容，不省图、不计数。
- absent：必须对应完整补查后的 absent 映射，evidence_times 为空，不得在 evidence 里伪造该镜帧，issues 说明原视频缺失内容。组 story 必须 FAIL；漏镜绝不能 PASS。

整组 PASS 仍要求全部 matched、要求 ready、四项通过、mapping_verified、每镜证据、无未决限制。不要求 actual_shots、各镜区间长度或覆盖时长验收。不可确认的动作/切镜保留 limitations/uncertainties，并使受影响镜头 uncertain；不能为通过而删记录。

reference_assessments 按镜顺序填 anchor/ai_fill/pending、reason、derivable、basis_shot_ids、evidence_times。有图评估复用 shot_reviews 的同镜 evidence_times；确认漏镜则留空，依据补查和已有镜头。

- 人物首次出场、关键状态变化、空间变化、叙事转折及必要首尾优先 anchor。
- PASS 或确认 absent 的镜头可以评估推导。若 derivable: true，decision: ai_fill，basis_shot_ids 必须是同来源组中顺序正确的前、后两个已有镜头；二者各自 PASS、有当前有效选帧且 decision: anchor，相关资产图存在。说明具体状态如何承接，不允许缺失镜头互作依据或循环推导。
- confirmed absent 且无法推导：decision: pending、derivable: false，说明必要缺失内容；尚不能判断推导：pending、derivable: null。
- FAIL/uncertain：pending，不批准省图。推导意见还须过首尾/关键锚点硬约束；被保护的缺失锚点仍为必要漏镜。

boundary_checks 按 context.boundaries 原顺序填 `{"shot_id":"S00","verdict":"PASS","observation":"本组首镜与前组末镜持物衔接"}`。PASS 需邻镜 matched 证据和 ready 要求；FAIL/uncertain 反映到 continuity 和本组受影响边缘镜。其他镜头可以独立通过。

FAIL/absent 的 issues 必填 id、shot_ids、time_range、severity、problem、expected、actual、evidence、repair_target、fix。severity 为 low/medium/high/critical；默认 repair_target: video_shot，证据未定用 unresolved 并保持 uncertain。time_range 只是定位/回看范围。建议针对具体错误，不自动修图或重生成。

## 漏镜统计、失效与停止

审查后规划只计“确认缺失且无法省去的必要镜头”为 bad_num，每份输入视频各计一次。默认至少 2 镜且占该视频应覆盖镜头数至少 20% 才给重新生成建议。2/10 触发；2/11 与 1/3 不触发。轻微错误、可推导漏镜及待检查不计数，不变更脚本覆盖范围规避阈值。

输出仅两表，阈值触发时在两表下加一句建议，不生成视频结论表。可推导漏镜仍标“视频漏镜；可推导省图，未验证”。省图不代表原视频完整，也不删脚本位置。

重选单镜帧：重看该镜及左右衔接，复用其他有效观察，以完整组结构重登记新指纹。替换整份视频：整份重新抽帧、匹配和审查，左右来源组只补查接壤边界并复用内部观察。脚本/资产/视频/依据图片/映射变更均使相关旧结论失效。previous_review 只供复用观察，不直接复制过期 PASS。

证据不足先补查；仍无法确认则交付待检查并停止。默认没有生成重试。旧生成模式仅在另外获得用户生成指令后按 [生成恢复规则](generation.md) 处理：确认 FAIL 才登记 repair，再改提示词或拆组；三轮上限、预算、提交数、max_retries=1、.lock、submission_unknown 查询原任务逻辑不变，uncertain 不触发付费重试。

## 三镜验收与调用数

S01 女孩持钥匙；S02 同场景观察无关键变化；S03 钥匙交接完成。输入不要求时长。

| LLM 判断 | 一次输入 | 一次输出 | 后续工具 |
|---|---|---|---|
| 1 完整提取 | 完整脚本、资产、输入视频信息 | 三镜 facts/state_changes/requirements/块级来源 | 状态计算、校验、登记视频、抽帧 |
| 2 全组匹配 | 三镜要求、全部候选及实际时间 | 三镜映射、哈希观察、选帧理由 | map、顺序 select、一次组 context |
| 3 全组校对与推导 | context、已存观察、连续帧/视频 | 三镜独立结论、四项总检查、证据、取舍和边界 | 一次组 review、规则规划、两表渲染 |

正常路径由“3 提取＋1 匹配＋3 审查”的 7 次 LLM 判断合并为 3 次；旧逐镜 context/review 共 6 次工具往返变为一次组 context＋一次组 review 共 2 次。工具抽帧、登记和渲染另计。此为调用设计，不是实测耗时；补查如实增加判断，质量优先。

正常 S01/S03 保留，S02 可推导省图且标建议/未验证。模拟 S02 漏镜时先补查，确认 absent 后若前后通过且满足推导/硬规则，可给省图建议但仍保留漏镜结论；若必要或不确定则分别计数或待检查。测试覆盖轻微错误、重新抽帧纠正、混合结果、来源失效、阈值与无脚本时长；合成颜色视频只验证实际抽帧/PTS，模拟语义判断不当作真实视觉验收。

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
