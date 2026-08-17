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
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
PROXY = os.environ.get("PROXY", "socks://127.0.0.1:1080")
LOGIN_TYPE = os.environ.get("NEOH_LOGIN_TYPE", "auto").strip().lower()
TARGET_COINS = 25.0
CHECK_EVERY_ROUNDS = 500
MAX_CAPTCHA_FAILURES = max(int(os.environ.get("NEOH_MAX_CAPTCHA_FAILURES", "5")), 1)
LOGIN_TIMEOUT = min(int(os.environ.get("NEOH_LOGIN_TIMEOUT", "20")), 20)
ROUND_TIMEOUT = int(os.environ.get("NEOH_ROUND_TIMEOUT", "600"))
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


def dismiss_popups(sb):
    selectors = [
        "#dismiss-button",
        "#dismiss-button-element",
        ".close-button-outer",
        '[aria-label="Fermer l\'annonce"]',
        ".fc-cta-consent",
        "button.fc-primary-button",
        ".cmpboxbtn-yes",
    ]
    closed = 0
    for _ in range(3):
        element, selector = visible_element(sb, selectors)
        if not element:
            break
        if click_element(sb, element, selector):
            closed += 1
            time.sleep(0.4)

    try:
        js_click = sb.execute_script("""
            var clicked = false;
            var elems = document.querySelectorAll('button, p.fc-button-label, a, span');
            for (var i = 0; i < elems.length; i++) {
                var text = elems[i].innerText.trim().toLowerCase();
                if (text === 'consent' || text === 'accepter' || text === 'accept all' || text === 'agree' || text === 'tout accepter' || text === 'i accept') {
                    elems[i].click();
                    clicked = true;
                    break;
                }
            }
            return clicked;
        """)
        if js_click:
            closed += 1
    except:
        pass
    return closed


def read_coins(sb):
    try:
        value = sb.execute_script("""
            var allElements = document.querySelectorAll('p, span, div, h2, h3, h4');
            for (var i = 0; i < allElements.length; i++) {
                var el = allElements[i];
                if ((el.innerText || '').trim() === 'Coins') {
                    var parent = el.parentElement;
                    if (parent) {
                        var text = parent.innerText;
                        var m = text.match(/(\\d+[.,]\\d+)/);
                        if (m) return m[1];
                    }
                }
            }
            for (var j = 0; j < allElements.length; j++) {
                var item = allElements[j];
                var t = (item.innerText || '').trim();
                var match = t.match(/(\\d+[.,]\\d+)\\s*coins/i);
                if (match) return match[1];
            }
            return null;
        """)
        if not value:
            return None
        match = re.search(r"\d+(?:[.,]\d+)?", str(value))
        if not match:
            return None
        return float(match.group(0).replace(",", "."))
    except Exception:
        return None


# ==========================================================
# 1. 登录页专属：Cloudflare Turnstile 验证器
# ==========================================================
def solve_login_turnstile(sb: SB, max_retries: int = 3, wait_per_try: int = 8) -> bool:
    print("🛡 处理登录页 Cloudflare Turnstile 验证...")
    for attempt in range(1, max_retries + 1):
        dismiss_popups(sb)

        has_passed = sb.execute_script("""
            var tokens = [...document.querySelectorAll('input[name="cf-turnstile-response"]')];
            return tokens.some(t => t.value && t.value.length > 20);
        """)
        if has_passed:
            print("✅ 登录页 Cloudflare 验证已生成有效 Token！")
            return True

        print(f"🛡 [登录页第 {attempt}/{max_retries} 次尝试] 触发 Turnstile 点击...")
        try:
            sb.uc_gui_click_captcha()
        except Exception:
            pass

        try:
            sb.execute_script("""
                var iframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
                if (iframe) {
                    var rect = iframe.getBoundingClientRect();
                    var x = rect.left + rect.width / 2;
                    var y = rect.top + rect.height / 2;
                    var el = document.elementFromPoint(x, y);
                    if (el) el.click();
                }
            """)
        except Exception:
            pass

        deadline = time.monotonic() + wait_per_try
        while time.monotonic() < deadline:
            time.sleep(1)
            token_ready = sb.execute_script("""
                var tokens = [...document.querySelectorAll('input[name="cf-turnstile-response"]')];
                return tokens.some(t => t.value && t.value.length > 20);
            """)
            if token_ready or "dash.neoheberg.fr" in current_url(sb) and "/login" not in current_url(sb):
                print("✅ 登录页 Cloudflare 挑战通过！")
                time.sleep(1.5)
                return True

    return False


