#!/usr/bin/env python3
"""
Game Client - 通用遊戲客戶端

支援兩種模式：
1. File-based mode: 通過檔案與 game server 的 action reader 通訊
2. HTTP mode: 直接通過 HTTP API 與 game server 通訊

使用範例：
    # File-based mode (適合 LabVIEW 整合)
    client = GameClient(mode="file", match_id="abc123")
    client.send_action([1, 2, 0])  # 跳躍
    state = client.read_result()

    # HTTP mode (適合 Python 腳本)
    client = GameClient(mode="http", match_id="abc123")
    client.send_action([2, 1, 0])  # 向右移動
    state = client.get_state()
"""

import configparser
import json
import time
from pathlib import Path
from typing import Dict, List, Optional
import requests


# ==== Configuration ====

def _load_game_service_url() -> str:
    """Load Game Service URL from config/configfile.ini"""
    try:
        config_path = Path(__file__).parent.parent / "config" / "configfile.ini"
        if config_path.exists():
            config = configparser.ConfigParser()
            config.read(config_path)
            return config.get("Server", "game_service_url", fallback="http://localhost:8001")
    except Exception:
        pass
    return "http://localhost:8001"

_default_game_service_url = _load_game_service_url()


class GameClient:
    """通用遊戲客戶端"""

    def __init__(
        self,
        match_id: str,
        mode: str = "file",
        player_id: str = "player1",
        game_service_url: Optional[str] = None
    ):
        """
        初始化遊戲客戶端

        Args:
            match_id: 遊戲/比賽 ID
            mode: 通訊模式 ("file" 或 "http")
            player_id: 玩家 ID
            game_service_url: Game service 的 URL (None 則從 config/configfile.ini 讀取)
        """
        self.match_id = match_id
        self.mode = mode
        self.player_id = player_id
        self.game_service_url = (game_service_url or _default_game_service_url).rstrip('/')

        # 檔案路徑
        self.base_dir = Path(__file__).resolve().parent.parent
        self.actions_file = self.base_dir / "data" / "actions.txt"
        self.results_file = self.base_dir / "data" / "action_results.txt"

        # 確保 data 目錄存在
        self.actions_file.parent.mkdir(parents=True, exist_ok=True)

        # 結果讀取位置追蹤
        self.last_read_position = 0

    def send_action(self, action: List[int]) -> bool:
        """
        發送動作

        Args:
            action: [x, y, power] 動作陣列
                x: 0=左, 1=無, 2=右
                y: 0=無, 1=一般, 2=跳躍
                power: 0=一般, 1=強力擊球

        Returns:
            是否成功發送
        """
        if len(action) != 3:
            raise ValueError("動作必須是 [x, y, power] 格式")

        if self.mode == "file":
            return self._send_action_file(action)
        elif self.mode == "http":
            return self._send_action_http(action)
        else:
            raise ValueError(f"不支援的模式: {self.mode}")

    def _send_action_file(self, action: List[int]) -> bool:
        """通過檔案發送動作（不包含 match_id）"""
        try:
            line = f"{self.player_id}, {action[0]}, {action[1]}, {action[2]}\n"
            with open(self.actions_file, 'a') as f:
                f.write(line)
            return True
        except Exception as e:
            print(f"[ERROR] 寫入動作失敗: {e}")
            return False

    def _send_action_http(self, action: List[int]) -> bool:
        """通過 HTTP API 發送動作"""
        try:
            url = f"{self.game_service_url}/game/{self.match_id}/step"
            response = requests.post(
                url,
                json={"p1_action": action},
                timeout=5.0
            )
            return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] HTTP 請求失敗: {e}")
            return False

    def read_result(self, timeout: float = 1.0) -> Optional[Dict]:
        """
        讀取最新結果（僅 file 模式）

        Args:
            timeout: 等待結果的超時時間（秒）

        Returns:
            結果字典，如果沒有新結果則返回 None
        """
        if self.mode != "file":
            raise ValueError("read_result() 僅支援 file 模式")

        start_time = time.time()

        while time.time() - start_time < timeout:
            if not self.results_file.exists():
                time.sleep(0.01)
                continue

            try:
                with open(self.results_file, 'r') as f:
                    f.seek(self.last_read_position)
                    lines = f.readlines()

                    if lines:
                        # 讀取最後一行（最新結果）
                        for line in reversed(lines):
                            line = line.strip()
                            if line and line.startswith(self.match_id):
                                # 解析結果
                                result = self._parse_result_line(line)
                                if result:
                                    # 更新讀取位置
                                    self.last_read_position = f.tell()
                                    return result

                        # 更新讀取位置（即使沒找到匹配的結果）
                        self.last_read_position = f.tell()

            except Exception as e:
                print(f"[ERROR] 讀取結果失敗: {e}")

            time.sleep(0.01)

        return None

    def _parse_result_line(self, line: str) -> Optional[Dict]:
        """解析結果行"""
        try:
            # 格式: match_id,player_id,ball_x,ball_y,p1_x,p1_y,p2_x,p2_y,score_p1,score_p2,terminated
            parts = [p.strip() for p in line.split(',')]

            if len(parts) < 11:
                return None

            return {
                "match_id": parts[0],
                "player_id": parts[1],
                "ball": {
                    "x": float(parts[2]),
                    "y": float(parts[3])
                },
                "p1": {
                    "x": float(parts[4]),
                    "y": float(parts[5])
                },
                "p2": {
                    "x": float(parts[6]),
                    "y": float(parts[7])
                },
                "score_p1": int(parts[8]),
                "score_p2": int(parts[9]),
                "terminated": bool(int(parts[10]))
            }
        except Exception as e:
            print(f"[ERROR] 解析結果失敗: {e}")
            return None

    def get_state(self) -> Optional[Dict]:
        """
        獲取當前遊戲狀態（僅 HTTP 模式）

        Returns:
            狀態字典
        """
        if self.mode != "http":
            raise ValueError("get_state() 僅支援 HTTP 模式")

        try:
            url = f"{self.game_service_url}/game/{self.match_id}/state"
            response = requests.get(url, timeout=5.0)

            if response.status_code == 200:
                return response.json()["state"]
            return None
        except Exception as e:
            print(f"[ERROR] 獲取狀態失敗: {e}")
            return None

    # Action reader 控制方法（僅 file 模式）

    def start_action_reader(self) -> bool:
        """啟動 action reader（僅 file 模式）"""
        if self.mode != "file":
            return False

        try:
            url = f"{self.game_service_url}/action-reader/start"
            response = requests.post(url, timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] 啟動 action reader 失敗: {e}")
            return False

    def stop_action_reader(self) -> bool:
        """停止 action reader（僅 file 模式）"""
        if self.mode != "file":
            return False

        try:
            url = f"{self.game_service_url}/action-reader/stop"
            response = requests.post(url, timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] 停止 action reader 失敗: {e}")
            return False

    def clear_results(self) -> bool:
        """清空結果檔案（僅 file 模式）"""
        if self.mode != "file":
            return False

        try:
            url = f"{self.game_service_url}/action-reader/clear-results"
            response = requests.post(url, timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] 清空結果失敗: {e}")
            return False

    def action_reader_status(self) -> Optional[Dict]:
        """獲取 action reader 狀態（僅 file 模式）"""
        if self.mode != "file":
            return None

        try:
            url = f"{self.game_service_url}/action-reader/status"
            response = requests.get(url, timeout=5.0)

            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"[ERROR] 獲取 action reader 狀態失敗: {e}")
            return None

    # 遊戲管理方法

    def create_game(self, mode: str = "pvai") -> bool:
        """
        創建遊戲

        Args:
            mode: "pvai" (vs AI) 或 "pvp" (vs Player)

        Returns:
            是否成功創建
        """
        try:
            url = f"{self.game_service_url}/game/create"
            response = requests.post(
                url,
                json={"game_id": self.match_id, "mode": mode},
                timeout=5.0
            )
            return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] 創建遊戲失敗: {e}")
            return False

    def delete_game(self) -> bool:
        """刪除遊戲"""
        try:
            url = f"{self.game_service_url}/game/{self.match_id}"
            response = requests.delete(url, timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] 刪除遊戲失敗: {e}")
            return False


