# Pikachu Volleyball 微服務架構指南

## 架構概覽

本專案採用**微服務架構**，將遊戲物理引擎和匹配服務分離為兩個獨立的服務：

```
┌──────────────────────────────────────────────────────────┐
│                    Client (LabVIEW)                      │
│  - HTTP REST API (create match, get stats, etc.)        │
│  - WebSocket (real-time game state updates)             │
└────────────────┬─────────────────────────────────────────┘
                 │
                 │ HTTP + WebSocket
                 ▼
┌──────────────────────────────────────────────────────────┐
│              Match Server (port 8000)                    │
│  - 管理玩家連接                                            │
│  - WebSocket 狀態廣播 (60 FPS)                            │
│  - 匹配管理和玩家註冊                                       │
└────────────────┬─────────────────────────────────────────┘
                 │
                 │ HTTP REST API
                 ▼
┌──────────────────────────────────────────────────────────┐
│              Game Service (port 8001)                    │
│  - Gymnasium 物理引擎                                      │
│  - 遊戲狀態管理                                            │
│  - AI 對手邏輯                                            │
│  - 您修改過的 game/ 代碼                                   │
└──────────────────────────────────────────────────────────┘
```

## 為什麼使用微服務架構？

### ✅ 優點

1. **獨立開發和部署**
   - Game Service 和 Match Server 可以獨立開發、測試、部署
   - 修改 game/ 代碼後只需重啟 Game Service

2. **技術解耦**
   - Match Server 不需要導入 pygame、gymnasium 等重量級依賴
   - 減少依賴衝突

3. **擴展性**
   - 未來可以部署多個 Game Service 實例進行負載均衡
   - 支援分布式架構

4. **易於測試**
   - 可以單獨測試 Game Service 的物理引擎
   - Mock Game Service 進行 Match Server 測試

5. **支援未來的雙人模式**
   - Game Service 已經設計為支援 PvP
   - 只需更新 game/ 代碼即可

### ⚠️ 注意事項

1. **網絡延遲**
   - 服務間通過 HTTP 通信會有輕微延遲
   - 對於 60 FPS 的遊戲來說可以接受（本地延遲 < 1ms）

2. **需要管理兩個服務**
   - 開發時需要同時啟動兩個 server
   - 生產環境需要監控兩個服務的健康狀態

## 服務 API 規格

### Game Service (port 8001)

#### 1. 健康檢查
```http
GET /health
```

回應：
```json
{
  "status": "ok",
  "service": "game-service",
  "version": "1.0",
  "active_games": 2
}
```

#### 2. 創建遊戲
```http
POST /game/create
Content-Type: application/json

{
  "mode": "pvai",  // "pvai" or "pvp"
  "game_id": "abc123"  // optional
}
```

回應：
```json
{
  "game_id": "abc123",
  "mode": "pvai",
  "state": {
    "game_id": "abc123",
    "ball": {"x": 216.0, "y": 100.0, "vx": 0.0, "vy": 0.0},
    "p1": {"x": 64.0, "y": 244.0, "vy": 0.0},
    "p2": {"x": 368.0, "y": 244.0, "vy": 0.0},
    "score_p1": 0,
    "score_p2": 0,
    "terminated": false,
    "mode": "pvai"
  }
}
```

#### 3. 遊戲步進
```http
POST /game/{game_id}/step
Content-Type: application/json

{
  "p1_action": "jump",  // "left", "right", "jump", "none"
  "p2_action": "left"   // optional, for PvP mode
}
```

回應：
```json
{
  "state": {
    "game_id": "abc123",
    "ball": {"x": 220.5, "y": 105.2, "vx": 2.5, "vy": 1.2},
    "p1": {"x": 64.0, "y": 230.0, "vy": -8.0},
    "p2": {"x": 363.0, "y": 244.0, "vy": 0.0},
    "score_p1": 0,
    "score_p2": 0,
    "terminated": false,
    "mode": "pvai"
  }
}
```

#### 4. 獲取狀態
```http
GET /game/{game_id}/state
```

#### 5. 重置遊戲
```http
POST /game/{game_id}/reset
```

#### 6. 刪除遊戲
```http
DELETE /game/{game_id}
```

#### 7. 列出所有遊戲
```http
GET /games
```

回應：
```json
{
  "games": [
    {"game_id": "abc123", "mode": "pvai", "score": {"p1": 2, "p2": 1}},
    {"game_id": "def456", "mode": "pvp", "score": {"p1": 0, "p2": 0}}
  ]
}
```

### Match Server (port 8000)

Match Server 的 API 保持不變，與之前版本相同。

## 安裝和運行

### 1. 安裝 Game Service 依賴

```bash
cd game_service
uv sync
```

### 2. 安裝 Match Server 依賴

```bash
cd ../server
uv sync
```

### 3. 安裝 Client 依賴

```bash
cd ../client
uv sync
```

### 4. 啟動服務

**終端 1 - 啟動 Game Service：**
```bash
cd game_service
uv run python game_server.py
```

輸出：
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001
```

**終端 2 - 啟動 Match Server：**
```bash
cd server
uv run python main_microservice.py
```

輸出：
```
============================================================
Pikachu Volleyball Match Server (Microservice Architecture)
============================================================
Match Server will run on: http://0.0.0.0:8000
Game Service expected at: http://localhost:8001

Make sure Game Service is running first:
  cd game_service && python game_server.py
============================================================
INFO:     Uvicorn running on http://0.0.0.0:8000
```

## 使用示例

### Python 測試

```python
import requests
import time