# ==========================================================
# 2. 广告页专属：自建 CapJS 方框模拟点击器
# ==========================================================
def click_custom_checkbox(sb: SB) -> bool:
    dismiss_popups(sb)

    clicked = sb.execute_script("""
        var checkboxes = document.querySelectorAll('input[type="checkbox"]');
        for (var i = 0; i < checkboxes.length; i++) {
            if (!checkboxes[i].checked) {
                checkboxes[i].scrollIntoView({block: 'center'});
                ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(evt => {
                    checkboxes[i].dispatchEvent(new MouseEvent(evt, { bubbles: true, cancelable: true, view: window }));
                });
                return true;
            }
        }

        var all = document.querySelectorAll('div, label, span, p, button');
        for (var j = 0; j < all.length; j++) {
            var el = all[j];
            var txt = (el.innerText || '').toLowerCase();
            if (txt.includes('vérifiez que vous êtes humain') || txt.includes('verifiez que vous etes humain')) {
                var target = el.querySelector('input, span, div') || el;
                target.scrollIntoView({block: 'center'});
                ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(evt => {
                    target.dispatchEvent(new MouseEvent(evt, { bubbles: true, cancelable: true, view: window }));
                });
                return true;
            }
        }
        return false;
    """)

    if clicked:
        print("✅ 成功命中并点击了验证方框！")
        return True

    selectors = [
        "input[type='checkbox']",
        "label:contains('Vérifiez')",
        "div:contains('Vérifiez que vous êtes humain')",
        ".captcha-checkbox",
        "#cap-checkbox",
    ]
    element, sel = visible_element(sb, selectors)
    if element and click_element(sb, element, sel):
        print(f"✅ 成功点击选择器：{sel}")
        return True

    return False


def cookie_login(sb):
    if not NEOH_COOKIE:
        return False

    cookies = parse_cookie_string(NEOH_COOKIE)
    if not cookies:
        return False

    print(f"🍪 尝试 Cookie 登录，共 {len(cookies)} 个 cookie")
    try:
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=4)
        sb.wait_for_ready_state_complete()
        for name, value in cookies:
            try:
                cookie = {"name": name, "value": value, "path": "/", "secure": True}
                if not name.startswith("__Host-"):
                    cookie["domain"] = ".neoheberg.fr"
                sb.driver.add_cookie(cookie)
            except Exception:
                pass
        sb.refresh()
        sb.wait_for_ready_state_complete()
        sb.sleep(2)
        if "dash.neoheberg.fr" in current_url(sb) and "/login" not in current_url(sb):
            print("✅ Cookie 登录成功")
            return True
        return False
    except Exception:
        return False


def ensure_login_fields(sb):
    try:
        sb.type("#identifier", USERNAME, timeout=5)
        sb.type("#password", PASSWORD, timeout=5)
        return True
    except Exception as exc:
        print(f"⚠️ 账号密码填写异常：{exc}")
        return False


