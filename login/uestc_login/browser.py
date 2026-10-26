"""Browser request conventions captured by the standalone manual diagnostic."""

from urllib.parse import urlparse

IDAS = "https://idas.uestc.edu.cn/authserver"
LOGIN_URL = IDAS + "/login"
JZSZ = "https://jzsz.uestc.edu.cn/"
SERVICE_LOGIN_URL = (
    LOGIN_URL + "?service=https%3A%2F%2Fjzsz.uestc.edu.cn%2F%23%2Fhall%2Fhome"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/27.0.1 Safari/605.1.15"
)
REQUEST_TIMEOUT_MS = 30000
REQUEST_DELAY = 0.3
LOCALE_COOKIE = "org.springframework.web.servlet.i18n.CookieLocaleResolver.LOCALE"
FINGERPRINT_COOKIES = ("JSESSIONID", "route", LOCALE_COOKIE)
IDAS_COOKIES = (
    "CASTGC",
    "JSESSIONID",
    "route",
    "MULTIFACTOR_BROWSER_FINGERPRINT",
    "happyVoyage",
    LOCALE_COOKIE,
)
PORTAL_COOKIES = ("SESSION", "_ga_968CMWQK03", "_ga")


def browser_headers(url, method, *, referer=None, site="same-origin"):
    target = urlparse(str(url))
    idas = target.hostname == "idas.uestc.edu.cn"
    ajax = idas and (
        target.path.endswith(("/bfp/info", "/checkNeedCaptcha.htl", "/reAuthSubmit.do"))
        or "/dynamicCode/" in target.path
        or "/common/" in target.path
    )
    api = not idas and "/api/" in target.path
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "application/json, text/javascript, */*; q=0.01"
            if ajax
            else (
                "application/json, text/plain, */*"
                if api
                else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            )
        ),
        "Sec-Fetch-Dest": "empty" if ajax or api else "document",
        "Sec-Fetch-Site": site,
        "Sec-Fetch-Mode": "cors" if ajax or api else "navigate",
        "Accept-Language": "en-US,en;q=0.9",
        "Priority": "u=3, i" if ajax or api else "u=0, i",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if method == "POST":
        headers["Origin"] = f"{target.scheme}://{target.netloc}"
        if idas:
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded;charset=utf-8"
                if ajax
                else "application/x-www-form-urlencoded"
            )
    return headers


def restrict_cookies(request, allowed=None):
    if allowed is None:
        if request.url.host == "idas.uestc.edu.cn":
            allowed = (
                FINGERPRINT_COOKIES
                if request.url.path.endswith("/bfp/info")
                else IDAS_COOKIES
            )
        else:
            allowed = () if "ticket" in request.url.params else PORTAL_COOKIES
    # HTTPX has already applied domain, path, secure and expiry rules.
    pairs = [
        part.strip()
        for part in request.headers.get("Cookie", "").split(";")
        if "=" in part
    ]
    selected = [
        part for name in allowed for part in pairs if part.split("=", 1)[0] == name
    ]
    request.headers.pop("Cookie", None)
    if selected:
        request.headers["Cookie"] = "; ".join(selected)
