#!/usr/bin/env python3
"""
測試擴展的遊戲狀態格式。

啟動服務後運行：
  cd Pikachu-Volleyball
  uv run python test_extended_state.py
"""

import sys
from pathlib import Path

# Add client to path
sys.path.insert(0, str(Path(__file__).parent / "client"))

import lv_ws_client as client
import time
import json


def test_extended_state():
    """測試新的擴展狀態格式。"""
    print("=" * 60)
    print("測試擴展遊戲狀態")
    print("=" * 60)

    # 1. 創建比賽
    print("\n1. 創建比賽...")
    match_info = client.create_match("pvai", "test", "Extended State Test")
    if "error" in match_info:
        print(f"❌ 創建比賽失敗: {match_info['error']}")
        return False

    match_id = match_info["match_id"]
    print(f"✓ Match ID: {match_id}")

    # 2. 註冊玩家
    print("\n2. 註冊玩家...")
    result = client.connect(match_id, "player1")
    if "error" in result:
        print(f"❌ 註冊失敗: {result['error']}")
        return False
    print(f"✓ 註冊成功，建議輪詢間隔: {result.get('polling_interval_ms', 'N/A')}ms")

    time.sleep(0.1)

    # 3. 輪詢並檢查狀態格式
    print("\n3. 檢查狀態格式...")
    state = client.poll_state(match_id, "player1")

    if not state:
        print("❌ 無法獲取狀態")
        return False

    print("\n✓ 成功獲取狀態，檢查必要欄位...")

    # 檢查必要欄位
    required_fields = {
        "type": str,
        "player1": dict,
        "player2": dict,
        "punch": dict,
        "ball_hyper": dict,
        "ball_trail": dict,
        "ball": dict,
        "score": dict,
    }

    all_ok = True
    for field, expected_type in required_fields.items():
        if field not in state:
            print(f"  ❌ 缺少欄位: {field}")
            all_ok = False
        elif not isinstance(state[field], expected_type):
            print(f"  ❌ 欄位 {field} 類型錯誤: 期望 {expected_type}, 實際 {type(state[field])}")
            all_ok = False
        else:
            print(f"  ✓ {field}: {expected_type.__name__}")

    # 檢查 player1 的詳細屬性
    print("\n  檢查 player1 屬性:")
    player1_fields = ["x", "y", "dive_direction", "state", "frame_num"]
    for field in player1_fields:
        if field in state["player1"]:
            value = state["player1"][field]
            print(f"    ✓ {field}: {value}")
        else:
            print(f"    ❌ 缺少: {field}")
            all_ok = False

    # 檢查 punch 屬性
    print("\n  檢查 punch 屬性:")
    punch_fields = ["visible", "x", "y"]
    for field in punch_fields:
        if field in state["punch"]:
            value = state["punch"][field]
            print(f"    ✓ {field}: {value}")
        else:
            print(f"    ❌ 缺少: {field}")
            all_ok = False

    # 檢查 ball 屬性
    print("\n  檢查 ball 屬性:")
    ball_fields = ["x", "y", "rotation"]
    for field in ball_fields:
        if field in state["ball"]:
            value = state["ball"][field]
            print(f"    ✓ {field}: {value}")
        else:
            print(f"    ❌ 缺少: {field}")
            all_ok = False

    # 4. 玩一小段並觀察狀態變化
    print("\n4. 玩 3 秒並觀察狀態變化...")
    start = time.time()
    frame_count = 0
    state_changes = []

    while time.time() - start < 3:
        # 發送輸入
        move = "jump" if frame_count % 30 == 0 else "left"
        client.send_input(match_id, move, "player1")

        # 輪詢狀態
        new_state = client.poll_state(match_id, "player1")
        if new_state:
            state_changes.append({
                "frame": frame_count,
                "player1_state": new_state["player1"]["state"],
                "ball_rotation": new_state["ball"]["rotation"],
                "punch_visible": new_state["punch"]["visible"],
            })

        frame_count += 1
        time.sleep(0.016)  # ~60 FPS

    print(f"\n  總共輪詢: {frame_count} 幀")
    print(f"  成功接收: {len(state_changes)} 個狀態")

    # 顯示一些有趣的狀態變化
    if state_changes:
        print("\n  狀態變化範例（前 5 個）:")
        for change in state_changes[:5]:
            print(f"    Frame {change['frame']:3d}: "
                  f"Player State={change['player1_state']}, "
                  f"Ball Rotation={change['ball_rotation']:.1f}, "
                  f"Punch={change['punch_visible']}")

    # 5. 清理
    print("\n5. 清理...")
    client.disconnect(match_id, "player1")
    client.stop_match(match_id)
    print("✓ 清理完成")

    # 最終結果
    print("\n" + "=" * 60)
    if all_ok and len(state_changes) > 0:
        print("✅ 所有測試通過！新狀態格式正常工作！")
        print("=" * 60)
        return True
    else:
        print("❌ 某些測試失敗")
        print("=" * 60)
        return False


if __name__ == "__main__":
    try:
        success = test_extended_state()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n測試被中斷")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
