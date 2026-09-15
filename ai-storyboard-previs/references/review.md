# 视频匹配、组级审查与有限返修

## 默认输入与问题处理

输入为用户视频、原脚本和资产图，先通过 import-video 登记。资产用于外观及身份核对，脚本用于内容、动作和顺序核对；不需要视频提示词。确认错误时输出待检查及修改建议，不调用生成或修图。用户提供替换视频后重新登记并审查该来源组及左右边界。下文的付费返修段仅适用于用户另外启用的旧生成模式。

## 批量匹配与观察复用

先用 media.py extract 从当前视频提取镜头内部、切点前后和均匀采样帧。--project/--group 会核对当前视频并记录实测时长；计划区间只辅助定位，真实 PTS 才是匹配时间。稀疏帧不能证明动作完整、没有短暂字幕或正确转场。

一次读取完整组的脚本、requirements、资产及候选帧，批量完成映射。每张图按 SHA256 记录可见 observation，后续复用；观察有遗漏或矛盾才补看同一图。一个 observation 涉及多个候选时要逐个说明对应路径或哈希，不能把不同帧的状态合成一个事实。回看视频发现新信息时追加记录。

```json
{
  "group_id": "G01", "video_sha256": "CURRENT_VIDEO_SHA256",
  "evidence_file": "evidence/G01-v1/evidence.json",
  "shots": [
    {"shot_id": "S01", "status": "matched", "observation": "该候选中女孩拿着唯一钥匙，男孩未接触",
     "candidates": [{"path": "ABSOLUTE_EXTRACTED_PATH", "time": 0.25}]},
    {"shot_id": "S02", "status": "uncertain", "observation": "当前抽样未定位观察镜头，需补查", "candidates": []},
    {"shot_id": "S03", "status": "matched", "observation": "该候选中男孩拿稳钥匙，女孩松手",
     "candidates": [{"path": "ABSOLUTE_EXTRACTED_PATH", "time": 4.5}]}
  ]
}
```

`storyboard.py map PROJECT.json MAPPING.json` 一次登记整组。候选路径必须来自未改动的 evidence.json，时间严格按原镜头顺序排列。发现乱序时不能交换脚本编号掩盖问题，记录 uncertain 或确认后的问题。

- matched：确有对应内容且有候选。只是定位成功，不代表身份、道具、动作或连续性通过。
- uncertain：没有足够证据。先完整回看或加密抽帧，在新证据目录中保存新映射；不省图，不触发付费重试。
- absent：补查完整原视频后确认确实没有该镜，填 full_rescan: true 和所查范围/可见依据。不是“没抽到”。随后登记有证据的问题，才可进入确认失败返修。

选帧是工具操作，复用匹配判断，不再逐镜调用 LLM。将整组选择写成数组，用一次工具调用顺序登记：

```python
from previs import read, save, locked
from storyboard import select_image
with locked(project_path):
    p = read(project_path)
    for selection in read(selections_path):
        select_image(p, project_path, selection)
    save(project_path, p)
```

数组元素为 `{"shot_id":"S01","path":"已匹配候选路径","source":{"kind":"frame","time":0.25},"reason":"对应入口关键状态"}`。缺失或不确定镜头不强选图。每镜先选一张当前候选，ai_fill 是否交付由之后的建议决定；选帧不产生费用。

## 按组读取与登记

```text
python scripts/previs.py context PROJECT.json G01
python scripts/previs.py review PROJECT.json GROUP_REVIEW.json
```

context 一次输出整组 requirements、资产及其哈希、当前视频路径/哈希、候选和抽帧、左右组各一个边界镜头的要求及映射、context_fingerprint、previous_review。一次 LLM 判断完成整组和邻接连续性，再一次 review 保存。禁止逐镜调用旧 storyboard.py context/review。

优先使用可用视频理解能力检查完整时序；否则看切点前后及镜头内部连续帧。复用匹配时已按哈希保存的观察，仅补充尚未观察的帧或缺失证据。previous_review 供复用观察，旧 PASS 不能直接复制到新指纹。新视频全部镜头都需重新匹配；相邻未变化组只补查边界，其内部有效观察不重看。

四个 checks 统一为 PASS/FAIL/uncertain：

| 检查 | 覆盖内容 |
|---|---|
| shot | 人物身份/服装、场景、道具数量/持有者、动作与结果、关键帧阶段、画面瑕疵；composition 只比对脚本明确景别与关键帧描述 |
| continuity | 组内相邻镜头以及左右组边界的身份、服装、空间、手别、持物和动作状态；按脚本授权变化 |
| story | 全部原镜头覆盖、实际顺序、必要硬切、无新增剧情，主要事件是否可理解 |
| subtitles | 视频是否出现不应有的字幕、文字或水印 |

composition 使用“明确要求 → 已有画面描述 → 满足/违反/证据不足”的规则，不添加审美评分或开放式视觉推理。画外、遮挡、特写裁掉的状态不能当消失；缺乏可见证据也不能当验证。

组级 review 的结构如下，示例仅列一镜，实填必须覆盖整个组及全部边界：

