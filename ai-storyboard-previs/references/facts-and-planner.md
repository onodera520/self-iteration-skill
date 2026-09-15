# 事实约束与相邻分组

代理从资产和原脚本提取有来源的事实，工具只计算结构化约束。不把抽取判断包装成数学确定性。

每镜 facts 示例：

```json
{"entity":"key","attribute":"holder","value":"girl","status":"known","phase":"before","critical":true,"source":{"kind":"script","ref":"S02 女孩递出钥匙，尚未交接完成"}}
```

phase 为 static/before/after；status 为 known/unknown，未知值可为 null。source.kind 为 script/asset/inference。屏幕左右与人物自身左右手分开，脚本未规定左右手时不擅自设为关键要求。

state_changes 保存 entity、attribute、before、after、critical、authorized、source。只有脚本授权变化才能更新期望状态，生成图中的错误不成为后镜基线。未知状态不是没变化；前后事实矛盾先核对来源。

intent 为 critical_result、narrative_turn、required_cut 三个布尔值。omission_assessment 的 allowed、risk、rationale、source 保留作为旧 anchor 输入模式的补足评估，不决定最终省图。最终省图走 storyboard.py omit，关键结果或关键状态变化不能省略。

## 模型配置与求解

assets/example-model-profile.json 是假设数据，实际运行查询模型准确能力与来源。填 max_images、min_duration、max_duration、allowed_durations（或 null）、aspect_ratios、allow_multi_shot、max_shots_per_group（最多 12），以及兼容字段 max_fill_per_group、video_cost_cny、missing_anchor_cost_cny。

默认资产模式枚举相邻、同场景、同连续事件的区间，以使用的资产数检查图片上限，以原镜计划时长之和检查时间限制，用动态规划选择可行的较低估价方案。没有最终分镜图也能先规划和生成。上传资产数与最终输出图数无关。

可选 anchor 模式才启用组首尾、关键结果、未知事实及锁定输入参考图保护，以及前后 anchor 夹住的低风险补足。ΔI 只是新增事实比例，不能独自决定删图。

```text
python scripts/planner.py PROJECT.json PROFILE.json --output PLAN.json --apply
```

只在未生成、未选择最终图的项目上使用 --apply。已有成果使用局部修复保留图片与任务。最优性只针对当前同场景区间、模型限制和可加估价，不代表真实画面质量最优。求解记录只在内部保存。
