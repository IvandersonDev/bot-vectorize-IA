import asyncio
import json
import logging
import math
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

import vtracer
from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import TelegramError, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", encoding="utf-8-sig", override=True)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("telegram-vectorizer-bot")


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Valor invalido para %s=%r. Usando %s.", name, value, default)
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Valor invalido para %s=%r. Usando %s.", name, value, default)
        return default


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if not value:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "sim", "on"}:
        return True
    if normalized in {"0", "false", "no", "nao", "não", "off"}:
        return False

    logger.warning("Valor invalido para %s=%r. Usando %s.", name, value, default)
    return default


def env_path(name: str, default: str) -> Path:
    value = os.getenv(name, default).strip() or default
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_MAX_FILE_MB = env_int("TELEGRAM_MAX_FILE_MB", 20)
MAX_FILE_BYTES = TELEGRAM_MAX_FILE_MB * 1024 * 1024
TELEGRAM_TIMEOUT_SECONDS = env_float("TELEGRAM_TIMEOUT_SECONDS", 180.0)
VECTORIZATION_PROVIDER = os.getenv("VECTORIZATION_PROVIDER", "vectorizer_ai").strip().lower()
if VECTORIZATION_PROVIDER not in {"vectorizer_ai", "local"}:
    logger.warning(
        "Provedor invalido VECTORIZATION_PROVIDER=%r. Usando vectorizer_ai.",
        VECTORIZATION_PROVIDER,
    )
    VECTORIZATION_PROVIDER = "vectorizer_ai"

OUTPUT_FORMAT = os.getenv("OUTPUT_FORMAT", "eps").strip().lower()
if OUTPUT_FORMAT not in {"eps", "svg", "pdf", "dxf", "png"}:
    logger.warning("Formato invalido OUTPUT_FORMAT=%r. Usando eps.", OUTPUT_FORMAT)
    OUTPUT_FORMAT = "eps"
OUTPUT_LABEL = OUTPUT_FORMAT.upper()

VECTORIZER_AI_URL = os.getenv("VECTORIZER_AI_URL", "https://pt.vectorizer.ai/").strip()
VECTORIZER_AI_HEADLESS = env_bool("VECTORIZER_AI_HEADLESS", True)
VECTORIZER_AI_PROFILE_DIR = env_path("VECTORIZER_AI_PROFILE_DIR", ".vectorizer-ai-profile")
VECTORIZER_AI_TIMEOUT_SECONDS = env_float("VECTORIZER_AI_TIMEOUT_SECONDS", 300.0)
VECTORIZER_AI_LOGIN_SECONDS = env_float("VECTORIZER_AI_LOGIN_SECONDS", 300.0)
VECTORIZER_AI_INPUT_MAX_PIXELS = env_int("VECTORIZER_AI_INPUT_MAX_PIXELS", 3_000_000)
VECTORIZER_AI_OFFSCREEN_PROCESSING = env_bool("VECTORIZER_AI_OFFSCREEN_PROCESSING", True)
VECTORIZER_AI_FINAL_DOWNLOAD_DELAY_SECONDS = env_float(
    "VECTORIZER_AI_FINAL_DOWNLOAD_DELAY_SECONDS",
    5.0,
)
VECTORIZER_AI_DIRECT_DOWNLOAD_TIMEOUT_SECONDS = env_float(
    "VECTORIZER_AI_DIRECT_DOWNLOAD_TIMEOUT_SECONDS",
    90.0,
)
VECTORIZER_AI_DOWNLOAD_LINK_TIMEOUT_SECONDS = env_float(
    "VECTORIZER_AI_DOWNLOAD_LINK_TIMEOUT_SECONDS",
    90.0,
)
VECTORIZER_AI_VERBOSE_LOGS = env_bool("VECTORIZER_AI_VERBOSE_LOGS", True)
VECTORIZER_AI_NETWORK_ERROR_TIMEOUT_SECONDS = env_float(
    "VECTORIZER_AI_NETWORK_ERROR_TIMEOUT_SECONDS",
    45.0,
)
PLAYWRIGHT_AUTO_INSTALL = env_bool("PLAYWRIGHT_AUTO_INSTALL", True)
VECTORIZER_AI_COOKIE_NAME = os.getenv("VECTORIZER_AI_COOKIE_NAME", "VK").strip() or "VK"
VECTORIZER_AI_COOKIE_VALUE = os.getenv("VECTORIZER_AI_COOKIE_VALUE", "").strip()
VECTORIZER_AI_COOKIE_DOMAIN = (
    os.getenv("VECTORIZER_AI_COOKIE_DOMAIN", ".vectorizer.ai").strip()
    or ".vectorizer.ai"
)
VECTORIZER_AI_COOKIE_HEADER = os.getenv("VECTORIZER_AI_COOKIE_HEADER", "").strip()
VECTORIZER_AI_COOKIES_JSON = os.getenv("VECTORIZER_AI_COOKIES_JSON", "").strip()
VECTORIZER_AI_COOKIES_FILE = os.getenv("VECTORIZER_AI_COOKIES_FILE", "").strip()
VECTORIZER_AI_LOCK = threading.Lock()

VTRACER_INPUT_MAX_PIXELS = env_int("VTRACER_INPUT_MAX_PIXELS", 6_000_000)
VTRACER_COLORMODE = os.getenv("VTRACER_COLORMODE", "color")
VTRACER_HIERARCHICAL = os.getenv("VTRACER_HIERARCHICAL", "stacked")
VTRACER_MODE = os.getenv("VTRACER_MODE", "spline")
VTRACER_FILTER_SPECKLE = env_int("VTRACER_FILTER_SPECKLE", 4)
VTRACER_COLOR_PRECISION = env_int("VTRACER_COLOR_PRECISION", 6)
VTRACER_LAYER_DIFFERENCE = env_int("VTRACER_LAYER_DIFFERENCE", 16)
VTRACER_CORNER_THRESHOLD = env_int("VTRACER_CORNER_THRESHOLD", 60)
VTRACER_LENGTH_THRESHOLD = env_float("VTRACER_LENGTH_THRESHOLD", 4.0)
VTRACER_MAX_ITERATIONS = env_int("VTRACER_MAX_ITERATIONS", 10)
VTRACER_SPLICE_THRESHOLD = env_int("VTRACER_SPLICE_THRESHOLD", 45)
VTRACER_PATH_PRECISION = env_int("VTRACER_PATH_PRECISION", 3)
PATH_TOKEN_RE = re.compile(
    r"[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
)


def image_suffix(file_name: str | None, mime_type: str | None) -> str:
    if file_name:
        suffix = Path(file_name).suffix.lower()
        if suffix:
            return suffix

    if mime_type:
        suffix = mimetypes.guess_extension(mime_type)
        if suffix:
            return suffix

    return ".jpg"


def prepare_input_image(input_path: Path, output_path: Path, max_pixels: int | None = None) -> None:
    with Image.open(input_path) as image:
        image = ImageOps.exif_transpose(image)

        max_pixels = max_pixels or VTRACER_INPUT_MAX_PIXELS
        pixels = image.width * image.height
        if pixels > max_pixels:
            scale = math.sqrt(max_pixels / pixels)
            new_size = (
                max(1, int(image.width * scale)),
                max(1, int(image.height * scale)),
            )
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        if image.mode in {"RGBA", "LA"}:
            image = image.convert("RGBA")
        else:
            image = image.convert("RGB")

        image.save(output_path, format="PNG")


def vectorize_image(input_path: Path, output_path: Path) -> None:
    vtracer.convert_image_to_svg_py(
        str(input_path),
        str(output_path),
        colormode=VTRACER_COLORMODE,
        hierarchical=VTRACER_HIERARCHICAL,
        mode=VTRACER_MODE,
        filter_speckle=VTRACER_FILTER_SPECKLE,
        color_precision=VTRACER_COLOR_PRECISION,
        layer_difference=VTRACER_LAYER_DIFFERENCE,
        corner_threshold=VTRACER_CORNER_THRESHOLD,
        length_threshold=VTRACER_LENGTH_THRESHOLD,
        max_iterations=VTRACER_MAX_ITERATIONS,
        splice_threshold=VTRACER_SPLICE_THRESHOLD,
        path_precision=VTRACER_PATH_PRECISION,
    )


