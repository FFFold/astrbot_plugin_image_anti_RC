import hashlib
import io
import sys
import types
from pathlib import Path

import pytest
from PIL import Image as PILImage


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = [
    ROOT / "tests" / "test-image.jpg",
    ROOT / "tests" / "test-image.png",
    ROOT / "tests" / "test-image.webp",
]


class Config(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def _install_astrbot_stubs() -> None:
    astrbot = types.ModuleType("astrbot")
    astrbot_api = types.ModuleType("astrbot.api")
    astrbot_api_event = types.ModuleType("astrbot.api.event")
    astrbot_api_star = types.ModuleType("astrbot.api.star")
    astrbot_api_components = types.ModuleType("astrbot.api.message_components")
    astrbot_core = types.ModuleType("astrbot.core")
    astrbot_core_message = types.ModuleType("astrbot.core.message")
    astrbot_core_result = types.ModuleType("astrbot.core.message.message_event_result")
    astrbot_core_platform = types.ModuleType("astrbot.core.platform")
    astrbot_core_event = types.ModuleType("astrbot.core.platform.astr_message_event")

    class Logger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

    class AstrBotConfig(dict):
        pass

    class AstrMessageEvent:
        pass

    class MessageChain:
        def __init__(self, chain=None):
            self.chain = chain or []

    class Star:
        def __init__(self, context):
            self.context = context

    class Context:
        pass

    class Filter:
        def on_decorating_result(self, **_kwargs):
            def decorator(func):
                return func

            return decorator

    class Component:
        pass

    astrbot_api.AstrBotConfig = AstrBotConfig
    astrbot_api.logger = Logger()
    astrbot_api_event.AstrMessageEvent = AstrMessageEvent
    astrbot_api_event.filter = Filter()
    astrbot_api_star.Context = Context
    astrbot_api_star.Star = Star
    astrbot_api_components.Image = Component
    astrbot_api_components.Node = Component
    astrbot_api_components.Nodes = Component
    astrbot_core_result.MessageChain = MessageChain
    astrbot_core_event.AstrMessageEvent = AstrMessageEvent

    modules = {
        "astrbot": astrbot,
        "astrbot.api": astrbot_api,
        "astrbot.api.event": astrbot_api_event,
        "astrbot.api.star": astrbot_api_star,
        "astrbot.api.message_components": astrbot_api_components,
        "astrbot.core": astrbot_core,
        "astrbot.core.message": astrbot_core_message,
        "astrbot.core.message.message_event_result": astrbot_core_result,
        "astrbot.core.platform": astrbot_core_platform,
        "astrbot.core.platform.astr_message_event": astrbot_core_event,
    }
    sys.modules.update(modules)


@pytest.fixture(scope="module")
def plugin_class():
    _install_astrbot_stubs()
    sys.path.insert(0, str(ROOT))
    from main import ImageAntiRiskPlugin

    return ImageAntiRiskPlugin


@pytest.fixture(params=SAMPLES, ids=lambda path: path.suffix.removeprefix("."))
def sample_bytes(request):
    if not request.param.exists():
        pytest.skip(f"测试图片不存在：{request.param}")
    return request.param.read_bytes()


def _plugin(plugin_class, config):
    plugin = object.__new__(plugin_class)
    plugin.config = Config(config)
    return plugin


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _image_size(value: bytes) -> tuple[int, int]:
    with PILImage.open(io.BytesIO(value)) as img:
        return img.size


def test_no_enabled_strategy_keeps_original(plugin_class, sample_bytes):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {"enabled": False},
            "metadata_jitter": {"enabled": False},
            "random_border": {"enabled": False},
            "pixel_jitter": {"enabled": False},
        },
    )

    output, output_format = plugin._process_image_bytes(sample_bytes)

    assert output == sample_bytes
    assert output_format == ""


def test_metadata_jitter_changes_hash_without_changing_size(plugin_class, sample_bytes):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {"enabled": False},
            "metadata_jitter": {"enabled": True},
            "random_border": {"enabled": False},
            "pixel_jitter": {"enabled": False},
        },
    )

    output, output_format = plugin._process_image_bytes(sample_bytes)

    assert output_format in {"JPEG", "PNG", "WEBP"}
    assert _sha256(output) != _sha256(sample_bytes)
    assert _image_size(output) == _image_size(sample_bytes)


def test_random_border_changes_hash_and_expands_size(plugin_class, sample_bytes):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {"enabled": False},
            "metadata_jitter": {"enabled": False},
            "random_border": {
                "enabled": True,
                "max_border_px": 1,
                "side": "random_one",
                "min_image_side": 1,
            },
            "pixel_jitter": {"enabled": False},
        },
    )

    source_size = _image_size(sample_bytes)
    output, output_format = plugin._process_image_bytes(sample_bytes)
    output_size = _image_size(output)

    assert output_format in {"JPEG", "PNG", "WEBP"}
    assert _sha256(output) != _sha256(sample_bytes)
    assert tuple(sorted(output_size)) in {
        tuple(sorted((source_size[0] + 1, source_size[1]))),
        tuple(sorted((source_size[0], source_size[1] + 1))),
    }


def test_pixel_jitter_changes_hash_without_changing_size(plugin_class, sample_bytes):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {"enabled": False},
            "metadata_jitter": {"enabled": False},
            "random_border": {"enabled": False},
            "pixel_jitter": {
                "enabled": True,
                "pixel_count": 16,
                "channel_delta": 1,
                "min_image_side": 1,
            },
        },
    )

    output, output_format = plugin._process_image_bytes(sample_bytes)

    assert output_format in {"JPEG", "PNG", "WEBP"}
    assert _sha256(output) != _sha256(sample_bytes)
    assert _image_size(output) == _image_size(sample_bytes)