def login(sb):
    if cookie_login(sb):
        return True
    if not USERNAME or not PASSWORD:
        print("❌ Cookie 登录失败，且未提供有效 NEOH_AUTH，无法转入账号密码登录")
        return False

    print("🔐 转入账号密码登录...")
    sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=4)
    sb.wait_for_ready_state_complete()
    sb.sleep(1)

    if not ensure_login_fields(sb):
        return False

    # 登录页过 Cloudflare Turnstile
    solve_login_turnstile(sb, max_retries=3, wait_per_try=6)

    submit_selector = 'form[action="./login"] button[type="submit"]'
    if not wait_until(lambda: bool(visible_element(sb, [submit_selector])[0]), 10):
        return False

    element, _ = visible_element(sb, [submit_selector])
    click_element(sb, element, submit_selector)

    deadline = time.monotonic() + LOGIN_TIMEOUT
    while time.monotonic() < deadline:
        url = current_url(sb)
        if "dash.neoheberg.fr" in url and "/login" not in url:
            print(f"✅ 登录成功：{url}")
            return True
        time.sleep(1)

    print(f"❌ 登录超时，当前页面：{current_url(sb)}")
    return False


def ensure_logged_in(sb):
    url = current_url(sb)
    if "/login" in url or "Connexion" in (sb.get_title() or ""):
        print("⚠️ 检测到 Session 过期/掉线，正在自动重新登录...")
        return login(sb)
    return True


def start_round(sb):
    print("🛒 打开广告页面...")
    sb.uc_open_with_reconnect(SHOP_URL, reconnect_time=4)
    sb.wait_for_ready_state_complete()
    dismiss_popups(sb)

    if not ensure_logged_in(sb):
        return False

    if "/shop/ads" not in current_url(sb):
        sb.uc_open_with_reconnect(SHOP_URL, reconnect_time=4)
        sb.wait_for_ready_state_complete()
        dismiss_popups(sb)

    commencer_selectors = [
        'button[type="submit"]:contains("Commencer")',
        'button:contains("Commencer")',
        'a:contains("Commencer")',
        'button.btn:contains("Commencer")',
        'a.btn:contains("Commencer")',
        '.btn-success:contains("Commencer")',
        '//button[contains(translate(., "COMMENCER", "commencer"), "commencer")]',
        '//a[contains(translate(., "COMMENCER", "commencer"), "commencer")]',
    ]

    if not wait_until(lambda: any(bool(visible_element(sb, [sel])[0]) for sel in commencer_selectors), 15):
        if "Mode automatique" in (sb.get_page_source() or ""):
            print("ℹ️ 广告系统处于自动运行中...")
            return True
        print(f"❌ 未找到“Commencer”按钮，当前页面：{current_url(sb)}")
        return False

    for sel in commencer_selectors:
        element, matched_sel = visible_element(sb, [sel])
        if element:
            if click_element(sb, element, matched_sel):
                print(f"✅ 已点击“Commencer” ({matched_sel})")
                return True

    return False


def wait_for_clipurl(sb):
    print("⏳ 等待跳转到 clipurl.fr...")

    def on_clipurl():
        if len(sb.driver.window_handles) > 1:
            sb.switch_to_tab(sb.driver.window_handles[-1])
        return "clipurl.fr" in urlparse(current_url(sb)).hostname

    if not wait_until(on_clipurl, 50):
        print(f"❌ 未进入 clipurl.fr，当前页面：{current_url(sb)}")
        ensure_logged_in(sb)
        return False
    print(f"✅ 已进入：{current_url(sb)}")
    return True


