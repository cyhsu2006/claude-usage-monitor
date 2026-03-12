# Claude Usage Monitor

桌面小工具，即時監控 Claude 訂閱方案的使用量限制。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![PyQt6](https://img.shields.io/badge/UI-PyQt6-green)

## 功能

- **5 小時視窗**使用率 + 重置時間
- **7 天視窗**使用率 + 重置時間
- **額外點數**消耗金額與百分比
- 顯示目前登入的帳號（名稱 + Email）
- 每 5 分鐘自動更新，或手動點擊重新整理
- 顏色警示：綠（正常）→ 黃（50%+）→ 橘（70%+）→ 紅（90%+）

## 運作原理

Claude 官方沒有提供使用量 API，但網頁版內部有呼叫：

```
GET https://claude.ai/api/organizations/{org_id}/usage
```

本程式從 Firefox 的 SQLite cookie 資料庫讀取 session，使用 `tls-client` 模擬 Firefox TLS 指紋（繞過 Cloudflare），定期呼叫該 API 取得資料。

## 安裝

```bash
pip3 install tls-client PyQt6 --break-system-packages
```

## 前置條件

- 使用 **Firefox** 瀏覽器並登入 claude.ai
- 本程式會自動從 Firefox profile 讀取 session cookie

## 使用方式

```bash
DISPLAY=:1 python3 monitor.py
```

### 設定自動啟動（systemd）

```bash
# 複製 service 檔案
cp claude-monitor.service ~/.config/systemd/user/

# 啟用
systemctl --user enable --now claude-monitor.service
```

`claude-monitor.service` 內容：

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

> 請將 `YOUR_USER` 替換為你的使用者名稱。

## 注意事項

- 每次重新整理都會從 Firefox 讀取最新的 cookie，若 session 過期需重新登入 Firefox
- 此工具僅供個人監控自己的帳號使用
- 非官方工具，API 可能隨時變更