def describe_image_file(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    try:
        with Image.open(path) as image:
            return f"{path.name} ({image.width}x{image.height}px, {size} bytes)"
    except Exception:
        return f"{path.name} ({size} bytes)"


def parse_svg_number(value: str | None) -> float:
    if not value:
        return 0.0
    match = re.search(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", value)
    return float(match.group(0)) if match else 0.0


def parse_color(value: str | None) -> tuple[float, float, float] | None:
    if not value or value.lower() == "none":
        return None

    value = value.strip()
    if value.startswith("#"):
        hex_value = value[1:]
        if len(hex_value) == 3:
            hex_value = "".join(part * 2 for part in hex_value)
        if len(hex_value) == 6:
            red = int(hex_value[0:2], 16) / 255
            green = int(hex_value[2:4], 16) / 255
            blue = int(hex_value[4:6], 16) / 255
            return red, green, blue

    rgb_match = re.match(r"rgb\(([^)]+)\)", value, re.IGNORECASE)
    if rgb_match:
        parts = [part.strip() for part in rgb_match.group(1).split(",")]
        if len(parts) == 3:
            channels = []
            for part in parts:
                if part.endswith("%"):
                    channels.append(float(part[:-1]) / 100)
                else:
                    channels.append(float(part) / 255)
            return tuple(max(0, min(1, channel)) for channel in channels)

    return 0.0, 0.0, 0.0


def svg_path_to_postscript(path_data: str) -> list[str]:
    tokens = PATH_TOKEN_RE.findall(path_data)
    lines: list[str] = []
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    last_cubic_control: tuple[float, float] | None = None
    last_quad_control: tuple[float, float] | None = None

    def is_command(token: str) -> bool:
        return len(token) == 1 and token.isalpha()

    def has_number() -> bool:
        return index < len(tokens) and not is_command(tokens[index])

    def read_number() -> float:
        nonlocal index
        if index >= len(tokens) or is_command(tokens[index]):
            raise ValueError(f"Path SVG invalido perto do token {index}.")
        number = float(tokens[index])
        index += 1
        return number

    while index < len(tokens):
        if is_command(tokens[index]):
            command = tokens[index]
            index += 1
        elif not command:
            raise ValueError("Path SVG sem comando inicial.")

        lower_command = command.lower()
        relative = command.islower()

        if lower_command == "z":
            lines.append("closepath")
            current = start
            last_cubic_control = None
            last_quad_control = None
            command = ""
            continue

        if lower_command == "m":
            first_point = True
            while has_number():
                x = read_number()
                y = read_number()
                if relative:
                    x += current[0]
                    y += current[1]

                if first_point:
                    lines.append(f"{x:.4f} {y:.4f} moveto")
                    start = (x, y)
                    first_point = False
                else:
                    lines.append(f"{x:.4f} {y:.4f} lineto")

                current = (x, y)
                last_cubic_control = None
                last_quad_control = None

            command = "l" if relative else "L"
            continue

        if lower_command == "l":
            while has_number():
                x = read_number()
                y = read_number()
                if relative:
                    x += current[0]
                    y += current[1]
                lines.append(f"{x:.4f} {y:.4f} lineto")
                current = (x, y)
                last_cubic_control = None
                last_quad_control = None
            continue

        if lower_command == "h":
            while has_number():
                x = read_number()
                if relative:
                    x += current[0]
                y = current[1]
                lines.append(f"{x:.4f} {y:.4f} lineto")
                current = (x, y)
                last_cubic_control = None
                last_quad_control = None
            continue

        if lower_command == "v":
            while has_number():
                x = current[0]
                y = read_number()
                if relative:
                    y += current[1]
                lines.append(f"{x:.4f} {y:.4f} lineto")
                current = (x, y)
                last_cubic_control = None
                last_quad_control = None
            continue

        if lower_command == "c":
            while has_number():
                x1 = read_number()
                y1 = read_number()
                x2 = read_number()
                y2 = read_number()
                x = read_number()
                y = read_number()
                if relative:
                    x1 += current[0]
                    y1 += current[1]
                    x2 += current[0]
                    y2 += current[1]
                    x += current[0]
                    y += current[1]
                lines.append(f"{x1:.4f} {y1:.4f} {x2:.4f} {y2:.4f} {x:.4f} {y:.4f} curveto")
                current = (x, y)
                last_cubic_control = (x2, y2)
                last_quad_control = None
            continue

        if lower_command == "s":
            while has_number():
                if last_cubic_control:
                    x1 = 2 * current[0] - last_cubic_control[0]
                    y1 = 2 * current[1] - last_cubic_control[1]
                else:
                    x1, y1 = current
                x2 = read_number()
                y2 = read_number()
                x = read_number()
                y = read_number()
                if relative:
                    x2 += current[0]
                    y2 += current[1]
                    x += current[0]
                    y += current[1]
                lines.append(f"{x1:.4f} {y1:.4f} {x2:.4f} {y2:.4f} {x:.4f} {y:.4f} curveto")
                current = (x, y)
                last_cubic_control = (x2, y2)
                last_quad_control = None
            continue

        if lower_command == "q":
            while has_number():
                qx = read_number()
                qy = read_number()
                x = read_number()
                y = read_number()
                if relative:
                    qx += current[0]
                    qy += current[1]
                    x += current[0]
                    y += current[1]

                x1 = current[0] + (2 / 3) * (qx - current[0])
                y1 = current[1] + (2 / 3) * (qy - current[1])
                x2 = x + (2 / 3) * (qx - x)
                y2 = y + (2 / 3) * (qy - y)
                lines.append(f"{x1:.4f} {y1:.4f} {x2:.4f} {y2:.4f} {x:.4f} {y:.4f} curveto")
                current = (x, y)
                last_quad_control = (qx, qy)
                last_cubic_control = None
            continue

        if lower_command == "t":
            while has_number():
                if last_quad_control:
                    qx = 2 * current[0] - last_quad_control[0]
                    qy = 2 * current[1] - last_quad_control[1]
                else:
                    qx, qy = current
                x = read_number()
                y = read_number()
                if relative:
                    x += current[0]
                    y += current[1]

                x1 = current[0] + (2 / 3) * (qx - current[0])
                y1 = current[1] + (2 / 3) * (qy - current[1])
                x2 = x + (2 / 3) * (qx - x)
                y2 = y + (2 / 3) * (qy - y)
                lines.append(f"{x1:.4f} {y1:.4f} {x2:.4f} {y2:.4f} {x:.4f} {y:.4f} curveto")
                current = (x, y)
                last_quad_control = (qx, qy)
                last_cubic_control = None
            continue

        raise ValueError(f"Comando SVG nao suportado para EPS: {command}")

    return lines


def transform_to_postscript(transform: str | None) -> list[str]:
    if not transform:
        return []

    lines: list[str] = []
    for name, values in re.findall(r"([a-zA-Z]+)\(([^)]*)\)", transform):
        numbers = [float(value) for value in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", values)]
        name = name.lower()
        if name == "translate" and numbers:
            x = numbers[0]
            y = numbers[1] if len(numbers) > 1 else 0
            lines.append(f"{x:.4f} {y:.4f} translate")
        elif name == "scale" and numbers:
            x = numbers[0]
            y = numbers[1] if len(numbers) > 1 else x
            lines.append(f"{x:.4f} {y:.4f} scale")
        elif name == "matrix" and len(numbers) == 6:
            a, b, c, d, e, f = numbers
            lines.append(f"[{a:.4f} {b:.4f} {c:.4f} {d:.4f} {e:.4f} {f:.4f}] concat")
        else:
            raise ValueError(f"Transform SVG nao suportado para EPS: {name}")

    return lines


def convert_svg_to_eps(svg_path: Path, eps_path: Path) -> None:
    root = ET.parse(svg_path).getroot()
    width = parse_svg_number(root.attrib.get("width"))
    height = parse_svg_number(root.attrib.get("height"))

    view_box = root.attrib.get("viewBox")
    if (not width or not height) and view_box:
        values = [float(value) for value in view_box.replace(",", " ").split()]
        if len(values) == 4:
            width = values[2]
            height = values[3]

    if width <= 0 or height <= 0:
        raise RuntimeError("SVG gerado sem largura/altura validas para EPS.")

    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"

    lines = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%BoundingBox: 0 0 {math.ceil(width)} {math.ceil(height)}",
        "%%Pages: 1",
        "%%EndComments",
        "gsave",
        f"1 -1 scale 0 {-height:.4f} translate",
    ]

    path_count = 0
    for element in root.iter(f"{namespace}path"):
        path_data = element.attrib.get("d", "").strip()
        color = parse_color(element.attrib.get("fill"))
        if not path_data or color is None:
            continue

        path_lines = svg_path_to_postscript(path_data)
        if not path_lines:
            continue

        red, green, blue = color
        lines.extend(
            [
                "gsave",
                *transform_to_postscript(element.attrib.get("transform")),
                f"{red:.6f} {green:.6f} {blue:.6f} setrgbcolor",
                "newpath",
                *path_lines,
                "fill",
                "grestore",
            ]
        )
        path_count += 1

    if path_count == 0:
        raise RuntimeError("SVG gerado sem paths preenchidos para converter em EPS.")

    lines.extend(["grestore", "showpage", "%%EOF", ""])
    eps_path.write_text("\n".join(lines), encoding="latin1")


def launch_vectorizer_ai_context(playwright, *, login: bool = False):
    VECTORIZER_AI_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    if not login and VECTORIZER_AI_OFFSCREEN_PROCESSING and not VECTORIZER_AI_HEADLESS:
        args.extend(["--window-position=-32000,-32000", "--window-size=1280,900"])

    context_options = {
        "user_data_dir": str(VECTORIZER_AI_PROFILE_DIR),
        "headless": VECTORIZER_AI_HEADLESS,
        "accept_downloads": True,
        "viewport": {"width": 1280, "height": 900},
        "locale": "pt-BR",
        "args": args,
    }

    logger.info(
        "Vectorizer.AI: abrindo Chromium (headless=%s, login=%s, perfil=%s, url=%s).",
        VECTORIZER_AI_HEADLESS,
        login,
        VECTORIZER_AI_PROFILE_DIR,
        VECTORIZER_AI_URL,
    )
    if VECTORIZER_AI_VERBOSE_LOGS:
        logger.info(
            "Vectorizer.AI: timeouts result=%.1fs, login=%.1fs, "
            "download_link=%.1fs, direct_download=%.1fs; output=%s.",
            VECTORIZER_AI_TIMEOUT_SECONDS,
            VECTORIZER_AI_LOGIN_SECONDS,
            VECTORIZER_AI_DOWNLOAD_LINK_TIMEOUT_SECONDS,
            VECTORIZER_AI_DIRECT_DOWNLOAD_TIMEOUT_SECONDS,
            OUTPUT_LABEL,
        )

    try:
        return playwright.chromium.launch_persistent_context(**context_options)
    except PlaywrightError as exc:
        if not PLAYWRIGHT_AUTO_INSTALL or not is_playwright_browser_missing(exc):
            raise

        install_playwright_chromium()
        return playwright.chromium.launch_persistent_context(**context_options)


def save_vectorizer_ai_debug(page, prefix: str) -> None:
    debug_dir = BASE_DIR / "logs" / "vectorizer-ai-debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_prefix = re.sub(r"[^a-zA-Z0-9_.-]+", "-", prefix).strip("-") or "debug"
    base_path = debug_dir / f"{stamp}-{safe_prefix}"
    html_path = base_path.with_suffix(".html")
    screenshot_path = base_path.with_suffix(".png")

    try:
        html_path.write_text(page.content(), encoding="utf-8")
        logger.info("Debug Vectorizer.AI salvo: %s", html_path)
    except Exception:
        logger.exception("Nao consegui salvar HTML de debug do Vectorizer.AI.")

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        logger.info("Screenshot Vectorizer.AI salvo: %s", screenshot_path)
    except Exception:
        logger.exception("Nao consegui salvar screenshot de debug do Vectorizer.AI.")


def compact_log_text(value: str, limit: int = 700) -> str:
    compacted = re.sub(r"\s+", " ", value or "").strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."


def extract_vectorizer_ai_error_text(page) -> str:
    try:
        text = page.evaluate(
            """
            () => {
                const selectors = [
                    '#RetryDialog-Dialog',
                    '#App-Error-Dialog',
                    '[role="dialog"]',
                    '.modal',
                    '.alert',
                    '.error',
                    '.Error',
                    '.text-danger',
                    '.TaskStatus',
                    '.TaskStatus-error'
                ];
                const parts = [];
                for (const selector of selectors) {
                    for (const element of document.querySelectorAll(selector)) {
                        const style = window.getComputedStyle(element);
                        const box = element.getBoundingClientRect();
                        const visible = style.display !== 'none' &&
                            style.visibility !== 'hidden' &&
                            box.width > 0 &&
                            box.height > 0;
                        const text = (element.innerText || element.textContent || '').trim();
                        if (visible && text) {
                            parts.push(text);
                        }
                    }
                }
                return Array.from(new Set(parts)).join(' | ');
            }
            """
        )
    except PlaywrightError:
        text = ""

    if text:
        return compact_log_text(text)

    try:
        body_text = page.locator("body").inner_text(timeout=1_000)
    except PlaywrightError:
        return ""

    markers = [
        "Erro de rede",
        "Tarefa\tErro",
        "Network Error",
        "Connect to worker",
        "Unable to connect to the worker",
        "Failed to connect to the server",
        "Muitas solicita",
        "Too many",
        "slow down",
    ]
    for marker in markers:
        index = body_text.find(marker)
        if index >= 0:
            start = max(0, index - 220)
            end = min(len(body_text), index + 500)
            return compact_log_text(body_text[start:end])

    return compact_log_text(body_text)


def click_vectorizer_ai_retry(page) -> bool:
    selectors = [
        "#RetryDialog-RetryNowButton",
        "#App-Error-Dialog button",
        "[role='dialog'] button:has-text('Tentar novamente')",
        "[role='dialog'] button:has-text('Tente novamente')",
        "[role='dialog'] button:has-text('Retry')",
        "[role='dialog'] button:has-text('Try again')",
        "button:has-text('Tentar novamente')",
        "button:has-text('Tente novamente')",
        "button:has-text('Retry')",
        "button:has-text('Try again')",
        "a:has-text('Tentar novamente')",
        "a:has-text('Tente novamente')",
        "a:has-text('Retry')",
        "a:has-text('Try again')",
    ]

    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except PlaywrightError:
            continue

        if count == 0:
            continue

        logger.info(
            "Vectorizer.AI: candidato de retry encontrado (%s elemento[s]): %s",
            count,
            selector,
        )
        for index in range(count):
            target = locator.nth(index)
            try:
                if not target.is_visible(timeout=300):
                    continue
                target.click(timeout=1_500)
                logger.info("Vectorizer.AI: cliquei no retry com seletor: %s", selector)
                return True
            except PlaywrightError:
                continue

    logger.info("Vectorizer.AI: nenhum botao de retry visivel encontrado.")
    return False


def log_vectorizer_ai_state(page, stage: str) -> None:
    if not VECTORIZER_AI_VERBOSE_LOGS:
        return

    try:
        if page.is_closed():
            logger.info("Vectorizer.AI[%s]: pagina fechada.", stage)
            return
    except PlaywrightError:
        logger.info("Vectorizer.AI[%s]: nao consegui ler estado da pagina.", stage)
        return

    try:
        page_count = len(page.context.pages)
    except PlaywrightError:
        page_count = -1

    try:
        url = page.url
    except PlaywrightError:
        url = "<sem-url>"

    try:
        title = page.title()
    except PlaywrightError:
        title = "<sem-title>"

    download_count = 0
    download_visible = False
    download_href = None
    try:
        download_link = page.locator("#App-DownloadLink")
        download_count = download_link.count()
        if download_count > 0:
            first_download = download_link.first
            download_visible = first_download.is_visible(timeout=500)
            download_href = first_download.get_attribute("href", timeout=500)
    except PlaywrightError:
        pass

    href_state = "ausente"
    if download_href:
        href_state = "tokenizado" if normalize_vectorizer_ai_download_url(page, download_href) else download_href[:80]

    file_inputs = 0
    try:
        file_inputs = page.locator('input[type="file"]').count()
    except PlaywrightError:
        pass

    markers = []
    try:
        body_text = page.locator("body").inner_text(timeout=1_000)
        marker_checks = [
            ("login", "Fazer login" in body_text or "Login" in body_text),
            ("criar-conta", "Criar conta" in body_text),
            ("download", "DOWNLOAD" in body_text or "Download" in body_text),
            ("formato", "File Format" in body_text or "Formato" in body_text),
            (OUTPUT_LABEL, OUTPUT_LABEL in body_text),
            ("erro-rede", "Erro de rede" in body_text or "Network Error" in body_text),
            ("muitas-solicitacoes", "Muitas solicita" in body_text or "Too many" in body_text),
            ("bem-vindo", "Welcome" in body_text or "Bem-vindo" in body_text),
        ]
        markers = [name for name, present in marker_checks if present]
    except PlaywrightError:
        markers = ["body-indisponivel"]

    logger.info(
        "Vectorizer.AI[%s]: url=%s | titulo=%s | paginas=%s | "
        "file_inputs=%s | download_link=%s visivel=%s href=%s | marcadores=%s",
        stage,
        url,
        title,
        page_count,
        file_inputs,
        download_count,
        download_visible,
        href_state,
        ",".join(markers) if markers else "-",
    )


def is_playwright_target_closed(error: Exception) -> bool:
    message = str(error).lower()
    return "target page" in message and "closed" in message


def is_playwright_browser_missing(error: Exception) -> bool:
    message = str(error).lower()
    return "executable doesn't exist" in message and "playwright install" in message


def install_playwright_chromium() -> None:
    logger.info("Chromium do Playwright nao encontrado; instalando navegador.")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
        )
    except Exception as exc:
        raise RuntimeError(
            "Nao consegui executar 'python -m playwright install chromium' "
            "no ambiente de hospedagem."
        ) from exc

    if result.returncode != 0:
        output = (result.stdout or "").strip()
        raise RuntimeError(
            "Nao consegui instalar o Chromium do Playwright. "
            f"Saida: {output[-1000:]}"
        )

    logger.info("Chromium do Playwright instalado.")


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            cookies[name] = value
    return cookies


def load_cookie_payload(raw_payload: str, source: str) -> list[dict[str, object]]:
    if not raw_payload:
        return []

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        logger.warning("Cookies JSON do Vectorizer.AI invalidos em %s: %s", source, exc)
        return []

    if isinstance(payload, dict):
        payload = payload.get("cookies", [])

    if not isinstance(payload, list):
        logger.warning("Cookies JSON do Vectorizer.AI em %s nao e uma lista.", source)
        return []

    cookies = []
    for cookie in payload:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name", "")).strip()
        value = str(cookie.get("value", "")).strip()
        if not name or not value:
            continue

        normalized = {
            "name": name,
            "value": value,
            "path": str(cookie.get("path") or "/"),
            "secure": bool(cookie.get("secure", True)),
            "httpOnly": bool(cookie.get("httpOnly", name.lower() in {"vk", "atk"})),
            "sameSite": cookie.get("sameSite") or "Lax",
        }

        if cookie.get("domain"):
            normalized["domain"] = str(cookie["domain"])
        elif cookie.get("url"):
            normalized["url"] = str(cookie["url"])
        else:
            normalized["domain"] = VECTORIZER_AI_COOKIE_DOMAIN

        if cookie.get("expires") not in {None, -1}:
            try:
                normalized["expires"] = float(cookie["expires"])
            except (TypeError, ValueError):
                pass

        cookies.append(normalized)

    return cookies


def vectorizer_ai_json_cookies_from_env() -> list[dict[str, object]]:
    cookies = load_cookie_payload(VECTORIZER_AI_COOKIES_JSON, "VECTORIZER_AI_COOKIES_JSON")

    if VECTORIZER_AI_COOKIES_FILE:
        cookie_path = Path(VECTORIZER_AI_COOKIES_FILE)
        if not cookie_path.is_absolute():
            cookie_path = BASE_DIR / cookie_path
        try:
            cookies.extend(
                load_cookie_payload(
                    cookie_path.read_text(encoding="utf-8-sig"),
                    str(cookie_path),
                )
            )
        except FileNotFoundError:
            logger.warning("Arquivo de cookies do Vectorizer.AI nao encontrado: %s", cookie_path)
        except OSError as exc:
            logger.warning("Nao consegui ler arquivo de cookies do Vectorizer.AI %s: %s", cookie_path, exc)

    return cookies


def vectorizer_ai_cookies_from_env() -> list[dict[str, object]]:
    cookies = vectorizer_ai_json_cookies_from_env()
    raw_cookies = parse_cookie_header(VECTORIZER_AI_COOKIE_HEADER)
    if VECTORIZER_AI_COOKIE_VALUE:
        value_cookies = parse_cookie_header(VECTORIZER_AI_COOKIE_VALUE)
        if value_cookies:
            raw_cookies.update(value_cookies)
        else:
            raw_cookies[VECTORIZER_AI_COOKIE_NAME] = VECTORIZER_AI_COOKIE_VALUE

    for name, value in raw_cookies.items():
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": VECTORIZER_AI_COOKIE_DOMAIN,
                "path": "/",
                "secure": True,
                "httpOnly": name.lower() in {"vk", "atk"},
                "sameSite": "Lax",
            }
        )

    return cookies


