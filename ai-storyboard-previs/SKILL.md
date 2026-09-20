---
name: ai-storyboard-previs
description: 根据用户的视频、脚本和资产图，抽帧匹配、回看补查并校对内容与连续性，判断保留图、可推导省图和必要漏镜，再聚合相邻分镜，交付带小分镜图的两张 Markdown 表。用于已有视频的分镜校对、聚合规划与参考图取舍；已授权时按证据阈值通过固定 RunningHub 工作流返修一次并独立复审。
---

# 抽帧校对与分镜聚合

默认输入：**视频＋脚本＋资产图**。

默认链路：**抽帧匹配 → 画面校对 → 必要时回看并替换抽帧 → 保留或可推导省图 → 相邻聚合 → 图片＋Markdown 两张表**。先保存原视频审查；达到独立返修阈值且已获 RH 币消耗授权时，使用固定工作流完整返修一次，独立审查新视频并保存第二份 MD。未触发或执行受阻时保留首份及真实状态。按脚本计划时长聚合，每组不超过 15 秒、12 镜；实际时间戳只用于寻找镜头和定位问题。不比较实际与计划时长，不检查具体对白逐字一致、配音文本或口型同步；对白/OS/VO 的剧情含义、剧情必要的画面动作仍在审查范围内；不检查屏幕文字（包括字幕、字样、标牌文字），不为文字补查。

机械整理、冻结前预检与失败恢复见 [执行提效](references/efficiency.md)。默认记录总墙钟及准备、匹配、审查、补证、收尾阶段，保留失败与重试耗时；工具重放不代表视觉审查提速。每镜一个主审，协调仅处理边界、新矛盾和跨任务依赖；不按固定镜数强制选择串行或并行。

## 默认执行流程

首次执行工具前先按下方“环境探测与复用”定位运行环境；同一任务及其子代理复用探测结果。

