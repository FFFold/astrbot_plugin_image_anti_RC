# 更新日志

本项目遵循按版本记录主要变更的方式。由于插件仍处于早期阶段，版本号以当前发布状态为准。

## 0.2.1 - 代码质量与稳定性

### 修复

- 修复 `temp_file` 输出模式下临时文件仅在插件停止时清理、长期运行导致磁盘空间泄漏的问题，改为发送完成后立即清理。
- 修复 `on_decorating_result` 中图片处理后直接使用同步 Pillow 调用阻塞 asyncio 事件循环的问题，改用 `asyncio.to_thread` 在线程池中执行 CPU 密集型图像处理。
- 修复 `terminate()` 中临时文件清理存在 TOCTOU 竞态的冗余 `path.exists()` 检查。
- 修复四处 `logger.warning` 捕获 `Exception` 时缺少 `exc_info=True`，导致异常调用栈丢失、难以调试的问题。

### 测试

- 修复 `_install_astrbot_stubs()` 注入 `sys.modules` 后未清理导致测试环境污染的问题，改为 `yield` fixture 自动清理。
- 为 `sys.path.remove` 添加 `ValueError` 防护，避免 teardown 阶段异常。

## 0.2.0 - 策略增强

### 新增

- 新增 `metadata_jitter` 元数据扰动策略。
- 新增 `random_border` 随机边框策略。
- 新增 `pixel_jitter` 极轻微像素扰动策略。
- 支持用户同时开启多项策略，并按照插件内部固定顺序逐个执行。

### 图片处理

- 将图片处理流程调整为统一流水线，图片只打开一次，多个策略按顺序处理后统一保存。
- `metadata_jitter` 支持 JPEG 写入随机 comment，PNG 写入随机 `tEXt` 元数据。
- `metadata_jitter` 支持通过重新保存图片改变 WebP 文件数据。
- `random_border` 支持随机单边或四边添加极小边框。
- `random_border` 支持边缘平均色、近似边缘色、透明色三种边框颜色模式。
- `pixel_jitter` 支持随机修改少量 RGB 通道值。
- `pixel_jitter` 支持避开透明像素，降低无效扰动概率。

### 配置

- 新增 `metadata_jitter.enabled`、`metadata_jitter.random_comment`、`metadata_jitter.skip_gif`。
- 新增 `random_border.enabled`、`random_border.max_border_px`、`random_border.side`、`random_border.color_mode`、`random_border.min_image_side`、`random_border.skip_gif`。
- 新增 `pixel_jitter.enabled`、`pixel_jitter.pixel_count`、`pixel_jitter.channel_delta`、`pixel_jitter.avoid_transparent`、`pixel_jitter.min_image_side`、`pixel_jitter.skip_gif`。
- 新增策略默认关闭，避免升级后处理强度突然增加。

### 性能

- `_border_fill_color` 将 `getpixel` 循环替换为 `crop` + `getdata`/`get_flattened_data`，兼容 Pillow 10-14。
- `pixel_jitter` 的 `attempts` 增加上限 `min(max(pixel_count * 10, 10), width * height)`，避免极端配置下的无意义迭代。

### 日志

- 处理完成日志同时记录输入格式和实际输出格式（`format_in`/`format_out`），便于调试格式回退。

### 测试

- 新增 `tests/test_image_processing.py`，使用 Pillow stub 隔离 AstrBot 运行时。
- 新增动图测试：验证所有策略启用时动画 GIF 返回原字节。
- 新增 `random_edge_crop` 启用状态测试：裁剪减小尺寸、`edge_crop_max=0` 不做处理、小图跳过。
- 新增 `pixel_jitter` 透明度测试：`avoid_transparent=True` 全透明图不变、`avoid_transparent=False` 有像素变化。
- 新增 `random_border` 尺寸变化测试。
- 新增 `metadata_jitter` hash 变化但尺寸不变测试。

### 文档

- 更新 README，说明四种策略的用途、执行顺序、默认配置和推荐组合。
- 增加 `random_border` 会改变图片尺寸的说明。
- 增加 `pixel_jitter` 对二维码、文字截图、二值图存在潜在影响的风险提示。
- 重写 README，优化排版结构，使用表格、徽章、流程图提升可读性。

## 0.1.0 - 首次开发

### 新增

- 创建 AstrBot 图片反风控插件基础结构。
- 新增插件入口 `main.py`，插件类继承 `astrbot.api.star.Star`。
- 新增插件元数据文件 `metadata.yaml`。
- 新增 WebUI 配置 schema `_conf_schema.json`。
- 新增依赖声明 `requirements.txt`，使用 `Pillow` 处理图片。
- 新增中文使用说明 `README.md`。

### 图片处理

- 实现图片发送前处理能力，用于轻微改变图片内容或文件数据，降低重复图片哈希命中风险。
- 实现四边随机裁剪策略 `random_edge_crop`。
- 支持按最大裁剪像素和最大裁剪比例限制裁剪强度。
- 支持按图片最短边跳过过小图片。
- 支持跳过 GIF，避免破坏动图。
- 支持在处理失败时回退原始图片，避免影响正常发送。

### 捕获范围

- 支持捕获标准回复链路 `on_decorating_result`，默认开启。
- 支持可选捕获 `context.send_message` 主动发送链路，默认关闭。
- 支持可选捕获 `event.send` 直接发送链路，默认关闭。
- 支持可选递归处理合并转发中的 `Node` / `Nodes` 图片，默认关闭。
- 为 `event.send` 捕获增加重入保护，避免适配器子类调用 `super().send()` 时重复处理。

### 输出模式

- 支持处理后以 base64 形式回写图片。
- 支持处理后写入临时文件再发送。
- 临时文件输出会根据实际图片格式选择 `.jpg`、`.png`、`.webp` 等后缀。

### 配置

- 新增全局开关 `enabled`。
- 新增输出模式配置 `output_mode`。
- 新增详细日志开关 `log_detail`。
- 新增捕获范围配置分组 `capture`。
- 新增四边随机裁剪策略配置分组 `random_edge_crop`。
- 默认仅开启标准回复捕获，其他更激进的捕获方式默认关闭，以降低兼容风险。

### 文档

- 说明插件能力边界和无法保证捕获的发送方式。
- 说明与 `astrbot_plugin_pixiv_reborn`、`astrbot_plugin_media_parser` 等插件的典型配合方式。
- 说明开启 `context.send_message`、`event.send`、合并转发递归处理时的兼容风险。
- 增加风险提示：长期或大量发送平台已判定为高风险的图片仍可能触发限制，甚至带来账号风险。

### 验证

- 通过 `ruff format .` 格式化。
- 通过 `ruff check .` 静态检查。
- 通过 `python -m py_compile main.py` 语法检查。
- 完成实装测试，确认核心图片处理链路可用。
