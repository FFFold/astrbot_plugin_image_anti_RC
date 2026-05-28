import base64
import io
import random
import secrets
import tempfile
import uuid
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.astr_message_event import (
    AstrMessageEvent as CoreAstrMessageEvent,
)

try:
    from astrbot.api.message_components import Image, Node, Nodes
except ImportError:  # pragma: no cover
    Image = Node = Nodes = None

try:
    from PIL import Image as PILImage
    from PIL import ImageOps, PngImagePlugin
except ImportError:  # pragma: no cover
    PILImage = None
    ImageOps = None
    PngImagePlugin = None


PLUGIN_NAME = "astrbot_plugin_image_anti_rc"


class ImageAntiRiskPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._original_send_message = None
        self._send_message_patched = False
        self._original_event_sends = {}
        self._event_send_patched = False
        self._processing_event_send_chain_ids = set()
        self._temp_dir = Path(tempfile.gettempdir()) / PLUGIN_NAME
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._tracked_temp_files: set[Path] = set()

        if self._enabled() and self._process_context_send():
            self._patch_context_send_message()
        if self._enabled() and self._process_event_send():
            self._patch_event_send()

        logger.info(
            "图片反风控插件已加载："
            f"standard={self._process_decorating_result()}, "
            f"context_send={self._process_context_send()}, "
            f"event_send={self._process_event_send()}, "
            f"forward_nodes={self._process_forward_nodes()}, "
            f"random_edge_crop={self._random_edge_crop_enabled()}, "
            f"metadata_jitter={self._metadata_jitter_enabled()}, "
            f"random_border={self._random_border_enabled()}, "
            f"pixel_jitter={self._pixel_jitter_enabled()}"
        )

    @filter.on_decorating_result(priority=-100)
    async def on_decorating_result(self, event: AstrMessageEvent):
        if not self._enabled() or not self._process_decorating_result():
            return

        result = event.get_result()
        if result is None or not result.chain:
            return

        result.chain = await self._process_components(result.chain)

    async def terminate(self):
        self._restore_context_send_message()
        self._restore_event_send()
        self._cleanup_temp_files()

    def _enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def _capture_config(self) -> dict[str, Any]:
        value = self.config.get("capture", {})
        return value if isinstance(value, dict) else {}

    def _random_edge_crop_config(self) -> dict[str, Any]:
        value = self.config.get("random_edge_crop", {})
        return value if isinstance(value, dict) else {}

    def _metadata_jitter_config(self) -> dict[str, Any]:
        value = self.config.get("metadata_jitter", {})
        return value if isinstance(value, dict) else {}

    def _random_border_config(self) -> dict[str, Any]:
        value = self.config.get("random_border", {})
        return value if isinstance(value, dict) else {}

    def _pixel_jitter_config(self) -> dict[str, Any]:
        value = self.config.get("pixel_jitter", {})
        return value if isinstance(value, dict) else {}

    def _process_decorating_result(self) -> bool:
        return bool(self._capture_config().get("process_decorating_result", True))

    def _process_context_send(self) -> bool:
        return bool(self._capture_config().get("process_context_send", False))

    def _process_event_send(self) -> bool:
        return bool(self._capture_config().get("process_event_send", False))

    def _process_forward_nodes(self) -> bool:
        return bool(self._capture_config().get("process_forward_nodes", False))

    def _random_edge_crop_enabled(self) -> bool:
        return bool(self._random_edge_crop_config().get("enabled", True))

    def _metadata_jitter_enabled(self) -> bool:
        return bool(self._metadata_jitter_config().get("enabled", False))

    def _random_border_enabled(self) -> bool:
        return bool(self._random_border_config().get("enabled", False))

    def _pixel_jitter_enabled(self) -> bool:
        return bool(self._pixel_jitter_config().get("enabled", False))

    def _log_detail(self) -> bool:
        return bool(self.config.get("log_detail", False))

    def _patch_context_send_message(self) -> None:
        current = getattr(self.context, "send_message", None)
        if current is None or getattr(current, "_image_anti_rc_owner", None) == id(
            self
        ):
            return

        self._original_send_message = current

        async def wrapped_send_message(session, message_chain):
            if self._enabled() and self._process_context_send():
                try:
                    message_chain = await self._process_message_chain(message_chain)
                except Exception as exc:
                    logger.warning(
                        f"图片反风控：主动发送图片处理失败，使用原消息链 - {exc}",
                        exc_info=True,
                    )
            return await self._original_send_message(session, message_chain)

        setattr(wrapped_send_message, "_image_anti_rc_owner", id(self))
        self.context.send_message = wrapped_send_message
        self._send_message_patched = True
        logger.info("图片反风控：已启用 context.send_message 主动发送处理。")

    def _cleanup_temp_files(self) -> None:
        cleaned = 0
        for path in self._tracked_temp_files:
            try:
                path.unlink()
                cleaned += 1
            except OSError:
                pass
        self._tracked_temp_files.clear()
        if cleaned:
            logger.info(f"图片反风控：已清理 {cleaned} 个临时文件。")

    def _restore_context_send_message(self) -> None:
        if not self._send_message_patched or self._original_send_message is None:
            return
        current = getattr(self.context, "send_message", None)
        if getattr(current, "_image_anti_rc_owner", None) == id(self):
            self.context.send_message = self._original_send_message
            logger.info("图片反风控：已恢复 context.send_message。")
        self._send_message_patched = False
        self._original_send_message = None

    def _patch_event_send(self) -> None:
        patched_count = 0
        for event_class in self._event_classes_to_patch():
            current = getattr(event_class, "send", None)
            if current is None or getattr(current, "_image_anti_rc_owner", None) == id(
                self
            ):
                continue

            self._original_event_sends[event_class] = current

            async def wrapped_event_send(event_self, message_chain, _original=current):
                chain_id = id(message_chain)
                already_processing = chain_id in self._processing_event_send_chain_ids
                if (
                    self._enabled()
                    and self._process_event_send()
                    and not already_processing
                ):
                    try:
                        self._processing_event_send_chain_ids.add(chain_id)
                        message_chain = await self._process_message_chain(message_chain)
                        return await _original(event_self, message_chain)
                    except Exception as exc:
                        logger.warning(
                            f"图片反风控：event.send 图片处理失败，使用原消息链 - {exc}",
                            exc_info=True,
                        )
                        return await _original(event_self, message_chain)
                    finally:
                        self._processing_event_send_chain_ids.discard(chain_id)
                return await _original(event_self, message_chain)

            setattr(wrapped_event_send, "_image_anti_rc_owner", id(self))
            event_class.send = wrapped_event_send
            patched_count += 1

        self._event_send_patched = patched_count > 0
        logger.info(
            f"图片反风控：已启用 event.send 直接发送处理，patch {patched_count} 个事件类。"
        )

    def _restore_event_send(self) -> None:
        if not self._event_send_patched or not self._original_event_sends:
            return
        restored_count = 0
        for event_class, original_send in self._original_event_sends.items():
            current = getattr(event_class, "send", None)
            if getattr(current, "_image_anti_rc_owner", None) == id(self):
                event_class.send = original_send
                restored_count += 1
        logger.info(f"图片反风控：已恢复 {restored_count} 个 event.send。")
        self._event_send_patched = False
        self._original_event_sends = {}

    def _event_classes_to_patch(self) -> list[type]:
        classes = []
        stack = [CoreAstrMessageEvent]
        while stack:
            event_class = stack.pop()
            classes.append(event_class)
            stack.extend(event_class.__subclasses__())
        return classes

    async def _process_message_chain(self, message_chain: MessageChain) -> MessageChain:
        if not isinstance(message_chain, MessageChain) or not message_chain.chain:
            return message_chain
        message_chain.chain = await self._process_components(message_chain.chain)
        return message_chain

    async def _process_components(self, components: list[Any]) -> list[Any]:
        processed = []
        for component in components:
            try:
                processed.append(await self._process_component(component))
            except Exception as exc:
                logger.warning(
                    f"图片反风控：消息段处理失败，保留原消息段 - {exc}",
                    exc_info=True,
                )
                processed.append(component)
        return processed

    async def _process_component(self, component: Any) -> Any:
        if Image is not None and isinstance(component, Image):
            return await self._process_image_component(component)

        if not self._process_forward_nodes():
            return component

        if Node is not None and isinstance(component, Node):
            component.content = await self._process_components(component.content or [])
            return component

        if Nodes is not None and isinstance(component, Nodes):
            for node in component.nodes or []:
                node.content = await self._process_components(node.content or [])
            return component

        return component

    async def _process_image_component(self, component: Any) -> Any:
        if PILImage is None or ImageOps is None:
            logger.warning("图片反风控：未安装 Pillow，跳过图片处理。")
            return component

        if not self._has_enabled_strategy():
            return component

        try:
            raw_base64 = await component.convert_to_base64()
            image_bytes = base64.b64decode(raw_base64)
            output_bytes, output_format = self._process_image_bytes(image_bytes)
            if output_bytes is image_bytes:
                return component
            return self._build_output_image(output_bytes, output_format)
        except Exception as exc:
            logger.warning(
                f"图片反风控：图片处理失败，使用原图 - {exc}",
                exc_info=True,
            )
            return component

    def _has_enabled_strategy(self) -> bool:
        return any(
            (
                self._random_edge_crop_enabled(),
                self._metadata_jitter_enabled(),
                self._random_border_enabled(),
                self._pixel_jitter_enabled(),
            )
        )

    def _process_image_bytes(self, image_bytes: bytes) -> tuple[bytes, str]:
        with io.BytesIO(image_bytes) as input_buffer:
            with PILImage.open(input_buffer) as img:
                fmt = (img.format or "JPEG").upper()
                if getattr(img, "is_animated", False):
                    return image_bytes, ""

                img = ImageOps.exif_transpose(img)
                applied_strategies = []

                img, applied = self._apply_random_edge_crop(img, fmt)
                if applied:
                    applied_strategies.append("random_edge_crop")

                img, applied = self._apply_random_border(img, fmt)
                if applied:
                    applied_strategies.append("random_border")

                img, applied = self._apply_pixel_jitter(img, fmt)
                if applied:
                    applied_strategies.append("pixel_jitter")

                metadata_jitter = self._should_apply_metadata_jitter(fmt)
                if metadata_jitter:
                    applied_strategies.append("metadata_jitter")

                if not applied_strategies:
                    return image_bytes, ""

                output_bytes, output_format = self._save_image(
                    img, fmt, metadata_jitter
                )
                if self._log_detail():
                    logger.info(
                        "图片反风控：处理完成 "
                        f"format_in={fmt}, format_out={output_format}, "
                        f"strategies={','.join(applied_strategies)}"
                    )
                return output_bytes, output_format

    def _apply_random_edge_crop(self, img: Any, fmt: str) -> tuple[Any, bool]:
        if not self._random_edge_crop_enabled():
            return img, False

        crop_config = self._random_edge_crop_config()
        edge_crop_max = int(crop_config.get("edge_crop_max", 2) or 0)
        if edge_crop_max <= 0:
            return img, False
        if crop_config.get("skip_gif", True) and fmt == "GIF":
            return img, False

        width, height = img.size
        min_side = int(crop_config.get("min_image_side", 80) or 1)
        if width < min_side or height < min_side:
            return img, False

        max_crop_ratio = float(crop_config.get("max_crop_ratio", 0.02) or 0)
        max_allowed_total = int(min(width, height) * max_crop_ratio)
        max_per_side = min(edge_crop_max, max_allowed_total // 2)
        if max_per_side <= 0:
            return img, False

        top = random.randint(0, max_per_side)
        bottom = random.randint(0, max_per_side)
        left = random.randint(0, max_per_side)
        right = random.randint(0, max_per_side)
        if top == bottom == left == right == 0:
            top = 1

        new_width = width - left - right
        new_height = height - top - bottom
        if new_width <= 10 or new_height <= 10:
            return img, False

        cropped = img.crop((left, top, width - right, height - bottom))
        if self._log_detail():
            logger.info(
                "图片反风控：四边随机裁剪 "
                f"[{width}x{height}] -> [{new_width}x{new_height}], "
                f"T:{top} B:{bottom} L:{left} R:{right}"
            )
        return cropped, True

    def _apply_random_border(self, img: Any, fmt: str) -> tuple[Any, bool]:
        if not self._random_border_enabled():
            return img, False

        border_config = self._random_border_config()
        if border_config.get("skip_gif", True) and fmt == "GIF":
            return img, False

        width, height = img.size
        min_side = int(border_config.get("min_image_side", 64) or 1)
        if width < min_side or height < min_side:
            return img, False

        max_border_px = int(border_config.get("max_border_px", 1) or 0)
        if max_border_px <= 0:
            return img, False
        border_px = random.randint(1, max_border_px)

        side = str(border_config.get("side", "random_one") or "random_one")
        if side == "all":
            border = (border_px, border_px, border_px, border_px)
            color_side = random.choice(("left", "top", "right", "bottom"))
        else:
            color_side = random.choice(("left", "top", "right", "bottom"))
            border = {
                "left": (border_px, 0, 0, 0),
                "top": (0, border_px, 0, 0),
                "right": (0, 0, border_px, 0),
                "bottom": (0, 0, 0, border_px),
            }[color_side]

        border_img = self._border_ready_image(img)
        fill = self._border_fill_color(border_img, color_side)
        expanded = ImageOps.expand(border_img, border=border, fill=fill)
        if self._log_detail():
            logger.info(
                "图片反风控：随机边框 "
                f"[{width}x{height}] -> [{expanded.size[0]}x{expanded.size[1]}], "
                f"border={border}, fill={fill}"
            )
        return expanded, True

    def _border_ready_image(self, img: Any) -> Any:
        if img.mode == "P":
            return img.convert("RGBA" if self._has_alpha(img) else "RGB")
        return img

    def _border_fill_color(self, img: Any, side: str) -> Any:
        border_config = self._random_border_config()
        color_mode = str(
            border_config.get("color_mode", "edge_average") or "edge_average"
        )
        if color_mode == "transparent" and self._has_alpha(img):
            return (0, 0, 0, 0)

        rgba = img.convert("RGBA")
        width, height = rgba.size
        if side == "top":
            edge = rgba.crop((0, 0, width, 1))
        elif side == "bottom":
            edge = rgba.crop((0, height - 1, width, height))
        elif side == "left":
            edge = rgba.crop((0, 0, 1, height))
        else:
            edge = rgba.crop((width - 1, 0, width, height))
        get_pixels = getattr(edge, "get_flattened_data", edge.getdata)
        pixels = list(get_pixels())

        if color_mode == "near_edge":
            pixel = list(random.choice(pixels))
            for index in range(3):
                pixel[index] = self._clamp_channel(
                    pixel[index] + random.choice((-1, 1))
                )
            return tuple(pixel) if self._has_alpha(img) else tuple(pixel[:3])

        averaged = tuple(
            sum(pixel[index] for pixel in pixels) // len(pixels) for index in range(4)
        )
        return averaged if self._has_alpha(img) else averaged[:3]

    def _apply_pixel_jitter(self, img: Any, fmt: str) -> tuple[Any, bool]:
        if not self._pixel_jitter_enabled():
            return img, False

        jitter_config = self._pixel_jitter_config()
        if jitter_config.get("skip_gif", True) and fmt == "GIF":
            return img, False

        width, height = img.size
        min_side = int(jitter_config.get("min_image_side", 64) or 1)
        if width < min_side or height < min_side:
            return img, False

        pixel_count = int(jitter_config.get("pixel_count", 8) or 0)
        channel_delta = int(jitter_config.get("channel_delta", 1) or 0)
        if pixel_count <= 0 or channel_delta <= 0:
            return img, False

        has_alpha = self._has_alpha(img)
        output_mode = "RGBA" if has_alpha else "RGB"
        jittered = img.convert(output_mode)
        pixels = jittered.load()
        avoid_transparent = bool(jitter_config.get("avoid_transparent", True))
        changed = 0
        attempts = min(max(pixel_count * 10, 10), width * height)

        for _ in range(attempts):
            if changed >= pixel_count:
                break
            x = random.randrange(width)
            y = random.randrange(height)
            pixel = list(pixels[x, y])
            if has_alpha and avoid_transparent and pixel[3] == 0:
                continue

            channel = random.randrange(3)
            delta = random.randint(1, channel_delta) * random.choice((-1, 1))
            new_value = self._clamp_channel(pixel[channel] + delta)
            if new_value == pixel[channel]:
                continue
            pixel[channel] = new_value
            pixels[x, y] = tuple(pixel)
            changed += 1

        if changed <= 0:
            return img, False
        if self._log_detail():
            logger.info(
                "图片反风控：极轻微像素扰动 "
                f"[{width}x{height}], pixels={changed}, delta={channel_delta}"
            )
        return jittered, True

    def _should_apply_metadata_jitter(self, fmt: str) -> bool:
        if not self._metadata_jitter_enabled():
            return False
        metadata_config = self._metadata_jitter_config()
        if metadata_config.get("skip_gif", True) and fmt == "GIF":
            return False
        return fmt in {"JPEG", "JPG", "PNG", "WEBP"}

    def _save_image(
        self, img: Any, fmt: str, metadata_jitter: bool = False
    ) -> tuple[bytes, str]:
        output = io.BytesIO()
        save_kwargs = self._metadata_save_kwargs(fmt) if metadata_jitter else {}
        if fmt in {"JPEG", "JPG"}:
            self._jpeg_ready_image(img).save(
                output,
                format="JPEG",
                quality=95,
                optimize=True,
                progressive=True,
                **save_kwargs,
            )
            output_format = "JPEG"
        elif fmt == "PNG":
            img.save(output, format="PNG", optimize=True, **save_kwargs)
            output_format = "PNG"
        elif fmt == "WEBP":
            img.save(output, format="WEBP", quality=95, method=6)
            output_format = "WEBP"
        else:
            try:
                img.save(output, format=fmt)
                output_format = fmt
            except Exception:
                output = io.BytesIO()
                self._jpeg_ready_image(img).save(
                    output, format="JPEG", quality=95, optimize=True
                )
                output_format = "JPEG"
        return output.getvalue(), output_format

    def _metadata_save_kwargs(self, fmt: str) -> dict[str, Any]:
        metadata_config = self._metadata_jitter_config()
        if not metadata_config.get("random_comment", True):
            return {}

        token = f"iarc-{secrets.token_hex(8)}"
        if fmt in {"JPEG", "JPG"}:
            return {"comment": token.encode("ascii")}
        if fmt == "PNG" and PngImagePlugin is not None:
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_text("anti_rc", token)
            return {"pnginfo": pnginfo}
        return {}

    def _has_alpha(self, img: Any) -> bool:
        return img.mode in {"RGBA", "LA"} or (
            img.mode == "P" and "transparency" in getattr(img, "info", {})
        )

    def _clamp_channel(self, value: int) -> int:
        return max(0, min(255, int(value)))

    def _jpeg_ready_image(self, img: Any) -> Any:
        if img.mode in {"RGBA", "LA"}:
            background = PILImage.new("RGB", img.size, (255, 255, 255))
            alpha = img.split()[-1]
            background.paste(img.convert("RGBA"), mask=alpha)
            return background
        if img.mode == "P" or img.mode != "RGB":
            return img.convert("RGB")
        return img

    def _build_output_image(self, image_bytes: bytes, output_format: str) -> Any:
        output_mode = str(self.config.get("output_mode", "base64") or "base64")
        if output_mode == "temp_file":
            suffix = self._suffix_for_format(output_format)
            file_path = self._temp_dir / f"anti_rc_{uuid.uuid4().hex}{suffix}"
            file_path.write_bytes(image_bytes)
            self._tracked_temp_files.add(file_path)
            return Image.fromFileSystem(str(file_path))
        return Image.fromBytes(image_bytes)

    def _suffix_for_format(self, output_format: str) -> str:
        return {
            "JPEG": ".jpg",
            "JPG": ".jpg",
            "PNG": ".png",
            "WEBP": ".webp",
        }.get(output_format.upper(), ".jpg")
