#!/usr/bin/env python3
"""
Config File (/data/match_ids.txt):
    abc123
    def456

Output:
    /data/pikachu_state_abc123.json
    /data/pikachu_state_def456.json
"""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lv_ws_client import poll_state

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "data" / "match_ids.txt"
DATA_DIR = BASE_DIR / "data"
POLL_INTERVAL = 1.0 / 60.0


def atomic_write_json(file_path: Path, data: dict):
    temp_file = file_path.with_suffix('.tmp')
    with open(temp_file, 'w', encoding="utf-8") as f:
        json.dump(data, f, separators=(',', ':'))
    temp_file.replace(file_path)


def read_config() -> list:
    if not CONFIG_FILE.exists():
        return []
    try:
        with open(CONFIG_FILE) as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception as e:
        print(f"[ERROR] 讀取配置失敗: {e}")
        return []


def main():
    print(f"Config File: {CONFIG_FILE}")
    print(f"Output Dir: {DATA_DIR}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    frame_count = 0
    start_time = time.time()

    try:
        while True:
            loop_start = time.time()
            match_ids = read_config()

            if not match_ids:
                if frame_count == 0:
                    logging.info("No match")
                time.sleep(1.0)
                continue

            for match_id in match_ids:
                try:
                    state_json = poll_state(match_id, role=None)

                    if state_json and not state_json.startswith("Error"):
                        state_data = json.loads(state_json)
                        state_data["match_id"] = match_id
                        state_data["poller_frame"] = frame_count
                        state_data["poller_time"] = time.time()

                        state_file = DATA_DIR / f"pikachu_state_{match_id}.json"
                        atomic_write_json(state_file, state_data)
                except:
                    pass

            frame_count += 1

            # 每秒報告
            if frame_count % 60 == 0:
                elapsed = time.time() - start_time
                fps = frame_count / elapsed if elapsed > 0 else 0
                print(f"[STATS] Frames: {frame_count}, FPS: {fps:.1f}, Matches: {len(match_ids)}")

            # 等待
            elapsed = time.time() - loop_start
            sleep_time = max(0.0, POLL_INTERVAL - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[INFO] 停止中...")

    finally:
        total_time = time.time() - start_time
        fps = frame_count / total_time if total_time > 0 else 0
        print(f"\n{'=' * 60}")
        print(f"總計: {frame_count} frames, {total_time:.2f}s, {fps:.1f} FPS")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
