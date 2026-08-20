"""
葫芦侠腾讯滑块验证自动化

核心方法：
    from solve_captcha import solve_captcha

    result = solve_captcha(max_tries=3, backend="auto")
    if result["success"]:
        print(result["ticket"], result["randstr"])
    else:
        print(result["error"])

成功返回：
    {
        "success": True,
        "ret": 0,
        "randstr": "@xxx",
        "ticket": "tr03...",
        "posts": [{"url": "...", "post_data": "...", "response_body": "..."}],
        "postback": null,
    }

失败返回：
    {
        "success": False,
        "error": "错误原因",
        "detail": "详细异常信息",
    }

命令行用法：
    python solve_captcha.py                    # headless，自动选择识别后端
    python solve_captcha.py --headed           # 显示浏览器窗口
    python solve_captcha.py --backend ddddocr  # 强制 ddddocr
    python solve_captcha.py --backend opencv   # 强制 OpenCV
    python solve_captcha.py --max-tries 5      # 最多尝试次数
"""

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path
import hashlib
import cv2
import numpy as np
import requests
from playwright.async_api import async_playwright
from typing import Any

# ============================================================
# 全局常量
# ============================================================

DEFAULT_PARAMS: dict[str, Any] = {
    "platform": "2",
    "gkey": "000000",
    "app_version": "4.4.0.4",
    "versioncode": "20141520",
    "market_id": "floor_web",
    "_key": "",
    "device_code": "[d]0ffa6f53-a6f6-4596-bba3-22c80572255e",
    "phone_brand_type": "UN",
}

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "okhttp/3.8.1",
    "Connection": "close",
    "Accept-Encoding": "gzip",
}

DEVICE_CODE: str = DEFAULT_PARAMS["device_code"]

try:
    import ddddocr
except Exception:  # ddddocr 未安装时自动退回 OpenCV
    ddddocr = None


CAPTCHA_URL = "https://floor.huluxia.com/tencent/vcode/ANDROID/4.2.3"
OUT_DIR = Path(__file__).resolve().parent

