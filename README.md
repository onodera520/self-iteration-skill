# AI 分镜抽帧校对与聚合 Skill

`ai-storyboard-previs` 用已有预演视频校对有序分镜脚本。它会把视频抽帧与角色、场景、道具资产图对应起来，检查每一镜和相邻镜头的连续性，再按连续事件聚合分镜，并交付带小分镜图的 Markdown。

默认链路是：**整理输入 → 登记视频 → 抽帧匹配 → 组级审查 → 漏镜与省图判断 → 相邻分组 → 输出图片和 Markdown**。

先交付原视频审查；达到返修阈值且已获 RH 币消耗授权时，通过固定 RunningHub 工作流完整返修一次，独立审查后交付第二份 MD。最终不交付视频，`ai_fill` 仍只是省图建议。

## 输入

提供以下材料即可：

1. **已有视频**：需要核对的预演或样片。一段视频对应一个视频来源组；多段视频可以分别登记。
2. **有序分镜脚本**：保留原始镜头编号、顺序、剧情和画幅。每镜写画面描述、关键动作、结果及计划时长；未给时长可先审查，交付聚合前根据动作提出明确标为“建议”的时长。
3. **资产图**：角色、场景、道具及简短说明。审查时资产只在本地使用；已授权且触发返修后，按原始顺序上传原资产图。

人物和画面按剧情等效判断：不影响角色、行动和剧情理解的脸部、服装、站位或景别偏差可通过；关键动作、结果和用户明确严格要求仍须满足。只有剧情必需信息看不清时标为“待检查”，不把猜测写成确定结论。

用户不需要手写项目 JSON。Skill 会在内部维护视频哈希、实测时长、抽帧证据、镜头映射和审查状态；这些内部数据不属于交付物。

从零整理已有视频时，建议先做路径预检，再用统一准备入口完成结构校验、视频登记、原视频基线冻结和稀疏抽帧。准备入口只检查输入和生成证据，不做视觉判断、审查登记或付费操作；这样后续审查使用的是同一份可追溯证据。

审查登记完成后，可以由统一收尾入口一次完成规划、保存不可覆盖的原视频 Markdown 与图片、生成返修判定并校验交付物。这个入口只整理已经完成的审查结果，不替代视觉判断，也不会自行提交付费任务。

## 怎么判断和分组

视频来源组表示一段视频应该覆盖哪些连续脚本镜头，最终聚合组是审查后的展示和后续建议，两者不是同一个概念。省略一张独立参考图不会删除原镜头，组内仍保留原顺序。

先通读完整剧情，以事件（`event`）找自然初分，再强制检查相邻段是否能自然承接合并，最后复核小于 8 秒的短段。事件编号不是最终硬边界；景别、即时反应、短 OS/VO 或连续推门到室外不单独构成拆组理由。独立事件、明显时空跳跃和整段过高复杂度等可以阻止合并。

每组按脚本计划时长计算，不超过 **15 秒、12 镜**；漏镜、待检查和可推导省图仍计时。短段优先并入承接更强的一侧，相同时优先前组；无法合并则注明原因。单镜超过 15 秒标为需拆分或调整计划时长。先确定剧情分组，再保留组首尾、场景变化和关键状态等必要锚点，不以减少参考图决定剧情边界。

抽帧先取全片稀疏证据和切点代表帧；仅对争议区间局部加密，补帧后默认只看新增帧及受影响镜头。时间戳只用于定位证据和问题，不反推脚本时长，也不单独作为“画面正确”的证明。

## 审查结果

抽帧定位和内容审查分开记录：

- `matched`：找到候选帧，只说明位置已定位，不代表内容通过。
- `uncertain`：现有证据不足，需回看或补抽帧，交付中标为“待检查”。
- `absent`：完整扫描原视频后仍未找到对应镜头，才可确认视频漏镜；稀疏抽帧不能证明漏镜。

组级审查一次覆盖整组，并分别检查：

- 单镜头：人物、场景、道具、动作和动作结果。
- 相邻镜头：身份、服装、位置、持物、左右手和状态承接。
- 整段故事：是否漏镜、乱序或增加剧情，静音观看能否理解主要事件。

