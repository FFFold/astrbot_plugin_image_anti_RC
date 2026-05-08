# 图片反风控

AstrBot 图片发送前处理插件。插件会在图片发送前对图片做轻微随机处理，改变图片文件哈希，降低被平台基于哈希匹配直接阻断的概率。

当前内置四种处理策略：元数据扰动、四边随机裁剪、随机边框、极轻微像素扰动。用户开启多项策略时，插件会按照内部固定顺序逐个执行，不会自动挑选或随机跳过已启用策略。

## 工作方式

默认情况下，插件只处理 AstrBot 标准回复链路中的图片：

- `yield event.image_result(...)`
- `yield event.chain_result([... Image ...])`
- 普通 LLM 或插件回复结果中的 `Image` 消息段

处理流程：

1. 发送前捕获消息链中的 `Image`。
2. 读取图片字节。
3. 使用 Pillow 打开图片。
4. 按配置依次执行已启用的图片处理策略。
5. 用处理后的图片替换原图片消息段。
6. 如果处理失败，保留原图继续发送。

内部策略执行顺序：

1. `random_edge_crop`：四边随机裁剪。
2. `random_border`：随机边框。
3. `pixel_jitter`：极轻微像素扰动。
4. `metadata_jitter`：保存时写入随机元数据或重新保存文件。

## 默认配置

默认只开启基础捕获能力：

- `capture.process_decorating_result=true`：处理标准回复图片。
- `capture.process_context_send=false`：不处理 `context.send_message(...)` 主动发送。
- `capture.process_event_send=false`：不处理 `event.send(...)` 直接发送。
- `capture.process_forward_nodes=false`：不递归处理合并转发节点内部图片。
- `metadata_jitter.enabled=false`：默认不启用元数据扰动。
- `random_edge_crop.enabled=true`：启用四边随机裁剪。
- `random_edge_crop.edge_crop_max=2`：每条边最多随机裁剪 2 像素。
- `random_edge_crop.max_crop_ratio=0.02`：总裁剪量受图片最小边 2% 限制。
- `random_edge_crop.skip_gif=true`：跳过 GIF，避免动图丢帧。
- `random_border.enabled=false`：默认不启用随机边框。
- `pixel_jitter.enabled=false`：默认不启用极轻微像素扰动。

## 处理策略

### 元数据扰动

`metadata_jitter` 会在保存图片时写入少量随机元数据，或通过重新保存改变文件数据。它不会改变图片的可见内容。

适用场景：

- 希望尽量不影响图片视觉效果。
- 希望在四边裁剪之外增加一层低风险扰动。

注意事项：

- 平台上传图片时可能剥离元数据，因此该策略不能保证单独有效。
- 当前保存流程不会主动保留原始 EXIF 等元数据。

### 四边随机裁剪

`random_edge_crop` 会随机裁掉图片上、下、左、右边缘的少量像素。这是默认启用的基础策略。

注意事项：

- 该策略会改变图片尺寸。
- 对边缘内容敏感的截图、二维码、表格图片，应降低裁剪强度或关闭该策略。

### 随机边框

`random_border` 会给图片随机增加极小边框，改变图片像素和尺寸。

适用场景：

- 希望不裁掉原图内容。
- 希望对表情包、插图类图片增加轻量扰动。

注意事项：

- 该策略会改变图片尺寸。
- `color_mode=transparent` 仅对带透明通道的图片生效，普通图片会回退到边缘平均色。

### 极轻微像素扰动

`pixel_jitter` 会随机修改少量像素的 RGB 通道，默认每张图片最多修改 8 个像素，每个通道最大改变量为 1。

适用场景：

- 希望获得比元数据和边框更强的像素级扰动。
- 图片不是二维码、精细文字截图或二值图。

注意事项：

- 该策略真实改变图片像素，默认关闭。
- 对二维码、条形码、精细文字、小尺寸图片、二值图有潜在影响。
- 建议保持 `channel_delta=1`，不要盲目提高强度。

### 推荐组合

低风险组合：

```text
metadata_jitter.enabled=true
random_edge_crop.enabled=true
random_border.enabled=false
pixel_jitter.enabled=false
```

更强组合：

```text
metadata_jitter.enabled=true
random_edge_crop.enabled=true
random_border.enabled=true
pixel_jitter.enabled=false
```

强力组合：

```text
metadata_jitter.enabled=true
random_edge_crop.enabled=true
random_border.enabled=true
pixel_jitter.enabled=true
```

截图、二维码、文字图建议：

```text
metadata_jitter.enabled=true
random_edge_crop.enabled=false
random_border.enabled=true
pixel_jitter.enabled=false
```

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

开启 `capture.process_event_send` 后，可处理：

- 其他插件直接 `await event.send(...)` 发送的图片。
- 部分媒体解析插件直接发送的图片，例如 `astrbot_plugin_media_parser`。

开启 `capture.process_forward_nodes` 后，可处理：

- `Node.content` 内的图片。
- `Nodes.nodes` 内的合并转发图片。

这些可选项默认关闭，因为它们覆盖范围更深，可能和其他插件或平台适配器存在兼容风险。

### astrbot_plugin_media_parser

`astrbot_plugin_media_parser` 的图片发送主要走直接发送路径：

- 普通图集会调用 `await event.send(event.chain_result(images))`。
- 打包模式会调用 `await event.send(event.chain_result([Nodes(...)]))`。
- 图片组件通常由 `Image.fromURL(...)` 或 `Image.fromFileSystem(...)` 构造。

因此，仅开启默认的 `capture.process_decorating_result` 无法捕获它。若要处理该插件发送的图片，通常需要开启：

- `capture.process_event_send=true`
- `capture.process_forward_nodes=true`，当媒体解析插件启用打包/合并转发模式时需要。

## 无法保证捕获的发送方式

以下图片可能绕过本插件：

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

当前版本为 `0.2.0`，已实现元数据扰动、四边随机裁剪、随机边框和极轻微像素扰动。后续可继续扩展测试命令、处理统计、资源保护和更多重编码策略。
