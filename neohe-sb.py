#!/usr/bin/env python3

import os
import re
import shutil
import sys
import time
from urllib.parse import urlparse

import requests
from seleniumbase import SB

NEOH_AUTH = os.environ.get("NEOH_AUTH", "")
NEOH_COOKIE = os.environ.get("NEOH_COOKIE", "").strip()
#NEOH_COOKIE = os.environ.get("NEOH_COOKIE","")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
PROXY = os.environ.get("PROXY", "socks://127.0.0.1:1080")
LOGIN_TYPE = os.environ.get("NEOH_LOGIN_TYPE", "auto").strip().lower()
TARGET_COINS = 25.0
CHECK_EVERY_ROUNDS = 500
MAX_CAPTCHA_FAILURES = max(int(os.environ.get("NEOH_MAX_CAPTCHA_FAILURES", "2")), 1)
LOGIN_TIMEOUT = min(int(os.environ.get("NEOH_LOGIN_TIMEOUT", "15")), 15)
ROUND_TIMEOUT = int(os.environ.get("NEOH_ROUND_TIMEOUT", "600"))
CONFIRM_TIMEOUT = min(int(os.environ.get("NEOH_CONFIRM_TIMEOUT", "30")), 30)
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
)

LOGIN_URL = "https://dash.neoheberg.fr/login"
DASHBOARD_URL = "https://dash.neoheberg.fr/"
SHOP_URL = "https://dash.neoheberg.fr/shop/ads.php"
LOGIN_FAILURE_SCREENSHOT = "neohe_login_failed.png"
LOGIN_CAPTCHA_SCREENSHOT = "neohe_login_captcha_after_10s.png"


USERNAME = ""
PASSWORD = ""
skip_next_start_round = False

def ensure_display_env():
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":1"
    if not os.environ.get("XAUTHORITY") and os.path.exists("/root/.Xauthority"):
        os.environ["XAUTHORITY"] = "/root/.Xauthority"
    print(f"DISPLAY={os.environ.get('DISPLAY')} XAUTHORITY={os.environ.get('XAUTHORITY')}")


def resolve_chrome_path():
    preferred = "/usr/bin/google-chrome"
    if os.path.exists(preferred):
        return preferred
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser") or preferred


def configure_browser_window(sb):
    try:
        sb.driver.set_window_rect(0, 0, 1920, 1080)
        print("🪟 已设置浏览器窗口尺寸为 1920x1080")
    except Exception as exc:
        print(f"⚠️ 设置浏览器窗口尺寸失败：{exc}")


def parse_auth(value):
    username, separator, password = value.partition(",")
    if not separator or not username.strip() or not password:
        raise ValueError("NEOH_AUTH 必须使用 username,password 格式")
    return username.strip(), password


def parse_cookie_string(value):
    cookies = []
    for part in value.split(";"):
        name, separator, cookie_value = part.strip().partition("=")
        if not separator or not name.strip():
            continue
        cookies.append((name.strip(), cookie_value.strip()))
    return cookies


def telegram_proxies():
    proxy_url = None
    if PROXY:
        proxy_url = PROXY if PROXY.startswith(("http://", "https://", "socks://", "socks5://")) else f"http://{PROXY}"
    return {"http": proxy_url, "https": proxy_url} if proxy_url else None


def send_tg(message):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": message},
            proxies=telegram_proxies(),
            timeout=15,
        )
        if response.ok:
            print("📨 Telegram 通知已发送")
        else:
            print(f"⚠️ Telegram 通知失败：HTTP {response.status_code}")
    except Exception as exc:
        print(f"⚠️ Telegram 通知异常：{exc}")


def send_tg_photo(photo_path, caption):
    if not TG_BOT_TOKEN or not TG_CHAT_ID or not os.path.exists(photo_path):
        return

    try:
        with open(photo_path, "rb") as photo:
            response = requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto",
                data={"chat_id": TG_CHAT_ID, "caption": caption},
                files={"photo": (os.path.basename(photo_path), photo, "image/png")},
                proxies=telegram_proxies(),
                timeout=30,
            )
        if response.ok:
            print(f"📸 Telegram 截图已发送：{photo_path}")
        else:
            print(f"⚠️ Telegram 截图发送失败：HTTP {response.status_code}")
    except Exception as exc:
        print(f"⚠️ Telegram 截图发送异常：{exc}")