def apply_vectorizer_ai_cookies(context) -> None:
    cookies = vectorizer_ai_cookies_from_env()
    if not cookies:
        logger.info("Nenhum cookie do Vectorizer.AI configurado no ambiente.")
        return

    context.add_cookies(cookies)
    cookie_names = ", ".join(cookie["name"] for cookie in cookies)
    logger.info(
        "Cookies do Vectorizer.AI aplicados via ambiente (%s): %s.",
        len(cookies),
        cookie_names,
    )


def has_visible_vectorizer_ai_download(page) -> bool:
    try:
        download_link = page.locator("#App-DownloadLink")
        return download_link.count() > 0 and download_link.first.is_visible()
    except PlaywrightError:
        return False


def dismiss_vectorizer_ai_blocking_dialogs(page) -> None:
    try:
        page.evaluate(
            """
            () => {
                for (const selector of [
                    '#RetryDialog-Dialog',
                    '#App-Error-Dialog',
                    '.modal-backdrop'
                ]) {
                    for (const element of document.querySelectorAll(selector)) {
                        element.classList.remove('in', 'show');
                        element.style.display = 'none';
                        element.setAttribute('aria-hidden', 'true');
                    }
                }
                document.body.classList.remove('modal-open');
                document.body.style.removeProperty('overflow');
                document.body.style.removeProperty('padding-right');
            }
            """
        )
        page.wait_for_timeout(200)
    except PlaywrightError:
        pass


