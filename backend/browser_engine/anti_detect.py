"""Anti-detection measures for Playwright browser automation.

Applies stealth techniques to make automated Chrome indistinguishable from a
real user session. Used by DeepSeek / Doubao / ChatGPT browser adapters.
"""

from __future__ import annotations

import os
import random

# Real Chrome UA strings — matched with platform/vendor/WebGL renderer.
# Each profile is internally consistent so navigator.userAgent,
# navigator.platform, and the WebGL renderer don't contradict each other.
#
# Cloudflare Turnstile cross-checks UA, Sec-CH-UA-Platform, and
# navigator.userAgentData.platform. For cross-machine session reuse
# (local login → AWS runtime), both sides MUST use the same profile.
# The Linux profile is the canonical choice for CF-gated international
# engines (ChatGPT / Gemini / Grok) because the server runs Linux.
_UA_PROFILES = [
    {
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "platform": "Linux x86_64",
        "ua_platform_label": "Linux",
        "ua_brands": '"Chromium";v="135", "Not-A.Brand";v="24", "Google Chrome";v="135"',
        "vendor": "Google Inc.",
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Mesa Intel(R) UHD Graphics 630 (CFL GT2), OpenGL 4.6)",
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "platform": "Win32",
        "ua_platform_label": "Windows",
        "ua_brands": '"Chromium";v="135", "Not-A.Brand";v="24", "Google Chrome";v="135"',
        "vendor": "Google Inc.",
        "webgl_vendor": "Google Inc. (NVIDIA)",
        "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "platform": "MacIntel",
        "ua_platform_label": "macOS",
        "ua_brands": '"Chromium";v="135", "Not-A.Brand";v="24", "Google Chrome";v="135"',
        "vendor": "Google Inc.",
        "webgl_vendor": "Google Inc. (Apple)",
        "webgl_renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)",
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "platform": "Win32",
        "ua_platform_label": "Windows",
        "ua_brands": '"Chromium";v="134", "Not-A.Brand";v="24", "Google Chrome";v="134"',
        "vendor": "Google Inc.",
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "platform": "MacIntel",
        "ua_platform_label": "macOS",
        "ua_brands": '"Chromium";v="134", "Not-A.Brand";v="24", "Google Chrome";v="134"',
        "vendor": "Google Inc.",
        "webgl_vendor": "Google Inc. (Apple)",
        "webgl_renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)",
    },
]


def _pick_profile(platform_filter: str | None = None) -> dict:
    """Pick a UA/fingerprint profile.

    Args:
        platform_filter: e.g. "Linux x86_64" to force a Linux profile.
            Used by CF-gated login scripts to ensure cross-machine consistency.
            When None, picks randomly from all profiles (existing behavior).
    """
    if platform_filter:
        pool = [p for p in _UA_PROFILES if p["platform"] == platform_filter]
        return random.choice(pool) if pool else _UA_PROFILES[0]
    return random.choice(_UA_PROFILES)


def get_random_ua() -> str:
    return _pick_profile()["ua"]


def get_launch_options(
    headless: bool = True,
    profile: dict | None = None,
    channel: str | None = None,
) -> dict:
    """Return Playwright browser launch options with anti-detect settings.

    Args:
        headless: If True, launch in headless mode. Previously broken (always
            returned headless=False); now correctly respected.
        profile: Pre-picked UA profile. If omitted, a random one is picked.
        channel: Playwright browser channel. Pass "chrome" to use a real
            Chrome installation (required for CF-gated sites whose Sec-CH-UA
            brand list must include "Google Chrome").
    """
    if profile is None:
        profile = _pick_profile()
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=AutomationControlled",
        "--disable-infobars",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        # UA is set per-context via user_agent option; don't also set it
        # as a launch arg (context-level takes precedence and they must match).
    ]
    opts: dict = {"headless": headless, "args": args}
    if channel:
        opts["channel"] = channel
    proxy_url = os.environ.get("PROXY_URL", "").strip()
    if proxy_url:
        opts["proxy"] = {"server": proxy_url}
    return opts