def current_url(sb):
    try:
        return sb.get_current_url() or ""
    except Exception:
        return ""


def wait_until(predicate, timeout, interval=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def visible_element(sb, selectors):
    for selector in selectors:
        try:
            elements = sb.find_elements(selector)
            for element in elements:
                if element.is_displayed() and element.is_enabled():
                    return element, selector
        except Exception:
            continue
    return None, None


def click_element(sb, element, selector):
    try:
        sb.uc_click(selector, timeout=5)
        return True
    except Exception:
        try:
            sb.driver.execute_script("arguments[0].click();", element)
            return True
        except Exception as exc:
            print(f"⚠️ 点击 {selector} 失败：{exc}")
            return False


def save_login_failure(sb, reason):
    try:
        sb.save_screenshot(LOGIN_FAILURE_SCREENSHOT)
        print(f"📸 已保存登录失败截图：{LOGIN_FAILURE_SCREENSHOT}")
        send_tg_photo(LOGIN_FAILURE_SCREENSHOT, f"NeoHeberg 登录失败：{reason}\nURL：{current_url(sb)}")
    except Exception as exc:
        print(f"⚠️ 保存或发送登录失败截图异常：{exc}")

def dismiss_popups(sb):
    selectors = [
        "#dismiss-button",
        "#dismiss-button-element",
        ".close-button-outer",
        '[aria-label="Fermer l\'annonce"]',
    ]
    closed = 0
    for _ in range(3):
        element, selector = visible_element(sb, selectors)
        if not element:
            break
        if click_element(sb, element, selector):
            closed += 1
            time.sleep(0.4)
    if closed:
        print(f"🔕 已关闭弹窗 {closed} 次")
    return closed


def read_coins(sb):
    value = sb.execute_script(
        """
        const labels = [...document.querySelectorAll('p')];
        const label = labels.find((node) => node.textContent.trim() === 'Coins');
        if (!label) return null;
        const card = label.closest('div.bg-glass-light') || label.parentElement;
        const amount = card ? card.querySelector('h3') : label.nextElementSibling;
        return amount ? amount.textContent.trim() : null;
        """
    )
    if not value:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def read_login_debug(sb):
    try:
        return sb.execute_script(
            """
            const identifier = document.querySelector('#identifier');
            const password = document.querySelector('#password');
            const button = document.querySelector('form[action="./login"] button[type="submit"]');
            const tokens = [...document.querySelectorAll('input[name="cf-turnstile-response"]')]
                .map((node) => ({id: node.id, length: (node.value || '').length}));
            return {
                readyState: document.readyState,
                url: location.href,
                title: document.title,
                identifierPresent: !!identifier,
                identifierLength: identifier ? (identifier.value || '').length : 0,
                passwordPresent: !!password,
                passwordLength: password ? (password.value || '').length : 0,
                loginType: document.querySelector('#login_type')?.value || null,
                buttonPresent: !!button,
                buttonVisible: !!button && !!(button.offsetWidth || button.offsetHeight),
                buttonDisabled: !!button && button.disabled,
                buttonText: button ? button.innerText.trim() : null,
                turnstile: tokens,
            };
        """
        )
    except Exception as exc:
        return {"debugError": str(exc), "url": current_url(sb)}


def print_login_debug(sb, label):
    debug = read_login_debug(sb)
    print(f"🔎 登录调试（{label}）：{debug}")
    return debug


def click_login_button(sb, element, selector):
    try:
        sb.uc_click(selector, timeout=5)
        print("🖱 登录按钮点击方式：uc_click 已执行，停止重复提交")
        return True
    except Exception as exc:
        print(f"⚠️ uc_click 登录按钮失败：{exc}")

    try:
        element.click()
        print("🖱 登录按钮点击方式：selenium_click 已执行")
        return True
    except Exception as exc:
        print(f"⚠️ selenium_click 登录按钮失败：{exc}")

    try:
        sb.driver.execute_script("arguments[0].click();", element)
        print("🖱 登录按钮点击方式：javascript_click 已执行")
        return True
    except Exception as exc:
        print(f"⚠️ javascript_click 登录按钮失败：{exc}")
        return False


def fill_login_field(sb, selector, value, label):
    attempts = [
        ("clear_and_type", lambda: (sb.clear(selector), sb.type(selector, value, timeout=10))),
        ("send_keys", lambda: (sb.click(selector), sb.send_keys(selector, value))),
        ("javascript_value_event", lambda: sb.driver.execute_script(
            """
            const element = arguments[0];
            const value = arguments[1];
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(element, value);
            element.dispatchEvent(new Event('input', {bubbles: true}));
            element.dispatchEvent(new Event('change', {bubbles: true}));
            """,
            sb.find_element(selector),
            value,
        )),
    ]
    for name, action in attempts:
        try:
            action()
            actual_length = sb.execute_script(
                "return (document.querySelector(arguments[0])?.value || '').length;",
                selector,
            )
            print(f"📝 {label} 填写方式：{name}，当前长度：{actual_length}")
            if int(actual_length) == len(value):
                return True
        except Exception as exc:
            print(f"⚠️ {label} 填写方式 {name} 失败：{exc}")
    return False


def turnstile_state(sb):
    try:
        return sb.execute_script(
            """
            return {
                url: location.href,
                widgets: document.querySelectorAll('.cf-turnstile').length,
                iframes: document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]').length,
                tokens: [...document.querySelectorAll('input[name="cf-turnstile-response"]')]
                    .map((node) => ({id: node.id, length: (node.value || '').length})),
                securityError: /sécurité|security|échoué|failed/i.test(document.body?.innerText || ''),
            };
            """
        )
    except Exception as exc:
        return {"error": str(exc), "url": current_url(sb)}


def save_captcha_checkpoint(sb):
    try:
        sb.save_screenshot(LOGIN_CAPTCHA_SCREENSHOT)
        state = turnstile_state(sb)
        print(f"📸 认证后 10 秒截图已保存：{LOGIN_CAPTCHA_SCREENSHOT}")
        print(f"🔎 认证后 10 秒 Turnstile 状态：{state}")
        try:
            text = " ".join((sb.get_text("body") or "").split())
            print(f"🧾 认证后 10 秒页面文本尾部：{text[-1000:]}")
        except Exception as exc:
            print(f"⚠️ 读取认证后页面文本失败：{exc}")
        send_tg_photo(
            LOGIN_CAPTCHA_SCREENSHOT,
            f"NeoHeberg 登录认证后 10 秒截图\nURL：{current_url(sb)}\nTurnstile：{state}",
        )
    except Exception as exc:
        print(f"⚠️ 保存或发送认证后截图异常：{exc}")


def solve_login_turnstile(sb):
    print("🛡 处理登录页 Turnstile...")
    result = handle_cloudflare_challenge(sb, extra_sleep=8.0, max_retries=3)
    if result["success"]:
        print("✅ 登录页 Cloudflare 挑战已通过")
        save_captcha_checkpoint(sb)
        print_login_debug(sb, "登录页 Cloudflare 挑战处理后")
        return True
    print(f"❌ 登录页 Cloudflare 挑战未通过：{result}")
    save_captcha_checkpoint(sb)
    return False


def cookie_login(sb):
    if not NEOH_COOKIE:
        print("ℹ️ 未设置 NEOH_COOKIE，跳过 Cookie 登录")
        return False

    cookies = parse_cookie_string(NEOH_COOKIE)
    if not cookies:
        print("⚠️ NEOH_COOKIE 无有效 cookie，跳过 Cookie 登录")
        return False

    print(f"🍪 尝试 Cookie 登录，共 {len(cookies)} 个 cookie")
    try:
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=4)
        sb.wait_for_ready_state_complete()
        injected = 0
        for name, value in cookies:
            try:
                cookie = {"name": name, "value": value, "path": "/", "secure": True}
                if not name.startswith("__Host-"):
                    cookie["domain"] = ".neoheberg.fr"
                sb.driver.add_cookie(cookie)
                injected += 1
                print(f"🍪 已注入 cookie：{name}")
            except Exception as exc:
                print(f"⚠️ 注入 cookie {name} 失败：{exc}")
        print(f"🍪 Cookie 注入完成：{injected}/{len(cookies)}")
        sb.refresh()
        sb.wait_for_ready_state_complete()
        sb.sleep(2)
        if "dash.neoheberg.fr" in current_url(sb) and "/login" not in current_url(sb):
            print("✅ Cookie 登录成功")
            return True
        sb.open(DASHBOARD_URL, reconnect_time=4)
        print(f"🍪 Cookie 登录后页面：{current_url(sb)} | Title={sb.get_title() or ''}")
        sb.wait_for_ready_state_complete()
        sb.sleep(2)
        print(f"🍪 Cookie 登录面板检查：{current_url(sb)} | Title={sb.get_title() or ''}")
        if "/login" not in current_url(sb) and read_coins(sb) is not None:
            print("✅ Cookie 登录成功，Dashboard Coins 可读取")
            return True
        print("⚠️ Cookie 登录未成功，转入账号密码登录")
        return False
    except Exception as exc:
        print(f"⚠️ Cookie 登录异常：{exc}")
        return False


