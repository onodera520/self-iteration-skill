# 单条视频：最多两个任务并行审查

并行的是视觉审查草稿。全脚本解释、状态计算、全片匹配先统一完成；补帧、改映射、项目写回和所有付费操作均由主流程串行执行。本文件不改变 review.md 的证据门槛、剧情优先规则、漏镜语义或审查版本。脚本工具只管理分工与校验，不会启动模型或证明视觉判断正确。

## 何时启用与如何分工

在已有视频完成整组匹配后，若有两个以上可独立审查的连续事件，并且运行环境提供审查子代理，则默认启用。只有一个紧密事件、旧项目缺事件字段、任务太小或无法使用子代理时，继续原来的串行组级审查。不要为了并行把一个连续事件切成两半。多来源视频逐份处理，第一版不同时建立多个写回中的来源审查。

在原有整理/匹配批次中给出 units，不额外逐镜询问。每个 unit 必须覆盖连续镜号，可将多个自然承接的小事件合为一个 unit。每个已有脚本审查组都完整覆盖；短组可合批。相邻相同 event.id 不得分给不同 unit；event 标签不同仍可能是同一连续行动，需先通读剧情合批。不能按固定镜数、秒数、最终 15 秒聚合组机械拆任务。

workload 是同批估计的相对审查工作量，考虑候选/连续帧数量、角色与道具关系、动作链和疑点；不是视频时长或成本。工具将完整 unit 分到最多两个任务，使估计负载尽量接近。一项任务可以负责多个完整 unit。估计偏差会影响加速效果，不降低审查范围。

```json
[
  {"shot_ids":["S01","S02"],"reason":"人物离开并建立淋雨状态，完整事件","workload":2},
  {"shot_ids":["S03","S04","S05","S06"],"reason":"观察后决定追出，保留完整判断过程","workload":4},
  {"shot_ids":["S07","S08"],"reason":"推门、开伞并追出，连续行动不拆","workload":3}
]
```

units 仅是审查分工，不能覆盖 event、状态、生成来源组或最终聚合。最终仍从全脚本按三步法聚合，≤15 秒、≤12 镜。

## 冻结输入与只读工作区

```text
python scripts/parallel_review.py prepare PROJECT.json G01 UNITS.json REVIEW_BUNDLE
```

工具一次读取完整组 context，保存 bundle.json：完整 source_script、资产与哈希、镜头要求、由 requirements.py 计算的 entry_state/exit_state、映射、选帧、全部证据及外部边界；每个任务目录有 task.json 和独立 draft.json 路径。项目文件与上下文分别绑定 SHA256/指纹。子任务不能重新解释或改写状态种子、出口状态、脚本和映射；发现错误只报告主流程。

每个 task.json 另指向 worklist.json。先读工作清单中的完整脚本、负责镜头的要求/状态/映射观察及邻镜，再按需读取所指的完整证据；共享上下文与 project_base 仍可访问。清单是导航，不能据此断言漏镜或排除其他候选。工具核对清单与冻结输入一致，手改清单会被拒绝。

使用可用的审查子代理同时运行 T01/T02，最多两个；不得再派生子任务。给每个任务 task.json、技能入口、review.md、repair-assessments.md 的证据字段约定，以及以下指令：

> 先读完整脚本及共用状态基线，再读分配镜头的全部必要候选、连续帧、资产和邻接状态。只审查 owned shot_ids，邻镜用于理解衔接；按 review.md 输出逐镜结论、可见事实/解释、省图候选、问题和修复证据。观察按图片 SHA256 复用。只写指定 draft.json，不改项目、映射、资产或其他任务目录，不抽帧、不调用 API、不决定最终聚合、不增加任务。证据不足写 uncertain、所需补查区间和原因；不能凭采样断言 absent。问题与比较 ID 加任务前缀。

draft.json 字段：task_id、bundle_fingerprint，及原格式的 shot_reviews、reference_assessments、evidence、asset_comparisons、issues、uncertainties、limitations；有确认问题时依 repair-assessments.md 填 repair_assessments。两份逐镜表必须各自完整覆盖 owned shot_ids 的原顺序。跨任务问题只在草稿中列本任务受影响镜号，并在 uncertainties 说明另一侧；主流程复核后合并定位。basis_shot_ids 可引用其他任务的镜号，但仅为候选，不预设对方通过。

等待任务完成期间不自行重复审查它负责的镜头。任务失败只重做未完成草稿；已有草稿在冻结输入未变化时复用。一个任务持续受阻时退回串行完成该任务，仍只允许主流程写项目。

## 收集、有限复核、唯一写回点

```text
python scripts/parallel_review.py assemble PROJECT.json REVIEW_BUNDLE COLLECTED.json --drafts-dir COORDINATOR_DIR
```

收集器拒绝缺镜、重复镜、越权镜号、重复问题 ID、错误任务/上下文指纹及中途变化的输入。输出完整 review 草稿和待复核清单，绝不自动填 PASS。保留 worker 的 FAIL、uncertain、漏镜、限制和证据。

