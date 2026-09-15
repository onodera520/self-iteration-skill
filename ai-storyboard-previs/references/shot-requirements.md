# 轻量镜头要求：生成、取图、修图和验收共用

已有有序分镜只补齐执行必需的信息，不另走完整剧本创作流程，不改原镜号、顺序或剧情。用户输入仍是图片和自然语言；下面字段由代理整理，留在内部项目，不要求用户填写或随交付输出。

## 定稿与使用

每镜在 `requirements` 中明确目的、目标静态时刻、持久状态和针对该时刻的必要画面约束。`required_result` 继续表示完整镜头要表达的结果，`keyframe` 表示最终图片选在哪一阶段；二者可以不同，不能把视频终态硬塞进动作前的图片。

在生成前核对 requirements 与原脚本、facts、state_changes、资产一致。生成提示词、选帧和修图只转写这份设计。优化措辞不能另改身份、手别、动作对象或添加运镜；出现互斥要求，先回到设计修订并提高 requirements.version，再重建受影响请求。组 prompt_notes 与图像 KEEP/CHANGE/AVOID 也不能覆盖已定稿事实。

关键矛盾未解决用 status: provisional；受影响镜头及依赖它的镜头停止生成与通过判定，其他独立镜头可继续。可执行的最少设计假设记录 assumed，不冒称来自资产或脚本。未知的关键手别会造成互斥画面时先明确设计；无关隐藏纹理可保持 unknown。

## 内部约定

```json
{
  "version": 1,
  "status": "ready",
  "purpose": "让观众确认钥匙交接已完成",
  "inherits_from": "S02",
  "entry_state": {},
  "keyframe": {
    "phase": "exit",
    "description": "男孩已拿稳唯一的钥匙，女孩已经松手",
    "state": {}
  },
  "must_have": ["钥匙只由男孩持有", "女孩的交接手已松开"],
  "must_not_have": ["复制出第二把钥匙", "女孩仍握住钥匙"],
  "provenance": [{"field": "purpose,keyframe,must_have,must_not_have", "status": "script", "source": "S03 原脚本：男孩接住钥匙，女孩松手"}]
}
```

- `inherits_from`：同 continuity_id 的更早镜号，也可跨视频组、场景或跳过平行叙事镜头；新时间链用 null。它继承该镜的出口状态，不继承其画面左右或裁切。闪回不能默认继承剪辑顺序的上一镜。
- `entry_state`：键为 `实体.属性` 的持久状态初值，例如 `key.holder: girl`、`girl.coat_worn: false`。只补充此前未定义属性，不能悄悄覆盖继承值。确有时间跳跃或状态重置时明确时间链与脚本依据。
- 出口状态由入口加原有 `state_changes` 中有授权、有来源的变化计算，`before` 必须吻合。跨镜变化也要在所属动作镜中记录。不要另维护一份可随意填写的出口快照。道具唯一持有者与临时接触者分开；同一把钥匙交接中两只手接触不等于两把钥匙。
- `keyframe.phase`：entry、action、exit。entry/exit 从对应持久状态取得，`keyframe.state` 可补充当时的画面位置、身体朝向、视线及遮挡；不得覆盖该阶段已知的持久状态。action 可描述中间接触等临时状态，不改出口。用画面阶段匹配，不把计划秒数当成实际视频时间。
- `must_have/must_not_have`：只针对目标静帧，写具体风险。视频会注明它们只在目标时刻适用，完整动作仍来自脚本与状态变化。不要写泛化负面词库。主图不足以表达关键剧情时在同一镜号下补图。
- `provenance`：用 field 指出依据覆盖的字段，status 为 observed/user_provided/script/assumed/unknown，source 为实际图片及视角、原文位置或假设说明。observed 必须确实看过图片。校验器验证结构，不验证来源真实性或自然语言语义。

当前旧项目可不含 requirements；继续实做前逐镜补齐。直接保留原项目和旧结果，新增要求会使受影响审查过期；先复查现有图片是否能复用，不因过期自动付费重做。

## 空间、外观和可见性

固定形象和动态状态分开：外套款式来自资产，是否穿着来自剧情事件。最新明确用户要求优先；资产与文字仍矛盾时只处理影响执行的冲突，不能混合两套外貌。多视角绑定同一人物，服装脱下后作为同一物品继续跟踪。

持久空间以门、窗等地标为基准；画面左右以观众为基准；左手右手以角色自身为基准。可用 `girl.world_position` 表示位置，`girl.screen_position`、`girl.body_facing_camera`、`girl.head_facing_camera`、`girl.gaze` 仅放关键帧状态。反打只改变画面投影，不能把窗移墙、把持物换手或把看向某人等同于身体转向某人。

画外、遮挡、特写裁掉的属性继续留在持久状态，但不要求都画出来；看不见不能判定消失，也不能判定已验证。取图时同时看阶段、构图、可见关键状态；身份相似或匹配成功不是图片通过。

## 变更与复查

`storyboard.py context PROJECT.json S03` 返回解析后的镜头要求及图片审查指纹。视频提示词和图片请求自动引用相同要求；图像请求需指定准确的 prompt_field，代理仍要填写资产映射和具体 KEEP/CHANGE/AVOID。

只修图片不改设计时沿用原有本镜及邻图复查。修改持久状态时，沿 inherits_from 向后计算；跨组后续上下文发生变化会使旧审查和旧生成映射失效。相同出口状态下更换前镜关键帧或措辞，不使远处无关镜头自动失效。保留旧图、旧任务，重新核对受影响图及相邻衔接；失效表示需要复查，不是已确认失败。

## 借鉴位置

参考 General-skill 的固定提交 `dfd90e3e5e691451bae0e796600574cb8fbdcfe4`，独立实现轻量字段和工具衔接：

- [prompt-building.md](https://github.com/onodera520/General-skill/blob/dfd90e3e5e691451bae0e796600574cb8fbdcfe4/generator/references/prompt-building.md)：设计定稿后只读转写、静态时刻与完整动作分开。
- [continuity.md](https://github.com/onodera520/General-skill/blob/dfd90e3e5e691451bae0e796600574cb8fbdcfe4/generator/references/continuity.md)：统一状态来源、画外状态保留、空间与手别区分、沿依赖复查。
- [asset-binding.md](https://github.com/onodera520/General-skill/blob/dfd90e3e5e691451bae0e796600574cb8fbdcfe4/generator/references/asset-binding.md)：固定形象与动态状态分开、来源和未知项标注。
- [spec-prompt-fidelity.md](https://github.com/onodera520/General-skill/blob/dfd90e3e5e691451bae0e796600574cb8fbdcfe4/generator/evals/spec-prompt-fidelity.md)：交接阶段、持物、反打的正反例。我们的工具测试使用模拟事实，不等于真实生图或视觉审查验收。
