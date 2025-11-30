# 🚀 快速啟動指南

## 📋 系統架構

```
┌─────────────────┐
│  LabVIEW Client │  (你的 LabVIEW 程式)
└────────┬────────┘
         │ 調用 Python API
         ▼
┌─────────────────┐
│  Client API     │  (lv_ws_client.py)
│  (port N/A)     │
└────────┬────────┘
         │ HTTP REST (輪詢 60 FPS)
         ▼
┌─────────────────┐
│  Match Server   │  (main_microservice.py)
│  (port 8000)    │  [REST API 只]
└────────┬────────┘
         │ HTTP REST
         ▼
┌─────────────────┐
│  Game Service   │  (game_server.py)
│  (port 8001)    │
└─────────────────┘
```

## 🎯 啟動步驟（必須按順序）

### 1️⃣ 啟動 Game Service

**終端 1：**
```bash
cd game_service
uv run python game_server.py
```

**看到這個表示成功：**
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
```

### 2️⃣ 啟動 Match Server

**終端 2：**
```bash
cd server
uv run python main_microservice.py
```

**看到這個表示成功：**
```
============================================================
Pikachu Volleyball Match Server (Microservice Architecture)
============================================================
Match Server will run on: http://0.0.0.0:8000
Game Service expected at: http://localhost:8001

Logging enabled - WebSocket connections will be logged
============================================================
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 3️⃣ 測試連接（可選）

**終端 3：**
```bash
# 測試 Game Service
curl http://localhost:8001/health

# 測試 Match Server
curl http://localhost:8000/health
```

## 🎮 使用 Client

### 選項 A：Python 腳本測試

**終端 3：**
```bash
cd client

# 運行簡單測試
uv run python -c "
import lv_ws_client as client
import time

# 創建比賽
match = client.create_match('pvai', 'player1', 'Howard')
print(f'Match ID: {match[\"match_id\"]}')

# 連接
client.connect(match['ws_url'])
time.sleep(1)

# 發送輸入
for i in range(20):
    client.send_input('jump' if i % 5 == 0 else 'left')
    state = client.poll_state()
    if state:
        print(f'Score: P1={state[\"score\"][\"p1\"]}, P2={state[\"score\"][\"p2\"]}')
    time.sleep(0.1)

client.disconnect()
print('Done!')
"
```

### 選項 B：運行測試套件

```bash
cd client

# 快速測試
uv run pytest tests/test_simple_game.py -v

# 壓力測試
uv run pytest tests/test_stress.py::test_stress_light -v
```

### 選項 C：LabVIEW 調用

**在 LabVIEW 中：**

1. **導入 Python 模組**
   - Python 路徑在 `config/configfile.ini` 中設定
   - 模組：`lv_ws_client`

2. **基本流程：**

```
┌─────────────────────────────────────────┐
│ 1. 創建比賽                              │
│    match_info = create_match(           │
│        "pvai",                          │
│        "labview_player",                │
│        "Player Name"                    │
│    )                                    │
│    match_id = match_info["match_id"]    │
└───────────────┬─────────────────────────┘
                │
┌───────────────▼─────────────────────────┐
│ 2. 註冊玩家                              │
│    connect(match_id, "player1")         │
│    等待 100ms                            │
└───────────────┬─────────────────────────┘
                │
┌───────────────▼─────────────────────────┐
│ 3. 遊戲循環 (每 16ms = 60 FPS)           │
│    Loop:                                │
│      user_input = 讀取按鍵               │
│      send_input(match_id, user_input,   │
│                 "player1")              │
│                                         │
│      state = poll_state(match_id,       │
│                         "player1")      │
│      if state:                          │
│          更新 UI 顯示                    │
│          - 球的位置 state["ball"]        │
│          - 玩家位置 state["p1"]          │
│          - 分數 state["score"]           │
│                                         │
│      等待 16ms (維持 60 FPS)             │
└───────────────┬─────────────────────────┘
                │
┌───────────────▼─────────────────────────┐
│ 4. 結束時清理                            │
│    disconnect(match_id, "player1")      │
│    stop_match(match_id)                 │
└─────────────────────────────────────────┘
```

## 📂 重要文件位置

### Client 端（LabVIEW 調用）
- **主要 API**: `client/lv_ws_client.py`
- **配置文件**: `config/configfile.ini`

### Server 端
- **Match Server**: `server/main_microservice.py`
- **Game Service**: `game_service/game_server.py`

### 測試
- **測試文件**: `client/tests/`
- **測試腳本**: `client/tests/run_tests.sh`

## ⚙️ 配置文件

**`config/configfile.ini`**
```ini
[Python]
version = 3.8
path = /path/to/client/.venv/bin/python3

[Server]
match_server_url = http://localhost:8000
```

## 🔧 常見問題

### Q1: Server 無法啟動
**A:** 檢查端口是否被佔用
```bash
# 檢查 8000 和 8001 端口
lsof -i :8000
lsof -i :8001

# 如果被佔用，終止進程或換端口
```

### Q2: Client 連不上 Server
**A:** 確認兩個服務都在運行
```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### Q3: WebSocket 立刻斷開
**A:** 檢查 Python 版本（需要 3.8+）和 client 代碼

### Q4: 修改了 game/ 代碼沒生效
**A:** 重啟 Game Service
```bash
# 在 Game Service 終端按 Ctrl+C
# 然後重新運行
cd game_service
uv run python game_server.py
```

## 📊 監控狀態

### 查看系統狀態
```bash
# Match Server 狀態
curl http://localhost:8000/system/status

# Game Service 健康
curl http://localhost:8001/health

# 列出所有遊戲
curl http://localhost:8001/games
```

## 🛑 停止服務

在各個終端按 `Ctrl+C` 即可。

**順序建議：**
1. 先停 Client（如果在運行）
2. 再停 Match Server（終端 2）
3. 最後停 Game Service（終端 1）

## 📝 完整示例

**完整的 Python 測試腳本：**

```python
#!/usr/bin/env python3
import lv_ws_client as client
import time

print("1. 創建比賽...")
match_info = client.create_match(
    mode="pvai",
    player_id="test",
    player_name="Test Player"
)
match_id = match_info["match_id"]
print(f"   Match ID: {match_id}")

print("2. 註冊玩家...")
result = client.connect(match_id, "player1")
print(f"   建議輪詢間隔: {result['polling_interval_ms']}ms (60 FPS)")
time.sleep(0.1)

print("3. 玩遊戲 10 秒 (60 FPS)...")
start = time.time()
while time.time() - start < 10:
    # 發送輸入
    move = "jump" if int(time.time()) % 3 == 0 else "left"
    client.send_input(match_id, move, "player1")

    # 輪詢狀態
    state = client.poll_state(match_id, "player1")
    if state:
        score = state["score"]
        print(f"   Score: P1={score['p1']}, P2={score['p2']}", end='\r')

    time.sleep(0.016)  # ~60 FPS

print("\n4. 斷開連接...")
client.disconnect(match_id, "player1")
client.stop_match(match_id)
print("✓ 完成！")
```

儲存為 `test_game.py` 然後運行：
```bash
cd client
uv run python test_game.py
```

---

## 🎉 完成！

現在你可以：
1. ✅ 啟動兩個服務
2. ✅ 用 Python 測試遊戲
3. ✅ 在 LabVIEW 中調用 API
4. ✅ 修改 game/ 代碼並測試

有問題查看詳細文檔：
- 微服務架構：`MICROSERVICE_GUIDE.md`
- 整合指南：`INTEGRATION_GUIDE.md`
- 測試說明：`client/tests/README.md`
