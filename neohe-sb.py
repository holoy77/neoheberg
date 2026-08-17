import os
import time
import logging
from seleniumbase import SB

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

LOGIN_URL = "https://dash.neoheberg.fr/auth/login"
ADS_URL = "https://dash.neoheberg.fr/shop/ads.php"

USERNAME = os.getenv("NEOHE_USER", "")
PASSWORD = os.getenv("NEOHE_PASS", "")

def solve_clipurl_flow(sb):
    """处理 ClipURL 4步广告流程"""
    logging.info("开始处理 ClipURL 广告流程...")
    
    # 步骤 1: CAPTCHA 验证
    logging.info("[Step 1/4] 等待并处理 CAPTCHA / 人机验证...")
    sb.wait_for_element_visible("body", timeout=15)
    
    # 优先尝试过 UC 模式验证码
    try:
        sb.uc_gui_click_captcha()
    except Exception:
        pass
    
    # 尝试模拟点击通用的验证框复选框
    captcha_selectors = [
        "input[type='checkbox']",
        ".captcha-checkbox",
        "div[class*='captcha']",
        "iframe[src*='captcha']",
        "iframe[src*='turnstile']"
    ]
    for sel in captcha_selectors:
        if sb.is_element_visible(sel):
            try:
                sb.click(sel)
                logging.info(f"[Step 1] 点击验证元素: {sel}")
                break
            except Exception:
                pass
    
    # 步骤 2: Mini-jeu (等待5秒自动跳转)
    logging.info("[Step 2/4] 进入 Mini-jeu 阶段，等待 5~7 秒自动跳转...")
    time.sleep(7)
    
    # 步骤 3: Attente 模拟验证
    logging.info("[Step 3/4] 进入 Attente 阶段，尝试模拟点击确认/验证按钮...")
    time.sleep(2)
    step3_selectors = [
        "button:contains('Continuer')",
        "button:contains('Valider')",
        "button:contains('Verify')",
        "button:contains('Next')",
        "input[type='checkbox']",
        "a:contains('Continuer')",
        ".btn-primary"
    ]
    
    try:
        sb.uc_gui_click_captcha()
    except Exception:
        pass

    clicked = False
    for sel in step3_selectors:
        if sb.is_element_visible(sel):
            try:
                sb.click(sel)
                logging.info(f"[Step 3] 成功点击确认按钮: {sel}")
                clicked = True
                break
            except Exception:
                pass
    if not clicked:
        logging.info("[Step 3] 未检测到显式按钮，等待倒计时自动结算...")

    # 步骤 4: Vérif 自动跳转回原面板
    logging.info("[Step 4/4] 等待验证完成并自动跳转回主面板...")
    start_wait = time.time()
    while time.time() - start_wait < 20:
        curr_url = sb.get_current_url()
        if "neoheberg.fr" in curr_url:
            logging.info("已成功跳转回 NeoHeberg 控制台！")
            return True
        time.sleep(2)
        
    return False

def run():
    # 开启 UC 模式以绕过反爬与验证码检测
    with SB(uc=True, headless=False) as sb:
        logging.info("正在打开登录页面...")
        sb.open(LOGIN_URL)
        time.sleep(2)
        
        # 登录流程 (如已登录则跳过)
        if sb.is_element_visible("input[name='email']"):
            logging.info("输入账号密码登录...")
            sb.type("input[name='email']", USERNAME)
            sb.type("input[name='password']", PASSWORD)
            sb.click("button[type='submit']")
            time.sleep(5)
        
        # 广告主循环
        while True:
            try:
                logging.info(f"访问广告中心: {ADS_URL}")
                sb.open(ADS_URL)
                time.sleep(3)
                
                # 寻找并点击 Commencer 按钮
                commencer_btn = "button:contains('Commencer'), a:contains('Commencer')"
                if sb.is_element_visible(commencer_btn):
                    logging.info("点击 Commencer 启动广告任务...")
                    sb.click(commencer_btn)
                    time.sleep(5)
                    
                    # 检查是否打开了新标签页
                    tabs = sb.driver.window_handles
                    if len(tabs) > 1:
                        sb.switch_to_tab(tabs[-1])
                    
                    # 执行四步广告通关逻辑
                    success = solve_clipurl_flow(sb)
                    
                    # 如果多标签页未自动关闭，切回主标签页
                    if len(sb.driver.window_handles) > 1:
                        sb.driver.close()
                        sb.switch_to_tab(sb.driver.window_handles[0])
                        
                    time.sleep(3)
                else:
                    logging.info("未找到 Commencer 按钮或暂无广告，等待 15 秒重试...")
                    time.sleep(15)
                    
            except Exception as e:
                logging.error(f"运行过程中发生异常: {e}")
                time.sleep(5)

if __name__ == "__main__":
    run()
