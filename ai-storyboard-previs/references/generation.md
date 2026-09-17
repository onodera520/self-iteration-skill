# 模型调用与恢复（旧模式兼容）

默认审查后的固定工作流返修使用 [auto-repair.md](auto-repair.md)，不走本文件的公开模型接口。本文件仅维护另行指定的旧公开模型生成模式，原有安全限制不变。

先读本机 `runninghub/SKILL.md`，使用其模型发现/参数查询能力，必要时查注册表与模型文档。记录模型支持的图像数量、输入顺序含义、时长、比例、音频开关。不要把普通多图功能等同于保证多镜头复现。不支持的时长/比例必须先协调规划。

脚本默认加载个人技能目录中的 `runninghub/examples/python/client.py` 和 `model-registry.public.json`；可用 `--rh-skill PATH` 指定位置。沿用客户端上传、提交、鉴权与结果提取；查询调用其 `_post_json`，将每次状态写入项目。客户端设置 `max_retries=1`，避免模糊提交后自动重复收费。接口变更时先适配，不绕过注册表校验。

请求单独保存 JSON。下例的 endpoint、字段名、duration 都是占位示意，必须换成所选模型准确参数：

```json
{
  "id": "G01-v1-video", "kind": "video", "target_id": "G01", "version": 1,
  "endpoint": "REPLACE-WITH-REGISTERED-ENDPOINT",
  "payload": {"duration": 6},
  "prompt_field": "prompt", "reference_field": "imageUrls",
  "mute_fields": {}, "estimated_cost_cny": 1.0
}
```

本旧模式 workflow: video_evidence、video_input_mode: assets。video 默认按项目 assets 顺序上传组内用到的资产图，写入 reference_field 数组；prompt_field 直接使用用户原文（多组使用 group.video_prompt 对应片段），不自动追加脚本或旧基础提示词。上传前在输入整理中核对资产顺序与提示词图片编号。无需已有逐镜分镜图。旧 video_input_mode: anchors 仍兼容按镜头顺序上传 anchor，但本次默认流程不用它。video 不接受额外 local_files，避免映射移位。模型不支持数组多图时改用支持的模型或另做明确适配，不能假装多图复现可用。

默认只提交 video 请求，不生成或编辑独立分镜图。旧 image 请求与单图返修接口保持兼容，不进入此链路。确认失败时使用 previs.py repair/split，并调整受影响组的视频提示词；不通过补图绕过视频的漏镜或内容错误。图片与视频的已有共用额度逻辑不变。

mute_fields 可填已确认的关闭音频参数，没有开关则留空。中间视频不交付，无需静音拼接；仍须审查镜头顺序、必要硬切及动作结果；当前默认审查不检查屏幕文字或字幕。音频配置不代替视觉检查。

`dry-run` 不鉴权、不上传、不提交，验证本地文件、镜头映射、注册表参数。正式 run 前配置本次 `max_submissions` 和估价；有 budget_cny 时每次预留估价，未知或超限就停止。估价不等于结算费用，预算要求严格时使用服务端额度限制。

提交前持久化请求指纹和 submitting 状态、占用一次额度；返回 taskId 后立刻持久化。断网/进程中断而没有 ID 时标记或保留 submission_unknown/submitting，禁止自动重提。到服务端核实后用：

```text
python scripts/rh_tasks.py attach PROJECT.json REQUEST_ID REAL_TASK_ID
python scripts/rh_tasks.py resume PROJECT.json REQUEST_ID --wait-seconds 300
```

有 ID 的超时继续查询同一任务。SUCCESS 但下载失败时 resume 只重试下载。FAILED/CANCEL 保留记录；新提交需要新请求 ID 和剩余额度。重复 run 同一请求仅恢复；请求内容变化必须建立新版本请求。项目 `.lock` 防止并发操作；崩溃遗留锁只能在确认原进程已退出后人工删除。

API 密钥来自 RH_API_KEY，不写入项目、交付文档或日志。运行失败仅报告错误类型以免服务端文本泄漏密钥；任务响应作为本地调试数据保存，交付文档不复制响应或输入配置。
