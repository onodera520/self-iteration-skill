# 首轮审查的返修证据字段

本文件只规定原有组级审查顺便填写的证据，不启动返修、不增加逐镜判断。付费执行、提示词、预算与恢复仅在需要执行时读 [自动返修](auto-repair.md)。视觉规则仍以 review.md 为准。

首次整理将 `shots[].script` 保存为该镜原始脚本文本（含标点、换行），不得摘要；`source_script` 保留完整输入。可选 `video_format_requirements` 只能逐字摘录原文中的全局格式要求。`repair_cycle.py baseline` 冻结基准。旧项目只存摘要时，从原输入恢复并重建有效审查；真实脚本修订须创建独立项目版本，不得清除已占用付费额度。

在每份来源视频的组级审查中填写 `repair_assessments`：每个确认 `FAIL` 或 `absent` 镜头恰有一条，无此类镜头时填空数组；PASS 和 uncertain 不填。以下仅为字段示意，必须换为本案真实证据：

```json
{
  "shot_id": "S03",
  "critical": true,
  "critical_kind": "wrong_transfer_result",
  "affects_story": true,
  "script_quote": "钥匙交接完成，钥匙在乙手中。",
  "issue_ids": ["I03"],
  "impact": "钥匙仍在甲手中，使交接结果相反。",
  "correction": "明确呈现乙接住钥匙，结束时钥匙留在乙手中；其他镜头遵循原文。",
  "preserves_script": true
}
```

`critical_kind` 仅用于关键问题，可取 missing_key_node / wrong_actor / broken_causality / wrong_transfer_result / explicit_key_requirement。不能仅用“严重”定级；必须引用本镜原文、本镜问题和有效证据。已定位错误引用同镜有效帧及实际时间；确认漏镜引用覆盖整个原视频的有效补查记录，不伪造图片。稀疏抽帧不证明 absent。

工具只验证引文、镜号、关联和字段完整性，不能证明视觉或修复语义真实。审查者须确认影响与关键程度，补充仅恢复本镜原意，不添加事件、改变其他镜约束或资产编号。已有证据不足就保留 uncertain，不猜测修复依据。

旧审查缺这些字段仍可用于两表交付，但不能自动产生返修判定；利用有效事实一次补齐组级审查。review_schema=5 / reference_policy_version=5 不变；独立 repair policy=2 纳入返修绑定，旧版返修判定须重算。返修阈值不等同于审查是否通过。