def wait_for_vectorizer_ai_result(page) -> None:
    deadline = time.monotonic() + VECTORIZER_AI_TIMEOUT_SECONDS
    last_error = ""
    retried_network_error = False
    next_error_check = 0.0
    download_button_without_href_logged = False
    download_link_deadline = None
    setattr(page, "_vectorizer_ai_download_link_waited", False)
    last_logged_url = None
    next_wait_log = time.monotonic() + 10.0
    network_error_started_at = None
    network_error_logged_detail = ""
    network_error_debug_saved = False

    while time.monotonic() < deadline:
        now = time.monotonic()
        if VECTORIZER_AI_VERBOSE_LOGS:
            try:
                current_url = page.url
            except PlaywrightError:
                current_url = "<sem-url>"
            if current_url != last_logged_url:
                last_logged_url = current_url
                logger.info("Vectorizer.AI: URL atual durante processamento: %s", current_url)

        download_button_visible = has_visible_vectorizer_ai_download(page)
        if download_button_visible:
            if download_link_deadline is None:
                download_link_deadline = now + max(
                    VECTORIZER_AI_DOWNLOAD_LINK_TIMEOUT_SECONDS,
                    1.0,
                )

            download_link = page.locator("#App-DownloadLink").first
            download_url = get_vectorizer_ai_download_url(page, download_link)
            if download_url:
                dismiss_vectorizer_ai_blocking_dialogs(page)
                logger.info("Resultado do Vectorizer.AI pronto; link Download tokenizado visivel.")
                return

            if not download_button_without_href_logged:
                download_button_without_href_logged = True
                logger.info(
                    "Botao Download visivel, aguardando href tokenizado antes de clicar."
                )
                log_vectorizer_ai_state(page, "botao-download-visivel-sem-href")

            if now >= download_link_deadline:
                save_vectorizer_ai_debug(page, "download-link-timeout")
                setattr(page, "_vectorizer_ai_download_link_waited", True)
                logger.info(
                    "Href tokenizado nao apareceu no tempo esperado; "
                    "prosseguindo com clique normal no Download."
                )
                return
        else:
            download_link_deadline = None

        if VECTORIZER_AI_VERBOSE_LOGS and now >= next_wait_log:
            next_wait_log = now + 10.0
            log_vectorizer_ai_state(page, "aguardando-resultado")

        body_text = ""
        if now >= next_error_check:
            next_error_check = now + 2.0
            try:
                body_text = page.locator("body").inner_text(timeout=1_000)
            except PlaywrightError:
                body_text = ""

        network_error_markers = [
            "Erro de rede",
            "Tarefa\tErro",
            "Network Error",
            "Connect to worker",
            "Unable to connect to the worker",
            "Failed to connect to the server",
            "Muitas solicita",
            "Too many",
            "slow down",
        ]
        if any(marker in body_text for marker in network_error_markers):
            last_error = "O Vectorizer.AI mostrou erro durante o processamento/download."
            if network_error_started_at is None:
                network_error_started_at = now

            error_detail = extract_vectorizer_ai_error_text(page)
            if error_detail and error_detail != network_error_logged_detail:
                network_error_logged_detail = error_detail
                logger.warning(
                    "Vectorizer.AI: erro detectado na tela de processamento: %s",
                    error_detail,
                )

            if not network_error_debug_saved:
                network_error_debug_saved = True
                save_vectorizer_ai_debug(page, "network-error-processing")

            if not retried_network_error and click_vectorizer_ai_retry(page):
                retried_network_error = True
                network_error_started_at = None
                page.wait_for_timeout(3_000)
                log_vectorizer_ai_state(page, "apos-retry-erro-rede")
                continue

            if (
                network_error_started_at is not None
                and now - network_error_started_at >= VECTORIZER_AI_NETWORK_ERROR_TIMEOUT_SECONDS
            ):
                save_vectorizer_ai_debug(page, "network-error-timeout")
                raise RuntimeError(
                    "O Vectorizer.AI recebeu a imagem, mas ficou em erro de rede "
                    "durante o processamento no navegador da hospedagem. Detalhe: "
                    f"{(error_detail or last_error)[:500]}"
                )

            page.wait_for_timeout(1_000)
            continue
        else:
            network_error_started_at = None

        page.wait_for_timeout(250)

    if last_error:
        raise RuntimeError(
            f"{last_error} Abra o navegador com /login e confira se a sessao funciona."
        )

    raise RuntimeError("Tempo esgotado aguardando o resultado do Vectorizer.AI.")


