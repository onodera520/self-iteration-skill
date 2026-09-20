# 减少重复整理，分清耗时来源

这些入口只减少机械整理与工具往返，保留逐镜判断、完整证据、SHA256 失效检查、漏镜全片补查和付费保护。

## 准备入口

整理前路径预检、整理后串行准备统一使用 prepare_imported.py，参数、失败恢复与实体字段约定见 [项目约定](project.md#一次校验与字段类型)。PREPARE_REPORT.json 的阶段耗时仅含工具处理，不含脚本提取、资产观察或视觉审查；不能拿它与过去未完整打点的整段准备时间计算提速比例。稀疏默认、完整语义校验和 baseline 冻结阶段不变。

## 工作清单与协调草稿

默认串行组级审查，短片和紧密连续事件优先串行。只有多个完整事件可独立核对、确有足够视觉工作量，且预计收益高于分发、草稿整理、边界复核和协调成本时，才启用最多两个任务；同批简述选择理由，不为分流另开模型调用，不按固定镜数或秒数强制并行。

串行路径在批量匹配与选帧完成后，使用 `review_draft.py prepare PROJECT.json G01 REVIEW_DRAFT.json` 生成新草稿：镜号、当前版本/指纹、选帧路径、SHA256、精确时间和证据引用自动带入，不手抄、不四舍五入。观察、理由、判定、省图依据、身份范围及必要返修证据仍由审查者按 review.md 填写；matched 不自动 PASS，确认 absent 沿用映射但不伪造本镜帧。草稿的空观察、空理由和 uncertain/false 不能直接通过登记。

填写后用 `review_draft.py check PROJECT.json REVIEW_DRAFT.json` 一次汇总当前能独立检查的结构和证据问题，并在内存副本上运行完整原审查校验。结构或上下文失效先修上游，不替换指纹伪造新审查。此入口只诊断、不登记、不放宽提交门槛，也不证明视觉判断正确；修正后走原 review/commit 写回。并行的最终审查草稿也可使用该检查入口。

parallel_review.py prepare 保存完整冻结上下文，同时为每个任务生成 worklist.json。先读完整脚本和负责镜头的要求、状态、映射观察及邻镜，再按需查看完整证据。清单不是证据范围上限，也不自动证明漏镜。

assemble 加 --drafts-dir 新目录，生成 FINAL_REVIEW.json、COORDINATOR_AUDIT.json、WORKLIST.json。已有逐镜记录原样保留，任务哈希、边界状态及原记录哈希由工具填入；全局检查保持 uncertain/false，需要协调者填写真实核对结果。不会覆盖已有目录或替审查者批准结论。

并行 prepare 同时生成每个任务的 draft.json 机械骨架。协调修改结论后，用 parallel_review.py resolutions 自动比较原草稿与最终记录，生成新审计草稿中的全部差异引用；填写实际修改理由后才能提交，不手抄 digest。命令与边界见 parallel-review.md。

每镜一个主审。协调者只复核边界、新矛盾、有限争议及跨任务省图依赖，不重看无新矛盾的通过镜头。按完整事件和工作量选择串行或最多两个审查任务，不新增固定镜数分流阈值。详细提交约定见 parallel-review.md。

## 单入口收尾

```text
python scripts/finish_review.py PROJECT.json PROFILE.json --output DELIVERY_DIR --run-dir FINISH_INTERNAL_DIR
```

审查登记完成后执行。工具持有同一项目锁，顺序完成规划、原视频不可覆盖快照、返修机读判定及交付校验。所有依赖哈希检查完成后才保存对应项目状态；不启动模型、不提交付费任务。原来的单步命令继续兼容。

run-dir 必须是新的内部目录，与交付目录分开，保存 AGGREGATION.json、REPAIR_DECISIONS.json 和含阶段耗时的 FINISH_REPORT.json。交付仍只有两表 Markdown 与图片。已存在快照只有聚合指纹和文件哈希一致时才能复用，不能把旧快照标成新结果。实际返修视频独立审查完成后才可指定 --stage repaired。

缺少返修证据字段时保留已完成的原视频交付，报告 delivery_complete_decision_blocked，退出码 2；不能当作无需返修或允许提交。其他阶段失败立即停止并记录失败，已经成功保存的阶段不回滚。图片和表结构校验不代替视觉审查。

## 阶段计时与对比

```text
python scripts/review_timing.py start TIMING.json preparation --kind reviewer_wall
python scripts/review_timing.py end TIMING.json preparation
python scripts/review_timing.py report TIMING.json
```

在开始和结束相应工作时调用。分别记录 preparation、review_T01、review_T02、coordination、supplement 等阶段，阶段名不可重复。只读审查任务若需自行计时，应使用各自工作区的独立日志；也可由主流程记录从派发到收集的墙钟，其中包含等待。不得让多个任务随意写同一文件。

kind 可用 reviewer_wall、tool、wait，区分审查墙钟、工具处理和明确等待。日志报告已完成区间的并集与跨度，不累加重叠任务；未结束阶段单独列出。未完整打点不能推算纯模型思考时间。finish 的计时只代表工具处理，不代表整个审查耗时。

串行与并行比较必须使用相同冻结素材哈希、脚本和规则，分别实际判断后比较逐镜 FAIL/uncertain/漏镜、省图锚点和边界结果，并报告准备、审查、协调、补证及总墙钟。复用旧结论的工具重放只验证机械结果一致，不是独立视觉盲测，不承诺固定分钟数或整体提速比例。
