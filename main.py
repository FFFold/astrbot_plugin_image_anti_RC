import base64
import io
import random
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
    from PIL import ImageOps
except ImportError:  # pragma: no cover
    PILImage = None
    ImageOps = None


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
            f"random_edge_crop={self._random_edge_crop_enabled()}"
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

    def _enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def _capture_config(self) -> dict[str, Any]:
        value = self.config.get("capture", {})
        return value if isinstance(value, dict) else {}

    def _random_edge_crop_config(self) -> dict[str, Any]:
        value = self.config.get("random_edge_crop", {})
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
                        f"图片反风控：主动发送图片处理失败，使用原消息链 - {exc}"
                    )
            return await self._original_send_message(session, message_chain)

        setattr(wrapped_send_message, "_image_anti_rc_owner", id(self))
        self.context.send_message = wrapped_send_message
        self._send_message_patched = True
        logger.info("图片反风控：已启用 context.send_message 主动发送处理。")

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
                            f"图片反风控：event.send 图片处理失败，使用原消息链 - {exc}"
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
                logger.warning(f"图片反风控：消息段处理失败，保留原消息段 - {exc}")
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

        if not self._random_edge_crop_enabled():
            return component

        try:
            raw_base64 = await component.convert_to_base64()
            image_bytes = base64.b64decode(raw_base64)
            output_bytes, output_format = self._apply_random_edge_crop(image_bytes)
            if output_bytes is image_bytes:
                return component
            return self._build_output_image(output_bytes, output_format)
        except Exception as exc:
            logger.warning(f"图片反风控：图片处理失败，使用原图 - {exc}")
            return component

    def _apply_random_edge_crop(self, image_bytes: bytes) -> tuple[bytes, str]:
        crop_config = self._random_edge_crop_config()
        edge_crop_max = int(crop_config.get("edge_crop_max", 2) or 0)
        if edge_crop_max <= 0:
            return image_bytes, ""

        with io.BytesIO(image_bytes) as input_buffer:
            with PILImage.open(input_buffer) as img:
                fmt = (img.format or "JPEG").upper()
                if crop_config.get("skip_gif", True) and fmt == "GIF":
                    return image_bytes, ""
                if getattr(img, "is_animated", False):
                    return image_bytes, ""

                img = ImageOps.exif_transpose(img)
                width, height = img.size
                min_side = int(crop_config.get("min_image_side", 80) or 1)
                if width < min_side or height < min_side:
                    return image_bytes, ""

                max_crop_ratio = float(crop_config.get("max_crop_ratio", 0.02) or 0)
                max_allowed_total = int(min(width, height) * max_crop_ratio)
                max_per_side = min(edge_crop_max, max_allowed_total // 2)
                if max_per_side <= 0:
                    return image_bytes, ""

                top = random.randint(0, max_per_side)
                bottom = random.randint(0, max_per_side)
                left = random.randint(0, max_per_side)
                right = random.randint(0, max_per_side)
                if top == bottom == left == right == 0:
                    top = 1

                new_width = width - left - right
                new_height = height - top - bottom
                if new_width <= 10 or new_height <= 10:
                    return image_bytes, ""

                cropped = img.crop((left, top, width - right, height - bottom))
                if self._log_detail():
                    logger.info(
                        "图片反风控：四边随机裁剪 "
                        f"[{width}x{height}] -> [{new_width}x{new_height}], "
                        f"T:{top} B:{bottom} L:{left} R:{right}"
                    )
                return self._save_image(cropped, fmt)

    def _save_image(self, img: Any, fmt: str) -> tuple[bytes, str]:
        output = io.BytesIO()
        if fmt in {"JPEG", "JPG"}:
            self._jpeg_ready_image(img).save(
                output,
                format="JPEG",
                quality=95,
                optimize=True,
                progressive=True,
            )
            output_format = "JPEG"
        elif fmt == "PNG":
            img.save(output, format="PNG", optimize=True)
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
            return Image.fromFileSystem(str(file_path))
        return Image.fromBytes(image_bytes)

    def _suffix_for_format(self, output_format: str) -> str:
        return {
            "JPEG": ".jpg",
            "JPG": ".jpg",
            "PNG": ".png",
            "WEBP": ".webp",
        }.get(output_format.upper(), ".jpg")