def ensure_login_fields(sb, stage_name=""):
    """智能检查并填写账号密码：仅在未填写或长度不匹配时才执行填写"""
    prefix = f"（{stage_name}）" if stage_name else ""
    
    # 检查 identifier
    id_len = sb.execute_script("return (document.querySelector('#identifier')?.value || '').length;")
    if int(id_len) != len(USERNAME):
        print(f"📧 填写账号/邮箱{prefix}...")
        if not fill_login_field(sb, "#identifier", USERNAME, f"identifier{prefix}"):
            return False
    else:
        print(f"✅ identifier 已确认{prefix}")

    # 检查 password
    pw_len = sb.execute_script("return (document.querySelector('#password')?.value || '').length;")
    if int(pw_len) != len(PASSWORD):
        print(f"🔑 填写密码{prefix}...")
        if not fill_login_field(sb, "#password", PASSWORD, f"password{prefix}"):
            return False
    else:
        print(f"✅ password 已确认{prefix}")

    return True


def login(sb):
    if cookie_login(sb):
        return True
    if not USERNAME or not PASSWORD:
        print("❌ Cookie 登录失败，且未提供有效 NEOH_AUTH，无法回退到账号密码登录")
        return False

    print("🔐 Cookie 登录未通过，转入账号密码登录")
    print("🌐 打开 NeoHeberg 登录页面...")
    sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=4)
    sb.wait_for_ready_state_complete()
    sb.sleep(1)
    sb.execute_script("window.scrollBy(0, 300);")
    # 1. 初次填写账号密码
    if not ensure_login_fields(sb):
        print_login_debug(sb, "账号密码初次填写失败")
        save_login_failure(sb, "账号密码初次填写失败")
        return False

    # 2. 处理 Cloudflare Turnstile 验证
    if not solve_login_turnstile(sb):
        print_login_debug(sb, "Turnstile 处理失败")
        save_login_failure(sb, "登录页 Turnstile 处理失败")
        return False

    state = turnstile_state(sb)
    if state.get("securityError"):
        print("❌ 认证后页面明确报告安全验证失败，不提交登录表单")
        save_login_failure(sb, "认证后 Turnstile 验证失败")
        return False

    # 3. 检查表单状态：只有在 DOM 被 CF 刷新清空时才补填
    if not ensure_login_fields(sb, stage_name="过盾后校验"):
        print_login_debug(sb, "过盾后账号密码校验/补填失败")
        save_login_failure(sb, "过盾后账号密码校验失败")
        return False

    # 4. 查找并点击登录按钮
    submit_selector = 'form[action="./login"] button[type="submit"]'
    print(f"🔍 查找登录按钮：{submit_selector}")
    if not wait_until(lambda: bool(visible_element(sb, [submit_selector])[0]), 10):
        print_login_debug(sb, "找不到登录按钮")
        save_login_failure(sb, "找不到登录按钮")
        return False

    element, _ = visible_element(sb, [submit_selector])
    try:
        sb.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    except Exception as exc:
        print(f"⚠️ 滚动登录按钮失败：{exc}")

    clicked = click_login_button(sb, element, submit_selector)
    print(f"🖱 登录按钮点击结果：{'成功' if clicked else '失败'}")
    if not clicked:
        save_login_failure(sb, "登录按钮点击失败")
        return False

    # 5. 等待页面跳转
    print(f"⏳ 点击完成，等待登录跳转，最多 {LOGIN_TIMEOUT} 秒...")
    deadline = time.monotonic() + LOGIN_TIMEOUT
    last_url = None
    while time.monotonic() < deadline:
        url = current_url(sb)
        if url != last_url:
            print(f"📄 登录等待：URL={url} | Title={sb.get_title() or ''}")
            last_url = url
        if "dash.neoheberg.fr" in url and "/login" not in url:
            print(f"✅ 登录成功：{url}")
            print_login_debug(sb, "登录跳转成功")
            return True
        time.sleep(1)

    print(f"❌ 登录超时（已等待 {LOGIN_TIMEOUT} 秒），当前页面：{current_url(sb)}")
    save_login_failure(sb, f"点击登录后 {LOGIN_TIMEOUT} 秒仍未跳转")
    return False