def get_context_options(
    locale: str = "zh-CN",
    timezone_id: str = "Asia/Shanghai",
    profile: dict | None = None,
) -> dict:
    """Return browser context options for realistic fingerprints.

    `profile` ties the context UA to the same profile used at launch and
    in the stealth JS. Without it, Playwright's per-call randomness can
    produce a Mac UA on a Win32 platform — an instant tell.

    Includes extra_http_headers to override Chromium's automatic
    Sec-CH-UA / Sec-CH-UA-Platform headers, which would otherwise leak
    the real OS and contradict the spoofed navigator.platform.
    """
    if profile is None:
        profile = _pick_profile()
    opts = {
        "viewport": {"width": 1920, "height": 1080},
        "locale": locale,
        "timezone_id": timezone_id,
        "user_agent": profile["ua"],
        "color_scheme": "light",
        "device_scale_factor": 1.0,
        "has_touch": False,
        "java_script_enabled": True,
    }
    # Override Chromium's automatic client hints so Sec-CH-UA-Platform
    # matches the spoofed navigator.platform. Without this, CF sees
    # e.g. UA="Linux" but Sec-CH-UA-Platform="macOS" → instant fail.
    ua_brands = profile.get("ua_brands")
    ua_platform_label = profile.get("ua_platform_label")
    if ua_brands and ua_platform_label:
        opts["extra_http_headers"] = {
            "sec-ch-ua": ua_brands,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": f'"{ua_platform_label}"',
        }
    return opts


def get_context_options_international(profile: dict | None = None) -> dict:
    """Context options for international (non-Chinese) AI sites."""
    return get_context_options(
        locale="en-US", timezone_id="America/New_York", profile=profile
    )


