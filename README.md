# 图片反风控

AstrBot 图片发送前处理插件。插件会在图片发送前对图片做轻微随机处理，改变图片文件哈希，降低被平台基于哈希匹配直接阻断的概率。

第一版只内置一种抗风控策略：四边随机裁剪。

## 工作方式

默认情况下，插件只处理 AstrBot 标准回复链路中的图片：

- `yield event.image_result(...)`
- `yield event.chain_result([... Image ...])`
- 普通 LLM 或插件回复结果中的 `Image` 消息段

处理流程：

1. 发送前捕获消息链中的 `Image`。
2. 读取图片字节。
3. 使用 Pillow 打开图片。
4. 按配置对上、下、左、右四边随机裁剪少量像素。
5. 用处理后的图片替换原图片消息段。
6. 如果处理失败，保留原图继续发送。

## 默认配置

默认只开启基础捕获能力：

- `capture.process_decorating_result=true`：处理标准回复图片。
- `capture.process_context_send=false`：不处理 `context.send_message(...)` 主动发送。
- `capture.process_forward_nodes=false`：不递归处理合并转发节点内部图片。
- `strategies.random_edge_crop=true`：启用四边随机裁剪。
- `edge_crop_max=2`：每条边最多随机裁剪 2 像素。
- `max_crop_ratio=0.02`：总裁剪量受图片最小边 2% 限制。
- `skip_gif=true`：跳过 GIF，避免动图丢帧。

## 捕获范围

### 默认可捕获

- 标准命令回复中的图片。
- 插件通过 `yield event.chain_result(...)` 返回的顶层 `Image`。
- 插件通过 `yield event.image_result(...)` 返回的图片。
- 标准回复结果中 `Image.fromURL(...)`、`Image.fromFileSystem(...)`、`Image.fromBytes(...)` 形式的图片。

### 可选捕获

开启 `capture.process_context_send` 后，可处理：

- `self.context.send_message(...)` 主动发送的图片。
- 定时任务、订阅推送等使用 `context.send_message` 的主动消息。

开启 `capture.process_forward_nodes` 后，可处理：

- `Node.content` 内的图片。
- `Nodes.nodes` 内的合并转发图片。

这两个选项默认关闭，因为它们覆盖范围更深，可能和其他插件或平台适配器存在兼容风险。

## 无法保证捕获的发送方式

以下图片可能绕过本插件：

- 其他插件直接调用 `await event.send(...)` 发送的图片。
- 其他插件直接调用平台 adapter 的 `send_by_session(...)`。
- 其他插件直接调用协议端 API，例如 OneBot 的 `send_group_msg`、`send_private_msg`。
- 流式输出中的图片。
- Markdown、JSON、卡片消息、CQ 码文本中内嵌的图片 URL。
- 平台适配器在发送阶段之后才生成的图片，例如某些文本转图片或卡片封面。
- 已经上传到平台并只以资源 ID、media ID、缓存文件名引用的图片。
- 非 `Image` 组件但平台展示为图片的内容，例如文件、视频封面、音乐或分享卡片缩略图。

如果需要真正全局捕获所有 AstrBot 平台发送图片，需要 AstrBot Core 提供更底层的统一发送前 hook。插件层只能覆盖常规消息链路径。

## 风险说明

本插件只能改变图片文件哈希，不能保证规避所有平台风控。

长期、大量发送已被平台风控的图片，仍可能触发更严格的账号、群聊或设备风控，包括但不限于：

- 图片继续发送失败。
- 账号被限制发图。
- 群聊消息被限流或屏蔽。
- 机器人账号被临时或永久封禁。

请自行评估使用风险。建议只在合理、合法、低频的场景下使用，不要将本插件用于持续对抗平台审核或发送违规内容。

## 依赖

```text
Pillow>=10.0.0
```

## 开发状态

当前版本为 `0.1.0`，只实现四边随机裁剪。后续可在 `strategies` 配置分组中继续扩展更多策略，例如重编码、轻微像素扰动、元数据处理等。
