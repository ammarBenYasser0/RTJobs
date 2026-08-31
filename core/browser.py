"""Browser session workarounds.

scrapling's browser fetchers wait for the 'load' event on every navigation
(page.goto defaults to wait_until='load' and _wait_for_page_stability also
waits for it unconditionally). Some sites — LinkedIn especially — keep
tracker/CDN resources loading indefinitely, so 'load' never fires and every
fetch times out (tab spinner spins forever).

Fix: patch the page instance via scrapling's documented page_setup hook
(runs before navigation) so navigations wait only for 'domcontentloaded'.
The page is fully usable at that point; element waits (wait_for_selector /
locator.wait_for) handle the rest.

Both session flavors are supported: async sessions (AsyncStealthySession)
await the page_setup result and their goto/wait_for_load_state, so the
installed wrappers are coroutines there; sync sessions keep sync wrappers.

CDP attach (live debugging / manual 2FA solves):
Playwright always launches Chrome with --remote-debugging-pipe, which
disables the HTTP DevTools endpoint — so port 9222 would never serve
anything. Instead WE launch Chrome with --remote-debugging-port and let
scrapling connect via cdp_url. But scrapling's cdp_url path calls
browser.new_context(), which is isolated from the profile's default
context (cookies/session are lost — verified empirically). The patch
installed here swaps in the browser's default context instead.
"""

import inspect
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request


def patch_no_load_wait(page):
    """Make this page's navigations wait for domcontentloaded, not load.

    Returns a coroutine for async pages (scrapling awaits page_setup in
    async sessions) and None for sync pages.

    Idempotent: scrapling's page pool reuses pages, so page_setup can run
    multiple times on the same page object.  A sentinel attribute prevents
    re-wrapping the already-patched methods.
    """
    if getattr(page, "_rtjobs_patched", False):
        # Already patched — return a no-op coroutine for async pages so
        # scrapling's ``await page_setup(page)`` doesn't break.
        if inspect.iscoroutinefunction(page.goto):
            async def _noop():
                pass
            return _noop()
        return None
    if inspect.iscoroutinefunction(page.goto):
        return _patch_async(page)
    return _patch_sync(page)


def _patch_sync(page) -> None:
    orig_goto = page.goto

    def goto(url, *args, **kwargs):
        kwargs.setdefault("wait_until", "domcontentloaded")
        return orig_goto(url, *args, **kwargs)

    page.goto = goto

    orig_wait = page.wait_for_load_state

    def wait_for_load_state(state=None, *args, **kwargs):
        if state == "load":
            state = "domcontentloaded"
        return orig_wait(state, *args, **kwargs)

    page.wait_for_load_state = wait_for_load_state
    page._rtjobs_patched = True


async def _patch_async(page) -> None:
    orig_goto = page.goto

    async def goto(url, *args, **kwargs):
        kwargs.setdefault("wait_until", "domcontentloaded")
        return await orig_goto(url, *args, **kwargs)

    page.goto = goto

    orig_wait = page.wait_for_load_state

    async def wait_for_load_state(state=None, *args, **kwargs):
        if state == "load":
            state = "domcontentloaded"
        return await orig_wait(state, *args, **kwargs)

    page.wait_for_load_state = wait_for_load_state
    page._rtjobs_patched = True


# ---------------------------------------------------------------------------
# CDP attach: launch Chrome ourselves with an HTTP DevTools port, let
# scrapling connect via cdp_url, and reuse the browser's default context.
# ---------------------------------------------------------------------------


def _find_chrome() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chrome"):
        path = shutil.which(name)
        if path:
            return path
    return "/opt/google/chrome/chrome"


_FORWARDER_SOCKET: socket.socket | None = None


def _start_tcp_forwarder(listen_port: int, target_port: int) -> socket.socket | None:
    """Forward TCP traffic from 0.0.0.0:listen_port to 127.0.0.1:target_port.

    Linux Chrome ignores --remote-debugging-address=0.0.0.0 and binds CDP
    only to loopback 127.0.0.1, causing external connections via Docker port
    forwarding to be refused. This bridge listens on 0.0.0.0 and forwards
    packets locally so Chrome sees loopback connections.
    """
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        server.bind(("0.0.0.0", listen_port))
        server.listen(10)
    except Exception as e:
        print(f"[browser] TCP forwarder couldn't bind port {listen_port}: {e}")
        return None

    def pipe(src, dst):
        try:
            while True:
                data = src.recv(4096)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                src.close()
            except Exception:
                pass
            try:
                dst.close()
            except Exception:
                pass

    def accept_loop():
        while True:
            try:
                client, _ = server.accept()
                target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                target.connect(("127.0.0.1", target_port))
                threading.Thread(target=pipe, args=(client, target), daemon=True).start()
                threading.Thread(target=pipe, args=(target, client), daemon=True).start()
            except Exception:
                break

    threading.Thread(target=accept_loop, daemon=True).start()
    return server


