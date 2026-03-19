#!/usr/bin/env python3
"""
Claude Usage Monitor - Desktop System Tray Widget
Monitors Claude subscription plan usage limits from claude.ai

Requirements:
    pip3 install tls-client PyQt6 --break-system-packages
"""

import json
import os
import shutil
import sqlite3
import sys
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Optional

try:
    import tls_client
except ImportError:
    print("Missing: pip3 install tls-client --break-system-packages")
    sys.exit(1)

try:
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
    from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QIcon, QPixmap
    from PyQt6.QtWidgets import (
        QApplication, QSystemTrayIcon, QMenu, QWidget,
        QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
        QProgressBar, QMessageBox
    )
except ImportError:
    print("Missing: pip3 install PyQt6 --break-system-packages")
    sys.exit(1)


# ─── Configuration ───────────────────────────────────────────────────────────

FIREFOX_PROFILES = [
    os.path.expanduser("~/snap/firefox/common/.mozilla/firefox"),
    os.path.expanduser("~/.mozilla/firefox"),
]
REFRESH_INTERVAL = 300  # seconds (5 minutes)
STATUS_REFRESH_INTERVAL = 120  # seconds (2 minutes)
STATUS_API_URL = "https://status.claude.com/api/v2/status.json"

STATUS_COLORS = {
    "none":     "#52c05a",   # 綠
    "minor":    "#d4c022",   # 黃
    "major":    "#e08c32",   # 橘
    "critical": "#e05252",   # 紅
}
STATUS_LABELS = {
    "none":     "正常",
    "minor":    "輕微異常",
    "major":    "重大異常",
    "critical": "嚴重中斷",
}


# ─── Cookie Management ────────────────────────────────────────────────────────

def find_firefox_profile() -> Optional[str]:
    """Find the default Firefox profile directory."""
    for base in FIREFOX_PROFILES:
        if not os.path.exists(base):
            continue
        ini_path = os.path.join(base, "profiles.ini")
        if os.path.exists(ini_path):
            import configparser
            cfg = configparser.ConfigParser()
            cfg.read(ini_path)
            # Find the default profile section
            for section in cfg.sections():
                if cfg.get(section, "default", fallback="0") == "1" and cfg.has_option(section, "path"):
                    profile_path = cfg.get(section, "path")
                    is_relative = cfg.get(section, "isrelative", fallback="1") == "1"
                    if is_relative:
                        return os.path.join(base, profile_path)
                    return profile_path
        for name in os.listdir(base):
            if "default" in name:
                path = os.path.join(base, name)
                if os.path.isdir(path) and os.path.exists(os.path.join(path, "cookies.sqlite")):
                    return path
    return None


def load_cookies_as_string() -> str:
    """Load claude.ai cookies from Firefox and return as cookie string."""
    profile = find_firefox_profile()
    if not profile:
        raise RuntimeError("Firefox profile not found. Please log in to claude.ai in Firefox.")

    cookies_db = os.path.join(profile, "cookies.sqlite")
    tmp_db = "/tmp/.claude_monitor_cookies.sqlite"
    shutil.copy2(cookies_db, tmp_db)

    conn = sqlite3.connect(tmp_db)
    cur = conn.cursor()
    cur.execute("""
        SELECT name, value FROM moz_cookies
        WHERE host LIKE '%claude.ai%' OR host LIKE '%anthropic.com%'
    """)
    cookies = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    if "sessionKey" not in cookies:
        raise RuntimeError("Not logged in to claude.ai. Please log in via Firefox first.")

    return "; ".join(f"{k}={v}" for k, v in cookies.items())


# ─── API Client ───────────────────────────────────────────────────────────────

