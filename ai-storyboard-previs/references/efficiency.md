# 减少重复整理，分清耗时来源

这些入口只减少机械整理与工具往返，保留逐镜判断、完整证据、SHA256 失效检查、漏镜全片补查和付费保护。

## 工作清单与协调草稿

parallel_review.py prepare 保存完整冻结上下文，同时为每个任务生成 worklist.json。先读完整脚本和负责镜头的要求、状态、映射观察及邻镜，再按需查看完整证据。清单不是证据范围上限，也不自动证明漏镜。

assemble 加 --drafts-dir 新目录，生成 FINAL_REVIEW.json、COORDINATOR_AUDIT.json、WORKLIST.json。已有逐镜记录原样保留，任务哈希、边界状态及原记录哈希由工具填入；全局检查保持 uncertain/false，需要协调者填写真实核对结果。不会覆盖已有目录或替审查者批准结论。

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