# 便捷函數

def list_games(game_service_url: str = "http://localhost:8001") -> List[Dict]:
    """列出所有遊戲"""
    try:
        url = f"{game_service_url.rstrip('/')}/games"
        response = requests.get(url, timeout=5.0)

        if response.status_code == 200:
            return response.json()["games"]
        return []
    except Exception as e:
        print(f"[ERROR] 列出遊戲失敗: {e}")
        return []


def health_check(game_service_url: Optional[str] = None) -> Optional[Dict]:
    """健康檢查"""
    try:
        url = f"{(game_service_url or _default_game_service_url).rstrip('/')}/health"
        response = requests.get(url, timeout=5.0)

        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"[ERROR] 健康檢查失敗: {e}")
        return None


if __name__ == "__main__":
    # 簡單測試
    print("=" * 60)
    print("Game Client Test")
    print("=" * 60)

    # 健康檢查
    health = health_check()
    if health:
        print(f"✓ Game Service 運行中: {health}")
    else:
        print("✗ Game Service 未運行")
        exit(1)

    # 測試 file 模式
    print("\n[TEST] File-based mode")
    client = GameClient(match_id="test123", mode="file")

    # 創建遊戲
    print("Creating game...")
    if client.create_game():
        print("✓ Game created")

    # 啟動 action reader
    print("Starting action reader...")
    if client.start_action_reader():
        print("✓ Action reader started")

    # 發送測試動作
    print("Sending action [2, 1, 0]...")
    client.send_action([2, 1, 0])

    # 讀取結果
    print("Reading result...")
    result = client.read_result(timeout=2.0)
    if result:
        print(f"✓ Result: ball=({result['ball']['x']:.1f}, {result['ball']['y']:.1f}), "
              f"score={result['score_p1']}:{result['score_p2']}")
    else:
        print("✗ No result received")

    # 停止 action reader
    print("Stopping action reader...")
    client.stop_action_reader()

    print("\n" + "=" * 60)