def wait_for_dashboard(sb):
    print("🏠 返回 Tableau de bord · NeoHeberg 查询 Coins...")
    global skip_next_start_round
    skip_next_start_round=False
    sb.uc_open_with_reconnect(DASHBOARD_URL, reconnect_time=4)
    sb.wait_for_ready_state_complete()
    if not wait_until(lambda: read_coins(sb) is not None, 30):
        print(f"❌ Dashboard Coins 读取失败，当前页面：{current_url(sb)}")
        return False
    return True


def report_coins(sb, reason):
    if not wait_for_dashboard(sb):
        message = f"⚠️ 无法读取 Dashboard Coins（{reason}），当前页面：{current_url(sb)}"
        print(message)
        send_tg(message)
        return None

    coins = read_coins(sb)
    if coins is None:
        message = f"⚠️ Dashboard Coins 读取失败（{reason}）"
        print(message)
        send_tg(message)
        return None

    message = f"💰 NeoHeberg Dashboard Coins：{coins:.2f}（{reason}）"
    print(message)
    send_tg(message)
    return coins


def restart_ad_flow(sb, reason):
    print(f"🔁 {reason}，返回 Publicités - NeoHeberg 重启流程...")
    try:
        sb.uc_open_with_reconnect(SHOP_URL, reconnect_time=4)
        sb.wait_for_ready_state_complete()
        dismiss_popups(sb)
        print(f"✅ 已返回 Publicités 页面：{current_url(sb)}")
        return True
    except Exception as exc:
        print(f"⚠️ 返回 Publicités 页面失败：{exc}")
        return False