匹配完成后可以先用 `review_draft.py prepare` 生成带镜号、时间点、证据路径和 SHA256 的审查草稿，再根据实际画面填写观察和判断。填写后用 `review_draft.py check` 批量检查结构、证据指纹和字段完整性；它是只读诊断，不会把草稿登记为正式审查，也不会自动判定画面正确。只有完成视觉审查后，才使用 `previs.py review` 正式登记结果。

准备审查时先完成整组候选定位，再集中补看动作过程、关键状态、疑似漏镜和组边界；不会因为稀疏抽帧或联系表没有明显问题就跳过逐镜和相邻承接审查。候选帧的 `observation` 与 `visible_facts` 必须绑定当前证据的精确时间和 SHA256，只能复用画面中可见的事实，不能自动变成解释、PASS 或省图结论。证据变化后必须重新查看。

不检查屏幕文字、具体对白逐字一致性、配音文本或对白口型同步；对白的剧情含义和明确的画面动作仍用于理解与校对。原视频实际时长不同于计划时长不会导致画面失败。

内容不符且影响剧情或违反明确严格要求时，定位到镜号和视频时间，并写成“该镜需重新生成”的建议。确认漏镜后，只有在前后镜头检验通过、资产和状态能够承接时，才会建议“可推导省图，未验证”；不能推导的必要镜头标为“必要漏镜，需补生成”；证据不足则继续标“待检查”。缺失镜头不会用另一个缺失或不确定镜头互相证明。

每个视频来源的必要漏镜默认在同时满足 **至少 2 镜且占应覆盖镜头数至少 20%** 时，才在文档底部建议重新生成该视频。轻微错误、可推导漏镜和待检查不计入此阈值。

## 交付内容

输出目录只有用户需要阅读的图片和 Markdown：

```text
01_原视频审查.md
images/
  S01-...png          # 可点击查看的原抽帧
  thumb-S01-...png    # 240×168 小分镜图或缺图文字卡
```

每份 MD 固定包含两张表：

1. **分组结果**：分组编号、镜头顺序、总时长、简短分组理由。
2. **逐镜审查与取舍**：分组、原镜号、镜头时长、脚本描述、小分镜图、检验结果、图片处理、推导依据镜号、问题或修改建议。

建议时长逐镜标注，包含建议值的组总时长标为“含建议值”。

所有原镜头都会出现。保留图会链接到原抽帧；最终批准省图的镜头只显示纯文字“可推导生成”，不放图或图片链接；必要漏镜和待检查镜头使用缺图卡或有效抽帧。文档不输出视频结论表，不展示内部漏镜统计、项目清单、JSON、抽帧日志或审查记录。

## 一次自动返修

没有必要漏镜时，影响剧情的确认错误至少 3 镜且占比 ≥20% 才触发，关键问题也受此门槛约束。存在必要漏镜时保留原规则：一处有本镜证据的关键剧情错误或关键必要漏镜即可触发；其他影响剧情的错误与必要漏镜至少 2 镜且占比 ≥20% 才触发。同镜去重，可推导漏镜和不确定项不计；必要漏镜 bad_num 的原意不变。

当前返修判定策略版本为 2。没有必要漏镜时，关键问题也必须满足 3 镜且 20% 的累计门槛；存在必要漏镜时才保留关键问题一镜触发的旧规则。策略更新会使旧判定失效，继续处理前必须按当前规则重算。

脚本始终是唯一剧情基准。返修 prompt 保留所有镜头原文，附上已整理的必须出现、不得出现和关键变化约束，仅给已确认错误或必要漏镜追加修复要求，采用“镜头N,【时长】1.0s。【镜头设计】…。【镜头内容】…”格式。需修正或补齐的镜头另列清单，强调独立硬切。每镜固定 1.0 秒，末尾绑定快速硬切、无台词/音乐/字幕要求和按原图分析的资产风格。两表仍展示原始脚本计划时长。

使用 `runninghub-fixed-workflow` 的 `2099403222661287938`、Plus、原始资产顺序。每份来源视频最多一次自动付费，提交结果不明只核实原任务；超时只查询、下载失败只重试下载。保留已有预算和提交上限。具体结构、命令和恢复见 [自动返修规则](ai-storyboard-previs/references/auto-repair.md)。