class ClaudeAPIClient:
    def __init__(self):
        self._org_id: Optional[str] = None

    def _make_request(self, url: str) -> dict:
        """Make an authenticated GET request using Firefox TLS fingerprint."""
        cookie_str = load_cookies_as_string()
        session = tls_client.Session(
            client_identifier="firefox_120",
            random_tls_extension_order=True,
        )
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0",
            "referer": "https://claude.ai/settings/usage",
            "cookie": cookie_str,
        }
        resp = session.get(url, headers=headers, timeout_seconds=15)
        if resp.status_code == 200:
            return resp.json()
        raise RuntimeError(f"API error {resp.status_code} for {url}")

    def get_org_id(self) -> str:
        """Get primary organization UUID (cached)."""
        if self._org_id:
            return self._org_id
        data = self._make_request("https://claude.ai/api/account")
        for m in data.get("memberships", []):
            org = m.get("organization", {})
            if "claude_pro" in org.get("capabilities", []):
                self._org_id = org["uuid"]
                return self._org_id
        # Fallback to first org
        orgs = self._make_request("https://claude.ai/api/organizations")
        if orgs:
            self._org_id = orgs[0]["uuid"]
        return self._org_id

    def get_account_info(self) -> dict:
        """取得目前登入帳號的名稱與 Email。"""
        data = self._make_request("https://claude.ai/api/account")
        return {
            "name": data.get("display_name") or data.get("full_name") or "未知",
            "email": data.get("email_address") or "未知",
        }

    def get_usage(self) -> dict:
        """Fetch and parse usage statistics."""
        org_id = self.get_org_id()
        raw = self._make_request(f"https://claude.ai/api/organizations/{org_id}/usage")

        result = {
            "fetched_at": datetime.now(timezone.utc),
            "five_hour": None,
            "seven_day": None,
            "extra": None,
        }

        def parse_window(d):
            if not d:
                return None
            return {
                "utilization": float(d.get("utilization") or 0),
                "resets_at": datetime.fromisoformat(d["resets_at"]) if d.get("resets_at") else None,
            }

        result["five_hour"] = parse_window(raw.get("five_hour"))
        result["seven_day"] = parse_window(raw.get("seven_day"))

        extra = raw.get("extra_usage")
        if extra and extra.get("is_enabled"):
            result["extra"] = {
                "used": float(extra.get("used_credits") or 0),
                "limit": float(extra.get("monthly_limit") or 0),
                "utilization": float(extra.get("utilization") or 0),
            }

        return result


# ─── Helpers ─────────────────────────────────────────────────────────────────

def format_time_remaining(resets_at: Optional[datetime]) -> str:
    if not resets_at:
        return "unknown"
    delta = resets_at - datetime.now(timezone.utc)
    total = delta.total_seconds()
    if total < 0:
        return "resetting..."
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    return f"{h}h {m:02d}m" if h > 0 else f"{m}m"


def pct_color(pct: float) -> str:
    if pct >= 90:
        return "#e05252"
    elif pct >= 70:
        return "#e08c32"
    elif pct >= 50:
        return "#d4c022"
    return "#52c05a"


# ─── Tray Icon ────────────────────────────────────────────────────────────────

