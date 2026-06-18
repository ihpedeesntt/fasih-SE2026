import random

from playwright.sync_api import sync_playwright


USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 16; ONEPLUS 15 Build/SKQ1.211202.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/143.0.7499.192 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 15; SM-S928B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/133.0.6943.88 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8a Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.6723.102 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 15; POCO X7 Pro Build/UKQ1.231003.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/133.0.6943.45 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 16; SM-A556E Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.88 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; ONEPLUS PJZ110 Build/SKQ1.210216.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/132.0.6834.102 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 15; Redmi Note 14 Pro Build/UKQ1.231003.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/133.0.6943.127 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 16; Pixel 9 Pro Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.45 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; moto g85 5G Build/S3SGS32.12-78-7; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.200 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 15; SM-G991B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/132.0.6834.88 Mobile Safari/537.36",
]

LOGIN_URL = "https://fasih-sm.bps.go.id/app/surveys"
MANUAL_LOGIN_WAIT_MS = 60_000
MANUAL_OTP_WAIT_MS = 60_000

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


def _sso_login_visible(page):
    selectors = [
        'a:has-text("Lanjutkan dengan SSO")',
        'a[href*="/app/auth/login"]',
        'text="Login SSO BPS"',
    ]

    for selector in selectors:
        try:
            if page.locator(selector).first.is_visible(timeout=1000):
                return True
        except Exception:
            continue
    return False


def _click_visible_submit(page):
    return _click_first_visible(
        page,
        [
            'input[type="submit"]',
            'button[type="submit"]',
            'button:has-text("Login")',
            'button:has-text("Masuk")',
            'button:has-text("Submit")',
            'button:has-text("Verifikasi")',
            'button:has-text("Lanjut")',
        ],
    )


def _is_logged_in(page):
    current_url = page.url.lower()
    if "/auth/login" in current_url or "sso.bps.go.id" in current_url:
        return False
    if _sso_login_visible(page):
        return False
    return "fasih-sm.bps.go.id" in current_url


def _otp_input(page):
    selectors = [
        'input[name="otp"]',
        'input[name="totp"]',
        'input[name="code"]',
        'input[type="tel"]',
        'input[inputmode="numeric"]',
    ]

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=3000):
                return locator
        except Exception:
            continue

    return None


def login_with_sso():
    pw = _get_playwright()
    browser = pw.chromium.launch(headless=False)
    page = browser.new_page(user_agent=random.choice(USER_AGENTS))

    try:
        page.goto(LOGIN_URL, timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)

        if not _is_logged_in(page):
            if not _click_sso_login(page):
                raise RuntimeError("Tombol login SSO tidak ditemukan.")
            page.wait_for_load_state("networkidle", timeout=60000)

        if not _is_logged_in(page):
            print("Silakan isi username dan password di browser. Menunggu 60 detik...")
            page.wait_for_timeout(MANUAL_LOGIN_WAIT_MS)
            _click_visible_submit(page)
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except Exception:
                pass

        if _otp_input(page) is not None and not _is_logged_in(page):
            print("Field OTP terdeteksi. Silakan isi OTP di browser. Menunggu 60 detik...")
            page.wait_for_timeout(MANUAL_OTP_WAIT_MS)
            _click_visible_submit(page)
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except Exception:
                pass

        if _is_logged_in(page):
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