生成并完成独立复审后，在独立目录交付 `02_返修视频审查.md` 及图片，不覆盖首份。仍有问题如实列出，不会自动再次付费；未触发或执行受阻时仅交付首份并说明状态。内部 JSON、prompt 和视频不属于用户默认交付。

当前固定工作流只支持上述一次受控返修，不提供第二、第三轮交付入口。配置中的返修轮次上限不会增加这一次自动额度。返修后仍有缺镜或错误时，如实交付问题与修改建议；拆分生成、人工补镜是后续处理建议，尚未接入自动流程。

## 在 Codex 中使用

把仓库中的 `ai-storyboard-previs` 文件夹安装到个人技能目录：

```text
Windows: %USERPROFILE%\.codex\skills\ai-storyboard-previs
macOS/Linux: ~/.codex/skills/ai-storyboard-previs
```

安装后可以这样描述任务：

```text
使用 $ai-storyboard-previs，读取这个已有预演视频、分镜脚本和资产图。
请抽帧匹配，审查人物、场景、道具、动作和连续性，
按剧情初步分组，再检查相邻组能否自然合并，只交付分镜图片和易读的 Markdown。
```

如果只提供脚本和资产图而没有已有视频，当前默认链路没有可供校对的视觉证据；可以先整理脚本和事件，或明确要求进入兼容的生成工作流。真实生成、补图和局部重生成需要用户另外授权，模型、图片数量、时长和预算由运行配置决定，不写死在脚本中。

## 本地开发与检查

开发检查需要 Python 3.10+、Pillow、FFmpeg 和 FFprobe。Skill 会先验证显式配置和本机缓存、包管理器中的候选路径，再决定是否需要下载缺失组件；每个候选都要实际执行版本检查，结果保存到稳定缓存中的 `runtime-paths.json`。FFmpeg/FFprobe 也可以用 `FFMPEG`、`FFPROBE` 环境变量指定完整路径。

```powershell
python -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File tests/run_checks.ps1
```

检查包括行为测试、合成视频抽帧、导入视频审查、事件分组和模拟渲染；不会调用付费模型，也不宣称验证了真实模型的视觉质量。若安装了 Codex 的 `skill-creator`，检查脚本还会运行技能结构校验器。

已有项目在继续处理前必须先通过一次集中校验。校验失败会按字段路径一次性列出需要修正的问题；上游字段无效时，相关后续检查会标记为阻断，避免用补空值或逐条试错掩盖项目结构问题。

处理一个已有视频时，可以按下面的顺序准备证据和审查草稿（路径按实际项目替换）：

```powershell
python ai-storyboard-previs/scripts/prepare_imported.py preflight --script SCRIPT.md --video INPUT.mp4 --asset CHARACTER.png --asset SCENE.png
python ai-storyboard-previs/scripts/prepare_imported.py run PROJECT.json G01 INPUT.mp4 EVIDENCE_DIR --run-dir PREPARE_INTERNAL_DIR
python ai-storyboard-previs/scripts/review_draft.py prepare PROJECT.json G01 GROUP_REVIEW.json --context-output CONTEXT.json
# 查看 CONTEXT.json，并根据实际画面填写 GROUP_REVIEW.json 后再检查
python ai-storyboard-previs/scripts/review_draft.py check PROJECT.json GROUP_REVIEW.json
# 视觉审查完成后才正式登记
python ai-storyboard-previs/scripts/previs.py review PROJECT.json GROUP_REVIEW.json
```

`preflight` 只确认脚本、视频和资产路径可读；`run` 串行完成集中校验、视频登记、基线冻结和稀疏抽帧，并在内部目录保存准备报告。`review_draft.py` 的 `prepare` 和 `check` 都是证据绑定的准备/诊断步骤，不替代人工或视频理解审查，也不代表已经通过。

`prepare --context-output` 会在同一次准备中生成审查草稿和候选上下文，减少重复定位。上下文里的单帧观察必须保留各自的证据时间和 SHA256；工具可以复用这些中性的可见事实，但不会合并不同帧、自动解释动作或批准审查。