UA = (
    "Mozilla/5.0 (Linux; Android 13; 23013RK75C Build/TKQ1.220829.002) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

JS_BRIDGE = """
Object.defineProperty(window, "jsBridge", {
    configurable: true,
    writable: true,
    value: {
        getData: function (data) {
            window.__captchaResult = data;
        }
    }
});
"""

_slide_ocr = None


def get_slide_ocr():
    global _slide_ocr
    if _slide_ocr is None:
        _slide_ocr = ddddocr.DdddOcr(ocr=False, det=False, show_ad=False)
    return _slide_ocr


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("图片解码失败")
    return img


def fetch_image(url: str) -> np.ndarray:
    headers = {
        "User-Agent": UA,
        "Referer": "https://turing.captcha.qcloud.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return decode_image(resp.content)


def piece_offset(block: np.ndarray) -> tuple[float, float]:
    """返回拼图块图形在整张 block 图片内的中心偏移（x, y），单位：block 图片像素。"""
    if block.ndim == 3 and block.shape[2] == 4:
        alpha = block[:, :, 3]
        ys, xs = np.where(alpha > 128)
        if len(xs):
            return (float((xs.min() + xs.max()) / 2), float((ys.min() + ys.max()) / 2))
    return (float(block.shape[1] / 2), float(block.shape[0] / 2))


def detect_gap_ddddocr(block: np.ndarray, bg: np.ndarray) -> dict:
    if ddddocr is None:
        raise RuntimeError("未安装 ddddocr")
    ocr = get_slide_ocr()
    block_bgr = block[:, :, :3] if block.ndim == 3 and block.shape[2] == 4 else block
    bg_bgr = bg[:, :, :3] if bg.ndim == 3 and bg.shape[2] == 4 else bg
    ok1, buf1 = cv2.imencode(".png", block_bgr)
    ok2, buf2 = cv2.imencode(".png", bg_bgr)
    if not ok1 or not ok2:
        raise RuntimeError("图片编码失败")
    res = ocr.slide_match(buf1.tobytes(), buf2.tobytes())
    x, y = float(res["target_x"]), float(res["target_y"])
    if not (0 <= x <= bg.shape[1] and 0 <= y <= bg.shape[0]):
        raise RuntimeError(f"ddddocr 识别结果越界: x={x}, y={y}")
    return {
        "backend": "ddddocr",
        "score": float(res.get("confidence", 0.0)),
        "gap_cx_img": x,
        "gap_cy_img": y,
    }


def detect_gap_opencv(block: np.ndarray, bg: np.ndarray) -> dict:
    bg_rgb = bg[:, :, :3] if bg.ndim == 3 and bg.shape[2] == 4 else bg
    block_rgb = block[:, :, :3] if block.ndim == 3 and block.shape[2] == 4 else block
    if block.ndim == 3 and block.shape[2] == 4:
        alpha = block[:, :, 3]
        mask = (alpha > 128).astype(np.uint8) * 255
        method = cv2.TM_CCORR_NORMED
    else:
        mask = None
        method = cv2.TM_CCOEFF_NORMED
    result = cv2.matchTemplate(bg_rgb, block_rgb, method, mask=mask)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return {
        "backend": "opencv",
        "score": float(max_val),
        "gap_cx_img": float(max_loc[0] + block_rgb.shape[1] / 2),
        "gap_cy_img": float(max_loc[1] + block_rgb.shape[0] / 2),
    }


def build_track(distance: float, steps: int = 36) -> list[float]:
    """生成带一点抖动的人手拖动轨迹。"""
    points = []
    for i in range(steps + 1):
        t = i / steps
        eased = t * t * (3 - 2 * t)
        x = distance * eased
        if 0 < i < steps:
            x += random.uniform(-1.2, 1.2)
        points.append(max(0.0, min(distance, x)))
    points[-1] = distance
    return points


async def get_element_boxes(frame) -> dict:
    boxes = {}
    for element_id in ("slideBg", "slideBlock", "tcaptcha_drag_button"):
        locator = frame.locator(f"#{element_id}")
        await locator.wait_for(state="visible", timeout=15000)
        box = await locator.bounding_box()
        if box is None:
            raise RuntimeError(f"找不到 #{element_id} 的坐标")
        boxes[element_id] = box
    return boxes


async def prepare_drag(page, captcha, backend: str):
    """下载图片、识别缺口，返回拖动按钮坐标和拖动距离。"""
    await captcha.locator("#slideBg").wait_for(state="visible", timeout=15000)
    await captcha.locator("#slideBlock").wait_for(state="visible", timeout=15000)
    await captcha.locator("#tcaptcha_drag_button").wait_for(state="visible", timeout=15000)

    images = await captcha.evaluate(
        """
        () => {
            const bg = document.getElementById("slideBg");
            const block = document.getElementById("slideBlock");
            return {
                bg: bg ? bg.getAttribute("src") : null,
                block: block ? block.getAttribute("src") : null,
            };
        }
        """
    )
    if not images.get("bg") or not images.get("block"):
        raise RuntimeError("验证码图片还没准备好")

    bg_img = await asyncio.to_thread(fetch_image, images["bg"])
    block_img = await asyncio.to_thread(fetch_image, images["block"])
    boxes = await get_element_boxes(captcha)
    bg_box = boxes["slideBg"]
    block_box = boxes["slideBlock"]
    button_box = boxes["tcaptcha_drag_button"]

    scale_x = bg_box["width"] / bg_img.shape[1]
    scale_y = bg_box["height"] / bg_img.shape[0]
    block_scale = block_box["width"] / block_img.shape[1]
    pcx_img, pcy_img = piece_offset(block_img)

    initial_piece_cx_css = (block_box["x"] - bg_box["x"]) + pcx_img * block_scale
    initial_piece_cy_css = (block_box["y"] - bg_box["y"]) + pcy_img * block_scale

    if backend == "ddddocr":
        det = await asyncio.to_thread(detect_gap_ddddocr, block_img, bg_img)
    else:
        det = await asyncio.to_thread(detect_gap_opencv, block_img, bg_img)

    gap_cx_css = det["gap_cx_img"] * scale_x
    gap_cy_css = det["gap_cy_img"] * scale_y
    distance = gap_cx_css - initial_piece_cx_css

    info = {
        "backend": det["backend"],
        "score": det["score"],
        "gap_cx_img": det["gap_cx_img"],
        "gap_cy_img": det["gap_cy_img"],
        "scale_x": scale_x,
        "scale_y": scale_y,
        "initial_piece_cx_css": initial_piece_cx_css,
        "initial_piece_cy_css": initial_piece_cy_css,
        "gap_cx_css": gap_cx_css,
        "gap_cy_css": gap_cy_css,
        "distance_css": distance,
        "image_urls": images,
    }
    # (OUT_DIR / "gap_info.json").write_text(
    #     json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    # )

    if not (5 <= distance <= 360) or abs(gap_cy_css - initial_piece_cy_css) > 25:
        raise RuntimeError(
            f"缺口识别结果不合理: distance={distance:.1f}, y偏差={abs(gap_cy_css - initial_piece_cy_css):.1f}"
        )

    #print(f"[gap] backend={det['backend']} score={det['score']:.4f} distance={distance:.1f}px")
    return button_box, distance, info


async def reload_captcha(page, captcha) -> None:
    reload = captcha.locator("#reload")
    if await reload.is_visible():
        await reload.click()
    await page.wait_for_timeout(1500)


async def solve_once(page, captcha, backend: str, attempts_left: int) -> dict:
    try:
        button_box, distance, _ = await prepare_drag(page, captcha, backend)
    except Exception as exc:
        print(f"[retry] 识别失败: {exc}，剩余 {attempts_left - 1} 次")
        if attempts_left > 1:
            await reload_captcha(page, captcha)
            return await solve_once(page, captcha, backend, attempts_left - 1)
        raise

    button_cx = button_box["x"] + button_box["width"] / 2
    button_cy = button_box["y"] + button_box["height"] / 2

    await page.mouse.move(button_cx, button_cy, steps=8)
    await page.wait_for_timeout(random.randint(120, 260))
    await page.mouse.down()
    await page.wait_for_timeout(random.randint(80, 160))

    for x in build_track(distance):
        await page.mouse.move(
            button_cx + x,
            button_cy + random.uniform(-1.5, 1.5),
            steps=2,
        )
        await page.wait_for_timeout(random.randint(12, 28))

    await page.wait_for_timeout(random.randint(120, 240))
    await page.mouse.up()

    deadline = time.time() + 8
    while time.time() < deadline:
        success = await page.evaluate("window.__captchaResult || null")
        if success:
            return json.loads(success)
        if await captcha.locator("#statusFail").is_visible():
            break
        await page.wait_for_timeout(300)

    #print(f"[retry] 拖动失败，剩余 {attempts_left - 1} 次")
    if attempts_left > 1:
        await reload_captcha(page, captcha)
        return await solve_once(page, captcha, backend, attempts_left - 1)
    raise RuntimeError("滑块验证多次尝试后仍未通过")


async def _solve_captcha_async(
    max_tries: int = 3,
    backend: str = "auto",
    headed: bool = False,
    post_url: str = "",
    save_files: bool = True,
) -> dict:
    """异步核心逻辑，供 solve_captcha() 同步方法调用。"""
    if backend == "auto":
        backend = "ddddocr" if ddddocr is not None else "opencv"
    if backend == "ddddocr" and ddddocr is None:
        print("[warn] ddddocr 不可用，退回 OpenCV")
        backend = "opencv"

    post_log = []
    seen_requests = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 430, "height": 900},
            user_agent=UA,
            locale="zh-CN",
        )
        await context.add_init_script(JS_BRIDGE)
        page = await context.new_page()

        async def on_response(res) -> None:
            req = res.request
            if req.method != "POST":
                return
            key = f"{req.method} {req.url} {req.post_data or ''}"
            if key in seen_requests:
                return
            seen_requests.add(key)
            entry = {
                "method": req.method,
                "url": req.url,
                "post_data": req.post_data,
                "response_status": res.status,
            }
            try:
                entry["response_body"] = (await res.body()).decode("utf-8", errors="replace")
            except Exception:
                entry["response_body"] = None
            post_log.append(entry)
            #print(f"[post] {req.method} {req.url}")

        page.on("response", lambda res: asyncio.create_task(on_response(res)))

        await page.goto(CAPTCHA_URL, wait_until="domcontentloaded", timeout=60000)
        captcha = None
        for _ in range(60):
            captcha = page.frame(url="https://turing.captcha.qcloud.com/*")
            if captcha is not None:
                break
            await page.wait_for_timeout(500)
        if captcha is None:
            raise RuntimeError("验证码 iframe 没有出现")

        result = await solve_once(page, captcha, backend, max_tries)
        #print(f"[success] {json.dumps(result, ensure_ascii=False)}")
        await page.wait_for_timeout(2000)

        # if save_files:
        #     (OUT_DIR / "captcha_result.json").write_text(
        #         json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        #     )
        #     (OUT_DIR / "post_requests.json").write_text(
        #         json.dumps(post_log, ensure_ascii=False, indent=2), encoding="utf-8"
        #     )

        postback = None
        if post_url:
            resp = requests.post(
                post_url,
                data=result,
                headers={"User-Agent": UA},
                timeout=20,
            )
            postback = {"url": post_url, "status": resp.status_code, "body": resp.text}
            print(f"[postback] {json.dumps(postback, ensure_ascii=False)}")
            if save_files:
                (OUT_DIR / "postback_result.json").write_text(
                    json.dumps(postback, ensure_ascii=False, indent=2), encoding="utf-8"
                )

        await browser.close()

    return {
        # "success": True,
        "ret": result.get("ret"),
        "randstr": result.get("randstr"),
        "ticket": result.get("ticket"),
        # "posts": post_log,
        # "postback": postback,
    }