def start_round(sb):
    print("🛒 打开广告页面...")
    sb.uc_open_with_reconnect(SHOP_URL, reconnect_time=4)
    sb.wait_for_ready_state_complete()
    dismiss_popups(sb)

    start_selector = 'button[type="submit"]:contains("Commencer")'
    if not wait_until(lambda: bool(visible_element(sb, [start_selector])[0]), 30):
        print(f"❌ 未找到“Commencer”按钮，当前页面：{current_url(sb)}")
        return False

    element, _ = visible_element(sb, [start_selector])
    if not click_element(sb, element, start_selector):
        return False
    print("✅ 已点击“Commencer”")
    return True


def wait_for_clipurl(sb):
    print("⏳ 等待跳转到 clipurl.fr...")

    def on_clipurl():
        hostname = urlparse(current_url(sb)).hostname
        return hostname in {"clipurl.fr", "www.clipurl.fr"}

    if not wait_until(on_clipurl, 90):
        print(f"❌ 未进入 clipurl.fr，当前页面：{current_url(sb)}")
        return False
    print(f"✅ 已进入：{current_url(sb)}")
    return True


def read_score(sb):
    try:
        text = sb.get_text("#score")
    except Exception:
        return None
    match = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def play_target_game(sb):
    print("🎯 开始点击 target 游戏...")
    if not wait_until(lambda: bool(visible_element(sb, ["#target"])[0]), 60):
        print("❌ 未找到 #target")
        return False

    score = read_score(sb)
    target_count = score[1] if score else 5
    clicked = score[0] if score else 0

    while clicked < target_count:
        dismiss_popups(sb)
        if not wait_until(lambda: bool(visible_element(sb, ["#target"])[0]), 15):
            print(f"❌ 等待 #target 超时，进度 {clicked}/{target_count}")
            return False

        element, _ = visible_element(sb, ["#target"])
        if not click_element(sb, element, "#target"):
            return False

        if not wait_until(
            lambda: (read_score(sb) or (clicked, target_count))[0] > clicked,
            10,
            0.2,
        ):
            print(f"❌ 点击后计数器没有增加，当前进度 {clicked}/{target_count}")
            return False

        score = read_score(sb)
        clicked = score[0] if score else clicked + 1
        print(f"🎯 target 进度：{clicked}/{target_count}")

    print(f"✅ target 游戏完成：{clicked}/{target_count}")
    return True


