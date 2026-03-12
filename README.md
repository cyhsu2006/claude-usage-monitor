# Claude Usage Monitor

**繁體中文** | **English**

桌面小工具，即時監控 Claude 訂閱方案的使用量限制。
A desktop widget for real-time monitoring of Claude subscription plan usage limits.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![PyQt6](https://img.shields.io/badge/UI-PyQt6-green)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey)

---

## 功能 / Features

- **5 小時視窗**使用率 + 重置時間
  **5-hour window** utilization + reset time
- **7 天視窗**使用率 + 重置時間
  **7-day window** utilization + reset time
- **額外點數**消耗金額與百分比
  **Extra credits** amount spent and percentage
- 顯示目前登入的帳號（名稱 + Email）
  Shows the currently logged-in account (name + email)
- 每 5 分鐘自動更新，或手動點擊重新整理
  Auto-refreshes every 5 minutes, or manually on demand
- 顏色警示：綠（正常）→ 黃（50%+）→ 橘（70%+）→ 紅（90%+）
  Color indicators: Green (normal) → Yellow (50%+) → Orange (70%+) → Red (90%+)

---

## 運作原理 / How It Works

Claude 官方沒有提供使用量 API，但網頁版內部會呼叫：
Claude provides no official usage API, but the web app internally calls:

```
GET https://claude.ai/api/organizations/{org_id}/usage
```

本程式從 Firefox 的 SQLite cookie 資料庫讀取 session，使用 `tls-client` 模擬 Firefox TLS 指紋（繞過 Cloudflare），定期呼叫該 API 取得資料。
This tool reads your session from Firefox's SQLite cookie database, uses `tls-client` to impersonate Firefox's TLS fingerprint (bypassing Cloudflare), and periodically calls that API to fetch usage data.

---

## 前置條件 / Prerequisites

- 使用 **Firefox** 瀏覽器並登入 claude.ai
  Use **Firefox** and be logged in to claude.ai
- Python 3.10+

---

## 安裝 / Installation

```bash
pip3 install tls-client PyQt6 --break-system-packages
```

---

## 使用方式 / Usage

```bash
DISPLAY=:1 python3 monitor.py
```

### 自動啟動（systemd）/ Auto-start (systemd)

```bash
cp claude-monitor.service ~/.config/systemd/user/
systemctl --user enable --now claude-monitor.service
```

`claude-monitor.service`:

```ini
[Unit]
Description=Claude Usage Monitor
After=graphical-session.target

[Service]
Type=simple
ExecStart=/home/YOUR_USER/Projects/UsageMonitor/run.sh
Environment=DISPLAY=:1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

> 將 `YOUR_USER` 替換為你的使用者名稱。
> Replace `YOUR_USER` with your username.

---

## 注意事項 / Notes

- 每次重新整理都會從 Firefox 讀取最新 cookie；若 session 過期需重新登入 Firefox
  Each refresh reads the latest cookies from Firefox; re-login to Firefox if your session expires
- 此工具僅供個人監控自己的帳號使用
  This tool is intended for personal use to monitor your own account only
- 非官方工具，API 端點可能隨時變更
  Unofficial tool — the API endpoint may change at any time