def solve_captcha(
    max_tries: int = 3,
    backend: str = "auto",
    headed: bool = False,
    post_url: str = "",
    save_files: bool = True,
) -> dict:
    """
    同步封装方法：过葫芦侠腾讯滑块验证。

    成功返回：
        {"success": True, "ret": 0, "randstr": "...", "ticket": "...", "posts": [...], "postback": ...}
    失败返回：
        {"success": False, "error": "错误原因", "detail": "详细异常信息"}
    """
    try:
        return asyncio.run(
            _solve_captcha_async(
                max_tries=max_tries,
                backend=backend,
                headed=headed,
                post_url=post_url,
                save_files=save_files,
            )
        )
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "detail": repr(exc),
        }
def getticket() ->dict:
    parser = argparse.ArgumentParser(description="葫芦侠腾讯滑块验证自动化")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--backend", choices=("auto", "ddddocr", "opencv"), default="auto")
    parser.add_argument("--max-tries", type=int, default=3)
    parser.add_argument("--post-url", default="", help="可选：成功后把 ticket/randstr POST 到该地址")
    # 使用 parse_known_args 避免劫持 main.py 的参数
    args, _ = parser.parse_known_args()

    result = solve_captcha(
        max_tries=args.max_tries,
        backend=args.backend,
        headed=args.headed,
        post_url=args.post_url,
    )
    return result





