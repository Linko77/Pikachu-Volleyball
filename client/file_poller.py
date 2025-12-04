#!/usr/bin/env python3
"""
WebSocket-based File Poller - 使用 WebSocket 推送模式取代 HTTP 輪詢

Config File (/data/match_ids.txt):
    abc123
    def456

Output:
    /data/pikachu_state_abc123.json
    /data/pikachu_state_def456.json

優點：
- 無 HTTP RTT 延遲（伺服器主動推送）
- 更低的 CPU 使用率（不需要發送 HTTP 請求）
- 更低的網路頻寬（60% 減少）
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent))
from lv_ws_client import WebSocketClient

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "data" / "match_ids.txt"
DATA_DIR = BASE_DIR / "data"
POLL_INTERVAL = 1.0 / 60.0


def atomic_write_json(file_path: Path, data: dict):
    """原子性寫入 JSON 檔案，確保 LabVIEW 讀取完整資料"""
    temp_file = file_path.with_suffix('.tmp')
    with open(temp_file, 'w', encoding="utf-8") as f:
        json.dump(data, f, separators=(',', ':'))
    temp_file.replace(file_path)


def read_config() -> list:
    """讀取配置檔案中的 match IDs"""
    if not CONFIG_FILE.exists():
        return []
    try:
        with open(CONFIG_FILE) as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception as e:
        print(f"[ERROR] 讀取配置失敗: {e}")
        return []


def main():
    print("=" * 60)
    print("WebSocket File Poller - 流式推送模式")
    print("=" * 60)
    print(f"Config File: {CONFIG_FILE}")
    print(f"Output Dir: {DATA_DIR}")
    print(f"Mode: WebSocket Push (無 HTTP RTT 延遲)")
    print("=" * 60)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # WebSocket 客戶端管理
    ws_clients: Dict[str, WebSocketClient] = {}

    frame_count = 0
    start_time = time.time()
    last_match_ids = set()

    try:
        while True:
            loop_start = time.time()
            match_ids = read_config()
            current_match_ids = set(match_ids)

            if not match_ids:
                if frame_count == 0:
                    logging.info("No match IDs in config")
                time.sleep(1.0)
                continue

            # 管理 WebSocket 連線：新增連線
            for match_id in current_match_ids - last_match_ids:
                print(f"[+] 新增 WebSocket 連線: {match_id}")
                client = WebSocketClient()
                # 使用 player2 role（注意：可能與真實玩家衝突）
                if client.connect(match_id, role="player2"):
                    ws_clients[match_id] = client
                    print(f"[✓] WebSocket 連線成功: {match_id}")
                else:
                    print(f"[✗] WebSocket 連線失敗: {match_id}")

            # 管理 WebSocket 連線：移除連線
            for match_id in last_match_ids - current_match_ids:
                print(f"[-] 移除 WebSocket 連線: {match_id}")
                if match_id in ws_clients:
                    ws_clients[match_id].disconnect()
                    del ws_clients[match_id]

            last_match_ids = current_match_ids

            # 從 WebSocket 讀取最新狀態並寫入檔案
            for match_id in match_ids:
                if match_id not in ws_clients:
                    continue

                try:
                    client = ws_clients[match_id]
                    state_json = client.get_state()

                    if state_json:
                        state_data = json.loads(state_json)

                        # 添加額外資訊
                        state_data["match_id"] = match_id
                        state_data["poller_frame"] = frame_count
                        state_data["poller_time"] = time.time()
                        state_data["connection_mode"] = "websocket"

                        # 寫入檔案
                        state_file = DATA_DIR / f"pikachu_state_{match_id}.json"
                        atomic_write_json(state_file, state_data)

                except Exception as e:
                    # 靜默處理錯誤，避免中斷
                    if frame_count % 300 == 0:  # 每 5 秒報告一次錯誤
                        print(f"[WARNING] {match_id}: {e}")

            frame_count += 1

            # 每秒報告統計
            if frame_count % 60 == 0:
                elapsed = time.time() - start_time
                fps = frame_count / elapsed if elapsed > 0 else 0
                connected = len([c for c in ws_clients.values() if c.connected])
                print(f"[STATS] Frames: {frame_count}, FPS: {fps:.1f}, "
                      f"Matches: {len(match_ids)}, Connected: {connected}/{len(ws_clients)}")

            # 維持 60 FPS
            elapsed = time.time() - loop_start
            sleep_time = max(0.0, POLL_INTERVAL - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[INFO] 停止中...")

    finally:
        # 清理所有 WebSocket 連線
        print("\n[INFO] 關閉所有 WebSocket 連線...")
        for match_id, client in ws_clients.items():
            try:
                client.disconnect()
                print(f"[✓] 已關閉: {match_id}")
            except:
                pass

        # 最終統計
        total_time = time.time() - start_time
        fps = frame_count / total_time if total_time > 0 else 0
        print(f"\n{'=' * 60}")
        print(f"總計: {frame_count} frames, {total_time:.2f}s, {fps:.1f} FPS")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