def launch_cdp_chrome(profile_dir: str, port: int, headless: bool = False,
                      timeout: float = 30.0, clean_locks: bool = False) -> subprocess.Popen:
    """Launch real Chrome with an HTTP DevTools endpoint on `port`.

    Returns the process; call stop_chrome() when done. Raises RuntimeError
    if the endpoint doesn't come up.

    clean_locks: remove stale Singleton* profile locks first. Only safe when
    no other Chrome can be using this profile (container mode — where the
    zombie-kill step just ran and this is the sole launcher). Without it, a
    previously killed Chrome makes the next launch exit with code 21
    ("profile appears to be in use").
    """
    global _FORWARDER_SOCKET
    if clean_locks:
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                os.remove(os.path.join(profile_dir, name))
            except OSError:
                pass

    internal_port = port + 1 if port == 9222 else port
    args = [
        _find_chrome(),
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={internal_port}",
        "--remote-allow-origins=*",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    if headless:
        args.insert(1, "--headless=new")

    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{internal_port}/json/version"
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Chrome exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    if internal_port != port:
                        _FORWARDER_SOCKET = _start_tcp_forwarder(port, internal_port)
                    print(
                        f"[browser] Chrome up — CDP attachable via chrome://inspect"
                        f" (target localhost:{port}) or http://localhost:{port}/json"
                    )
                    return proc
        except Exception:
            time.sleep(0.3)
    stop_chrome(proc)
    raise RuntimeError(f"Chrome CDP endpoint never came up on port {internal_port}")


def stop_chrome(proc: subprocess.Popen | None) -> None:
    """Terminate Chrome gracefully, force-kill if it doesn't exit."""
    global _FORWARDER_SOCKET
    if _FORWARDER_SOCKET:
        try:
            _FORWARDER_SOCKET.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            _FORWARDER_SOCKET.close()
        except Exception:
            pass
        _FORWARDER_SOCKET = None

    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def cdp_url_for(port: int) -> str:
    internal_port = port + 1 if port == 9222 else port
    return f"http://127.0.0.1:{internal_port}"


_PATCH_INSTALLED = False


def install_cdp_default_context_patch() -> None:
    """Make scrapling sessions connected via cdp_url reuse the browser's
    default (persistent profile) context.

    scrapling's own cdp_url path calls browser.new_context(), which is
    isolated from the profile's cookies — that would silently drop the
    LinkedIn login session / Wuzzuf cf_clearance cookie on every run.
    (Verified: cookies added in the default context survive reconnects;
    new_context() ones don't.) We replace the cdp branch of start() and
    grab browser.contexts[0] straight after connect_over_cdp — that's the
    profile's default context. (Careful: AFTER a new_context() call the
    list gets reordered and index 0 is the isolated one.) Idempotent.
    """
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    from playwright.async_api import async_playwright
    from playwright.sync_api import sync_playwright

    from scrapling.fetchers import AsyncStealthySession, StealthySession

    orig_sync_start = StealthySession.start

    def sync_start(self):
        if not getattr(self._config, "cdp_url", None):
            return orig_sync_start(self)
        if self.playwright:
            raise RuntimeError("Session has been already started")
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(
                endpoint_url=self._config.cdp_url
            )
            if not self._config.proxy_rotator:
                assert self.browser is not None
                if not self.browser.contexts:
                    raise RuntimeError(
                        "CDP-connected browser has no default context"
                    )
                self.context = self._initialize_context(
                    self._config, self.browser.contexts[0]
                )
            self._is_alive = True
        except Exception:
            self.playwright.stop()
            self.playwright = None
            raise

    StealthySession.start = sync_start

    orig_async_start = AsyncStealthySession.start

    async def async_start(self):
        if not getattr(self._config, "cdp_url", None):
            return await orig_async_start(self)
        if self.playwright:
            raise RuntimeError("Session has been already started")
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(
                endpoint_url=self._config.cdp_url
            )
            if not self._config.proxy_rotator:
                assert self.browser is not None
                if not self.browser.contexts:
                    raise RuntimeError(
                        "CDP-connected browser has no default context"
                    )
                self.context = await self._initialize_context(
                    self._config, self.browser.contexts[0]
                )
            self._is_alive = True
        except Exception:
            await self.playwright.stop()
            self.playwright = None
            raise

    AsyncStealthySession.start = async_start

    _PATCH_INSTALLED = True