#发送验证码 手机号登录
def sendSMSmessage(
    ticket: str,
    rand: str,
    phone: str,
):
    url = "https://floor.huluxia.com/vcode/send/ANDROID/4.0"

    params = dict(DEFAULT_PARAMS)

    payload = {
        'phone': phone,
        'bussiness_type': "1",
        'send_type': "0",
        'ticket': ticket,
        'rand': rand,
    }

    headers = dict(DEFAULT_HEADERS)

    response = requests.post(url, params=params, data=payload, headers=headers)
    return response.json()


#提交验证码内容
def postverify(
    vcode: str,
    phone: str,
):
    url = "https://floor.huluxia.com/vcode/verify/ANDROID/4.0"

    params = dict(DEFAULT_PARAMS)

    payload = {
        'phone': phone,
        'bussiness_type': "1",
        'vcode': vcode,
    }

    headers = dict(DEFAULT_HEADERS)

    return requests.post(url, params=params, data=payload, headers=headers).json()


#通过手机号登录，查询用户消息消息
#重要！！！！
#注册账号需要先进行这一步
#voice_code 验证码
#判断是否需要设置密码
def post_account_data(phone: str, code: str):
    sign = f"account{phone}device_code{DEVICE_CODE}passwordvoice_code{code}cPqzc91RXPJlNiWSPrDpzJjo2YuiImtx"
    url = "https://floor.huluxia.com/account/login/ANDROID/4.2.6"

    params = dict(DEFAULT_PARAMS)

    payload = {
        'account': phone,
        'login_type': "1",
        'voice_code': code,
        'sign': Md5(sign),
    }

    headers = dict(DEFAULT_HEADERS)

    response = requests.post(url, params=params, data=payload, headers=headers).json()
    if response['status'] == 0:
        return {
            "status": response['status'],
            "msg": response['msg'],
        }
    else:
        return {
            "status": response['status'],
            "_key": response['_key'],
            "userID": response['user']['userID'],
            "needSetPassword": response['user']['needSetPassword'],
        }

def setVerify(key: str, password: str):
    url = "https://floor.huluxia.com/account/security/setPassword/ANDROID/4.0"

    params = dict(DEFAULT_PARAMS)
    params["_key"] = key

    payload = {
        'password': Md5(password),
    }

    headers = dict(DEFAULT_HEADERS)

    return requests.post(url, params=params, data=payload, headers=headers).json()

def Md5(data):
    return hashlib.md5(data.encode("UTF-8")).hexdigest()




def main() -> None:
    parser = argparse.ArgumentParser(description="葫芦侠验证码工具")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--backend", choices=("auto", "ddddocr", "opencv"), default="auto")
    parser.add_argument("--max-tries", type=int, default=3)
    parser.add_argument("--post-url", default="", help="可选：成功后把 ticket/randstr POST 到该地址")
    args, _ = parser.parse_known_args()

    result = solve_captcha(
        max_tries=args.max_tries,
        backend=args.backend,
        headed=args.headed,
        post_url=args.post_url,
    )

    if not result.get("ticket"):
        print("获取 Ticket 失败", file=sys.stderr)
        sys.exit(1)

    print("Ticket 获取成功:", result["ticket"])
    sys.exit(0)

if __name__ == "__main__":
    main()