def make_tray_pixmap(five_h: float, seven_d: float) -> QPixmap:
    """Create 64x64 tray icon with usage arc."""
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Background circle
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(40, 40, 50, 220)))
    painter.drawEllipse(2, 2, size-4, size-4)

    pct = max(five_h, seven_d)
    color = QColor(pct_color(pct))

    # Arc
    pen = QPen(color)
    pen.setWidth(7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    span = int(-360 * pct / 100 * 16)
    painter.drawArc(8, 8, size-16, size-16, 90*16, span)

    # Text
    painter.setPen(QPen(QColor(230, 230, 230)))
    font = QFont("sans-serif", 11, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, f"{pct:.0f}%")

    painter.end()
    return pix


# ─── Main Window ─────────────────────────────────────────────────────────────

class UsageWorker(QObject):
    """背景執行緒工作者，用 signal 安全地回傳資料給主執行緒。"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, client: ClaudeAPIClient):
        super().__init__()
        self.client = client

    def run(self):
        try:
            usage = self.client.get_usage()
            # 第一次執行時一併取帳號資訊
            if not hasattr(self.client, '_account_info'):
                self.client._account_info = self.client.get_account_info()
            usage["account"] = self.client._account_info
            self.finished.emit(usage)
        except Exception as e:
            self.error.emit(str(e))


class StatusWorker(QObject):
    """背景查詢 Claude 服務狀態。"""
    finished = pyqtSignal(str, str)   # indicator, description
    error = pyqtSignal()

    def run(self):
        try:
            with urllib.request.urlopen(STATUS_API_URL, timeout=10) as resp:
                data = json.loads(resp.read())
            status = data.get("status", {})
            self.finished.emit(
                status.get("indicator", "none"),
                status.get("description", ""),
            )
        except Exception:
            self.error.emit()


class UsageWidget(QWidget):
    """深色主題浮動使用量監控視窗。"""

    def __init__(self, client: ClaudeAPIClient):
        super().__init__()
        self.client = client
        self._on_refresh_callback = None
        self._thread = None
        self._worker = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(REFRESH_INTERVAL * 1000)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(STATUS_REFRESH_INTERVAL * 1000)

        self._status_thread = None
        self._status_worker = None

        self._setup_ui()
        self._refresh()
        self._refresh_status()

    def _setup_ui(self):
        self.setWindowTitle("Claude Usage")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedWidth(400)
        self.setStyleSheet("""
            QWidget { background: #1a1a2e; color: #d0d0e8; font-family: sans-serif; font-size: 14px; }
            QLabel { color: #d0d0e8; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 標題列
        header = QFrame()
        header.setStyleSheet("background: #16213e;")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)
        hl.setSpacing(3)
        title = QLabel("☁  Claude 使用量監控")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #a0c8ff;")
        hl.addWidget(title)
        self._account_label = QLabel("帳號：讀取中...")
        self._account_label.setStyleSheet("font-size: 12px; color: #6080a0;")
        hl.addWidget(self._account_label)

        # 服務狀態燈號列
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("font-size: 13px; color: #404060;")
        status_row.addWidget(self._status_dot)
        self._service_status_label = QLabel("服務狀態：查詢中...")
        self._service_status_label.setStyleSheet("font-size: 12px; color: #6080a0;")
        status_row.addWidget(self._service_status_label)
        status_row.addStretch()
        hl.addLayout(status_row)

        layout.addWidget(header)

        # 主內容
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)

        self._five_hour = self._make_metric_section(cl, "5 小時視窗")
        self._add_divider(cl)
        self._seven_day = self._make_metric_section(cl, "7 天視窗")
        self._add_divider(cl)

        # 額外點數列
        extra_row = QHBoxLayout()
        extra_lbl = QLabel("額外點數")
        extra_lbl.setStyleSheet("font-size: 13px; color: #8080a0;")
        extra_row.addWidget(extra_lbl)
        self._extra_label = QLabel("—")
        self._extra_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._extra_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        extra_row.addWidget(self._extra_label)
        cl.addLayout(extra_row)

        layout.addWidget(content)

        # 狀態列
        footer = QFrame()
        footer.setStyleSheet("background: #0f3460;")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 6, 12, 6)
        self._status_label = QLabel("載入中...")
        self._status_label.setStyleSheet("font-size: 12px; color: #6080a0;")
        fl.addWidget(self._status_label)
        fl.addStretch()
        refresh_btn = QPushButton("↻ 重新整理")
        refresh_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #6090c0; border: none;
                          font-size: 13px; padding: 2px 6px; }
            QPushButton:hover { color: #80b0ff; }
        """)
        refresh_btn.clicked.connect(self._refresh)
        fl.addWidget(refresh_btn)
        layout.addWidget(footer)

    def _make_metric_section(self, parent_layout, title: str) -> dict:
        row = QHBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 13px; color: #8080a0;")
        row.addWidget(title_lbl)
        pct_lbl = QLabel("—")
        pct_lbl.setStyleSheet("font-size: 22px; font-weight: bold; color: #60a0ff;")
        pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(pct_lbl)
        parent_layout.addLayout(row)

        bar = QProgressBar()
        bar.setFixedHeight(10)
        bar.setTextVisible(False)
        bar.setStyleSheet("""
            QProgressBar { background: #2a2a4e; border-radius: 5px; border: none; }
            QProgressBar::chunk { border-radius: 5px; background: #4080c0; }
        """)
        parent_layout.addWidget(bar)

        reset_lbl = QLabel("")
        reset_lbl.setStyleSheet("font-size: 12px; color: #505070; margin-bottom: 4px;")
        parent_layout.addWidget(reset_lbl)

        return {"pct_lbl": pct_lbl, "bar": bar, "reset_lbl": reset_lbl}

    def _add_divider(self, layout):
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet("background: #2a2a4e;")
        layout.addWidget(div)

    def _update_metric(self, widgets: dict, data: Optional[dict]):
        if not data:
            widgets["pct_lbl"].setText("—")
            return
        pct = data["utilization"]
        color = pct_color(pct)
        widgets["pct_lbl"].setText(f"{pct:.0f}%")
        widgets["pct_lbl"].setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color};")
        widgets["bar"].setValue(int(pct))
        widgets["bar"].setStyleSheet(f"""
            QProgressBar {{ background: #2a2a4e; border-radius: 5px; border: none; }}
            QProgressBar::chunk {{ border-radius: 5px; background: {color}; }}
        """)
        if data.get("resets_at"):
            remaining = format_time_remaining(data["resets_at"])
            local_time = data["resets_at"].astimezone().strftime("%m/%d %H:%M")
            widgets["reset_lbl"].setText(f"  重置時間：{local_time}（剩餘 {remaining}）")

    def update_display(self, usage: dict):
        account = usage.get("account")
        if account:
            self._account_label.setText(
                f"帳號：{account['name']}  ({account['email']})"
            )
        self._update_metric(self._five_hour, usage.get("five_hour"))
        self._update_metric(self._seven_day, usage.get("seven_day"))

        extra = usage.get("extra")
        if extra:
            color = pct_color(extra["utilization"])
            self._extra_label.setText(
                f"${extra['used']:.0f} / ${extra['limit']:.0f}  ({extra['utilization']:.1f}%)"
            )
            self._extra_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
        else:
            self._extra_label.setText("未啟用")

        fetched = usage["fetched_at"].astimezone().strftime("%H:%M:%S")
        self._status_label.setText(f"更新時間：{fetched}")
        self._status_label.setStyleSheet("font-size: 12px; color: #6080a0;")

        if self._on_refresh_callback:
            self._on_refresh_callback(usage)

    def show_error(self, error: str):
        self._status_label.setText(f"錯誤：{error[:60]}")
        self._status_label.setStyleSheet("font-size: 12px; color: #e05252;")

    def _refresh(self):
        """在獨立執行緒中取得資料，透過 signal 更新 UI。"""
        # 避免重複執行
        if self._thread and self._thread.isRunning():
            return

        self._status_label.setText("更新中...")
        self._status_label.setStyleSheet("font-size: 12px; color: #80c0ff;")

        self._thread = QThread()
        self._worker = UsageWorker(self.client)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.update_display)
        self._worker.error.connect(self.show_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        self._thread.start()

    def _refresh_status(self):
        """查詢 Claude 服務狀態。"""
        if self._status_thread and self._status_thread.isRunning():
            return
        self._status_thread = QThread()
        self._status_worker = StatusWorker()
        self._status_worker.moveToThread(self._status_thread)
        self._status_thread.started.connect(self._status_worker.run)
        self._status_worker.finished.connect(self._update_service_status)
        self._status_worker.error.connect(self._on_status_error)
        self._status_worker.finished.connect(self._status_thread.quit)
        self._status_worker.error.connect(self._status_thread.quit)
        self._status_thread.start()

    def _update_service_status(self, indicator: str, description: str):
        color = STATUS_COLORS.get(indicator, "#404060")
        label = STATUS_LABELS.get(indicator, indicator)
        self._status_dot.setStyleSheet(f"font-size: 13px; color: {color};")
        self._service_status_label.setText(f"服務狀態：{label}")
        self._service_status_label.setStyleSheet(f"font-size: 12px; color: {color};")

    def _on_status_error(self):
        self._status_dot.setStyleSheet("font-size: 13px; color: #404060;")
        self._service_status_label.setText("服務狀態：無法查詢")
        self._service_status_label.setStyleSheet("font-size: 12px; color: #505070;")


# ─── System Tray ─────────────────────────────────────────────────────────────

class ClaudeMonitorApp:
    """System tray application with popup window."""

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.client = ClaudeAPIClient()
        self.latest_usage = None
        self.window = None
        self._setup_tray()

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("Warning: System tray not available, starting in window mode")
            self._start_window()
            return

        self.tray = QSystemTrayIcon(self.app)
        self.tray.setIcon(QIcon(make_tray_pixmap(0, 0)))
        self.tray.setToolTip("Claude Usage Monitor\nLoading...")

        menu = QMenu()
        show_action = menu.addAction("Show Details")
        show_action.triggered.connect(self._toggle_window)
        menu.addSeparator()
        refresh_action = menu.addAction("Refresh Now")
        refresh_action.triggered.connect(self._do_tray_refresh)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.app.quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self):
        if self.window is None:
            self._start_window()
        elif self.window.isVisible():
            self.window.hide()
        else:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def _start_window(self):
        self.window = UsageWidget(self.client)
        # Hook into refresh callback
        def on_refresh(usage):
            self.latest_usage = usage
            if hasattr(self, 'tray'):
                self._update_tray(usage)
        self.window._on_refresh_callback = on_refresh

        if self.latest_usage:
            self.window.update_display(self.latest_usage)
        self.window.show()

    def _update_tray(self, usage: dict):
        fh = usage.get("five_hour") or {}
        sd = usage.get("seven_day") or {}
        five_pct = fh.get("utilization", 0)
        seven_pct = sd.get("utilization", 0)

        self.tray.setIcon(QIcon(make_tray_pixmap(five_pct, seven_pct)))

        lines = ["Claude Usage Monitor"]
        if usage.get("five_hour"):
            fhd = usage["five_hour"]
            lines.append(f"5h: {fhd['utilization']:.0f}% (resets {format_time_remaining(fhd['resets_at'])})")
        if usage.get("seven_day"):
            sdd = usage["seven_day"]
            lines.append(f"7d: {sdd['utilization']:.0f}% (resets {format_time_remaining(sdd['resets_at'])})")
        extra = usage.get("extra")
        if extra:
            lines.append(f"Credits: ${extra['used']:.0f}/${extra['limit']:.0f} ({extra['utilization']:.1f}%)")
        self.tray.setToolTip("\n".join(lines))

    def _do_tray_refresh(self):
        if self.window:
            self.window._refresh()

    def run(self):
        print("Claude Usage Monitor started.")
        # Always show window on startup (GNOME doesn't display tray icons by default)
        self._start_window()
        sys.exit(self.app.exec())


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    monitor = ClaudeMonitorApp()
    monitor.run()