def select_vectorizer_ai_format(page, output_format: str) -> bool:
    logger.info("Vectorizer.AI: tentando selecionar formato %s.", output_format.upper())
    try:
        if page.evaluate(
            """
            (format) => {
                const wanted = String(format || '').trim().toLowerCase();
                const inputs = Array.from(
                    document.querySelectorAll('input[type="radio"], input[type="checkbox"]')
                );
                for (const input of inputs) {
                    const text = [
                        input.value,
                        input.id,
                        input.name,
                        input.closest('label')?.innerText,
                        input.closest('li')?.innerText,
                        input.closest('div')?.innerText,
                    ].filter(Boolean).join(' ').toLowerCase();
                    if (!text.split(/\\s+/).includes(wanted) && input.value.toLowerCase() !== wanted) {
                        continue;
                    }
                    input.checked = true;
                    input.click();
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }
            """,
            output_format,
        ):
            logger.info(
                "Vectorizer.AI: formato %s selecionado por script inicial.",
                output_format.upper(),
            )
            return True
    except PlaywrightError:
        logger.info("Vectorizer.AI: script inicial nao conseguiu selecionar formato.")

    title_format = output_format.capitalize()
    upper_format = output_format.upper()
    selectors = [
        f".Options-FileFormatGroup-{title_format}-input",
        f".Options-FileFormatGroup-{title_format}-row",
        f".Options-FileFormatGroup-{title_format}-attribute",
        f"input[value='{output_format}']",
        f"input[value='{upper_format}']",
        f"input[name*='format'][value='{output_format}']",
        f"input[name*='format'][value='{upper_format}']",
        f"[data-format='{output_format}']",
        f"[data-format='{upper_format}']",
        f"label:has-text('{upper_format}')",
    ]

    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue

        target = locator.first
        try:
            tag_name = target.evaluate("el => el.tagName.toLowerCase()")
            input_type = target.evaluate("el => (el.type || '').toLowerCase()")
            if tag_name == "input" and input_type in {"radio", "checkbox"}:
                target.check(force=True)
            elif tag_name != "input":
                nested_input = target.locator("input").first
                if nested_input.count() > 0:
                    nested_type = nested_input.evaluate("el => (el.type || '').toLowerCase()")
                    if nested_type in {"radio", "checkbox"}:
                        nested_input.check(force=True)
                    else:
                        nested_input.click(force=True)
                elif target.is_visible():
                    target.click()
                else:
                    continue
            else:
                if not target.is_visible():
                    continue
                target.click()
            logger.info(
                "Vectorizer.AI: formato %s selecionado com seletor %s.",
                output_format.upper(),
                selector,
            )
            return True
        except Exception:
            continue

    try:
        selected = bool(
            page.evaluate(
                """
                (format) => {
                    const wanted = String(format || '').trim().toLowerCase();
                    if (!wanted) return false;

                    const normalize = (value) =>
                        String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();

                    const chooseInput = (input) => {
                        input.checked = true;
                        input.click();
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    };

                    const inputs = Array.from(
                        document.querySelectorAll('input[type="radio"], input[type="checkbox"]')
                    );

                    for (const input of inputs) {
                        const value = normalize(input.value || input.getAttribute('value'));
                        const id = input.id || '';
                        const labelFor = Array.from(document.querySelectorAll('label'))
                            .find((label) => id && label.htmlFor === id);
                        const nearbyText = normalize([
                            input.closest('label')?.innerText,
                            input.closest('li')?.innerText,
                            input.closest('.radio')?.innerText,
                            input.closest('.checkbox')?.innerText,
                            input.closest('div')?.innerText,
                            labelFor?.innerText,
                        ].filter(Boolean).join(' '));

                        if (
                            value === wanted ||
                            nearbyText === wanted ||
                            nearbyText.split(/\\s+/).includes(wanted)
                        ) {
                            return chooseInput(input);
                        }
                    }

                    for (const label of Array.from(document.querySelectorAll('label'))) {
                        if (normalize(label.innerText).split(/\\s+/).includes(wanted)) {
                            label.click();
                            return true;
                        }
                    }

                    return false;
                }
                """,
                output_format,
            )
        )
        logger.info(
            "Vectorizer.AI: selecao final de formato %s retornou %s.",
            output_format.upper(),
            selected,
        )
        return selected
    except PlaywrightError:
        logger.info("Vectorizer.AI: selecao final de formato falhou.")
        return False


def download_from_vectorizer_ai(page, output_path: Path) -> str:
    download_link = page.locator("#App-DownloadLink").first
    download_link.wait_for(state="visible", timeout=30_000)
    select_vectorizer_ai_format(page, OUTPUT_FORMAT)

    try:
        with page.expect_download(timeout=20_000) as download_info:
            download_link.click()
        download = download_info.value
    except PlaywrightTimeoutError:
        select_vectorizer_ai_format(page, OUTPUT_FORMAT)

        body_text = page.locator("body").inner_text(timeout=10_000)
        if "Fazer login" in body_text and "Criar conta" in body_text:
            logger.info("Vectorizer.AI abriu fluxo de login/compra antes do download.")

        candidate_selectors = [
            "button:has-text('DOWNLOAD GRATUITO')",
            "a:has-text('DOWNLOAD GRATUITO')",
            "button:has-text('FAÇA DOWNLOAD')",
            "a:has-text('FAÇA DOWNLOAD')",
            "button:has-text('Download')",
            "a:has-text('Download')",
            ".download",
            "button[type='submit']",
            "input[type='submit']",
            "#App-DownloadLink",
        ]

        download = None
        for selector in candidate_selectors:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue

            target = locator.first
            try:
                if not target.is_visible():
                    continue
                with page.expect_download(timeout=15_000) as download_info:
                    target.click()
                download = download_info.value
                break
            except PlaywrightTimeoutError:
                select_vectorizer_ai_format(page, OUTPUT_FORMAT)
                continue

        if download is None:
            raise RuntimeError(
                "Nao consegui iniciar o download no Vectorizer.AI. "
                "Pode ser necessario fazer login, confirmar pagamento ou resolver uma etapa manual."
            )

    suggested_filename = download.suggested_filename or output_path.name
    temp_download_path = output_path.with_name(output_path.name + ".download")
    download.save_as(str(temp_download_path))
    temp_download_path.replace(output_path)
    return suggested_filename


def expect_download_from_click(
    page,
    locator,
    timeout: int = 20_000,
    *,
    force: bool = False,
    click_timeout: int = 5_000,
):
    try:
        with page.expect_download(timeout=timeout) as download_info:
            locator.click(force=force, timeout=click_timeout)
        return download_info.value
    except PlaywrightTimeoutError:
        return None


def wait_for_vectorizer_ai_download_event(page, timeout_seconds: float):
    try:
        return page.wait_for_event("download", timeout=int(timeout_seconds * 1000))
    except PlaywrightTimeoutError:
        return None


def wait_for_vectorizer_ai_download_options(page, timeout_ms: int = 15_000) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    should_log = VECTORIZER_AI_VERBOSE_LOGS and timeout_ms >= 1_000
    if should_log:
        logger.info(
            "Vectorizer.AI: aguardando tela de formatos por %.1fs.",
            timeout_ms / 1000,
        )
    while time.monotonic() < deadline:
        if page.is_closed():
            if should_log:
                logger.info("Vectorizer.AI: pagina fechou enquanto aguardava tela de formatos.")
            return False

        try:
            body_text = page.locator("body").inner_text(timeout=500)
            if OUTPUT_LABEL in body_text and (
                "File Format" in body_text
                or "Formato" in body_text
                or "SVG Options" in body_text
            ):
                if should_log:
                    logger.info("Vectorizer.AI: tela de formatos encontrada por texto.")
                return True

            if page.locator(f"label:has-text('{OUTPUT_LABEL}')").count() > 0:
                if should_log:
                    logger.info(
                        "Vectorizer.AI: tela de formatos encontrada por label %s.",
                        OUTPUT_LABEL,
                    )
                return True
            if page.locator(f"input[value='{OUTPUT_FORMAT}']").count() > 0:
                if should_log:
                    logger.info(
                        "Vectorizer.AI: tela de formatos encontrada por input %s.",
                        OUTPUT_FORMAT,
                    )
                return True
            if page.locator(f"input[value='{OUTPUT_LABEL}']").count() > 0:
                if should_log:
                    logger.info(
                        "Vectorizer.AI: tela de formatos encontrada por input %s.",
                        OUTPUT_LABEL,
                    )
                return True
        except PlaywrightError:
            pass

        page.wait_for_timeout(200)

    return False


