"""
GitHub Actions SharePoint sync script.

Workflow:
1. GET list of enabled aircraft utilization sources from Render API
2. For each source: open SharePoint URL in headless Chromium via Playwright,
   click File → Export → Download as CSV, get the file bytes
3. POST the (base64-encoded) bytes to Render's /api/aircraft-utilization-sources/gh-push
   which parses and saves data to the database.

Required environment variables (set as GitHub Secrets):
  RENDER_BASE_URL   – e.g. https://aviation-mro.onrender.com   (no trailing slash)
  GH_SYNC_TOKEN     – secret token matching GH_SYNC_TOKEN on Render
"""

import os
import sys
import base64
import json
import tempfile
import time
import re
import html as _html
from pathlib import Path
from urllib.request import urlopen, Request as UrlRequest
from urllib.parse import urljoin
from urllib.error import HTTPError

# ─── Config ───────────────────────────────────────────────────────────────────
RENDER_BASE_URL = os.environ["RENDER_BASE_URL"].rstrip("/")
GH_SYNC_TOKEN = os.environ["GH_SYNC_TOKEN"]
MAX_PAGE_RELOADS = 6
GH_MODE = (os.getenv("GH_MODE") or "sync").strip().lower()
GH_PREVIEW_JOB_ID = (os.getenv("GH_PREVIEW_JOB_ID") or "").strip()
GH_PREVIEW_URL = (os.getenv("GH_PREVIEW_URL") or "").strip()
GH_PREVIEW_SHEET = (os.getenv("GH_PREVIEW_SHEET") or "").strip() or None

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _api(method: str, path: str, body=None) -> dict:
    url = f"{RENDER_BASE_URL}{path}"
    headers = {
        "X-Sync-Token": GH_SYNC_TOKEN,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = UrlRequest(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _get_sources() -> list:
    url = f"{RENDER_BASE_URL}/api/aircraft-utilization-sources"
    req = UrlRequest(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _push_preview_result(job_id: str, file_bytes: bytes = None, preferred_sheet: str = None, error: str = None) -> dict:
    body = {
        "job_id": job_id,
        "preferred_sheet": preferred_sheet,
    }
    if error:
        body["error"] = error
    if file_bytes is not None:
        body["file_data_b64"] = base64.b64encode(file_bytes).decode()
    return _api("POST", "/api/aircraft-utilization-sources/gh-preview-push", body)


# ─── Playwright download ───────────────────────────────────────────────────────

def _download_via_playwright(source_url: str) -> bytes:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

    csv_texts = [
        "Скачать как CSV UTF-8",
        "Скачать в формате CSV UTF-8",
        "Download as CSV UTF-8",
        "Скачать как CSV",
        "Скачать в формате CSV",
        "Download as CSV",
    ]
    file_selectors = [
        'button:has-text("{text}")',
        '[role="tab"]:has-text("{text}")',
        '[role="button"]:has-text("{text}")',
        'span:has-text("{text}")',
    ]
    menu_selectors = [
        '[role="menuitem"]:has-text("{text}")',
        'button:has-text("{text}")',
        '[role="button"]:has-text("{text}")',
        'span:has-text("{text}")',
    ]

    def _extract_dl_from_html(page_html: str, current_url: str):
        candidates = []
        patterns = [
            r'"(?:downloadUrl|tempauthdownloadurl|fileGetUrl|FileGetUrl|@microsoft\.graph\.downloadUrl)":\s*"([^"\\]+(?:\\.[^"\\]*)*)"',
            r'(?:downloadUrl|tempauthdownloadurl|fileGetUrl)=([^"&\s\]]+)',
            r'href=["\']([^"\']*(?:download=1)[^"\']*)["\']',
            r'href=["\']([^"\']*(?:download\.aspx|guestaccess\.aspx)[^"\']*)["\']',
        ]
        for pat in patterns:
            for m in re.findall(pat, page_html, flags=re.IGNORECASE):
                raw = str(m).strip().replace('\\/', '/').replace('\\u0026', '&')
                raw = _html.unescape(raw)
                if raw.startswith('//'):
                    raw = 'https:' + raw
                elif not raw.startswith('http'):
                    raw = urljoin(current_url, raw)
                if raw and raw not in candidates:
                    candidates.append(raw)
        for dl_url in candidates:
            try:
                req = UrlRequest(dl_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
                with urlopen(req, timeout=60) as resp:
                    data = resp.read()
                    ct = str(resp.headers.get("Content-Type", "")).lower()
                    if not data or b"<html" in data[:512].lower():
                        continue
                    if data.startswith(b"PK") or 'csv' in ct or dl_url.lower().endswith('.csv'):
                        return data
            except Exception:
                continue
        return None

    network_candidates = []

    def _collect_from_text(text: str):
        pats = [
            r'"(?:downloadUrl|tempauthdownloadurl|fileGetUrl|FileGetUrl)":\s*"([^"]+)"',
            r'(?:downloadUrl|tempauthdownloadurl|fileGetUrl)=([^"&\s\]]+)',
            r'https?://[^\"\'\s]+(?:download\.aspx|guestaccess\.aspx|tempauth)[^\"\'\s]*',
            r'https?://[^\"\'\s]+\?[^\"\'\s]*download=1[^\"\'\s]*',
        ]
        for p in pats:
            for m in re.findall(p, text, flags=re.IGNORECASE):
                url = str(m).strip()
                if url and url not in network_candidates:
                    network_candidates.append(url)

    def _on_response(resp):
        try:
            resp_url = str(resp.url or '').strip()
            if resp_url:
                low = resp_url.lower()
                if any(x in low for x in ('download.aspx', 'guestaccess.aspx', 'tempauth', 'download=1')) \
                        or low.endswith('.csv') or low.endswith('.xlsx'):
                    if resp_url not in network_candidates:
                        network_candidates.append(resp_url)
            ct = str(resp.headers.get('content-type', '')).lower()
            if any(x in ct for x in ('json', 'javascript', 'text', 'html')):
                _collect_from_text(resp.text())
        except Exception:
            pass

    def _try_network_candidates(page_url):
        checked = set()
        for raw in list(network_candidates):
            raw = raw.replace('\\/', '/').replace('\\u0026', '&')
            raw = _html.unescape(raw)
            if raw.startswith('//'):
                raw = 'https:' + raw
            elif not raw.startswith('http'):
                raw = urljoin(page_url, raw)
            if raw in checked:
                continue
            checked.add(raw)
            try:
                req = UrlRequest(raw, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv,*/*",
                    "Referer": page_url,
                })
                with urlopen(req, timeout=90) as resp:
                    data = resp.read()
                    ct = str(resp.headers.get("Content-Type", "")).lower()
                    if not data or b"<html" in data[:1024].lower():
                        continue
                    if data.startswith(b"PK") or 'csv' in ct or raw.lower().endswith('.csv'):
                        return data
            except Exception:
                continue
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-http2",
                ],
            )
            try:
                context = browser.new_context(
                    accept_downloads=True,
                    locale="ru-RU",
                    ignore_https_errors=True,
                    bypass_csp=True,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                page.on("response", _on_response)
                last_error = None

                def _candidate_frames():
                    frames = list(page.frames)
                    office = [f for f in frames if "officeapps" in (f.url or "") or "xlviewer" in (f.url or "")]
                    return office + [f for f in frames if f not in office]

                def _click_in_frames(texts, selectors, timeout=10000):
                    for frame in _candidate_frames():
                        for text in texts:
                            for pattern in selectors:
                                sel = pattern.format(text=text)
                                try:
                                    loc = frame.locator(sel).first
                                    if loc.is_visible(timeout=2500):
                                        loc.click(timeout=timeout)
                                        return True
                                except Exception:
                                    continue
                    return False

                for attempt in range(MAX_PAGE_RELOADS):
                    try:
                        if attempt > 0 and attempt % 2 == 0:
                            try:
                                page.close()
                            except Exception:
                                pass
                            page = context.new_page()
                            page.on("response", _on_response)

                        if attempt == 0:
                            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
                        else:
                            try:
                                page.reload(wait_until="domcontentloaded", timeout=90000)
                            except Exception:
                                page.goto(source_url, wait_until="domcontentloaded", timeout=90000)

                        # Wait for File button
                        try:
                            page.wait_for_selector(
                                'button:has-text("Файл"), button:has-text("File"), [role="tab"]:has-text("File")',
                                timeout=15000,
                            )
                        except Exception:
                            page.wait_for_timeout(8000)

                        # PRIMARY: click Файл → Экспорт → Download as CSV
                        click_error = None
                        try:
                            if not _click_in_frames(["Файл", "File"], file_selectors, timeout=12000):
                                raise Exception('Could not find "Файл"/"File" ribbon tab')
                            page.wait_for_timeout(1600)

                            if not _click_in_frames(["Экспорт", "Export"], menu_selectors, timeout=12000):
                                raise Exception('Could not find "Экспорт"/"Export" menu item')
                            page.wait_for_timeout(1400)

                            csv_clicked = False
                            for frame in _candidate_frames():
                                if csv_clicked:
                                    break
                                for text in csv_texts:
                                    if csv_clicked:
                                        break
                                    for pattern in menu_selectors:
                                        sel = pattern.format(text=text)
                                        try:
                                            loc = frame.locator(sel).first
                                            if not loc.is_visible(timeout=2500):
                                                continue
                                            with page.expect_download(timeout=90000) as dl_info:
                                                loc.click(timeout=9000)
                                            dl = dl_info.value
                                            if dl.failure():
                                                raise Exception(f"Download failed: {dl.failure()}")
                                            target = Path(tmp_dir) / (dl.suggested_filename or "file.csv")
                                            dl.save_as(str(target))
                                            data = target.read_bytes()
                                            if data:
                                                return data
                                            csv_clicked = True
                                        except PlaywrightTimeoutError:
                                            continue
                                        except Exception:
                                            continue
                            if not csv_clicked:
                                raise Exception('Could not find CSV download option in Export menu')
                        except Exception as ce:
                            click_error = ce

                        # FALLBACK A: network-harvested URLs
                        net_data = _try_network_candidates(page.url)
                        if net_data:
                            return net_data

                        # FALLBACK B: download URL from page HTML
                        html_data = _extract_dl_from_html(page.content(), page.url)
                        if html_data:
                            return html_data

                        raise Exception(
                            f"Attempt {attempt + 1}/{MAX_PAGE_RELOADS}: "
                            f"click failed ({click_error}); HTML fallback found nothing."
                        )

                    except Exception as e:
                        last_error = e
                        print(f"  Attempt {attempt + 1} failed: {e}")
                        if attempt < MAX_PAGE_RELOADS - 1:
                            page.wait_for_timeout(4000)
                        continue

                raise Exception(f"All {MAX_PAGE_RELOADS} attempts failed. Last: {last_error}")
            finally:
                try:
                    browser.close()
                except Exception:
                    pass


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if GH_MODE == "preview":
        if not GH_PREVIEW_JOB_ID:
            raise SystemExit("GH_PREVIEW_JOB_ID is required in preview mode")
        if not GH_PREVIEW_URL:
            raise SystemExit("GH_PREVIEW_URL is required in preview mode")

        print(f"🔎 Preview mode: job={GH_PREVIEW_JOB_ID}")
        try:
            file_bytes = _download_via_playwright(GH_PREVIEW_URL)
            print(f"✅ Preview downloaded {len(file_bytes):,} bytes")
            _push_preview_result(GH_PREVIEW_JOB_ID, file_bytes=file_bytes, preferred_sheet=GH_PREVIEW_SHEET)
            print("✅ Preview result pushed to Render")
        except HTTPError as e:
            body = e.read().decode(errors="ignore")
            _push_preview_result(GH_PREVIEW_JOB_ID, error=f"Preview push failed HTTP {e.code}: {body[:300]}")
            raise
        except Exception as e:
            _push_preview_result(GH_PREVIEW_JOB_ID, error=str(e))
            raise
        return

    print("🔄 Fetching aircraft utilization sources from Render...")
    sources = _get_sources()

    enabled = [s for s in sources if s.get("is_enabled") and s.get("source_url", "").strip()]
    if not enabled:
        print("ℹ️  No enabled sources with URLs. Nothing to sync.")
        return

    print(f"✅ Found {len(enabled)} enabled source(s): {[s['aircraft_tail_number'] for s in enabled]}")

    errors = []
    for source in enabled:
        tail = source["aircraft_tail_number"]
        url = source["source_url"].strip()
        sheet = source.get("sheet_name") or None

        print(f"\n📥 [{tail}] Downloading from: {url[:80]}...")
        try:
            file_bytes = _download_via_playwright(url)
            print(f"   Downloaded {len(file_bytes):,} bytes")
        except Exception as e:
            msg = f"[{tail}] Download failed: {e}"
            print(f"   ❌ {msg}")
            errors.append(msg)
            continue

        print(f"   📤 Pushing to Render...")
        try:
            result = _api("POST", "/api/aircraft-utilization-sources/gh-push", {
                "aircraft_tail_number": tail,
                "file_data_b64": base64.b64encode(file_bytes).decode(),
                "preferred_sheet": sheet,
                "source_url": url,
            })
            print(
                f"   ✅ Saved: date={result.get('date')} "
                f"ttsn={result.get('ttsn')} tcsn={result.get('tcsn')} "
                f"sheet={result.get('sheet')}"
            )
        except HTTPError as e:
            body = e.read().decode(errors="ignore")
            msg = f"[{tail}] Push failed HTTP {e.code}: {body[:300]}"
            print(f"   ❌ {msg}")
            errors.append(msg)
        except Exception as e:
            msg = f"[{tail}] Push failed: {e}"
            print(f"   ❌ {msg}")
            errors.append(msg)

    print("\n" + "─" * 60)
    if errors:
        print(f"⚠️  Finished with {len(errors)} error(s):")
        for err in errors:
            print(f"   • {err}")
        sys.exit(1)
    else:
        print("✅ All sources synced successfully.")


if __name__ == "__main__":
    main()