# Stealth JS with configurable language list
def _build_stealth_js(
    languages: list[str] | None = None,
    platform: str = "Win32",
    vendor: str = "Google Inc.",
    webgl_vendor: str = "Google Inc. (NVIDIA)",
    webgl_renderer: str = "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    ua_platform_label: str = "Windows",
    ua_brands: str = "",
) -> str:
    langs = languages or ['zh-CN', 'zh', 'en-US', 'en']
    langs_js = str(langs)
    return f"""
// ── Core webdriver hiding ──────────────────────────────────
Object.defineProperty(navigator, 'webdriver', {{ get: () => false }});

// Delete automation indicators from chrome object
if (window.chrome) {{
    window.chrome.csi = () => {{}};
    window.chrome.loadTimes = () => {{}};
    window.chrome.app = {{
        isInstalled: false,
        InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }},
        RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }}
    }};
    // Add missing chrome.runtime (real Chrome has this)
    if (!window.chrome.runtime) {{
        window.chrome.runtime = {{
            OnInstalledReason: {{ CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' }},
            OnRestartRequiredReason: {{ APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' }},
            PlatformArch: {{ ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }},
            PlatformNaclArch: {{ ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }},
            PlatformOs: {{ ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' }},
            RequestUpdateCheckStatus: {{ NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }},
            connect: function() {{}},
            sendMessage: function() {{}},
            id: undefined,
        }};
    }}
}}

// ── Platform spoofing ──────────────────────────────────────
// Match platform to the UA we're using (Win32 for Windows, MacIntel for Mac)
Object.defineProperty(navigator, 'platform', {{
    get: () => '{platform}',
}});

// ── Plugins / MIME types ───────────────────────────────────
Object.defineProperty(navigator, 'plugins', {{
    get: () => {{
        const arr = [
            {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
            {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' }},
            {{ name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }},
        ];
        arr.refresh = () => {{}};
        return arr;
    }},
}});

Object.defineProperty(navigator, 'mimeTypes', {{
    get: () => {{
        const arr = [
            {{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
            {{ type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
        ];
        return arr;
    }},
}});

// ── Languages ──────────────────────────────────────────────
Object.defineProperty(navigator, 'languages', {{
    get: () => {langs_js},
}});

// ── Permissions API ────────────────────────────────────────
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({{ state: Notification.permission }}) :
        origQuery(parameters)
);

// ── Canvas fingerprint randomization ───────────────────────
const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {{
    if (type === 'image/png' && this.width > 16 && this.height > 16) {{
        const ctx = this.getContext('2d');
        if (ctx) {{
            const imageData = ctx.getImageData(0, 0, 1, 1);
            imageData.data[0] = imageData.data[0] ^ (Math.random() * 2 | 0);
            ctx.putImageData(imageData, 0, 0);
        }}
    }}
    return _toDataURL.apply(this, arguments);
}};

// ── WebGL vendor/renderer spoofing ─────────────────────────
// Hook BOTH WebGL1 and WebGL2 contexts. Vendor/renderer must be
// consistent with navigator.platform (Mac→Metal, Win→D3D11).
const _spoofWebGL = (proto) => {{
    const getParameter = proto.getParameter;
    proto.getParameter = function(param) {{
        // UNMASKED_VENDOR_WEBGL
        if (param === 37445) return '{webgl_vendor}';
        // UNMASKED_RENDERER_WEBGL
        if (param === 37446) return '{webgl_renderer}';
        return getParameter.apply(this, arguments);
    }};
}};
if (typeof WebGLRenderingContext !== 'undefined') _spoofWebGL(WebGLRenderingContext.prototype);
if (typeof WebGL2RenderingContext !== 'undefined') _spoofWebGL(WebGL2RenderingContext.prototype);

// ── Hide Playwright / Puppeteer artifacts ──────────────────
delete window.__playwright;
delete window.__pw_manual;

// Fix iframe contentWindow chrome check
const origGetter = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow').get;
Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {{
    get: function() {{
        const result = origGetter.call(this);
        if (result) {{
            try {{
                result.chrome = window.chrome;
            }} catch(e) {{}}
        }}
        return result;
    }}
}});

// ── Connection info ────────────────────────────────────────
Object.defineProperty(navigator, 'connection', {{
    get: () => ({{
        effectiveType: '4g',
        rtt: 100,
        downlink: 10,
        saveData: false,
    }}),
}});

// ── Hardware concurrency (simulate real machine) ───────────
Object.defineProperty(navigator, 'hardwareConcurrency', {{
    get: () => 8,
}});

Object.defineProperty(navigator, 'deviceMemory', {{
    get: () => 8,
}});

// ── Vendor ─────────────────────────────────────────────────
Object.defineProperty(navigator, 'vendor', {{
    get: () => '{vendor}',
}});

// ── Remove automation flags from Error.stack ───────────────
const origError = Error;
const origStack = Object.getOwnPropertyDescriptor(origError.prototype, 'stack');
if (origStack && origStack.get) {{
    Object.defineProperty(origError.prototype, 'stack', {{
        get: function() {{
            const stack = origStack.get.call(this);
            return stack
                ? stack.replace(/\\b(playwright|puppeteer|pptr)\\b/gi, '')
                : stack;
        }},
        configurable: true,
    }});
}}

// ── navigator.getBattery (some bots check for this) ────────
if (!navigator.getBattery) {{
    navigator.getBattery = () => Promise.resolve({{
        charging: true,
        chargingTime: 0,
        dischargingTime: Infinity,
        level: 1,
        addEventListener: function() {{}},
        removeEventListener: function() {{}},
    }});
}}

// ── navigator.userAgentData (Cloudflare Turnstile reads this) ──
// CF's challenge JS uses getHighEntropyValues() to cross-check
// platform against Sec-CH-UA-Platform header. Without this override,
// Mac/Windows machines spoofing as Linux would be caught immediately.
if (navigator.userAgentData) {{
    Object.defineProperty(navigator.userAgentData, 'platform', {{
        get: () => '{ua_platform_label}',
    }});
    const _origGetHighEntropy = navigator.userAgentData.getHighEntropyValues;
    if (_origGetHighEntropy) {{
        navigator.userAgentData.getHighEntropyValues = function(hints) {{
            return _origGetHighEntropy.call(this, hints).then(d => {{
                d.platform = '{ua_platform_label}';
                d.platformVersion = '6.5.0';
                return d;
            }});
        }};
    }}
}}
"""


# Keep the module-level constant for backward compat (Chinese engines)
STEALTH_JS = _build_stealth_js()


def build_stealth_js_for_profile(profile: dict, *, international: bool = False) -> str:
    """Build stealth JS bound to a single profile (UA / platform / WebGL match).

    The profile dict must include ua_platform_label and ua_brands for the
    navigator.userAgentData override to work (required for CF Turnstile).
    """
    languages = ['en-US', 'en'] if international else ['zh-CN', 'zh', 'en-US', 'en']
    return _build_stealth_js(
        languages=languages,
        platform=profile['platform'],
        vendor=profile['vendor'],
        webgl_vendor=profile['webgl_vendor'],
        webgl_renderer=profile['webgl_renderer'],
        ua_platform_label=profile.get('ua_platform_label', 'Windows'),
        ua_brands=profile.get('ua_brands', ''),
    )


async def apply_stealth(
    page, *, international: bool = False, profile: dict | None = None
) -> None:
    """Inject stealth JavaScript into a Playwright page."""
    if profile is None:
        profile = _pick_profile()
    await page.add_init_script(
        build_stealth_js_for_profile(profile, international=international)
    )
