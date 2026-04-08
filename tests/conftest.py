"""Shared fixtures for Playwright regression tests."""
import pytest
import subprocess
import time
import requests
from playwright.sync_api import Page

BASE_URL = "http://127.0.0.1:5000"
APP_DIR = r"c:\ClaudeMain\BA_Review_App"


@pytest.fixture(scope="session")
def app_server():
    """Start the Flask app if not already running. Session-scoped.
    Leaves the server running after tests to avoid repeated SSO prompts."""
    try:
        r = requests.get(f"{BASE_URL}/api/stats", timeout=10)
        if r.status_code == 200:
            yield None  # Server already running
            return
    except (requests.ConnectionError, requests.ReadTimeout):
        pass

    proc = subprocess.Popen(
        ["python", "app.py"],
        cwd=APP_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/api/stats", timeout=10)
            if r.status_code == 200:
                break
        except (requests.ConnectionError, requests.ReadTimeout):
            time.sleep(1)
    else:
        proc.terminate()
        raise RuntimeError("Flask server did not start within 30 seconds")

    yield proc
    # Leave Flask running to preserve the Snowflake SSO session.
    # The server will be reused by subsequent test runs.


@pytest.fixture(scope="function")
def app_page(page: Page, app_server) -> Page:
    """Navigate to the app and wait for AG Grid to fully load."""
    page.goto(BASE_URL)
    page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
    page.wait_for_selector("#recBreakdown .col", timeout=15000)
    # Wait for the first /api/matches response to populate #gridInfo
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=10000,
    )
    return page


@pytest.fixture(scope="function")
def app_page_fast(page: Page, app_server) -> Page:
    """Navigate to the app without waiting for full grid init."""
    page.goto(BASE_URL)
    page.wait_for_load_state("domcontentloaded")
    return page