def reconnect_after_captcha(sb, label):
    print(f"🔌 {label}，重新连接浏览器驱动...")
    try:
        sb.reconnect(timeout=10)
        sb.wait_for_ready_state_complete()
        sb.sleep(1)
        print(f"✅ {label}，浏览器驱动已恢复：{current_url(sb)}")
        return True
    except Exception as exc:
        print(f"❌ {label}，浏览器驱动恢复失败：{exc}")
        return False


def round_captcha_state(sb):
    try:
        return sb.execute_script(
            """
            const iframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
            const widget = document.querySelector('.cf-turnstile');
            const response = [...document.querySelectorAll('input[name="cf-turnstile-response"]')]
                .map((node) => ({id: node.id, length: (node.value || '').length}));
            const rect = iframe ? iframe.getBoundingClientRect() : null;
            return {
                url: location.href,
                widget: !!widget,
                iframe: !!iframe,
                iframeWidth: rect ? Math.round(rect.width) : 0,
                iframeHeight: rect ? Math.round(rect.height) : 0,
                response,
                bodyText: (document.body?.innerText || '').slice(-500),
            };
            """
        )
    except Exception as exc:
        return {"error": str(exc), "url": current_url(sb)}


def wait_for_round_captcha(sb):
    print("⏳ 等待本轮 Turnstile 组件出现...")
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        try:
            state = round_captcha_state(sb)
            if state.get("widget") or state.get("iframe") or state.get("response"):
                print(f"✅ 检测到 Turnstile 组件：{state}")
                break
        except Exception:
            pass
        time.sleep(0.5)
    sb.sleep(2)
    result = handle_cloudflare_challenge(sb, extra_sleep=0.1, max_retries=1, forward=True)
    if not result["success"]:
        print(f"❌ 本轮 Cloudflare 挑战未通过：{result}")
        return {"success": False, "jumped": False}
    print("✅ 本轮 Cloudflare 挑战已通过")
    return {"success": True, "jumped": bool(result.get("jumped"))}


def wait_for_round_completion(sb):
    print("⏳ 轻量检查本轮确认页是否已出现...")
    started_at = time.monotonic()
    last_url = None
    deadline = started_at + 5.0

    def completed():
        nonlocal last_url
        url = current_url(sb)
        if url != last_url:
            print(f"📄 本轮确认检查：URL={url}")
            last_url = url
        parsed = urlparse(url)
        return (
            parsed.hostname == "dash.neoheberg.fr"
            and parsed.path.rstrip("/") == "/shop/ads"
            and bool(parsed.query)
            and "token=" in parsed.query
        )

    if completed():
        print(f"✅ 本轮已看到确认页：{current_url(sb)}")
        return True

    while time.monotonic() < deadline:
        if completed():
            return True
        time.sleep(0.5)

    elapsed = int(time.monotonic() - started_at)
    print(f"ℹ️ 本轮确认页未在 {elapsed} 秒内出现，按 Turnstile 已处理成功继续下一步，当前页面：{current_url(sb)}")
    return True


