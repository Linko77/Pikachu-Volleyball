#!/usr/bin/env python3
"""
LabVIEW Bridge - 統一的遊戲狀態截取和 Action 發送

這個腳本同時處理：
1. 截取遊戲狀態（WebSocket -> JSON 文件）
2. 處理 Actions（文件 -> Game Service）

使用方式：
    # 自動模式（從 data/match_ids.txt 讀取）
    uv run client/labview_bridge.py

    # 手動指定 match ID
    uv run client/labview_bridge.py --match-id abc123

LabVIEW 端：
    讀取: data/pikachu_state_{match_id}.json
    寫入: data/actions.txt (格式: match_id, player_id, x, y, power)
    結果: data/action_results.txt
"""

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from game_client import GameClient, health_check
from lv_ws_client import WebSocketClient

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "data" / "match_id.txt"
DATA_DIR = BASE_DIR / "data"
POLL_INTERVAL = 1.0 / 60.0  # 60 FPS


class LabVIEWBridge:
    """統一的 LabVIEW 橋接器"""

    def __init__(self):
        self.running = False
        self.match_id: Optional[str] = None
        self.ws_client: Optional[WebSocketClient] = None
        self.game_client: Optional[GameClient] = None
        self.frame_count = 0
        self.start_time = time.time()
        self.last_result_position = 0  # 追踪已读取的结果位置

        # 確保目錄存在
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def atomic_write_json(self, file_path: Path, data: dict):
        """原子性寫入 JSON"""
        temp_file = file_path.with_suffix('.tmp')
        with open(temp_file, 'w', encoding="utf-8") as f:
            json.dump(data, f, separators=(',', ':'))
        temp_file.replace(file_path)

    def read_config(self) -> Optional[str]:
        """讀取配置文件（單個 match ID）"""
        if not CONFIG_FILE.exists():
            return None
        try:
            with open(CONFIG_FILE) as f:
                line = f.readline().strip()
                if line and not line.startswith('#'):
                    return line
            return None
        except Exception as e:
            print(f"[ERROR] 讀取配置失敗: {e}")
            return None

    def setup_match(self, match_id: str) -> bool:
        """設置 match"""
        print(f"[+] 設置 match: {match_id}")

        # 創建 WebSocket 客戶端（讀取狀態）
        self.ws_client = WebSocketClient()
        if self.ws_client.connect(match_id, role="player2"):
            print(f"  ✓ WebSocket 連線成功")
        else:
            print(f"  ✗ WebSocket 連線失敗")
            return False

        # 創建 Game 客戶端（處理 actions）
        self.game_client = GameClient(match_id=match_id, mode="file", player_id="player1")

        # 確保遊戲存在
        if not self.game_client.create_game(mode="pvai"):
            print(f"  ⚠ 遊戲可能已存在")

        # 啟動 action reader
        self.game_client.clear_results()
        if self.game_client.start_action_reader():
            print(f"  ✓ Action Reader 已啟動")
        else:
            print(f"  ⚠ Action Reader 啟動失敗（可能已在運行）")

        self.match_id = match_id
        return True

    def cleanup_match(self):
        """清理 match"""
        if not self.match_id:
            return

        print(f"[-] 清理 match: {self.match_id}")

        # 關閉 WebSocket
        if self.ws_client:
            try:
                self.ws_client.disconnect()
                print(f"  ✓ WebSocket 已關閉")
            except Exception as e:
                print(f"  ✗ WebSocket 關閉失敗: {e}")
            self.ws_client = None

        # 停止 action reader
        if self.game_client:
            try:
                self.game_client.stop_action_reader()
                print(f"  ✓ Action Reader 已停止")
            except Exception as e:
                print(f"  ✗ Action Reader 停止失敗: {e}")
            self.game_client = None

        self.match_id = None

    def check_action_results(self):
        """檢查並打印新的 action 結果"""
        results_file = DATA_DIR / "action_results.txt"

        if not results_file.exists():
            return

        try:
            with open(results_file, 'r') as f:
                f.seek(self.last_result_position)
                new_lines = f.readlines()

                for line in new_lines:
                    line = line.strip()
                    if line and line.startswith(self.match_id):
                        try:
                            # 解析結果：match_id,player_id,ball_x,ball_y,p1_x,p1_y,p2_x,p2_y,score_p1,score_p2,terminated
                            parts = line.split(',')
                            if len(parts) >= 11:
                                player_id = parts[1]
                                ball_x, ball_y = float(parts[2]), float(parts[3])
                                score_p1, score_p2 = int(parts[8]), int(parts[9])
                                terminated = bool(int(parts[10]))

                                # 打印 action 結果
                                status = "⚠ Ball Down!" if terminated else "✓"
                                print(f"  [ACTION] {player_id} → Ball({ball_x:.0f},{ball_y:.0f}) Score {score_p1}:{score_p2} {status}")
                        except (ValueError, IndexError):
                            pass  # 跳過格式錯誤的行

                self.last_result_position = f.tell()
        except Exception as e:
            pass  # 靜默處理錯誤

    def update_state(self):
        """更新 match 的狀態"""
        if not self.ws_client or not self.match_id:
            return

        try:
            state_json = self.ws_client.get_state()

            if state_json:
                state_data = json.loads(state_json)

                # 添加額外資訊
                state_data["match_id"] = self.match_id
                state_data["frame"] = self.frame_count
                state_data["timestamp"] = time.time()
                state_data["mode"] = "websocket"

                # 寫入檔案
                state_file = DATA_DIR / f"pikachu_state_{self.match_id}.json"
                self.atomic_write_json(state_file, state_data)

                # 每秒打印一次状态（60 frames = 1 second）
                if self.frame_count % 60 == 0:
                    try:
                        ball = state_data.get('ball', {})
                        ball_pos = f"Ball({ball.get('x', 0):.0f},{ball.get('y', 0):.0f})"
                        score_p1 = state_data.get('score_p1', 0)
                        score_p2 = state_data.get('score_p2', 0)
                        score = f"Score {score_p1}:{score_p2}"
                        print(f"[{self.match_id}] {ball_pos} {score}")
                    except Exception:
                        pass  # 如果格式不對，跳過這次打印
            # 如果 state_json 是 None，不打印任何东西

        except Exception as e:
            # 只在错误时打印
            if self.frame_count % 300 == 0:  # 每 5 秒報告一次
                print(f"[WARNING] {self.match_id}: {e}")

    def run(self):
        """主循環"""
        # 获取配置信息
        from game_client import _default_game_service_url
        from lv_ws_client import _server_base_url

        print("=" * 60)
        print("LabVIEW Bridge - 統一狀態截取與 Action 處理")
        print("=" * 60)
        print(f"配置文件: {CONFIG_FILE}")
        print(f"數據目錄: {DATA_DIR}")
        print(f"Match Server: {_server_base_url}")
        print(f"Game Service: {_default_game_service_url}")
        print("-" * 60)
        print(f"狀態輸出: data/pikachu_state_{{match_id}}.json")
        print(f"Action 輸入: data/actions.txt")
        print(f"Action 輸出: data/action_results.txt")
        print("=" * 60)
        print()

        self.running = True

        try:
            # 等待配置並設置 match（失敗會重試）
            setup_success = False
            while not setup_success and self.running:
                # 重新讀取配置
                config_match_id = self.read_config()

                if not config_match_id:
                    print("等待配置... (請在 data/match_id.txt 中添加 match ID)")
                    time.sleep(2.0)
                    continue

                # 嘗試設置 match
                if self.setup_match(config_match_id):
                    setup_success = True
                else:
                    print("設置失敗，2 秒後重試...")
                    time.sleep(2.0)

            if not self.running:
                return

            print("\n[就緒] 開始運行...")
            print("-" * 60)

            while self.running:
                loop_start = time.time()

                # 更新狀態
                self.update_state()

                # 檢查 action 結果
                self.check_action_results()

                self.frame_count += 1

                # 每 10 秒報告統計
                if self.frame_count % 600 == 0:
                    elapsed = time.time() - self.start_time
                    fps = self.frame_count / elapsed if elapsed > 0 else 0
                    connected = self.ws_client.connected if self.ws_client else False
                    if connected:  # 只在有连接时显示
                        print(f"[STATS] FPS={fps:.1f}, Connected={'✓' if connected else '✗'}")

                # 維持 60 FPS
                elapsed = time.time() - loop_start
                sleep_time = max(0.0, POLL_INTERVAL - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n[INFO] 停止中...")

        finally:
            self.shutdown()

    def shutdown(self):
        """清理所有資源"""
        print("\n[INFO] 清理連線...")
        self.running = False

        self.cleanup_match()

        # 最終統計
        total_time = time.time() - self.start_time
        fps = self.frame_count / total_time if total_time > 0 else 0
        print(f"\n{'=' * 60}")
        print(f"總計: {self.frame_count} frames, {total_time:.2f}s, {fps:.1f} FPS")
        print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(
        description="LabVIEW Bridge - 統一的遊戲狀態截取和 Action 發送"
    )

    parser.add_argument(
        "--match-id",
        type=str,
        help="手動指定 match ID（不指定則從 data/match_ids.txt 讀取）"
    )

    args = parser.parse_args()

    # 檢查服務
    print("檢查 Game Service...", end=' ')
    health = health_check()
    if not health:
        print("✗")
        print("\nGame Service 未運行！請先啟動：")
        print("  uv run game_service/game_server.py\n")
        return 1
    print(f"✓ (v{health['version']})\n")

    # 如果指定了 match_id，寫入配置文件
    if args.match_id:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            f.write(f"{args.match_id}\n")
        print(f"已設置 match ID: {args.match_id}")
        print(f"配置文件: {CONFIG_FILE}\n")

    # 啟動橋接器
    bridge = LabVIEWBridge()
    bridge.run()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n錯誤: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