```json
{
  "group_id": "G01", "version": 1,
  "video_sha256": "FROM_CONTEXT",
  "context_fingerprint": "FROM_CONTEXT",
  "checks": {"shot":"PASS","continuity":"PASS","story":"PASS","subtitles":"PASS"},
  "coverage": {
    "shot_ids": ["S01"], "mapping_verified": true,
    "actual_shots": [{"shot_id":"S01","start":0,"end":2}],
    "limitations": []
  },
  "evidence": [
    {"shot_id":"S01","time":0.25,"path":"EXTRACTED_PATH","sha256":"FRAME_SHA256",
     "observation":"可见的人物、道具状态和动作证据；补充已查看的连续时间范围"}
  ],
  "reference_assessments": [
    {"shot_id":"S01","decision":"anchor","reason":"人物首次出现，保留身份与持物基线","evidence_times":[0.25]}
  ],
  "boundary_checks": [],
  "issues": [], "uncertainties": []
}
```

reference_assessments 与组内原镜号顺序完全一致。decision 为 anchor/ai_fill/pending；理由说明新信息、关键状态及前后承接；evidence_times 必须引用同镜 evidence 的实际时间。关键状态/首次出场保留图；已匹配、无关键变化且可承接才候选 ai_fill；未知或失败标 pending。此处是候选意见，最终仍过规则约束，不再进行另一轮 LLM 取舍。

boundary_checks 对 context.boundaries 中每镜填 `{"shot_id":"S00","verdict":"PASS","observation":"前组末镜与本组首镜持物及位置相接" }`，按 context 顺序。PASS 必须有已匹配邻镜证据和 ready 要求；边界 FAIL/uncertain 同步影响 continuity。边界未生成时暂 uncertain，可以继续生成其他独立组，待边界就绪后复用观察补登记，不能因此付费重试本组。

FAIL 的 issues 必填 id、shot_ids、time_range、severity、problem、expected、actual、evidence、repair_target、fix。severity 为 low/medium/high/critical，默认修复对象 video_shot；证据未定用 unresolved 并保持 uncertain。问题必须可定位，修复建议针对提示词或拆组，不转成独立修图请求。

PASS 需全部镜头 matched、要求 ready、四项检查通过、无未决限制和疑点，且实际镜头区间按原顺序完整覆盖实测视频时长，每镜都有区间内的哈希绑定帧证据。完整视频/连续帧仍不能确认的动作或转场记入 limitations/uncertainties，不能为了得到 PASS 清空限制。工具只校验记录和绑定，不能替代理证明真的看过视频。

## 返修、失效与停止

先补查再返修，确认缺失同样不能当 ai_fill。有当前 FAIL 审查后，先 `previs.py repair PROJECT.json G01 --reason "..."` 登记，再修改该组 prompt_notes；需拆组时用 `previs.py split PROJECT.json G01 S03`。先登记再改提示词，避免令 FAIL 证据提前失效。新请求用新 ID 和对应组版本，先 dry-run 再提交。

新视频出来后整组重新抽帧、匹配、选帧和审查。左右原组只重看与它接壤的边界镜；内部观察复用，但以完整组结构重新登记当前审查。其他有效组保持。脚本/资产/requirements/源视频/抽帧哈希/映射变化使相关旧审查与聚合结论失效；失效不等于确认失败，不直接启动收费生成。

每批受影响组计一轮，最多三轮，预算或提交上限先到即停。证据补查/重选帧不消耗生成轮次。超时、下载失败、submission_unknown 依 [恢复规则](generation.md) 处理，禁止清空任务或重复提交。到限保存最佳抽帧；历史帧标待检查，不能用于当前视频的 ai_fill 通过。

## 三镜组端到端验收说明

输入：S01 女孩拿着唯一钥匙；S02 同场景观察，人物/持物无关键变化；S03 钥匙交接完成，男孩拿稳、女孩松手。示例计划 2/1.5/2 秒，实际 API 参数以选择的模型为准。

| LLM 判断 | 一次输入 | 一次输出 | 后续工具 |
|---|---|---|---|
| 1 完整脚本提取 | 三镜原文、输入视频、资产观察、时长/画幅 | 全部 facts/state_changes/requirements/块级来源 | requirements.py 计算状态；按输入视频登记来源组；import-video 保存哈希与时长；工具抽帧 |
| 2 整组匹配 | 三镜要求、资产、整组候选及实际时间 | 三镜 matched/uncertain/absent、候选和 observation、选帧理由 | 一次 map 登记；一次工具调用顺序 select 全组；context 取得当前整组指纹 |
| 3 整组校对与取舍依据 | context、已保存观察、必要连续帧/视频 | 四项 checks、三镜证据与参考图评估、边界/问题 | 一次 review 登记；planner --post-review；render |

正常无缺证路径设计为 **3 次 LLM 判断**：逐镜三次提取合为一次，逐镜三次审查合为一次，取舍并入审查；原先按“3 提取＋1 组匹配＋3 审查”计为 7 次，现为 3 次。三镜旧 context/review 共 6 次工具往返改为 1 次组 context＋1 次组 review，共 2 次。API 提交/查询、抽帧、校验、选择、规划和渲染仍执行，不是三次工具调用。此为调用设计，不是实测耗时；需要补证或返修时如实增加判断，质量优先。

正常规则结果：相邻组 A01 保留 S01/S03，S02 标 ai_fill 建议/未验证，有承接理由。S02 的原编号和脚本仍展示；实际生成组与任务不被 A01 覆盖。

反例：模拟中间镜头未出现，先 uncertain 和补查；完整补查后才 absent、FAIL 与有限视频返修，绝不能因“省图合适”吞掉漏镜。测试还须覆盖新视频旧证据失效、邻组边界复查、预算停止、原任务恢复。合成颜色视频只测抽帧时间和顺序，不当作真实人物/交接验收。

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
