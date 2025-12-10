#!/usr/bin/env python3
"""
File 模式範例 - 演示如何使用 file-based 通訊

這個範例展示：
1. 創建遊戲
2. 啟動 action reader (25 FPS)
3. 發送一系列動作
4. 讀取並顯示結果
5. 清理
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from game_client import GameClient, health_check

def main():
    print("=" * 60)
    print("File Mode Example - 25 FPS Action Reader")
    print("=" * 60)

    # 檢查服務
    print("\n[1] 檢查 Game Service...")
    health = health_check()
    if not health:
        print("✗ Game Service 未運行！請先啟動：")
        print("  uv run game_service/game_server.py")
        return
    print(f"✓ Game Service 運行中: {health['service']} v{health['version']}")

    # 創建客戶端
    match_id = f"demo_{int(time.time())}"
    print(f"\n[2] 創建客戶端 (match_id={match_id})...")
    client = GameClient(match_id=match_id, mode="file", player_id="player1")
    print("✓ 客戶端已創建 (File 模式)")

    # 創建遊戲
    print("\n[3] 創建遊戲...")
    if client.create_game(mode="pvai"):
        print("✓ 遊戲已創建（vs AI）")
    else:
        print("✗ 創建遊戲失敗")
        return

    # 清空舊結果
    print("\n[4] 清空舊結果...")
    client.clear_results()
    print("✓ 結果檔案已清空")

    # 啟動 action reader
    print("\n[5] 啟動 Action Reader (25 FPS)...")
    if client.start_action_reader():
        print("✓ Action Reader 已啟動")
    else:
        print("✗ 啟動失敗")
        return

    # 等待 action reader 啟動
    time.sleep(0.5)

    # 發送測試動作
    print("\n[6] 發送測試動作...")
    print("    每個動作之間間隔 0.04 秒（25 FPS）\n")

    test_actions = [
        ([1, 1, 0], "無動作"),
        ([2, 1, 0], "向右移動"),
        ([2, 1, 0], "向右移動"),
        ([2, 1, 0], "向右移動"),
        ([1, 2, 0], "跳躍"),
        ([0, 1, 0], "向左移動"),
        ([0, 1, 0], "向左移動"),
        ([1, 1, 0], "無動作"),
    ]

    results = []

    for i, (action, desc) in enumerate(test_actions, 1):
        # 發送動作
        print(f"  [{i}/{len(test_actions)}] {desc} {action}...", end=' ')
        client.send_action(action)

        # 讀取結果
        result = client.read_result(timeout=1.0)

        if result:
            print(f"✓ Ball=({result['ball']['x']:.1f}, {result['ball']['y']:.1f}), "
                  f"P1=({result['p1']['x']:.1f}, {result['p1']['y']:.1f}), "
                  f"Score={result['score_p1']}:{result['score_p2']}")
            results.append(result)
        else:
            print("✗ 無結果")

        # 等待下一個 frame（25 FPS = 0.04s）
        time.sleep(0.04)

    # 顯示統計
    print(f"\n[7] 統計")
    print(f"    發送動作: {len(test_actions)}")
    print(f"    收到結果: {len(results)}")

    if results:
        first = results[0]
        last = results[-1]
        print(f"\n    初始位置:")
        print(f"      P1: ({first['p1']['x']:.1f}, {first['p1']['y']:.1f})")
        print(f"      Ball: ({first['ball']['x']:.1f}, {first['ball']['y']:.1f})")
        print(f"\n    最終位置:")
        print(f"      P1: ({last['p1']['x']:.1f}, {last['p1']['y']:.1f})")
        print(f"      Ball: ({last['ball']['x']:.1f}, {last['ball']['y']:.1f})")
        print(f"\n    最終比分: {last['score_p1']} : {last['score_p2']}")

    # 停止 action reader
    print("\n[8] 停止 Action Reader...")
    client.stop_action_reader()
    print("✓ Action Reader 已停止")

    # 檢查最終狀態
    print("\n[9] 最終狀態")
    status = client.action_reader_status()
    if status:
        print(f"    Running: {status['running']}")
        print(f"    FPS: {status['fps']}")
        print(f"    Input file: {status['input_file_exists']}")
        print(f"    Output file: {status['output_file_exists']}")

    print("\n" + "=" * 60)
    print("✓ 測試完成！")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INFO] 用戶中斷")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
