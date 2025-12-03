# 簡化後的 LabVIEW Client API 使用指南

## 概述

client API 已經大幅簡化：
- 所有動作使用統一的數字陣列格式 `[x, y, power]`
- 操作函數回傳簡單的字串結果，方便在 LabVIEW 中使用

## 動作映射表

```python
動作          陣列格式 [x, y, power]
----------------------------------------
none         [1, 1, 0]  # 無動作
left         [0, 1, 0]  # 左移
right        [2, 1, 0]  # 右移
jump         [1, 2, 0]  # 跳躍
power        [1, 1, 1]  # 重擊
jump_left    [0, 2, 0]  # 向左跳
jump_right   [2, 2, 0]  # 向右跳
```

參數說明：
- **x**: 0=左, 1=無, 2=右
- **y**: 0=無, 1=普通, 2=跳躍
- **power**: 0=普通, 1=重擊

## 基本使用流程

### 1. 設定伺服器位址（可選）

```python
import lv_ws_client as client

# 如果不是使用預設位址，可以設定
client.set_server_url("http://localhost:8000")
```

### 2. 建立比賽

```python
# 建立 PvAI 比賽
match_id = client.create_match("pvai", "player1", "Howard")
# 回傳: match_id 字串，例如 "abc12345"
```

### 3. 傳送玩家輸入

**不需要手動呼叫 `connect()`！** 伺服器會自動註冊。

```python
# 直接傳送動作陣列
result = client.send_input(match_id, [1, 2, 0])  # 跳躍
# 回傳: "True" 或錯誤訊息

# 其他動作範例
client.send_input(match_id, [0, 1, 0])  # 左移
client.send_input(match_id, [2, 1, 0])  # 右移
client.send_input(match_id, [1, 1, 1])  # 重擊
client.send_input(match_id, [0, 2, 0])  # 向左跳
```

### 4. 輪詢遊戲狀態

建議每 16ms 呼叫一次以達到 60 FPS。**不需要傳 role 參數**！

```python
state_json = client.poll_state(match_id)
# 回傳: JSON 字串

# 在 LabVIEW 中使用 JSON Parse VI 解析
# 在 Python 中可以這樣解析：
import json
state = json.loads(state_json)

# 球的位置
ball_x = state['ball']['x']
ball_y = state['ball']['y']

# 玩家位置
p1_x = state['player1']['x']
p1_y = state['player1']['y']

# 分數
score_p1 = state['score']['p1']
score_p2 = state['score']['p2']
```

### 5. 結束比賽

```python
result = client.stop_match(match_id)
# 回傳: True 或 False (boolean)
```

## 完整範例

```python
import lv_ws_client as client
import json
import time

# 1. 建立比賽
match_id = client.create_match("pvai", "player1", "Howard")
print(f"Match created: {match_id}")

# 2. 遊戲迴圈 (60 FPS)
for i in range(600):  # 10 秒
    # 傳送輸入（根據你的邏輯決定動作）
    if i % 60 == 0:  # 每秒跳一次
        result = client.send_input(match_id, [1, 2, 0])  # 跳躍
        print(f"Input result: {result}")
    else:
        client.send_input(match_id, [1, 1, 0])  # 無動作

    # 輪詢狀態
    state_json = client.poll_state(match_id)
    try:
        state = json.loads(state_json)
        print(f"Frame {i}: Ball at ({state['ball']['x']:.1f}, {state['ball']['y']:.1f})")
    except json.JSONDecodeError:
        print(f"Error parsing state: {state_json[:50]}")

    # 等待下一幀 (16.67ms ≈ 60 FPS)
    time.sleep(1/60)

# 3. 停止比賽
if client.stop_match(match_id):
    print("Match stopped successfully")
```

## API 函數參考

### 比賽管理

| 函數 | 參數 | 回傳 | 說明 |
|------|------|------|------|
| `create_match(mode, player_id, player_name)` | mode: "pvai"/"pvp"<br>player_id: str<br>player_name: str (optional) | str (match_id) | 建立新比賽 |
| `stop_match(match_id)` | match_id: str | bool | 停止比賽 |
| `restart_match(match_id)` | match_id: str | bool | 重新開始 |
| `get_match_status(match_id)` | match_id: str | dict | 取得狀態 |
| `get_server_status()` | - | dict | 伺服器狀態 |

### 遊戲操作

| 函數 | 參數 | 回傳 | 說明 |
|------|------|------|------|
| `send_input(match_id, move, role)` | match_id: str<br>move: list[int] (必須)<br>role: str (default "player1") | str | 傳送輸入陣列 |
| `poll_state(match_id)` | match_id: str | str (JSON) | 輪詢狀態，回傳 JSON 字串 |
| `connect(match_id, role)` | match_id: str<br>role: str (default "player1") | bool | **可選**註冊 |
| `disconnect(match_id, role)` | match_id: str<br>role: str (default "player1") | bool | 取消註冊 |

## 重要提示

1. **不需要手動 `connect()`**：首次呼叫 `send_input()` 或 `poll_state()` 時會自動註冊
2. **統一使用陣列格式**：所有動作都使用 `[x, y, power]` 陣列，不再支援字串動作名稱
3. **狀態輪詢**：建議每 16ms 呼叫一次 `poll_state()` 達到 60 FPS
4. **回傳值統一為字串**：
   - `send_input()` 回傳 `"True"` 表示成功，或回傳錯誤訊息字串
   - `poll_state()` 回傳 **JSON 字串**，在 LabVIEW 中使用 **Unflatten From JSON** 解析
   - `stop_match()`, `restart_match()`, `connect()`, `disconnect()` 回傳 `bool`

## LabVIEW 整合建議

### 基本架構
1. 使用 **While Loop** 配合 **Wait (ms)** 設定為 16ms (60 FPS)
2. 使用 **Case Structure** 根據輸入建構對應的 `[x, y, power]` 陣列

### JSON 解析
3. `poll_state()` 回傳 JSON 字串，使用 LabVIEW 內建的 **Unflatten From JSON** VI：
   - 路徑: `Data Communication > Protocols > JSON > Unflatten From JSON`
   - 輸入: poll_state() 回傳的字串
   - 輸出: Cluster 包含遊戲狀態資料

### JSON 結構範例
```json
{
  "type": "state",
  "ball": {
    "x": 216.0,
    "y": 100.0,
    "rotation": 0.0
  },
  "player1": {
    "x": 144.0,
    "y": 244.0,
    "state": 0,
    "frame_num": 0
  },
  "player2": {
    "x": 288.0,
    "y": 244.0,
    "state": 0,
    "frame_num": 0
  },
  "score": {
    "p1": 0,
    "p2": 0
  },
  "sequence": 123,
  "timestamp": 1234567890.123
}
```

### 在 LabVIEW 中建立對應的 Cluster
建議建立一個 Cluster 包含：
- `ball` (Cluster): x, y, rotation (DBL)
- `player1` (Cluster): x, y, state, frame_num
- `player2` (Cluster): x, y, state, frame_num
- `score` (Cluster): p1, p2 (I32)
- `sequence` (I32)
- `timestamp` (DBL)