def find_vectorizer_ai_download_options_page(page, timeout_ms: int = 15_000):
    deadline = time.monotonic() + (timeout_ms / 1000)
    if VECTORIZER_AI_VERBOSE_LOGS:
        logger.info(
            "Vectorizer.AI: procurando tela de formatos entre abas por %.1fs.",
            timeout_ms / 1000,
        )
    while time.monotonic() < deadline:
        pages = list(page.context.pages)
        if VECTORIZER_AI_VERBOSE_LOGS:
            logger.info("Vectorizer.AI: abas abertas na procura de formatos: %s.", len(pages))
        for candidate in reversed(pages):
            try:
                if candidate.is_closed():
                    continue
                if wait_for_vectorizer_ai_download_options(candidate, timeout_ms=500):
                    log_vectorizer_ai_state(candidate, "tela-formatos-encontrada")
                    return candidate
            except PlaywrightError:
                continue

        page.wait_for_timeout(200)

    return None


def click_locator_like_user(page, locator, timeout: int = 3_000) -> None:
    locator.wait_for(state="visible", timeout=timeout)
    locator.scroll_into_view_if_needed(timeout=timeout)
    box = locator.bounding_box()
    if box:
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        if VECTORIZER_AI_VERBOSE_LOGS:
            logger.info(
                "Vectorizer.AI: clique por coordenadas em x=%.1f y=%.1f "
                "(w=%.1f h=%.1f).",
                x,
                y,
                box["width"],
                box["height"],
            )
        page.mouse.move(x, y)
        page.wait_for_timeout(100)
        page.mouse.click(x, y)
        return

    if VECTORIZER_AI_VERBOSE_LOGS:
        logger.info("Vectorizer.AI: clique via locator.click sem bounding box.")
    locator.click(timeout=timeout)


def first_download_wait(page, pages_before, downloads, timeout_seconds: float):
    deadline = time.monotonic() + timeout_seconds
    if VECTORIZER_AI_VERBOSE_LOGS:
        logger.info(
            "Vectorizer.AI: aguardando evento de download ou tela de formatos por %.1fs.",
            timeout_seconds,
        )
    while time.monotonic() < deadline:
        if downloads:
            logger.info("Vectorizer.AI: evento de download detectado.")
            return page, downloads[0]

        for candidate in reversed(page.context.pages):
            try:
                if candidate.is_closed():
                    continue
                if candidate not in pages_before:
                    try:
                        candidate.wait_for_load_state("domcontentloaded", timeout=500)
                    except PlaywrightError:
                        pass
                if wait_for_vectorizer_ai_download_options(candidate, timeout_ms=500):
                    logger.info(
                        "Vectorizer.AI: tela de formatos detectada apos primeiro clique."
                    )
                    return candidate, None
            except PlaywrightError:
                continue

        page.wait_for_timeout(250)

    return None, None


def normalize_vectorizer_ai_download_url(page, value: str | None) -> str | None:
    if not value:
        return None

    download_url = urljoin(page.url, value.strip())
    if "/assets/" in download_url or "/images/download" in download_url:
        return None
    if re.search(r"/images/[0-9A-Za-z][0-9A-Za-z_-]{20,}", download_url):
        return download_url

    return None


def get_vectorizer_ai_download_url(page, locator=None) -> str | None:
    if locator is not None:
        for attribute in ("href", "data-href"):
            try:
                download_url = normalize_vectorizer_ai_download_url(
                    page,
                    locator.get_attribute(attribute, timeout=500),
                )
                if download_url:
                    return download_url
            except PlaywrightError:
                pass

    try:
        candidates = page.evaluate(
            """
            () => {
                const values = [];
                const push = (value) => {
                    if (value) values.push(String(value));
                };

                for (const selector of [
                    '#App-DownloadLink',
                    'a[alt="Download"]',
                    'a[title="Download"]',
                    'a[href*="/images/"]'
                ]) {
                    for (const element of document.querySelectorAll(selector)) {
                        push(element.getAttribute('href'));
                        push(element.href);
                        push(element.getAttribute('data-href'));
                    }
                }

                const html = document.documentElement.outerHTML;
                const matches = html.match(/(?:https?:\\/\\/[^"'\\s<>]+)?\\/images\\/[0-9A-Za-z][0-9A-Za-z_-]{20,}/g) || [];
                for (const match of matches) push(match);

                for (const storage of [window.localStorage, window.sessionStorage]) {
                    try {
                        for (let index = 0; index < storage.length; index += 1) {
                            const key = storage.key(index);
                            push(key);
                            push(storage.getItem(key));
                        }
                    } catch (_) {}
                }

                return values;
            }
            """
        )
    except PlaywrightError:
        return None

    for candidate in candidates:
        download_url = normalize_vectorizer_ai_download_url(page, candidate)
        if download_url:
            return download_url

    return None


def wait_for_vectorizer_ai_download_url(page, locator=None, timeout_ms: int = 10_000) -> str | None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    next_log = time.monotonic()
    while time.monotonic() < deadline:
        download_url = get_vectorizer_ai_download_url(page, locator)
        if download_url:
            logger.info("Vectorizer.AI: href tokenizado encontrado: %s", download_url)
            return download_url
        now = time.monotonic()
        if VECTORIZER_AI_VERBOSE_LOGS and now >= next_log:
            next_log = now + 10.0
            try:
                href = locator.get_attribute("href", timeout=500) if locator else None
            except PlaywrightError:
                href = None
            logger.info(
                "Vectorizer.AI: ainda sem href tokenizado (href atual=%s).",
                (href[:80] if href else "ausente"),
            )
        page.wait_for_timeout(250)

    return None


def open_vectorizer_ai_download_url(page, download_url, pages_before, downloads):
    logger.info("Abrindo href real do Download do Vectorizer.AI: %s", download_url)

    try:
        page.goto(download_url, wait_until="domcontentloaded", timeout=15_000)
    except PlaywrightError as exc:
        # Se a URL iniciar um download direto, o navegador pode abortar a navegacao.
        logger.info("Navegacao pelo href do Download retornou: %s", exc)

    resolved_page, download = first_download_wait(
        page,
        pages_before,
        downloads,
        timeout_seconds=10,
    )
    if resolved_page is not None or download is not None:
        return resolved_page or page, download

    return page, None


def open_vectorizer_ai_download_href(page, locator, pages_before, downloads):
    download_url = wait_for_vectorizer_ai_download_url(page, locator, timeout_ms=8_000)
    if download_url:
        return open_vectorizer_ai_download_url(page, download_url, pages_before, downloads)

    try:
        href = locator.get_attribute("href", timeout=1_000)
    except PlaywrightError:
        href = None

    download_url = normalize_vectorizer_ai_download_url(page, href)
    if not download_url:
        logger.info("Botao Download do Vectorizer.AI nao trouxe href tokenizado.")
        return page, None

    return open_vectorizer_ai_download_url(page, download_url, pages_before, downloads)


def click_vectorizer_ai_result_download(page, locator):
    pages_before = set(page.context.pages)
    downloads = []
    logger.info(
        "Vectorizer.AI: preparando primeiro Download (abas antes=%s).",
        len(pages_before),
    )

    def on_download(download):
        downloads.append(download)

    page.on("download", on_download)
    try:
        download_url_already_waited = bool(
            getattr(page, "_vectorizer_ai_download_link_waited", False)
        )
        if not download_url_already_waited:
            logger.info("Aguardando href tokenizado do primeiro Download do Vectorizer.AI.")
            download_url = wait_for_vectorizer_ai_download_url(
                page,
                locator,
                timeout_ms=int(VECTORIZER_AI_DOWNLOAD_LINK_TIMEOUT_SECONDS * 1000),
            )
            if download_url:
                resolved_page, download = open_vectorizer_ai_download_url(
                    page,
                    download_url,
                    pages_before,
                    downloads,
                )
                if resolved_page is not None or download is not None:
                    return resolved_page or page, download

        logger.info("Href tokenizado nao apareceu; tentando clique normal no Download.")
        log_vectorizer_ai_state(page, "antes-clique-primeiro-download")
        click_locator_like_user(page, locator, timeout=3_000)
        log_vectorizer_ai_state(page, "depois-clique-primeiro-download")
        resolved_page, download = first_download_wait(
            page,
            pages_before,
            downloads,
            timeout_seconds=15,
        )
        if resolved_page is not None or download is not None:
            return resolved_page or page, download

        logger.info(
            "Primeiro clique nao abriu as opcoes; tentando href tokenizado do botao."
        )
        resolved_page, download = open_vectorizer_ai_download_href(
            page,
            locator,
            pages_before,
            downloads,
        )
        if resolved_page is not None or download is not None:
            return resolved_page or page, download
    finally:
        try:
            page.remove_listener("download", on_download)
        except Exception:
            pass

    logger.info(
        "O primeiro Download nao abriu opcoes nem iniciou download."
    )
    return page, None