# 1. 測試 Game Service
game_health = requests.get("http://localhost:8001/health").json()
print(f"Game Service: {game_health}")

# 2. 測試 Match Server
match_health = requests.get("http://localhost:8000/health").json()
print(f"Match Server: {match_health}")

# 3. 創建比賽
response = requests.post(
    "http://localhost:8000/match/start",
    json={"mode": "pvai", "player_id": "test", "player_name": "Test Player"}
)
match_info = response.json()
print(f"Match created: {match_info}")

# 4. 使用 Client API
import sys
sys.path.insert(0, "../client")
import lv_ws_client as client

match_id = match_info["match_id"]
ws_url = match_info["ws_url"]

client.connect(ws_url)
time.sleep(0.5)

# 遊戲循環
for i in range(100):
    client.send_input("jump" if i % 20 == 0 else "left")
    state = client.poll_state()
    if state:
        print(f"Score: P1={state['score']['p1']}, P2={state['score']['p2']}")
    time.sleep(0.1)

client.disconnect()
```

### LabVIEW 使用

LabVIEW 的使用方式**完全不變**，因為 Match Server 的 API 保持兼容：

```
// 初始化（使用 Client API）
match_info = create_match("pvai", "labview_player", "Howard")
ws_url = match_info["ws_url"]

// 連接 WebSocket
connect(ws_url)

// 遊戲循環
Loop:
    send_input(user_action)
    state = poll_state()
    update_ui(state)

// 清理
disconnect()
stop_match(match_id)
```

## 修改 Game 代碼

當您需要修改 game 代碼時：

### 1. 修改代碼
編輯 `game/pykachu_env/` 下的任何文件：
- `constants.py` - 遊戲常數
- `physics.py` - 物理引擎
- `pykachu_volleyball_env.py` - Gymnasium 環境
- `render.py` - 渲染邏輯

### 2. 重啟 Game Service
```bash
# 在 Game Service 終端按 Ctrl+C
# 然後重新啟動
uv run python game_server.py
```

**Match Server 不需要重啟**！

### 3. 測試修改
```bash
# 測試 Game Service API
curl http://localhost:8001/health
```

## 支援雙人模式

Game Service 已經預留了雙人支持：

### Game Service 端（已完成）

```python
# 在 game_server.py 的 step_game 中：
@app.post("/game/{game_id}/step")
async def step_game(game_id: str, request: GameStepRequest):
    # 已支援 p2_action
    state = game.step(request.p1_action, request.p2_action)
    ...
```

### 需要修改的部分

1. **修改 `game/pykachu_env/pykachu_volleyball_env.py`**
   - 讓 `step()` 方法接受雙玩家輸入
   - 目前只接受單個 action，需要改為接受兩個 actions

2. **修改 `game/pykachu_env/physics.py`**
   - 確保 `physics_engine()` 正確處理兩個玩家的輸入
   - 目前已經支援，只需確認邏輯

### 示例修改（pykachu_volleyball_env.py）

```python
def step(self, action, action_p2=None):
    """
    Args:
        action: Player 1 action (MultiDiscrete)
        action_p2: Player 2 action (optional, uses AI if None)
    """
    player1_input = UserInput(action)

    if action_p2 is not None:
        # PvP mode: use provided player 2 action
        player2_input = UserInput(action_p2)
    else:
        # PvAI mode: let AI decide
        player2_input = UserInput(action)  # or use heuristic AI

    self.is_ball_touching_ground = self.physics.run_engine([player1_input, player2_input])
    ...
```

## 故障排除

### Game Service 無法啟動

**檢查依賴：**
```bash
cd game_service
uv sync
```

**檢查 game 目錄：**
```bash
ls ../game/pykachu_env/
# 應該看到：__init__.py, physics.py, constants.py, 等
```

### Match Server 無法連接 Game Service

**檢查 Game Service 是否運行：**
```bash
curl http://localhost:8001/health
```

**檢查防火牆設定**

**修改 Game Service URL（如果需要）：**

編輯 `server/main_microservice.py`:
```python
GAME_SERVICE_URL = "http://localhost:8001"  # 改為您的 URL
```

### WebSocket 連接失敗

確認兩個服務都在運行：
```bash
# 終端 1
cd game_service && uv run python game_server.py

# 終端 2
cd server && uv run python main_microservice.py
```

## 性能優化

### 本地部署
- Game Service 和 Match Server 在同一台機器上
- HTTP 延遲 < 1ms，對 60 FPS 遊戲影響極小

### 分布式部署
如果需要將服務部署在不同機器：
1. 調整 `GAME_SERVICE_URL` 為實際 IP
2. 考慮使用 gRPC 替代 HTTP 以降低延遲
3. 添加連接池和重試邏輯

## 監控和日誌

### 健康檢查
```bash
# Match Server 健康（包含 Game Service 狀態）
curl http://localhost:8000/health

# Game Service 健康
curl http://localhost:8001/health
```

### 系統狀態
```bash
# Match Server 狀態
curl http://localhost:8000/system/status

# Game Service 遊戲列表
curl http://localhost:8001/games
```

## 總結

微服務架構讓您能夠：
- ✅ 獨立修改和測試 game 物理引擎
- ✅ Match Server 保持輕量，只處理連接管理
- ✅ 為未來的雙人模式預留擴展空間
- ✅ 易於分布式部署和擴展

開發時只需啟動兩個服務，LabVIEW client 的使用方式完全不變！🎉
