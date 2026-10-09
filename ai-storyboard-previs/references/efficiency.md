# 减少重复整理，分清耗时来源

这些入口只减少机械整理与工具往返，保留逐镜判断、完整证据、SHA256 失效检查、漏镜全片补查和付费保护。

## 准备入口

整理前路径预检、整理后串行准备统一使用 prepare_imported.py，参数、失败恢复与实体字段约定见 [项目约定](project.md#一次校验与字段类型)。一次整理全部镜头：先固定资产 ID 和逐镜原文，再同批填写要求与来源、状态种子和变化、计划时长与剧情分组；工具计算完整状态，不另写一套入口/出口状态。项目草稿齐全后运行一次准备入口，按整批 ERROR 修正，不采用“先填三镜试跑，再逐镜补齐”的往返方式。模板示例剧情必须全部替换，不能把字段齐全当作语义已核对。PREPARE_REPORT.json 的阶段耗时仅含工具处理，不含脚本提取、资产观察或视觉审查；不能拿它与过去未完整打点的整段准备时间计算提速比例。

## 先全组定位，再集中补证

在稀疏联系表上按脚本顺序完成全组粗匹配，初轮每镜选 1–3 个候选；需要辨认的画面再看原图。每个已看候选立即记录单帧事实，明确镜头不在下一阶段重新从头搜片。联系表不足以看清的内容不得据缩略图作肯定判断。

整组定位后，一次整理补查范围：动作过程/瞬时结果、状态冲突、疑似漏镜、无法定位、边界不清。合并重叠时间段后批量局部补帧；动作检查保留连续证据，充分即停止。未发现上述疑点也仍须逐镜审查及相邻承接检查；这只是查看顺序，不是自动跳过或判 PASS。未完整回看或取得全片连续覆盖不能判 absent。改变选帧或出现新矛盾时按状态、省图依据及边界依赖增量复核，不限于左右一镜。

## 工作清单与协调草稿

默认串行组级审查，短片和紧密连续事件优先串行。只有多个完整事件可独立核对、确有足够视觉工作量，且预计收益高于分发、草稿整理、边界复核和协调成本时，才启用最多两个任务；同批简述选择理由，不为分流另开模型调用，不按固定镜数或秒数强制并行。

串行路径在批量匹配与选帧完成后，一次运行：

```text
python scripts/review_draft.py prepare PROJECT.json G01 REVIEW_DRAFT.json --context-output CONTEXT.json --view-output REVIEW_VIEW.json --worklist-output WORKLIST.json
```

prepare 保存同一有效上下文的四种表示，不另跑 context：CONTEXT.json 保留全部资产、抽帧、候选、要求、计算状态和边界；REVIEW_DRAFT.json 保存精确机械绑定；REVIEW_VIEW.json 是只读阅读视图，帧集中列一次，用 F001 等编号关联候选和选帧；WORKLIST.json 是 review-worklist-2 精简编辑清单，用 E001 等编号对应草稿证据。所有文件使用新的不同路径，不覆盖已有判断。完整 SHA256、实际时间、路径、版本和指纹留在上下文与草稿，视图不删候选或连续帧，也不代替有效证据。需要详细 evidence_refs 或发生矛盾时回查 CONTEXT.json；不凭视图摘要改绑证据。去除旧 previous_review 是已有行为，不复用旧批准。

先读 REVIEW_VIEW.json，再集中填写工作单：每个镜头的 review/reference 和组级检查仍全部显式填写，保留七项逐镜 checks、verdict、identity_reason、理由、推导依据、边界及问题。已有单帧中性事实可用 `{"id":"E001","reuse_facts":true,"interpretation":"本次按要求核对后的解释"}` 复用；没有已记 observation 和非空 visible_facts 时，必须填写 id/observation/visible_facts/interpretation。编号由固定草稿生成，base_digest 绑定整份草稿；缺项、重复编号、未知编号或私加时间/哈希均拒绝。E 编号不是镜号，不允许将不同帧合为一条观察。

只有 verdict 为 FAIL/absent 的镜头需要 repair 块，字段仍是 critical/critical_kind/affects_story/script_quote/issue_ids/impact/correction/preserves_script，按 [返修依据](repair-assessments.md) 填真实值；初始 uncertain 后改为 FAIL 时补齐该块，不能只改 verdict。PASS/uncertain 不保留空返修模板。所有判定仍由审查者作出，工具只复原原绑定，不默认 PASS，不省去正常镜头的检查。缺失镜头无本镜帧，不能因编号机制伪造画面。

`review_draft.py fill PROJECT.json REVIEW_DRAFT.json WORKLIST.json COMPLETED_REVIEW.json` 按原草稿恢复完整审查，写文件前执行原 check，包括当前素材哈希、指纹、全部逐镜要求、取舍和返修校验。fill 成功后一次 `previs.py review PROJECT.json COMPLETED_REVIEW.json` 登记，不重复独立 check；fill 不能代替登记。需要 identity_scope 等详细可选字段时直接编辑完整草稿再 check。CLI 默认精简清单；`--legacy-worklist` 恢复旧表单，原无附加参数的草稿入口继续兼容。不手写临时拼接脚本、不反复倾倒整个项目。

匹配阶段看过的单帧，在 `candidates[]` 中同时填 `observation`（该帧摘要）和非空 `visible_facts`（中性可见事实数组）；候选 path、time、sha256 直接取 evidence.json。本帧观察要求 SHA256 与时间精确一致，变化时重新查看，不允许自动改绑。prepare 把这些事实带入 evidence，保留每帧独立记录（包括已观察但非最终选帧的候选），不把多帧动作拼成某一帧事实。旧的逐镜 observation 可能是跨帧总结，因此不会自动移入单帧证据；没有单帧记录时仍留空待填写。

复用的是事实，不是解释或批准：interpretation、identity_reason、理由、逐镜 checks/判定、省图依据和必要返修证据仍由审查者按 review.md 完成。已有事实可读而无需重写；要求或新证据引发矛盾时重新核对。matched 不自动 PASS，确认 absent 沿用映射但不伪造本镜帧；不代填 mapping_verified 或 grouping_checked。空观察、空理由及未完成的 uncertain/false 不能直接通过登记。

直接填写完整草稿时，用 `review_draft.py check PROJECT.json REVIEW_DRAFT.json` 一次汇总当前能独立检查的结构、证据及返修字段问题，按镜号报告全部可检查缺项，并在内存副本上运行完整原审查校验。fill 已成功就不重复 check。结构或上下文失效先修上游，不替换指纹伪造新审查。此入口只诊断、不登记、不放宽提交门槛，也不证明视觉判断正确；修正后走原 review/commit 写回。并行的最终审查草稿也可使用该检查入口。

parallel_review.py prepare 保存完整冻结上下文，同时为每个任务生成 worklist.json。先读完整脚本和负责镜头的要求、状态、映射观察及邻镜，再按需查看完整证据。清单不是证据范围上限，也不自动证明漏镜。

assemble 加 --drafts-dir 新目录，生成 FINAL_REVIEW.json、COORDINATOR_AUDIT.json、WORKLIST.json。已有逐镜记录原样保留，任务哈希、边界状态及原记录哈希由工具填入；全局检查保持 uncertain/false，需要协调者填写真实核对结果。不会覆盖已有目录或替审查者批准结论。

并行 prepare 同时生成每个任务的 draft.json 机械骨架。协调修改结论后，用 parallel_review.py resolutions 自动比较原草稿与最终记录，生成新审计草稿中的全部差异引用；填写实际修改理由后才能提交，不手抄 digest。命令与边界见 parallel-review.md。

每镜一个主审。协调者只复核边界、新矛盾、有限争议及跨任务省图依赖，不重看无新矛盾的通过镜头。按完整事件和工作量选择串行或最多两个审查任务，不新增固定镜数分流阈值。详细提交约定见 parallel-review.md。

## 单入口收尾

```text
python scripts/finish_review.py PROJECT.json PROFILE.json --output DELIVERY_DIR --run-dir FINISH_INTERNAL_DIR
```

审查登记完成后执行。工具持有同一项目锁，顺序完成当前审查与返修字段预检 → 规划 → 返修机读判定 → 暂存交付 → 校验两表、图片及依赖哈希 → 冻结交付记录。不启动模型、不提交付费任务。原来的单步命令继续兼容，但默认不再自行拼接会提前冻结的旧命令顺序。

run-dir 必须是新的内部目录，与交付目录分开，保存 AGGREGATION.json、REPAIR_DECISIONS.json、恢复检查点 PENDING_DELIVERY.json 和含阶段耗时的 FINISH_REPORT.json。交付仍只有两表 Markdown 与图片。已存在快照只有聚合指纹和文件哈希一致时才能复用，不能把旧快照标成新结果。实际返修视频独立审查完成后才可指定 --stage repaired。

默认缺少返修字段时报告 preflight_blocked（退出码 2），按组/镜列出缺项，不改项目、不生成或冻结交付。补齐有依据的字段，check/review 后再收尾；只是文书缺项且证据/要求未变时复用已经核对的观察，不重看全片。

| 场景 | 正确入口与处理 |
| --- | --- |
| 常规收尾 | 上述 finish 命令；成功后只核对两表和图片一次，无新问题即停止。已有付费授权且满足返修门槛时按原规则继续。 |
| 旧项目明确只交付，暂缺返修依据 | check 和 finish 均显式加 `--delivery-only`；仍校验有效审查和证据，缺项保留 delivery_complete_decision_blocked，不能当作无需返修或允许付费。不得为了绕过缺项默认使用。 |
| 冻结后补正了审查 | 先登记有效审查，再用新交付目录、新 run-dir 和 `--revision-reason "实际补正原因"` 收尾。工具保存旧记录到 repair_delivery_history 并关联修订，旧文件必须仍通过哈希检查；不得覆盖旧目录、删除快照或清空任务/付费额度。 |
| 暂存交付后校验失败 | 修复原因，用新 run-dir 加 `--resume-from OLD_RUN/FINISH_REPORT.json`。项目、profile、阶段、修订原因及检查点/文件哈希全部匹配时，可沿用原 output 复用暂存文件，仍重新执行当前证据与交付校验。 |
| 渲染中断，尚无完整检查点，或输入已变 | 保留失败报告，用新的空 output 和新 run-dir 重试；没有有效检查点不能认领半成品。已冻结旧版且聚合变化时另加 revision-reason。 |

FINISH_REPORT.json 给出 status、failed_phase、next_action。仅字段缺项可走上述显式旧版兼容；证据过期、文件被改、基准冲突仍硬停止，不能降成警告。恢复只复用证据绑定的机械结果，不自动批准语义，不触发付费重投。图片和表结构校验不代替视觉审查；同一次成功收尾后不再重复 plan/snapshot/decide/render 做相同检查。

## 阶段计时与对比

```text
python scripts/review_timing.py start TIMING.json preparation --kind reviewer_wall
python scripts/review_timing.py end TIMING.json preparation
# On failure, retain the attempt; start a new ID for its retry.
python scripts/review_timing.py fail TIMING.json finish_1 --reason "实际失败原因"
python scripts/review_timing.py start TIMING.json finish_2 --retry-of finish_1 --kind tool
python scripts/review_timing.py report TIMING.json
```

默认从任务开始记录 total 墙钟，并为实际发生的 preparation、matching、review、supplement、finish 记录 start/end；条件并行时另记 review_T01、review_T02、coordination。阶段名不可重复；失败用 fail 结束并写真实原因，重试用新阶段 ID 和 --retry-of 指向失败记录，不删除失败时间。示例 fail 前必须已有同名 start。finish/prepare 的内部工具耗时自动记录，不能补造过去未打点的视觉审查时间。只读审查任务若需自行计时，应使用各自工作区的独立日志；也可由主流程记录从派发到收集的墙钟，其中包含等待。不得让多个任务随意写同一文件。

kind 可用 reviewer_wall、tool、wait，区分审查墙钟、工具处理和明确等待。日志报告已结束区间（含失败）的并集与跨度、失败及重试关系，不累加重叠任务；未结束阶段单独列出。未完整打点不能推算纯模型思考时间。finish 的计时只代表工具处理，不代表整个审查耗时。

串行与并行比较必须使用相同冻结素材哈希、脚本和规则，分别实际判断后比较逐镜 FAIL/uncertain/漏镜、省图锚点和边界结果，并报告准备、审查、协调、补证及总墙钟。复用旧结论的工具重放只验证机械结果一致，不是独立视觉盲测，不承诺固定分钟数或整体提速比例。

## 环境探测与复用

- **先探测，找到可用工具就复用，不按任务重新下载。** 优先检查显式配置的 PYTHON、FFMPEG、FFPROBE；未配置或不可用时，按下面固定位置查找，再检查 PATH。Python 必须实际执行版本检查（≥3.10）和所需模块导入；FFmpeg、FFprobe 分别执行 `-version`，路径存在或 WindowsApps 的 python 别名不代表可用。
- Windows 固定查找位置（按顺序逐个执行 `-version` 验证，跳过不存在的位置，但必须把「验证过哪些、结果如何」记入 `runtime-paths.json`；未逐项验证不得判为「本地不可用」）：Python 为 `%USERPROFILE%/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`，再查 `%USERPROFILE%/.cache/ai-storyboard-previs/tools/python/python.exe`；媒体工具先查 `%USERPROFILE%/.cache/ai-storyboard-previs/tools/ffmpeg/bin/ffmpeg.exe` 和 `ffprobe.exe`，再复用 `%USERPROFILE%/.cache/storyboard-test-deps/imageio_ffmpeg/binaries/` 下的 FFmpeg 可执行文件及本机 `D:/work skill/test-tools/ffprobe.exe`，最后按通配查 `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*-full_build\bin\ffmpeg.exe`（同目录取 `ffprobe.exe`）以及 `%ProgramData%\chocolatey\bin\ffmpeg.exe`、`%USERPROFILE%\scoop\apps\ffmpeg\current\bin\ffmpeg.exe`。这些旧位置不要求配套存在，分别确认两种工具可用即可。Codex 提供运行环境定位工具时也可用其返回路径。
- **全部本地候选均不可用时才下载缺失组件。** 新下载固定落在 `%USERPROFILE%/.cache/ai-storyboard-previs/tools/`：Python 放 `python/`，FFmpeg/FFprobe 放 `ffmpeg/bin/`；非 Windows 使用用户缓存目录下同名稳定目录。缺 Python 模块只补模块，不重装已有解释器；缺 FFprobe 不代表已有 FFmpeg 失效。禁止把运行环境下载到任务目录、日期目录或每次新建的临时目录。下载来源采用官方或项目认可发行源，安装完成后执行上述检查，失败则报告具体缺项，不循环重复下载。
- 主流程只探测/准备一次，将确认的绝对路径和版本写到稳定目录的 `runtime-paths.json` 供以后优先核验复用；该记录不是免检凭据，路径失效才重新探测。命令使用选定 Python 的绝对路径，并在当前进程设置 FFMPEG、FFPROBE、PYTHONUTF8=1；示例中的 `python` 均指这个解释器。子代理继承同一组路径，不单独安装；无需修改系统 PATH 或重复复制工具到项目。