# ==========================================================
# 3. ClipURL 4 步流执行逻辑
# ==========================================================
def solve_clipurl_pipeline(sb):
    print("🚀 开始执行 ClipURL 4 步流程...")
    sb.wait_for_ready_state_complete()
    dismiss_popups(sb)

    # 步骤 1: 首页方框点击
    print("🛡 [步骤 1/4] 点击首页自建验证方框...")
    for _ in range(5):
        if click_custom_checkbox(sb):
            break
        time.sleep(1)

    # 步骤 2 & 3: 缓冲与 Attente
    print("⏳ [步骤 2 & 3] 等待系统推进与缓冲倒计时...")
    time.sleep(5)
    dismiss_popups(sb)

    # 步骤 4: 最终 Vérif 验证
    print("🛡 [步骤 4/4] 点击最终 Vérif 验证方框...")
    for _ in range(5):
        click_custom_checkbox(sb)
        time.sleep(1)

    # 等待自动跳回 NeoHeberg
    print("⏳ 等待页面跳转回 NeoHeberg 控制台...")
    deadline = time.monotonic() + 35.0
    while time.monotonic() < deadline:
        dismiss_popups(sb)

        if len(sb.driver.window_handles) > 1:
            for handle in sb.driver.window_handles:
                sb.driver.switch_to.window(handle)
                if "dash.neoheberg.fr" in current_url(sb):
                    break

        url = current_url(sb)
        if "dash.neoheberg.fr" in url and "/login" not in url:
            print(f"🎉 页面已成功跳转回 NeoHeberg：{url}")
            if len(sb.driver.window_handles) > 1:
                current_handle = sb.driver.current_window_handle
                for handle in sb.driver.window_handles:
                    if handle != current_handle:
                        sb.driver.switch_to.window(handle)
                        sb.driver.close()
                sb.driver.switch_to.window(current_handle)
            return True

        click_custom_checkbox(sb)
        time.sleep(1.5)

    return "dash.neoheberg.fr" in current_url(sb) and "/login" not in current_url(sb)


def report_coins(sb, reason):
    time.sleep(2)
    coins = read_coins(sb)
    if coins is not None:
        message = f"💰 NeoHeberg Coins：{coins:.4f}（{reason}）"
        print(message)
        send_tg(message)
    return coins


def restart_ad_flow(sb, reason):
    print(f"🔁 {reason}，返回 Publicités 重启流程...")
    try:
        ensure_logged_in(sb)
        sb.uc_open_with_reconnect(SHOP_URL, reconnect_time=4)
        sb.wait_for_ready_state_complete()
        dismiss_popups(sb)
        return True
    except Exception as exc:
        print(f"⚠️ 返回 Publicités 失败：{exc}")
        return False


def run():
    global USERNAME, PASSWORD
    if NEOH_AUTH:
        try:
            USERNAME, PASSWORD = parse_auth(NEOH_AUTH)
        except ValueError as exc:
            print(f"❌ {exc}")
            return 1
    elif NEOH_COOKIE:
        print("ℹ️ 使用 NEOH_COOKIE 登录")
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

            report_coins(sb, "登录后")

            rounds = 0
            fail_streak = 0
            while True:
                if not start_round(sb):
                    if not restart_ad_flow(sb, "未能点击 Commencer"):
                        return 1
                    time.sleep(2)

                if not wait_for_clipurl(sb):
                    fail_streak += 1
                    if fail_streak >= MAX_CAPTCHA_FAILURES:
                        return 1
                    restart_ad_flow(sb, "未进入 clipurl")
                    continue

                if not solve_clipurl_pipeline(sb):
                    fail_streak += 1
                    shot_name = f"clipurl_failed_round_{rounds + 1}.png"
                    try:
                        sb.save_screenshot(shot_name)
                        print(f"📸 已自动保存失败现场截图：{shot_name}")
                        send_tg_photo(shot_name, f"ClipURL 第 {rounds + 1} 轮未完成\nURL: {current_url(sb)}")
                    except Exception:
                        pass

                    print(f"⚠️ 本轮未完成（连续重试: {fail_streak}/{MAX_CAPTCHA_FAILURES}）")
                    if fail_streak >= MAX_CAPTCHA_FAILURES:
                        print("🛑 连续失败达到上限，退出")
                        return 1
                    restart_ad_flow(sb, "流程未完成")
                    continue

                fail_streak = 0
                rounds += 1
                print(f"🎉 成功完成第 {rounds} 轮！")
                report_coins(sb, f"第 {rounds} 轮完成")
                time.sleep(3)

    except KeyboardInterrupt:
        print("\n⏹️ 用户手动中断")
        return 130
    except Exception as exc:
        message = f"❌ 运行异常：{exc}"
        print(message)
        send_tg(message)
        return 1


if __name__ == "__main__":
    sys.exit(run())
