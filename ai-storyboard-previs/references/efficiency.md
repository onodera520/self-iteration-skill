# 减少重复整理，分清耗时来源

这些入口只减少机械整理与工具往返，保留逐镜判断、完整证据、SHA256 失效检查、漏镜全片补查和付费保护。

## 准备入口

整理前路径预检、整理后串行准备统一使用 prepare_imported.py，参数、失败恢复与实体字段约定见 [项目约定](project.md#一次校验与字段类型)。一次整理全部镜头：先固定资产 ID 和逐镜原文，再同批填写要求与来源、状态种子和变化、计划时长与剧情分组；工具计算完整状态，不另写一套入口/出口状态。项目草稿齐全后运行一次准备入口，按整批 ERROR 修正，不采用“先填三镜试跑，再逐镜补齐”的往返方式。模板示例剧情必须全部替换，不能把字段齐全当作语义已核对。PREPARE_REPORT.json 的阶段耗时仅含工具处理，不含脚本提取、资产观察或视觉审查；不能拿它与过去未完整打点的整段准备时间计算提速比例。

## 先全组定位，再集中补证

在稀疏联系表上按脚本顺序完成全组粗匹配，初轮每镜选 1–3 个候选；需要辨认的画面再看原图。每个已看候选立即记录单帧事实，明确镜头不在下一阶段重新从头搜片。联系表不足以看清的内容不得据缩略图作肯定判断。

整组定位后，一次整理补查范围：动作过程/瞬时结果、状态冲突、疑似漏镜、无法定位、边界不清。合并重叠时间段后批量局部补帧；动作检查保留连续证据，充分即停止。未发现上述疑点也仍须逐镜审查及相邻承接检查；这只是查看顺序，不是自动跳过或判 PASS。未完整回看或取得全片连续覆盖不能判 absent。改变选帧或出现新矛盾时按状态、省图依据及边界依赖增量复核，不限于左右一镜。

## 工作清单与协调草稿

默认串行组级审查，短片和紧密连续事件优先串行。只有多个完整事件可独立核对、确有足够视觉工作量，且预计收益高于分发、草稿整理、边界复核和协调成本时，才启用最多两个任务；同批简述选择理由，不为分流另开模型调用，不按固定镜数或秒数强制并行。

串行路径在批量匹配与选帧完成后，使用 `review_draft.py prepare PROJECT.json G01 REVIEW_DRAFT.json --context-output CONTEXT.json --worklist-output WORKLIST.json` 同时生成新草稿、完整上下文和按镜号索引的编辑清单，不再先单独运行 context。镜号、当前版本/指纹、选帧路径、SHA256、精确时间和证据引用自动带入，不手抄、不四舍五入。旧命令不加参数仍兼容；输出路径必须不同且未存在。上下文保留完整抽帧、候选、资产、要求、状态和边界，去掉 previous_review，不能拿旧结论当本次审查。

先读完整上下文，再集中编辑 WORKLIST.json 中的逐镜 review/reference/repair、逐帧观察和组级问题。机械字段留在 REVIEW_DRAFT.json；不手写临时脚本拼装大型审查 JSON，不反复倾倒整个项目。repair 中的空值只是待填项，不能自动改成 false 或补占位引文；PASS/uncertain 保持空模板，FAIL/absent 完成真实返修依据。使用 `review_draft.py fill PROJECT.json REVIEW_DRAFT.json WORKLIST.json COMPLETED_REVIEW.json` 合并并在写文件前完成 check，成功后一次 `previs.py review PROJECT.json COMPLETED_REVIEW.json` 登记。fill 要求原草稿摘要和全部证据绑定一致，不能改时间、路径、哈希或指纹。需要可选的详细审查字段时可直接编辑完整草稿再 check，不改变原审查契约。

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