def click_vectorizer_ai_final_download(page):
    waited_before_click = False
    selectors = [
        "form button.btn-primary:has-text('DOWNLOAD')",
        "form button.btn-primary:has-text('FAÇA DOWNLOAD')",
        "form button.btn-primary:has-text('DOWNLOAD GRATUITO')",
        "button.btn-primary:has-text('DOWNLOAD')",
        "button.btn-primary:has-text('FAÇA DOWNLOAD')",
        "button.btn-primary:has-text('DOWNLOAD GRATUITO')",
        "button[type='submit']:has-text('DOWNLOAD')",
        "button[type='submit']:has-text('FAÇA DOWNLOAD')",
        "input[type='submit'][value='DOWNLOAD']",
        "input[type='submit'][value='Download']",
        "button:has-text('DOWNLOAD')",
        "button:has-text('FAÇA DOWNLOAD')",
        "a.btn-primary:has-text('DOWNLOAD')",
        "a.btn-primary:has-text('FAÇA DOWNLOAD')",
        "a:has-text('DOWNLOAD')",
        "a:has-text('FAÇA DOWNLOAD')",
        ".download",
    ]

    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()
        if count == 0:
            continue
        if VECTORIZER_AI_VERBOSE_LOGS:
            logger.info(
                "Vectorizer.AI: seletor de Download final encontrou %s elemento(s): %s",
                count,
                selector,
            )

        for index in range(count - 1, max(count - 4, -1), -1):
            target = locator.nth(index)
            try:
                if not target.is_visible(timeout=300):
                    continue

                target.scroll_into_view_if_needed(timeout=1_000)
                if (
                    not waited_before_click
                    and VECTORIZER_AI_FINAL_DOWNLOAD_DELAY_SECONDS > 0
                ):
                    waited_before_click = True
                    logger.info(
                        "Aguardando %.1fs antes do Download final do Vectorizer.AI.",
                        VECTORIZER_AI_FINAL_DOWNLOAD_DELAY_SECONDS,
                    )
                    page.wait_for_timeout(
                        int(VECTORIZER_AI_FINAL_DOWNLOAD_DELAY_SECONDS * 1000)
                    )

                logger.info(
                    "Clicando no Download final do Vectorizer.AI com seletor: %s",
                    selector,
                )
                download = expect_download_from_click(
                    page,
                    target,
                    timeout=8_000,
                    force=True,
                    click_timeout=1_500,
                )
                if download is not None:
                    return download
            except PlaywrightError:
                continue

    return None


def download_from_vectorizer_ai_after_format_choice(page, output_path: Path) -> str:
    download_link = page.locator("#App-DownloadLink").first
    logger.info("Vectorizer.AI: aguardando botao Download do resultado.")
    download_link.wait_for(state="visible", timeout=30_000)
    dismiss_vectorizer_ai_blocking_dialogs(page)
    log_vectorizer_ai_state(page, "antes-primeiro-download")

    # O site normalmente abre as opcoes de exportacao so depois do primeiro clique.
    page, download = click_vectorizer_ai_result_download(page, download_link)
    log_vectorizer_ai_state(page, "apos-primeiro-download")
    if download is None:
        options_page = find_vectorizer_ai_download_options_page(page, timeout_ms=1_500)
        if options_page is not None:
            page = options_page
            logger.info("Vectorizer.AI: usando aba/pagina de opcoes de formato.")
        options_ready = wait_for_vectorizer_ai_download_options(page, timeout_ms=1_000)
        page.wait_for_timeout(100)
        selected = select_vectorizer_ai_format(page, OUTPUT_FORMAT)
        if selected:
            logger.info("Formato %s selecionado no Vectorizer.AI.", OUTPUT_LABEL)
        else:
            logger.warning("Nao encontrei controle visivel para selecionar formato %s.", OUTPUT_LABEL)

        if not options_ready and not selected:
            save_vectorizer_ai_debug(page, "download-options-not-open")
            raise RuntimeError(
                "O primeiro clique em Download nao abriu as opcoes de formato e tambem "
                "nao iniciou um download direto no tempo esperado."
            )

        body_text = page.locator("body").inner_text(timeout=300)
        if "Fazer login" in body_text and "Criar conta" in body_text:
            logger.info("Vectorizer.AI abriu fluxo de login/compra antes do download.")

        log_vectorizer_ai_state(page, "antes-download-final")
        download = click_vectorizer_ai_final_download(page)
        candidate_selectors = [] if download is not None else [
            "button.btn-primary:has-text('DOWNLOAD')",
            "a.btn-primary:has-text('DOWNLOAD')",
            "button:has-text('DOWNLOAD')",
            "a:has-text('DOWNLOAD')",
            "input[type='submit'][value='DOWNLOAD']",
            "input[type='submit'][value='Download']",
            "button:has-text('DOWNLOAD GRATUITO')",
            "a:has-text('DOWNLOAD GRATUITO')",
            "button:has-text('FAÇA DOWNLOAD')",
            "a:has-text('FAÇA DOWNLOAD')",
            "button:has-text('Download')",
            "a:has-text('Download')",
            ".download",
            "button[type='submit']",
            "input[type='submit']",
            "#App-DownloadLink",
        ]

        for selector in candidate_selectors:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue

            for index in range(min(locator.count(), 5)):
                target = locator.nth(index)
                try:
                    if not target.is_visible():
                        continue

                    target.scroll_into_view_if_needed(timeout=2_000)
                    download = expect_download_from_click(
                        page,
                        target,
                        timeout=8_000,
                        force=True,
                        click_timeout=3_000,
                    )
                    if download is not None:
                        break

                    select_vectorizer_ai_format(page, OUTPUT_FORMAT)
                except PlaywrightError:
                    continue

            if download is not None:
                break

    if download is None:
        save_vectorizer_ai_debug(page, "download-format-not-found")
        raise RuntimeError(
            "Nao consegui baixar o arquivo depois de clicar Download e selecionar o formato. "
            "Pode ser necessario fazer login, confirmar pagamento ou resolver uma etapa manual."
        )

    suggested_filename = download.suggested_filename or output_path.name
    temp_download_path = output_path.with_name(output_path.name + ".download")
    logger.info(
        "Vectorizer.AI: download recebido (nome sugerido=%s). Salvando em %s.",
        suggested_filename,
        temp_download_path,
    )
    download.save_as(str(temp_download_path))
    temp_download_path.replace(output_path)
    logger.info(
        "Vectorizer.AI: arquivo final salvo em %s (%s bytes).",
        output_path,
        output_path.stat().st_size,
    )
    return suggested_filename


def validate_vectorizer_ai_download(output_path: Path, suggested_filename: str) -> None:
    logger.info(
        "Vectorizer.AI: validando download %s (nome sugerido=%s).",
        output_path,
        suggested_filename,
    )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("O download do Vectorizer.AI veio vazio.")

    head = output_path.read_bytes()[:512].lstrip()
    if OUTPUT_FORMAT == "eps" and not head.startswith(b"%!PS"):
        raise RuntimeError(
            "O Vectorizer.AI baixou um arquivo que nao parece EPS "
            f"(nome sugerido: {suggested_filename})."
        )
    if OUTPUT_FORMAT == "svg" and not (head.startswith(b"<svg") or head.startswith(b"<?xml")):
        raise RuntimeError(
            "O Vectorizer.AI baixou um arquivo que nao parece SVG "
            f"(nome sugerido: {suggested_filename})."
        )
    if OUTPUT_FORMAT == "pdf" and not head.startswith(b"%PDF"):
        raise RuntimeError(
            "O Vectorizer.AI baixou um arquivo que nao parece PDF "
            f"(nome sugerido: {suggested_filename})."
        )
    if OUTPUT_FORMAT == "png" and not head.startswith(b"\x89PNG"):
        raise RuntimeError(
            "O Vectorizer.AI baixou um arquivo que nao parece PNG "
            f"(nome sugerido: {suggested_filename})."
        )


