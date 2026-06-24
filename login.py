from playwright.sync_api import sync_playwright


LOGIN_URL = "https://fasih-sm.bps.go.id/app/surveys"
NAVIGATION_TIMEOUT_MS = 1200_000
MANUAL_LOGIN_WAIT_MS = 120_000

_PW = None


def _get_playwright():
    global _PW
    if _PW is None:
        _PW = sync_playwright().start()
    return _PW


def _stop_playwright():
    global _PW
    try:
        if _PW is not None:
            _PW.stop()
            _PW = None
    except Exception:
        pass


def _click_first_visible(page, selectors, timeout=5000):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=timeout):
                locator.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


def _click_sso_login(page):
    return _click_first_visible(
        page,
        [
            'a:has-text("Lanjutkan dengan SSO")',
            'a[href*="/app/auth/login"]',
            'text="Login SSO BPS"',
        ],
        timeout=10000,
    )


def _verified_login(page, verify_url=None):
    if not verify_url:
        current_url = page.url.lower()
        return "fasih-sm.bps.go.id" in current_url and "/auth/login" not in current_url

    try:
        result = page.evaluate(
            """async (url) => {
                try {
                    const response = await fetch(url, {
                        credentials: "include",
                        headers: {"Accept": "application/json, text/plain, */*"}
                    });
                    return {
                        ok: response.ok,
                        status: response.status,
                        text: (await response.text()).slice(0, 300)
                    };
                } catch (error) {
                    return {ok: false, status: 0, text: String(error)};
                }
            }""",
            verify_url,
        )
    except Exception:
        return False

    text = result["text"].lower()
    return result["ok"] and "<html" not in text and "login sso" not in text


def _launch_browser(pw):
    options = {
        "headless": False,
        "ignore_default_args": ["--enable-automation"],
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    try:
        return pw.chromium.launch(channel="chrome", **options)
    except Exception:
        return pw.chromium.launch(**options)


def ensure_verified_login(page, verify_url=None):
    page.goto(LOGIN_URL, timeout=NAVIGATION_TIMEOUT_MS)
    try:
        page.wait_for_load_state("networkidle", timeout=NAVIGATION_TIMEOUT_MS)
    except Exception:
        pass

    if verify_url and _verified_login(page, verify_url):
        return True

    _click_sso_login(page)
    print("Silakan selesaikan login SSO di browser. Script menunggu 2 menit...")
    page.wait_for_timeout(MANUAL_LOGIN_WAIT_MS)

    page.goto(LOGIN_URL, timeout=NAVIGATION_TIMEOUT_MS)
    try:
        page.wait_for_load_state("networkidle", timeout=NAVIGATION_TIMEOUT_MS)
    except Exception:
        pass

    return _verified_login(page, verify_url)


def login_with_sso(verify_url=None):
    pw = _get_playwright()
    browser = _launch_browser(pw)
    page = browser.new_page()

    try:
        if ensure_verified_login(page, verify_url):
            print("Login berhasil!")
            return page, browser

        print("Login gagal. Periksa input login atau OTP.")
        print(f"Current URL: {page.url}")
        browser.close()
        return None, None

    except Exception as e:
        print(f"Error selama login: {e}")
        try:
            browser.close()
        except Exception:
            pass
        return None, None


if __name__ == "__main__":
    page, browser = login_with_sso()
    if page:
        print("Objek halaman diperoleh. Browser tetap terbuka.")
        try:
            input("Tekan Enter untuk menutup browser...")
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
    else:
        print("Gagal memperoleh objek halaman.")

    _stop_playwright()
