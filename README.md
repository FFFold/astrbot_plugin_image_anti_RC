# 图片反风控

<p>
  <a href="https://github.com/FFFold/astrbot_plugin_image_anti_RC"><img alt="GitHub Repo" src="https://img.shields.io/badge/repo-astrbot__plugin__image__anti__RC-2B579A?style=flat-square&logo=github"></a>
  <a href="metadata.yaml"><img alt="Version" src="https://img.shields.io/badge/version-0.2.0-2ea44f?style=flat-square"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python">
  <img alt="AstrBot" src="https://img.shields.io/badge/AstrBot-%3E%3D4.16-FF6F00?style=flat-square">
</p>

AstrBot 图片发送前处理插件。在图片发送前对其执行轻微随机处理，改变文件哈希，降低被平台基于哈希匹配阻断的概率。

---

## 工作方式

```
发送前捕获消息链中的 Image
        │
        ▼
  读取图片字节
        │
        ▼
  Pillow 打开图片
        │
        ▼
  按配置依次执行处理策略
        │
        ▼
  用处理后图片替换原消息段
        │
        ▼
  处理失败则保留原图
```

### 内部策略执行顺序

| 步骤 | 策略 | 配置键 | 默认 |
|------|------|--------|------|
| 1 | 四边随机裁剪 | `random_edge_crop` | ✅ 启用 |
| 2 | 随机边框 | `random_border` | ❌ 关闭 |
| 3 | 极轻微像素扰动 | `pixel_jitter` | ❌ 关闭 |
| 4 | 元数据扰动 | `metadata_jitter` | ❌ 关闭 |

## 快速开始

### 安装

将本仓库添加至 AstrBot 插件市场或手动克隆至 `data/plugins` 目录：

```
cd data/plugins
git clone https://github.com/FFFold/astrbot_plugin_image_anti_RC
```

### 最小配置

默认配置即可工作——仅启用四边随机裁剪，处理标准回复链路中的图片。

## 配置

### 全局

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 启用插件 |
| `output_mode` | string | `base64` | 处理后图片输出方式：`base64` 或 `temp_file` |
| `log_detail` | bool | `false` | 输出详细日志（策略命中、格式变化、尺寸变化） |

### 捕获范围

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `capture.process_decorating_result` | bool | `true` | 处理标准回复图片 |
| `capture.process_context_send` | bool | `false` | 处理 `context.send_message()` 主动发送 |
| `capture.process_event_send` | bool | `false` | 处理 `event.send()` 直接发送 |
| `capture.process_forward_nodes` | bool | `false` | 递归处理合并转发节点内部图片 |

### 四边随机裁剪 `random_edge_crop`

对图片四边随机裁掉少量像素，改变图片尺寸，默认启用。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 是否启用 |
| `edge_crop_max` | int | `2` | 每条边最多裁剪像素数 |
| `max_crop_ratio` | float | `0.02` | 总裁剪量受图片最小边 2% 限制 |
| `min_image_side` | int | `80` | 图片宽或高小于该值时跳过 |
| `skip_gif` | bool | `true` | 跳过 GIF，避免动图丢帧 |

> 对边缘内容敏感的截图、二维码、表格图片，应降低裁剪强度或关闭。

### 随机边框 `random_border`

给图片增加极小随机边框，改变图片尺寸和像素。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用 |
| `max_border_px` | int | `1` | 最大边框像素 |
| `side` | str | `random_one` | `random_one` / `all` |
| `color_mode` | str | `edge_average` | `edge_average` / `near_edge` / `transparent` |
| `min_image_side` | int | `64` | 图片宽或高小于该值时跳过 |
| `skip_gif` | bool | `true` | 跳过 GIF |

> `color_mode=transparent` 仅对带透明通道的图片生效，普通图片回退到边缘平均色。

### 极轻微像素扰动 `pixel_jitter`

随机修改少量像素的 RGB 通道值。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用 |
| `pixel_count` | int | `8` | 最多修改像素数 |
| `channel_delta` | int | `1` | 单通道最大改变量 |
| `avoid_transparent` | bool | `true` | 跳过完全透明像素 |
| `min_image_side` | int | `64` | 图片宽或高小于该值时跳过 |
| `skip_gif` | bool | `true` | 跳过 GIF |

> 对二维码、条形码、精细文字、小尺寸图片、二值图有潜在影响。建议保持 `channel_delta=1`。

### 元数据扰动 `metadata_jitter`

保存时写入随机元数据或重新编码，不改变可见内容。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用 |
| `random_comment` | bool | `true` | 写入随机注释 |
| `skip_gif` | bool | `true` | 跳过 GIF |

> 平台上传时可能剥离元数据，单独使用该策略不能保证有效。

## 推荐组合

### 低风险

```yaml
metadata_jitter.enabled: true
random_edge_crop.enabled: true
random_border.enabled: false
pixel_jitter.enabled: false
```

### 更强

```yaml
metadata_jitter.enabled: true
random_edge_crop.enabled: true
random_border.enabled: true
pixel_jitter.enabled: false
```

### 强力

```yaml
metadata_jitter.enabled: true
random_edge_crop.enabled: true
random_border.enabled: true
pixel_jitter.enabled: true
```

### 截图 / 二维码 / 文字图

```yaml
metadata_jitter.enabled: true
random_edge_crop.enabled: false
random_border.enabled: true
pixel_jitter.enabled: false
```

## 捕获范围说明

### 默认捕获

- 标准命令回复中的图片
- 插件通过 `yield event.chain_result(...)` 返回的顶层 `Image`
- 插件通过 `yield event.image_result(...)` 返回的图片
- `Image.fromURL()` / `Image.fromFileSystem()` / `Image.fromBytes()` 形式的图片

### 可选捕获

| 配置项 | 捕获内容 | 兼容风险 |
|--------|----------|----------|
| `capture.process_context_send` | `self.context.send_message()` 主动发送的图片，定时任务、订阅推送等 | 低 |
| `capture.process_event_send` | 其他插件直接 `await event.send()` 发送的图片 | 中 |
| `capture.process_forward_nodes` | `Node.content` 及 `Nodes.nodes` 内合并转发图片 | 中 |

### 无法捕获的发送方式

- 直接调用平台 adapter 的 `send_by_session()`
- 直接调用协议端 API（如 OneBot 的 `send_group_msg`、`send_private_msg`）
- 流式输出中的图片
- Markdown、JSON、卡片消息、CQ 码中内嵌的图片 URL
- 平台适配器在发送后生成的图片（如文本转图、卡片封面）
- 已上传并以资源 ID / media ID / 缓存文件名引用的图片
- 非 `Image` 组件但平台展示为图片的内容（文件、视频封面、音乐卡片缩略图）

需要真正全局捕获需 AstrBot Core 提供更底层的统一发送前 hook。

## 注意事项

### 格式处理

- 动图（`is_animated=True`）始终跳过，不会被任何策略处理。
- 各策略的 `skip_gif` 控制是否跳过静态 GIF。
- 不支持的图片格式会自动回退为 JPEG 保存。
- 透明图（RGBA/LA）转 JPEG 时会合成白色背景。

### 风控提示

> 本插件只能改变图片文件哈希，**不能保证规避所有平台风控**。

长期、大量发送已被风控的图片，仍可能触发更严格的风控措施：

- 图片发送失败
- 账号被限制发图
- 群聊消息被限流或屏蔽
- 机器人账号被临时或永久封禁

请自行评估使用风险，在合理、合法、低频的场景下使用。

## 依赖

- `Pillow>=10.0.0`

## License

[MIT](LICENSE)