先用 `prepare_imported.py preflight` 一次核对脚本、视频、全部资产路径，再建立 [已有视频三镜模板](assets/imported-project.json)。失败时先定位真实文件；不按同名自动替换，不在路径失效时继续填写大项目。字段与批量纠错统一见 [项目约定](references/project.md#一次校验与字段类型)。整理完成后用 `prepare_imported.py run` 串行完成 validate → import-video → baseline → 稀疏抽帧；无需先重复运行独立 validate。写入前校验与证据哈希检查仍保留，原单步命令继续兼容。

1. **一次整理完整输入**：按下方阶段路由读项目约定、镜头要求和模板。一次 LLM 调用填写全部镜头的 facts/state_changes/requirements/块级 provenance 、event（初步事件编号、说明、来源）、duration/duration_source 与 narrative_plan（自然边界、相邻承接及整段复杂度依据）。代理只写入口状态种子与 state_changes，requirements.py 计算完整入口、出口状态。同批按 [原文要求核对](references/shot-requirements.md) 核实硬条件及其来源，不把推断的同框、站位写成原文要求；不逐镜提取，不用视频错误画面改写脚本。shots[].script 逐字保留每镜原文（不摘要），完整 source_script 是唯一剧情基准；同批摘取 shot_design，并按原图填写带 SHA256 的 repair_asset_style 风格事实与指导；不补设脚本没有的机位、剧情或场景。准备入口在登记后调用 repair_cycle.py baseline 冻结原文及设计，无需另跑一次。保留原镜号、顺序、剧情及画幅；脚本给定时长原值保留；缺时长先按动作和剧情提出建议并注明来源，不冒充原值或实测值。旧项目可先抽帧审查，交付新版聚合前须补齐计划时长和剧情依据。
2. **登记已有视频并两阶段取证**：设置 workflow: video_evidence、video_source: imported。一份视频对应一个来源组，列出应覆盖的连续脚本镜头；来源组不等于最终聚合。import-video 保存文件哈希与实测时长，独立于付费任务。审查阶段资产本地核对；授权返修时才按原始顺序上传。media.py extract 默认只取覆盖全片的稀疏帧、切点邻域和候选片段代表帧，并生成带实际时间戳的联系表。完成整组粗匹配后，只对 uncertain、疑似漏镜、瞬时动作、状态冲突或边界不清的区间批量加密；已有充分证据即停止补帧，不为安心反复加密。只有多数镜头无法定位、剪辑极快或时间映射整体失效时，才升级全片密查。抽帧不依赖脚本时长，稀疏或局部加密均不能单独判漏镜。
3. **一次批量匹配**：按 [审查规则](references/review.md) 整组对应脚本，记录候选、实际时间、SHA256 和 observation。按剧情事件和角色/场景关系匹配，非关键细节不同不妨碍 matched；matched 只表示已定位。无法对应事件或抽不到先 uncertain，回看原视频或加密抽帧。找到后替换错误候选；完整补查仍无对应画面才 absent，记录覆盖整个原视频的补查范围及观察。稀疏帧不能单独证明漏镜。
4. **批量审查与推导评估**：短片、紧密连续事件默认串行，整组统一上下文和计算状态；用 review_draft.py prepare 同时生成完整上下文、机械草稿和按镜号的工作清单，审查者集中填写观察、判断与返修依据，再用 fill 合并并批量检查后一次 previs.py review；直接编辑完整草稿时用 check。缺项在登记和冻结前一次汇总，不依靠失败后临时脚本补字段。只有独立事件的审查工作量足以抵消任务启动、协调和边界复核开销，且允许使用子任务时，才按 [条件并行审查](references/parallel-review.md) 分给最多两个只读任务，不设固定镜数门槛。并行主流程复核各边界两侧画面及入口/出口状态、最多 4 个非边界争议镜头和跨任务省图依赖；未解决疑点保留待检查。并行用 parallel_review.py prepare/assemble/resolutions/commit，机械生成原记录哈希，审查者解释改动，独立草稿、唯一写回。两种路径都必须核对自然边界、相邻承接和整个合并区间的生成复杂度（grouping_checked: true），判断并填写整组 shot_reviews、reference_assessments、三项总检查（shot/continuity/story）、证据和问题；同时按 [返修证据字段](references/repair-assessments.md) 填 repair_assessments，给确认错误/漏镜引用脚本要求及同镜证据，说明剧情影响与原意范围内的修复要求；一次 review 登记，禁止逐镜 context/review。逐镜独立通过，同组失败不扩散。默认按剧情等效匹配与审查：角色、行动主体、场景与空间关系可辨认，关键动作和结果成立即可通过；不影响剧情的姿势、具体站位、景别、视角与动作细节偏差允许保留。composition 只检查景别/关键帧是否呈现必要信息或违反用户明确严格要求，不因名称不一致判失败。只有剧情必需信息或必要切镜无法确认时标待检查。每图观察按哈希保存复用，不为后续步骤重复看图。
5. **按问题处理**：已定位但差异影响剧情理解、关键动作结果或违反用户明确严格要求时标“该镜需重新生成”，列具体影响和建议；非关键差异不判失败，也不因此补查。确认漏镜后判断推导：有检验通过的前后保留镜头和资产支持且不违反锚点保护，可标“视频漏镜；可推导省图，未验证”；无法推导且必要则标“必要漏镜，需补生成”；证据或推导仍不确定标待检查。缺失镜头不能互为依据，也不能标检验通过。重选帧只重看该镜及左右衔接，复用其他观察、按新指纹登记完整组。替换整份视频则整份重新匹配审查并复查左右来源组边界。
6. **规则聚合并交付**：运行 [审查后规划](references/planning.md)，先按剧情自然初分，再强制检查相邻段合并，最后复核小于 8 秒的短段；承接更强侧优先，同等条件优先前组。每组计划总时长 ≤15 秒、镜数 ≤12，不能仅凭两两可合并推断整段复杂度。event 不是最终硬边界，景别、即时反应和短 OS/VO 不自动拆组。确定最终组后再选择参考图；同场景可拆组，跨场景的连续行动可同组，保护首尾、首次出场、关键状态、空间变化及必要锚点，保留原镜序和必要切镜。独立保存 aggregation，不改来源组和实际时间映射。每份视频仅统计必要漏镜；默认 bad_num ≥ 2 且占应覆盖镜头数 ≥ 20% 才建议重新生成该视频。已定位的画面错误、可推导漏镜、待检查不计数。
7. **最终仅图片＋MD**：render 为已有镜头（含建议省图镜头）及非省图缺图项在本地生成 240×168 小分镜图及缺图文字卡，图下标镜号。MD 固定两张表：分组表含总时长，逐镜表含镜头计划时长。建议时长逐镜标“建议”，所属组总时长标“含建议值”。单镜超过 15 秒标“需拆分或调整计划时长”，不缩短、不删镜、不冒称合格方案。已有且通过的镜头即使最终批准 ai_fill，也展示抽帧缩略图及原图链接；图片处理写“建议省图，未验证”，检验结果为“检验通过”。仅确认漏镜且最终批准 ai_fill 时，小分镜图栏只写“可推导生成”，不复制原帧、不生成图片或图片链接，检验结果仍为“视频漏镜”。其他缺图卡标“必要漏镜”或“待检查”；逐镜展示检验、图片处理、推导依据及修改建议。**不输出视频结论表**。达到漏镜阈值，仅在两表下用一句话建议重新生成对应视频；未达到则仅逐镜列建议。格式见 [项目约定](references/project.md)。不交付视频、HTML、JSON 或内部审查记录。审查登记后用 finish_review.py 一次串行完成审查及返修字段预检、规划、机读判定、暂存 01_原视频审查.md 和图片，交付校验通过后才冻结；补正用新目录的关联修订，失败按报告恢复，详见 [执行提效](references/efficiency.md)；原独立命令继续兼容。

8. **机读判定与一次返修**：按 [自动返修规则](references/auto-repair.md) 对每份来源视频生成内部判定 JSON。没有必要漏镜时，影响剧情的确认错误按镜号去重，至少 3 镜且 ≥20% 才触发，关键问题也不例外；存在必要漏镜时保留原规则：有同镜证据的关键剧情问题一处触发，其他必要漏镜和影响剧情错误合计至少 2 镜且 ≥20% 才触发。可推导漏镜、允许偏差和 uncertain 不计；bad_num 原意不变。工具从原始脚本拼出完整 prompt，只给允许的错误/必要漏镜追加补充，逐字检查正确镜头。每镜固定 1.0s，格式为“镜头N,【时长】1.0s。【镜头设计】…。【镜头内容】原文”；来源总生成时长为完整镜数 ×1 秒。全文末尾绑定用户固定的快速硬切、无台词/音乐/字幕要求和基于原资产的风格说明（见自动返修规则），不改原计划时长及两表聚合。已授权时使用 runninghub-fixed-workflow 的 2099403222661287938 / Plus 及原序资产，每份来源最多一次付费提交；预检、持久化、恢复和预算按该规则执行。新视频整份重新匹配审查并复核相邻来源边界，生成 02_返修视频审查.md；仍有错误如实标注，额度已用完，不自动再次付费。

统一称“可推导省图”（内部 ai_fill），只省独立参考图，不删脚本镜头。按 [推导判据与决策表](references/review.md#可推导省图判据与决策表) 在原有组级审查中判断；以“省去独立图后故事仍可读且无歧义”为准，不要求唯一复原该画面。剧情节点（首次出场、交接完成、关键状态变化等）必须留；纯表演细节（手指滑过伞柄、普通微表情）不自动保护，可在有效双侧锚点与资产支持下省图。reason 简述前后仍能读懂的事件及无歧义的依据。审查输出候选，最终规划再执行组首尾和关键锚点保护。漏镜、待检查及 ai_fill 均计入计划总时长。已有画面可读或缺图可推导，均不证明后续生成一定成功；省图统一标建议/未验证。审查证据不足先补查；仍不足就保留待检查并结束，不强行给通过结论。

事实来源分级、SHA256、.lock 和观察复用规则保持。max_retries=1、budget_cny/max_submissions、三轮上限与 submission_unknown 恢复原则不变。固定工作流返修采用独立状态记录，先保存首轮交付与请求、预占一次额度，超时只查询、下载失败只重试下载。保留已有预算，不将 RH 币换算人民币。公开模型旧模式见 [生成与恢复](references/generation.md)；不进入独立修图或补图入口。不实现 CLIP。只允许最多两个只读视觉审查任务并行；共享项目写入、补帧/映射更新及所有付费操作保持串行。

资产对比以人物、行动及剧情能否正确理解为准，允许不影响剧情的脸部、服装颜色、材质与款式偏差；明确要求严格一致的特征仍须满足。按 [剧情优先的资产审查](references/review.md#资产外观判定剧情优先) 填每镜 identity_reason，普通通过复用可见事实与帧证据，不强制逐人填写 wardrobe＋appearance。仅剧情相关外观要求/问题填写详细 asset_comparisons；FAIL/uncertain 必须说明具体剧情要求及影响。保留本镜证据、逐镜问题绑定和事实/解释分离。review_schema=5、reference_policy_version=5 进入指纹，旧审查及聚合需复核，不能直接升级。剧情等效审查复用 shot_reviews.reason 说明成立的剧情或差异影响，不新增逐项表单。串行小组仍为三次判断与一次组 context/review；并行审查共用上下文，由主流程一次校验写回，不声称仍只有三次 LLM 判断。

## 工具入口

### 环境探测与复用

- **先探测，找到可用工具就复用，不按任务重新下载。** 优先检查显式配置的 PYTHON、FFMPEG、FFPROBE；未配置或不可用时，按下面固定位置查找，再检查 PATH。Python 必须实际执行版本检查（≥3.10）和所需模块导入；FFmpeg、FFprobe 分别执行 `-version`，路径存在或 WindowsApps 的 python 别名不代表可用。
- Windows 固定查找位置（按顺序逐个执行 `-version` 验证，跳过不存在的位置，但必须把「验证过哪些、结果如何」记入 `runtime-paths.json`；未逐项验证不得判为「本地不可用」）：Python 为 `%USERPROFILE%/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`，再查 `%USERPROFILE%/.cache/ai-storyboard-previs/tools/python/python.exe`；媒体工具先查 `%USERPROFILE%/.cache/ai-storyboard-previs/tools/ffmpeg/bin/ffmpeg.exe` 和 `ffprobe.exe`，再复用 `%USERPROFILE%/.cache/storyboard-test-deps/imageio_ffmpeg/binaries/` 下的 FFmpeg 可执行文件及本机 `D:/work skill/test-tools/ffprobe.exe`，最后按通配查 `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*-full_build\bin\ffmpeg.exe`（同目录取 `ffprobe.exe`）以及 `%ProgramData%\chocolatey\bin\ffmpeg.exe`、`%USERPROFILE%\scoop\apps\ffmpeg\current\bin\ffmpeg.exe`。这些旧位置不要求配套存在，分别确认两种工具可用即可。Codex 提供运行环境定位工具时也可用其返回路径。
- **全部本地候选均不可用时才下载缺失组件。** 新下载固定落在 `%USERPROFILE%/.cache/ai-storyboard-previs/tools/`：Python 放 `python/`，FFmpeg/FFprobe 放 `ffmpeg/bin/`；非 Windows 使用用户缓存目录下同名稳定目录。缺 Python 模块只补模块，不重装已有解释器；缺 FFprobe 不代表已有 FFmpeg 失效。禁止把运行环境下载到任务目录、日期目录或每次新建的临时目录。下载来源采用官方或项目认可发行源，安装完成后执行上述检查，失败则报告具体缺项，不循环重复下载。
- 主流程只探测/准备一次，将确认的绝对路径和版本写到稳定目录的 `runtime-paths.json` 供以后优先核验复用；该记录不是免检凭据，路径失效才重新探测。命令使用选定 Python 的绝对路径，并在当前进程设置 FFMPEG、FFPROBE、PYTHONUTF8=1；示例中的 `python` 均指这个解释器。子代理继承同一组路径，不单独安装；无需修改系统 PATH 或重复复制工具到项目。

### 默认节省重复工作

- 文档按阶段读取：整理读 project 的“一次校验与字段类型”“输入及内部状态”、shot-requirements 及模板；事实定义不清再读 facts-and-planner 的事实段落。匹配/审查时读 review、repair-assessments，需要双任务时才读 parallel-review；聚合时读 planning/efficiency。准备阶段不顺着链接提前展开审查、交付和返修文档，已读且未变的规则不反复展开。达到返修条件且需要执行时才读 auto-repair 和固定工作流技能；默认不读公开模型旧模式、修图文档。
- 缩短墙钟只合并「工具往返」，不合并「审查范围」。互不依赖的调用（读多份文档、读多张候选帧、探测命令）必须在同一条助手消息里并行发出；整理→`validate`→`import-video`→`baseline`→`extract` 这类存在先后依赖的命令可在一次 shell 调用中顺序执行，每一步失败立即停止；这些命令会改变项目状态，不能并行。项目写回（`.lock`）、付费提交、补帧后重新 `map`/`context`/`review` 始终串行；每镜仍须各自查看候选帧，不得为省请求而跳过取证。
- 维持完整提取、整组匹配、批量审查三个阶段；串行路径三次判断，并行路径增加审查任务及一次协调判断，目标是缩短墙钟时间。已有完整、有效的结构化输入复用，只补缺项；不得把字段齐全当作语义已校对。审查一次产出逐镜结论、连续性及省图依据，规划和渲染不再发起一次同内容的 LLM 评判。
- context 每组获取一次并保存在内部文件，后续按需读取；不反复向代理倾倒整个项目、历史审查或同一组上下文。完整证据和所有当前候选仍保留，不能裁掉连续帧、边界或待检查项来缩短上下文。
- 工具在一次 context、规划或渲染操作内复用 SHA256、证据文件解析和组级校验；返回前对读过的依赖重新计算完整 SHA256，变化则报错重读。缓存不跨操作，不用大小/时间戳代替哈希，不把缓存当作新的视觉通过结论。无需手动重复运行相同校验命令。
- 先把全组剧情事件整理为一行一镜的清单，在稀疏联系表上一次为每镜挑 1–3 个候选，再看必要的原图或连续片段；这是首轮目标，不是证据上限。明确镜头立即记录 matched、可见事实和 SHA256，证据足够即停止补帧，不逐镜重复遍历全片。连续动作优先查看局部视频；无视频查看能力则看连续帧，仍不清楚就待检查。状态约束与可见事实冲突时重点补查，工具不凭像素自动识别状态。
- 默认增量补查：--base-evidence 合并旧帧，重复 --dense-range 一次处理争议范围，写入新目录。局部默认 0.2 秒，必要时收窄至 0.1 秒或适合瞬时动作的步长。补帧联系表只展示新增帧，完整证据保留，旧上下文小表仅按需查看；完整联系表可用 --full-contact-sheet 生成，但默认不重看。
- 带 --project/--group 补帧会生成 incremental_review.json，列主要检查、邻接复核、状态/推导依赖及直接复用项，并提供整组映射草稿。按清单更新后一次 map；context --incremental-from 生成当前上下文与部分审查草稿，补齐受影响项后一次完整 review。事实可复用，旧审查不会自动转成新批准。候选时间不等于镜头边界，未可靠定位的镜头不按猜测时间排除；依赖变化时复核可超出左右一镜。详见 [增量补查](references/review.md#增量补查与批量登记)。
- 新视频仍整份匹配；脚本、资产、规则、状态或依据变化不能沿用旧结论。交付前核对两张表及图片一次；无新变化不重复抽帧、重审或渲染。漏镜仍须完整有效补查，缺证和冲突不因加速而降级。

Python 3.10+、Pillow、FFmpeg/FFprobe。内部项目和记录由代理维护，用户不必填 JSON。已有视频模式 PROFILE.json 可写 `{}`，不使用模型配置中的时长、图片数量或成本限制；新版聚合固定执行计划时长 ≤15 秒及每组 ≤12 镜。

```text
python scripts/prepare_imported.py preflight --script SCRIPT.txt --video INPUT.mp4 --asset A.png --asset B.png
python scripts/prepare_imported.py run PROJECT.json G01 INPUT.mp4 EVIDENCE_DIR --run-dir PREPARE_INTERNAL_DIR
python scripts/storyboard.py map PROJECT.json MAPPING.json
python scripts/review_draft.py prepare PROJECT.json G01 REVIEW_DRAFT.json --context-output CONTEXT.json --worklist-output WORKLIST.json
# Read CONTEXT.json; fill evidence-grounded judgments and repair fields in WORKLIST.json.
python scripts/review_draft.py fill PROJECT.json REVIEW_DRAFT.json WORKLIST.json COMPLETED_REVIEW.json
python scripts/previs.py review PROJECT.json COMPLETED_REVIEW.json
python scripts/finish_review.py PROJECT.json PROFILE.json --output DELIVERY_DIR --run-dir FINISH_INTERNAL_DIR
```

MAPPING.json 可带 selections 数组，一次 map 原子登记整组映射与选帧；候选单帧 observation/visible_facts 的精确绑定与草稿复用见 [执行提效](references/efficiency.md)。旧 select、context 入口仍兼容。补帧命令及独立镜头门槛见审查规则。单个连续事件的串行三镜路径仍为 3 次 LLM 判断：完整提取、批量匹配、组级校对与取舍。登记、抽帧、规划、渲染为工具操作。此为调用设计，不是实测耗时；补证时审查质量优先。