def vectorize_with_vectorizer_ai(input_path: Path, output_path: Path) -> None:
    logger.info(
        "Vectorizer.AI: inicio do fluxo remoto com entrada %s e saida %s.",
        describe_image_file(input_path),
        output_path.name,
    )
    with VECTORIZER_AI_LOCK:
        logger.info("Vectorizer.AI: lock adquirido; iniciando Playwright.")
        with sync_playwright() as playwright:
            context = launch_vectorizer_ai_context(playwright)
            try:
                apply_vectorizer_ai_cookies(context)
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(30_000)
                logger.info("Vectorizer.AI: abrindo site %s.", VECTORIZER_AI_URL)
                page.goto(VECTORIZER_AI_URL, wait_until="domcontentloaded", timeout=60_000)
                log_vectorizer_ai_state(page, "site-aberto")

                file_input = page.locator('input[type="file"]').first
                logger.info("Vectorizer.AI: procurando input de arquivo para upload.")
                file_input.wait_for(state="attached", timeout=30_000)
                logger.info("Vectorizer.AI: enviando imagem para o input de arquivo.")
                file_input.set_input_files(str(input_path))
                log_vectorizer_ai_state(page, "apos-upload")

                wait_for_vectorizer_ai_result(page)
                log_vectorizer_ai_state(page, "resultado-pronto")
                suggested_filename = download_from_vectorizer_ai_after_format_choice(
                    page,
                    output_path,
                )
                validate_vectorizer_ai_download(output_path, suggested_filename)
                logger.info("Vectorizer.AI: validacao do arquivo baixado concluida.")
            except PlaywrightError as exc:
                if is_playwright_target_closed(exc):
                    raise RuntimeError(
                        "a janela do Vectorizer.AI foi fechada antes do download terminar. "
                        "Envie a imagem de novo e nao feche o navegador de processamento."
                    ) from exc

                try:
                    save_vectorizer_ai_debug(page, "playwright-error")
                except Exception:
                    pass
                raise
            except Exception:
                try:
                    save_vectorizer_ai_debug(page, "vectorizer-error")
                except Exception:
                    pass
                raise
            finally:
                logger.info("Vectorizer.AI: fechando contexto do navegador.")
                context.close()


def open_vectorizer_ai_login_session() -> None:
    with VECTORIZER_AI_LOCK:
        with sync_playwright() as playwright:
            context = launch_vectorizer_ai_context(playwright, login=True)
            try:
                apply_vectorizer_ai_cookies(context)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(VECTORIZER_AI_URL, wait_until="domcontentloaded", timeout=60_000)

                login_link = page.get_by_text("Fazer login", exact=True)
                if login_link.count() > 0 and login_link.first.is_visible():
                    login_link.first.click()

                page.wait_for_timeout(int(VECTORIZER_AI_LOGIN_SECONDS * 1000))
            except PlaywrightError as exc:
                if not is_playwright_target_closed(exc):
                    logger.exception("Sessao de login do Vectorizer.AI falhou.")
                    raise
            finally:
                try:
                    context.close()
                except Exception:
                    pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    await update.effective_message.reply_text(
        f"Envie uma imagem como foto ou documento e eu devolvo um {OUTPUT_LABEL} vetorizado.\n"
        f"Provedor atual: {VECTORIZATION_PROVIDER}."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    await update.effective_message.reply_text(
        "Para melhor qualidade, envie PNG/JPG como documento.\n"
        f"Limite atual: {TELEGRAM_MAX_FILE_MB} MB.\n"
        f"Formato de saida atual: {OUTPUT_LABEL}.\n"
        f"Provedor atual: {VECTORIZATION_PROVIDER}.\n"
        "Use /login para abrir o navegador do Vectorizer.AI e salvar a sessao.\n"
        "Ajustes de vetorizacao ficam no arquivo .env."
    )


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if VECTORIZATION_PROVIDER != "vectorizer_ai":
        await update.effective_message.reply_text(
            "O /login so e necessario quando VECTORIZATION_PROVIDER=vectorizer_ai."
        )
        return

    await update.effective_message.reply_text(
        "Vou abrir uma janela do Vectorizer.AI. Faca login nela; a sessao sera salva no perfil local."
    )
    await asyncio.to_thread(open_vectorizer_ai_login_session)
    await update.effective_message.reply_text("Sessao de login do Vectorizer.AI encerrada.")


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    document = message.document
    photo = message.photo[-1] if message.photo else None

    if document:
        mime_type = document.mime_type or ""
        file_name = document.file_name or "imagem"
        if not mime_type.startswith("image/"):
            await message.reply_text("Envie um arquivo de imagem PNG, JPG ou WEBP.")
            return
        file_id = document.file_id
        file_size = document.file_size or 0
        suffix = image_suffix(file_name, mime_type)
    elif photo:
        file_id = photo.file_id
        file_size = photo.file_size or 0
        suffix = ".jpg"
    else:
        await message.reply_text("Envie uma imagem para vetorizar.")
        return

    logger.info(
        "Telegram: imagem recebida no chat %s (tipo=%s, tamanho=%s bytes, sufixo=%s).",
        message.chat_id,
        "documento" if document else "foto",
        file_size,
        suffix,
    )

    if file_size and file_size > MAX_FILE_BYTES:
        await message.reply_text(
            f"Arquivo muito grande. O limite configurado e {TELEGRAM_MAX_FILE_MB} MB."
        )
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.UPLOAD_DOCUMENT,
    )
    status = await message.reply_text("Recebi a imagem. Vetorizando...")

    with tempfile.TemporaryDirectory(prefix="telegram-vectorizer-") as temp_dir:
        temp_path = Path(temp_dir)
        original_path = temp_path / f"entrada{suffix}"
        prepared_path = temp_path / "entrada_preparada.png"
        svg_path = temp_path / "imagem-vetorizada.svg"
        output_path = temp_path / f"imagem-vetorizada.{OUTPUT_FORMAT}"

        try:
            telegram_file = await context.bot.get_file(file_id)
            await telegram_file.download_to_drive(str(original_path))
            logger.info("Telegram: arquivo baixado para %s.", describe_image_file(original_path))

            if VECTORIZATION_PROVIDER == "vectorizer_ai":
                await status.edit_text("Enviando para o Vectorizer.AI...")
                await asyncio.to_thread(
                    prepare_input_image,
                    original_path,
                    prepared_path,
                    VECTORIZER_AI_INPUT_MAX_PIXELS,
                )
                logger.info(
                    "Vectorizer.AI: imagem preparada para upload: %s.",
                    describe_image_file(prepared_path),
                )
                await asyncio.to_thread(vectorize_with_vectorizer_ai, prepared_path, output_path)
            else:
                if OUTPUT_FORMAT not in {"eps", "svg"}:
                    raise RuntimeError(
                        "O provedor local so suporta OUTPUT_FORMAT=eps ou OUTPUT_FORMAT=svg."
                    )

                await asyncio.to_thread(prepare_input_image, original_path, prepared_path)
                logger.info("Local: imagem preparada: %s.", describe_image_file(prepared_path))
                await asyncio.to_thread(vectorize_image, prepared_path, svg_path)
                if OUTPUT_FORMAT == "eps":
                    await asyncio.to_thread(convert_svg_to_eps, svg_path, output_path)
                else:
                    output_path = svg_path

            output_size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(
                "%s gerado via %s para chat %s com %.2f MB.",
                OUTPUT_LABEL,
                VECTORIZATION_PROVIDER,
                message.chat_id,
                output_size_mb,
            )
        except UnidentifiedImageError:
            await status.edit_text("Nao consegui abrir essa imagem. Tente PNG ou JPG.")
            return
        except Exception as exc:
            logger.exception("Falha ao vetorizar imagem")
            detail = str(exc).strip()
            if detail:
                await status.edit_text(f"Nao consegui vetorizar essa imagem: {detail[:700]}")
            else:
                await status.edit_text("Nao consegui vetorizar essa imagem.")
            return

        try:
            with output_path.open("rb") as output_file:
                await message.reply_document(
                    document=output_file,
                    filename=f"imagem-vetorizada.{OUTPUT_FORMAT}",
                    caption=f"{OUTPUT_LABEL} vetorizado.",
                    read_timeout=TELEGRAM_TIMEOUT_SECONDS,
                    write_timeout=TELEGRAM_TIMEOUT_SECONDS,
                    connect_timeout=30,
                    pool_timeout=30,
                )
            await status.delete()
        except TimedOut:
            logger.exception("Timeout ao enviar %s para chat %s", OUTPUT_LABEL, message.chat_id)
            await status.edit_text(
                f"O {OUTPUT_LABEL} foi gerado, mas o envio demorou demais e o Telegram cancelou. "
                "Tente enviar uma imagem menor ou mais simples."
            )
        except TelegramError:
            logger.exception("Falha ao enviar %s para chat %s", OUTPUT_LABEL, message.chat_id)
            await status.edit_text(
                f"O {OUTPUT_LABEL} foi gerado, mas nao consegui enviar pelo Telegram."
            )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None or chat.type != "private":
        return

    await message.reply_text("Envie uma imagem ou use /help.")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "COLE_AQUI_O_TOKEN_DO_BOTFATHER":
        raise RuntimeError(
            "Configure TELEGRAM_BOT_TOKEN no arquivo .env antes de iniciar o bot."
        )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(TELEGRAM_TIMEOUT_SECONDS)
        .write_timeout(TELEGRAM_TIMEOUT_SECONDS)
        .pool_timeout(30)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.ALL, unknown))

    logger.info("Bot iniciado. Aguardando imagens...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
