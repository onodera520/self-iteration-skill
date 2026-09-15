# 模型调用与恢复

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

video 默认按项目 assets 顺序上传组内用到的资产图，写入 reference_field 数组；自动追加资产映射、完整逐镜脚本及状态约束。无需已有逐镜分镜图。可选 video_input_mode: anchors 才上传按镜头顺序排列的 anchor。video 不接受额外 local_files，避免映射移位。模型不支持数组多图时改用支持的模型或另做明确适配，不能假装多图复现可用。

image 请求 target_id 为镜头编号、version 为所属组当前版本；payload 填入所选图像模型参数，可用 local_files 映射本地资产、待编辑图片及相邻分镜图。prompt 明确 KEEP/CHANGE/AVOID；有 requirements 时必须提供注册表中的 prompt_field，工具自动追加已定稿的目标静帧要求，代理写的修复指令不得与之冲突。该追加只覆盖镜头目标，资产图映射、编辑范围仍由代理填写。选择支持图像编辑的已注册模型，不能把仅文生图模型当局部编辑。补图优先资产加脚本，局部编辑优先保留构图和人物。新图下载后使用 storyboard.py select，source.kind 为 generated/edited 且 source.request_id 指向原请求，再实际审查；不要写回 reference.path 作为最终交付图。

修改最终图片不提高视频组版本，也不重生成视频；每次图片尝试使用新 request ID，返修先登记 storyboard.py repair。图片和视频共用预算与 max_submissions。

mute_fields 可填已确认的关闭音频参数，没有开关则留空。中间视频不交付，音轨无需另做静音拼接；最终图片仍须检查字幕和画面瑕疵。

`dry-run` 不鉴权、不上传、不提交，验证本地文件、镜头映射、注册表参数。正式 run 前配置本次 `max_submissions` 和估价；有 budget_cny 时每次预留估价，未知或超限就停止。估价不等于结算费用，预算要求严格时使用服务端额度限制。

提交前持久化请求指纹和 submitting 状态、占用一次额度；返回 taskId 后立刻持久化。断网/进程中断而没有 ID 时标记或保留 submission_unknown/submitting，禁止自动重提。到服务端核实后用：

```text
python scripts/rh_tasks.py attach PROJECT.json REQUEST_ID REAL_TASK_ID
python scripts/rh_tasks.py resume PROJECT.json REQUEST_ID --wait-seconds 300
```

有 ID 的超时继续查询同一任务。SUCCESS 但下载失败时 resume 只重试下载。FAILED/CANCEL 保留记录；新提交需要新请求 ID 和剩余额度。重复 run 同一请求仅恢复；请求内容变化必须建立新版本请求。项目 `.lock` 防止并发操作；崩溃遗留锁只能在确认原进程已退出后人工删除。

API 密钥来自 RH_API_KEY，不写入项目、交付文档或日志。运行失败仅报告错误类型以免服务端文本泄漏密钥；任务响应作为本地调试数据保存，交付文档不复制响应或输入配置。