def handle_cloudflare_challenge(sb: SB, extra_sleep: float = 8.0, max_retries: int = 3, forward: bool | None = None) -> dict:
    result = {"success": False, "challenge_detected": False, "challenge_handled": False, "error": None}

    def is_challenge_cleared():
        try:
            page_source = sb.get_page_source()
            source_lower = page_source.lower()
            challenge_keywords = ["just a moment", "verify you are human", "checking your browser"]
            if any(keyword in source_lower for keyword in challenge_keywords):
                return False
            token_patterns = [
                r'name="cf-turnstile-response"[^>]*value="(?!\s*")[^"<>]+',
                r'name="g-recaptcha-response"[^>]*value="(?!\s*")[^"<>]+',
            ]
            if any(re.search(pattern, page_source, re.IGNORECASE) for pattern in token_patterns):
                return True
            success_markers = ["success!", "verification complete", "cloudflare verification complete", "challenge passed"]
            return any(marker in source_lower for marker in success_markers)
        except Exception:
            return False

    try:
        print("🔎 检测当前页面是否有 Cloudflare 挑战...")
        page_source_lower = sb.get_page_source().lower()
        indicators = [
            "turnstile",
            "challenges.cloudflare",
            "just a moment",
            "verify you are human",
            "checking your browser",
            "cf-browser-verification",
            "cf-turnstile",
        ]
        result["challenge_detected"] = any(item in page_source_lower for item in indicators)
        if not result["challenge_detected"]:
            print("✅ 未检测到 Cloudflare 挑战")
            result["success"] = True
            return result

        result["challenge_handled"] = True
        print("🛡 检测到 Cloudflare 挑战，开始处理...")
        # configure_browser_window(sb)
        start_url = current_url(sb) or ""

        for attempt in range(1, max_retries + 1):
            print(f"🛡 第 {attempt}/{max_retries} 次执行 sb.uc_gui_click_captcha()...")
            try:
                sb.uc_gui_click_captcha()
                print("✅ sb.uc_gui_click_captcha() 已返回")
            except Exception as exc:
                print(f"⚠️ sb.uc_gui_click_captcha() 执行异常：{exc}")
            print(f"⏳ 等待 Cloudflare 验证结果 {extra_sleep:.1f} 秒...")
            sb.sleep(extra_sleep)
            try:
                sb.reconnect(timeout=10)
                sb.wait_for_ready_state_complete()
            except Exception as exc:
                print(f"⚠️ Cloudflare 处理后重连失败：{exc}")

            current_url_after = current_url(sb) or ""
            if forward is True and start_url and current_url_after and current_url_after != start_url:
                print(f"✅ Cloudflare 处理后页面已跳转：{start_url} -> {current_url_after}")
                result["success"] = True
                result["jumped"] = True
                return result

            if forward is not True and is_challenge_cleared():
                print("✅ Cloudflare 挑战已通过")
                result["success"] = True
                return result
            print("⚠️ Cloudflare 挑战仍未通过，准备重试")

        result["error"] = "Max retries reached, challenge not cleared."
        print("❌ 达到最大重试次数，Cloudflare 挑战仍未通过")
    except Exception as exc:
        result["error"] = str(exc)
        print(f"❌ 处理 Cloudflare 时出错：{exc}")
    return result