主流程检查全组结构化结论，并只针对以下内容读取必要图像：

1. **每个 unit 边界左右各一镜**：核对可见衔接和共同状态基线。对比左镜出口与右镜入口的继承/合法脚本变化，不假设不同 scene/continuity 的所有字段必须机械相等。不得只看画面相似就通过。来源视频外部边界仍填写原 boundary_checks。
2. **有限争议复核**：优先关键主体/动作结果错误、相互矛盾结论、uncertain 和疑似漏镜。每轮协调最多重看 4 个非边界镜头，不借自动新建轮次绕过上限。已有清楚证据、无需重看的局部 FAIL/absent 可直接保留；这不算争议重审。剩余未解决疑点保留 uncertain＋followup，不自动通过、不计为确认漏镜、不触发付费返修。已确证的 FAIL/absent 不因用完复核额度降级或删除。
3. **跨 unit 的省图依赖**：先用结构化结论检查双侧锚点确实通过、有资产支持、无循环、无关键状态冲突；有新矛盾才把相应镜头纳入上述争议额度。完整合并区间复杂度及 story 仍由主流程确认，不能由局部全 PASS 推断整体通过。

通过且没有新矛盾的镜头不重复看。补查由主流程合并区间一次抽取，再批量改映射；输入改变使旧 bundle 失效。使用 incremental_review 清单和按哈希缓存的观察构造新批次，只复核受影响镜头、邻接和实际依赖，其他事实复用，不自动升级旧审查。不能在旧 bundle 上替换指纹继续提交。

--drafts-dir 必须是新目录，工具生成 FINAL_REVIEW.json、COORDINATOR_AUDIT.json 和 WORKLIST.json，预填已有记录、任务哈希和边界状态，附待办及记录哈希。全局检查保持 uncertain/false，不能直接提交为通过；不覆盖既有协调成果。

在生成的 FINAL_REVIEW.json 中补齐 checks、coverage、grouping_checked、外部 boundary_checks、整体剧情关系和各疑点处理；在 COORDINATOR_AUDIT.json 中填写真实核对依据，不必重新手工拼接整份 JSON。完成后的审计示例：

```json
{
  "task_hashes":{"T01":"FROM_COLLECTED","T02":"FROM_COLLECTED"},
  "boundaries":[{
    "shot_ids":["S02","S03"],
    "exit_state":{"COPY":"FROM_COLLECTED"},"entry_state":{"COPY":"FROM_COLLECTED"},
    "verdict":"PASS","visual_reason":"具体可见衔接依据","state_reason":"具体状态继承或合法变化依据"
  }],
  "rechecked_shot_ids":[],"accepted_shot_ids":[],"deferred_shot_ids":[],
  "cross_references":[{"shot_id":"S02","reason":"两侧锚点及状态已核对，或说明为何撤销省图候选"}],
  "resolutions":[{"record_hash":"SHA256_OF_CHANGED_WORKER_RECORD","reason":"新证据及为何修正原判断"}]
}
```

boundaries/cross_references 严格按收集器清单填；边界 FAIL/uncertain 还需 affected_shot_ids，并落实到完整 review 的连续性和逐镜结论。accepted_shot_ids 表示直接保留的非边界问题结论；rechecked 是实际复核项；deferred 必须为未解决 uncertain，并写具体 followup。修改/移除任何 worker 记录或限制须在 resolutions 引用该原记录的 previs.digest 值，解释新证据；禁止合并时静默丢掉问题。原始两个草稿保留，不覆盖。结构校验不代替真实视觉核对。

```text
python scripts/parallel_review.py commit PROJECT.json REVIEW_BUNDLE COORDINATOR_DIR/FINAL_REVIEW.json COORDINATOR_DIR/COORDINATOR_AUDIT.json
```

这是并行路径唯一项目写回点：重新核验全部依赖、草稿哈希、状态边界和复核上限，再调用现有 record_review 全量证据校验，持有项目 .lock 后原子保存。不要绕过为多次普通 review。验证失败保留草稿，集中修正所指问题后再提交。工具无预算修改或生成入口；所有生成/返修安全流程仍串行。

## 验证与耗时口径

串行小故事仍可为整理、匹配、审查三次判断。并行示例是整理 1 次＋匹配 1 次＋两个审查任务各 1 次＋主流程协调 1 次，约 5 次判断，两个审查任务时间重叠；异常补证另计。不承诺调用次数减少，也不承诺固定速度提升。主流程不能再完整审一遍以制造“并行”表象。

对同一冻结素材比较串行/并行的逐镜漏镜、FAIL、uncertain、状态边界及省图依据，并记录准备、两任务、协调、补证和总墙钟时间，才可报告实测加速。自动测试覆盖分工、证据绑定、争议保留、单写入和原校验器行为；模拟判断不等于真实视频质量验收。使用 [阶段计时](efficiency.md) 分开记录工具处理和审查墙钟，重叠区间不相加；重放已有结论不是独立视觉盲测。