def test_enabled_strategies_run_in_internal_order(plugin_class):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {"enabled": True, "edge_crop_max": 1, "min_image_side": 1},
            "metadata_jitter": {"enabled": True},
            "random_border": {"enabled": True, "max_border_px": 1, "min_image_side": 1},
            "pixel_jitter": {"enabled": True, "pixel_count": 1, "min_image_side": 1},
        },
    )
    order = []

    original_crop = plugin._apply_random_edge_crop
    original_border = plugin._apply_random_border
    original_pixel = plugin._apply_pixel_jitter
    original_metadata = plugin._should_apply_metadata_jitter

    def crop(*args, **kwargs):
        order.append("random_edge_crop")
        return original_crop(*args, **kwargs)

    def border(*args, **kwargs):
        order.append("random_border")
        return original_border(*args, **kwargs)

    def pixel(*args, **kwargs):
        order.append("pixel_jitter")
        return original_pixel(*args, **kwargs)

    def metadata(*args, **kwargs):
        order.append("metadata_jitter")
        return original_metadata(*args, **kwargs)

    plugin._apply_random_edge_crop = crop
    plugin._apply_random_border = border
    plugin._apply_pixel_jitter = pixel
    plugin._should_apply_metadata_jitter = metadata

    sample = ROOT / "tests" / "test-image.png"
    if not sample.exists():
        pytest.skip(f"测试图片不存在：{sample}")

    plugin._process_image_bytes(sample.read_bytes())

    assert order == [
        "random_edge_crop",
        "random_border",
        "pixel_jitter",
        "metadata_jitter",
    ]


def _make_animated_gif_bytes() -> bytes:
    base = PILImage.new("RGBA", (48, 32), (80, 120, 160, 255))
    frames = [base.rotate(angle, expand=False) for angle in (0, 15, 30)]
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=100,
    )
    return buf.getvalue()


def test_animated_gif_skipped_when_all_strategies_enabled(plugin_class):
    gif_bytes = _make_animated_gif_bytes()
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {"enabled": True, "edge_crop_max": 2, "min_image_side": 1},
            "metadata_jitter": {"enabled": True},
            "random_border": {"enabled": True, "max_border_px": 1, "min_image_side": 1},
            "pixel_jitter": {"enabled": True, "pixel_count": 4, "min_image_side": 1},
        },
    )

    output, output_format = plugin._process_image_bytes(gif_bytes)

    assert output == gif_bytes
    assert output_format == ""


def test_random_edge_crop_reduces_size(plugin_class):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {
                "enabled": True,
                "edge_crop_max": 2,
                "max_crop_ratio": 0.1,
                "min_image_side": 1,
            },
            "metadata_jitter": {"enabled": False},
            "random_border": {"enabled": False},
            "pixel_jitter": {"enabled": False},
        },
    )
    sample = ROOT / "tests" / "test-image.png"
    if not sample.exists():
        pytest.skip(f"测试图片不存在：{sample}")
    input_bytes = sample.read_bytes()
    orig_width, orig_height = _image_size(input_bytes)

    output, output_format = plugin._process_image_bytes(input_bytes)
    new_width, new_height = _image_size(output)

    assert output_format == "PNG"
    assert new_width <= orig_width
    assert new_height <= orig_height
    assert new_width >= 10
    assert new_height >= 10


def test_random_edge_crop_edge_crop_max_zero_noop(plugin_class, sample_bytes):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {
                "enabled": True,
                "edge_crop_max": 0,
                "max_crop_ratio": 0.1,
                "min_image_side": 1,
            },
            "metadata_jitter": {"enabled": False},
            "random_border": {"enabled": False},
            "pixel_jitter": {"enabled": False},
        },
    )

    output, output_format = plugin._process_image_bytes(sample_bytes)

    assert output == sample_bytes
    assert output_format == ""


def test_random_edge_crop_small_image_skipped(plugin_class):
    img = PILImage.new("RGB", (4, 4), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    tiny_bytes = buf.getvalue()

    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {
                "enabled": True,
                "edge_crop_max": 10,
                "max_crop_ratio": 0.5,
                "min_image_side": 8,
            },
            "metadata_jitter": {"enabled": False},
            "random_border": {"enabled": False},
            "pixel_jitter": {"enabled": False},
        },
    )

    output, output_format = plugin._process_image_bytes(tiny_bytes)

    assert output == tiny_bytes
    assert output_format == ""


def test_pixel_jitter_avoid_transparent_true_no_change(plugin_class):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {"enabled": False},
            "metadata_jitter": {"enabled": False},
            "random_border": {"enabled": False},
            "pixel_jitter": {
                "enabled": True,
                "pixel_count": 16,
                "channel_delta": 2,
                "avoid_transparent": True,
                "min_image_side": 1,
            },
        },
    )
    img = PILImage.new("RGBA", (8, 8), (10, 20, 30, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    transparent_bytes = buf.getvalue()

    output, output_format = plugin._process_image_bytes(transparent_bytes)

    assert output == transparent_bytes
    assert output_format == ""


def test_pixel_jitter_avoid_transparent_false_changes_pixels(plugin_class):
    plugin = _plugin(
        plugin_class,
        {
            "random_edge_crop": {"enabled": False},
            "metadata_jitter": {"enabled": False},
            "random_border": {"enabled": False},
            "pixel_jitter": {
                "enabled": True,
                "pixel_count": 16,
                "channel_delta": 2,
                "avoid_transparent": False,
                "min_image_side": 1,
            },
        },
    )
    img = PILImage.new("RGBA", (8, 8), (10, 20, 30, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    transparent_bytes = buf.getvalue()

    output, output_format = plugin._process_image_bytes(transparent_bytes)

    assert output_format == "PNG"
    assert _sha256(output) != _sha256(transparent_bytes)