只有存在多个相互独立的事件、并且分派与协调成本确实值得时，才使用最多两个并行审查任务。并行流程中的 `resolutions` 会为被修改或丢弃的 worker 结论生成待填写的处理记录；理由补齐并完成最终检查后，才由唯一写回步骤提交。它是可选的内部提速路径，不承诺固定加速比例：

```powershell
python ai-storyboard-previs/scripts/parallel_review.py prepare PROJECT.json G01 UNITS.json REVIEW_BUNDLE
python ai-storyboard-previs/scripts/parallel_review.py assemble PROJECT.json REVIEW_BUNDLE FINAL_REVIEW.json
python ai-storyboard-previs/scripts/parallel_review.py resolutions PROJECT.json REVIEW_BUNDLE FINAL_REVIEW.json COORDINATOR_AUDIT.json UPDATED_AUDIT.json
python ai-storyboard-previs/scripts/review_draft.py check PROJECT.json FINAL_REVIEW.json
python ai-storyboard-previs/scripts/parallel_review.py commit PROJECT.json REVIEW_BUNDLE FINAL_REVIEW.json UPDATED_AUDIT.json
```

审查登记后可使用统一收尾入口（`PROJECT.json`、`PROFILE.json` 和目录名按实际项目替换）：

```powershell
python ai-storyboard-previs/scripts/finish_review.py PROJECT.json PROFILE.json `
  --output DELIVERY_DIR --run-dir FINISH_INTERNAL_DIR
```

`FINISH_INTERNAL_DIR` 必须是新的内部目录，并与交付目录分开；其中的 JSON 和计时报告只用于恢复、校验和调试。缺少返修判定所需证据时，入口会保留已经完成的原视频交付并报告阻断，不会把缺字段当成无需返修。

## 目录

```text
ai-storyboard-previs/  Skill 入口、规则、示例数据和工具脚本
tests/                 行为测试、媒体测试和检查脚本
requirements-dev.txt   开发与测试依赖
```

主要实现文件还包括：

- `ai-storyboard-previs/references/repair-assessments.md`：首轮审查需要填写的返修证据字段。
- `ai-storyboard-previs/references/efficiency.md`：统一准备、串行草稿审查、双任务审查和耗时记录的边界。
- `ai-storyboard-previs/references/facts-and-planner.md`：需求来源、事实账本和规划字段的校验约定。
- `ai-storyboard-previs/references/shot-requirements.md`：逐镜要求、来源证据和状态字段的约定。
- `ai-storyboard-previs/scripts/finish_review.py`：审查后的串行收尾与交付校验。
- `ai-storyboard-previs/scripts/prepare_imported.py`：已有视频的路径预检、集中准备和稀疏证据入口。
- `ai-storyboard-previs/scripts/review_draft.py`：证据绑定审查草稿、候选上下文的生成与只读批量检查。
- `ai-storyboard-previs/scripts/storyboard.py`：候选帧登记与单帧事实的精确证据绑定。
- `ai-storyboard-previs/scripts/repair_cycle.py`：返修策略版本、触发阈值和一次提交控制。
- `ai-storyboard-previs/scripts/parallel_review.py`：最多两个只读审查任务的冻结、收集和唯一写回。
- `ai-storyboard-previs/scripts/review_timing.py`：记录阶段区间并按重叠区间合并统计。

仓库不提交用户资产、实际视频、抽帧结果、缓存、私密配置、二进制媒体工具或历史演示产物；这些路径已写入 `.gitignore`。测试所需的脚本夹具保留在 `tests/fixtures/`。

单条视频完成统一匹配后，默认按串行路径审查；只有独立事件的审查工作量足以覆盖分派和协调成本时，才可按完整连续事件分配最多两个只读审查任务，主流程复核状态边界和有限争议后统一写回。没有固定镜数或时长门槛，是否并行由任务结构决定。实现与验证边界见 [双任务审查](ai-storyboard-previs/references/parallel-review.md)。并行不改变最终两表交付或付费安全，也不代表已测得固定加速比例。
