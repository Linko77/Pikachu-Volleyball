#!/usr/bin/env python3
"""
Game Client Runner - 正式運行遊戲客戶端

使用方式：
    python run_game.py --mode file --match-id abc123
    python run_game.py --mode http --match-id xyz789
    python run_game.py --demo  # 運行演示模式
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from game_client import GameClient, health_check


def run_file_mode(match_id: str, player_id: str = "player1", demo: bool = False):
    """運行 File 模式"""
    from game_client import _default_game_service_url

    print("=" * 60)
    print(f"File Mode - Match ID: {match_id}")
    print("=" * 60)
    print(f"Game Service: {_default_game_service_url}")
    print("-" * 60)

    # 檢查服務
    print("檢查 Game Service...", end=' ')
    health = health_check()
    if not health:
        print("✗")
        print("Game Service 未運行！請先啟動：")
        print("  uv run game_service/game_server.py")
        return False
    print(f"✓ (v{health['version']})")

    # 創建客戶端
    client = GameClient(match_id=match_id, mode="file", player_id=player_id)

    # 創建遊戲
    print(f"創建遊戲 {match_id}...", end=' ')
    if not client.create_game(mode="pvai"):
        print("✗ 失敗")
        return False
    print("✓")

    # 清空舊結果
    client.clear_results()

    # 啟動 action reader
    print("啟動 Action Reader (25 FPS)...", end=' ')
    if not client.start_action_reader():
        print("✗ 失敗")
        return False
    print("✓")

    time.sleep(0.5)  # 等待啟動

    if demo:
        # 演示模式：自動發送測試動作
        print("\n[演示模式] 發送測試動作...")
        print("-" * 60)

        actions = [
            ([1, 1, 0], "站立"),
            ([2, 1, 0], "右移"),
            ([2, 1, 0], "右移"),
            ([1, 2, 0], "跳躍"),
            ([0, 1, 0], "左移"),
            ([0, 1, 0], "左移"),
            ([1, 1, 0], "站立"),
        ]

        for i, (action, desc) in enumerate(actions, 1):
            print(f"[{i}/{len(actions)}] {desc} {action}...", end=' ')
            client.send_action(action)

            result = client.read_result(timeout=1.0)
            if result:
                print(f"Ball=({result['ball']['x']:.1f},{result['ball']['y']:.1f}) "
                      f"Score={result['score_p1']}:{result['score_p2']}")
            else:
                print("無結果")

            time.sleep(0.04)

        print("-" * 60)
        client.stop_action_reader()
        print("✓ 演示完成")

    else:
        # 正式模式：等待外部寫入動作
        print("\n[就緒] 等待動作輸入...")
        print(f"  輸入檔案: data/actions.txt")
        print(f"  輸出檔案: data/action_results.txt")
        print(f"  格式: {match_id}, {player_id}, x, y, power")
        print("\n按 Ctrl+C 停止")
        print("-" * 60)

        try:
            frame_count = 0
            while True:
                # 這裡可以添加監控邏輯
                time.sleep(1.0)
                frame_count += 1

                # 每10秒顯示狀態
                if frame_count % 10 == 0:
                    status = client.action_reader_status()
                    if status:
                        print(f"[{frame_count}s] Action Reader: {'運行中' if status['running'] else '已停止'}")

        except KeyboardInterrupt:
            print("\n\n停止中...")
            client.stop_action_reader()
            print("✓ Action Reader 已停止")

    return True


def run_http_mode(match_id: str, player_id: str = "player1"):
    """運行 HTTP 模式"""
    print("=" * 60)
    print(f"HTTP Mode - Match ID: {match_id}")
    print("=" * 60)

    # 檢查服務
    print("檢查 Game Service...", end=' ')
    health = health_check()
    if not health:
        print("✗")
        print("Game Service 未運行！")
        return False
    print("✓")

    # 創建客戶端
    client = GameClient(match_id=match_id, mode="http", player_id=player_id)

    # 創建遊戲
    print(f"創建遊戲 {match_id}...", end=' ')
    if not client.create_game(mode="pvai"):
        print("✗")
        return False
    print("✓")

    print("\n[就緒] HTTP 模式")
    print("使用 game_client.py 發送動作")
    print("-" * 60)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Game Client Runner - 正式運行遊戲客戶端"
    )

    parser.add_argument(
        "--mode",
        choices=["file", "http"],
        default="file",
        help="通訊模式 (預設: file)"
    )

    parser.add_argument(
        "--match-id",
        type=str,
        help="遊戲/比賽 ID (預設: 自動生成)"
    )

    parser.add_argument(
        "--player-id",
        type=str,
        default="player1",
        help="玩家 ID (預設: player1)"
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="運行演示模式（自動發送測試動作）"
    )

    args = parser.parse_args()

    # 生成 match_id（如果未指定）
    if not args.match_id:
        args.match_id = f"game_{int(time.time())}"

    # 運行對應模式
    if args.mode == "file":
        success = run_file_mode(args.match_id, args.player_id, args.demo)
    else:
        success = run_http_mode(args.match_id, args.player_id)

    return 0 if success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n用戶中斷")
        sys.exit(0)
    except Exception as e:
        print(f"\n錯誤: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