def run():
    global USERNAME, PASSWORD
    if NEOH_AUTH:
        try:
            USERNAME, PASSWORD = parse_auth(NEOH_AUTH)
        except ValueError as exc:
            print(f"❌ {exc}")
            return 1
    elif NEOH_COOKIE:
        print("ℹ️ 未设置 NEOH_AUTH，将优先尝试 NEOH_COOKIE 登录；如需账号密码登录请提供 NEOH_AUTH")
    else:
        print("❌ 必须设置 NEOH_COOKIE 或 NEOH_AUTH")
        return 1

    print("🚀 启动 NeoHeberg 自动续赚脚本")
    if PROXY:
        print(f"🌐 使用代理：{PROXY}")

    ensure_display_env()

    try:
        chrome_path = resolve_chrome_path()
        chromium_args = (
            f"--user-agent={USER_AGENT},"
            "--disable-blink-features=AutomationControlled,"
            "--no-sandbox,--disable-dev-shm-usage,--disable-gpu,--window-size=1920,1080"
        )
        print(f"🖥️ 使用浏览器路径：{chrome_path}")
        with SB(
            uc=True,
            headless=False,
            xvfb=True,
            incognito=True,
            proxy=PROXY,
            agent=USER_AGENT,
            binary_location=chrome_path,
            chromium_arg=chromium_args,
        ) as sb:
            configure_browser_window(sb)
            if not login(sb):
                message = "❌ NeoHeberg 登录失败"
                print(message)
                send_tg(message)
                return 1

            coins = report_coins(sb, "登录后")
            if coins is not None and coins >= TARGET_COINS:
                message = f"🎉 Coins 已达到目标 {TARGET_COINS:.2f}，停止操作。"
                print(message)
                send_tg(message)
                return 0

            rounds = 0
            captcha_failures = 0
            global skip_next_start_round
            while True:
                if skip_next_start_round:
                    print("⏭️ 上一轮 Turnstile 已发生页面跳转，跳过本次 start_round")
                    skip_next_start_round = False
                else:
                    if not start_round(sb):
                        send_tg("❌ 未能开始 NeoHeberg 新一轮任务")
                        if not restart_ad_flow(sb, "开始广告失败"):
                            return 1
                        continue
                if not wait_for_clipurl(sb):
                    send_tg("❌ 本轮未进入 clipurl.fr，尝试重启广告流程")
                    if not restart_ad_flow(sb, "未进入 clipurl.fr"):
                        return 1
                    continue
                if not play_target_game(sb):
                    send_tg("❌ 本轮 target 游戏失败，尝试重启广告流程")
                    if not restart_ad_flow(sb, "target 游戏失败"):
                        return 1
                    continue
                captcha_result = wait_for_round_captcha(sb)
                if not captcha_result["success"]:
                    captcha_failures += 1
                    message = f"❌ 本轮 Turnstile 未完成（连续失败 {captcha_failures}/{MAX_CAPTCHA_FAILURES}）"
                    print(message)
                    send_tg(message)
                    if captcha_failures >= MAX_CAPTCHA_FAILURES:
                        print("🛑 Turnstile 连续失败达到上限，保存截图并退出")
                        try:
                            sb.save_screenshot("neohe_captcha_failed.png")
                            print("📸 已保存 Turnstile 失败截图：neohe_captcha_failed.png")
                            send_tg_photo("neohe_captcha_failed.png", f"NeoHeberg Turnstile 连续失败 {captcha_failures} 次\nURL：{current_url(sb)}")
                        except Exception as exc:
                            print(f"⚠️ 保存或发送 Turnstile 失败截图异常：{exc}")
                        return 1
                    if not restart_ad_flow(sb, "本轮 Turnstile 未完成"):
                        return 1
                    continue
                if captcha_result.get("jumped"):
                    print("🔁 本轮 Turnstile 已发生页面跳转，下一轮将跳过一次 start_round")
                    skip_next_start_round = True
                if not wait_for_round_completion(sb):
                    captcha_failures += 1
                    message = f"❌ 本轮确认页未返回，视为 Turnstile 失败（连续失败 {captcha_failures}/{MAX_CAPTCHA_FAILURES}）"
                    print(message)
                    send_tg(message)
                    if captcha_failures >= MAX_CAPTCHA_FAILURES:
                        print("🛑 Turnstile 连续失败达到上限，保存截图并退出")
                        try:
                            sb.save_screenshot("neohe_captcha_failed.png")
                            print("📸 已保存 Turnstile 失败截图：neohe_captcha_failed.png")
                            send_tg_photo("neohe_captcha_failed.png", f"NeoHeberg Turnstile/确认页连续失败 {captcha_failures} 次\nURL：{current_url(sb)}")
                        except Exception as exc:
                            print(f"⚠️ 保存或发送 Turnstile 失败截图异常：{exc}")
                        return 1
                    if not restart_ad_flow(sb, "确认页面超时"):
                        return 1
                    continue

                captcha_failures = 0
                rounds += 1
                print(f"✅ 已完成第 {rounds} 轮")
                if rounds % CHECK_EVERY_ROUNDS == 0:
                    coins = report_coins(sb, f"完成 {rounds} 轮后")
                    if coins is not None and coins >= TARGET_COINS:
                        message = f"🎉 Coins 达到目标：{coins:.2f}，共完成 {rounds} 轮，脚本停止。"
                        print(message)
                        send_tg(message)
                        return 0
                    if coins is None:
                        print("⚠️ Dashboard Coins 暂时无法读取，返回 Publicités 页面继续流程")
                        restart_ad_flow(sb, f"完成 {rounds} 轮后的 Coins 查询失败")

    except KeyboardInterrupt:
        print("\n⏹️ 用户中断脚本")
        send_tg("⏹️ NeoHeberg 脚本已手动中断")
        return 130
    except Exception as exc:
        message = f"❌ 脚本异常：{exc}"
        print(message)
        send_tg(message)
        return 1


if __name__ == "__main__":
    sys.exit(run())
