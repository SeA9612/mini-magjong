"""
리치마작 2인 대전 (플레이어 vs AI)
메인 실행 진입점

사용법:
  - python mazak.py        : 그래픽 웹 GUI 모드 실행 (브라우저 자동 오픈)
  - python mazak.py --cli  : 터미널 콘솔 텍스트 모드 실행
"""

from __future__ import annotations
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_cli():
    """웹과 동일한 세션을 사용하여 CLI에서도 같은 턴·반응 검증을 적용한다."""
    from gui_server import WebMahjongSession

    session = WebMahjongSession()
    print("🀄 리치마작 2인 대전 (CLI)")
    print("타패: 번호 / 쯔모: t / 리치: r 번호 / 깡: k 번호 / 종료: q")
    try:
        while not session.game.is_game_over:
            game = session.game
            if game.current_turn == 1 and not session.pending_reaction:
                session.handle_action({"action": "ai_step"})
                print(session.last_message)
                continue

            if session.pending_reaction:
                pending = session.pending_reaction
                print(f"상대 버림패: {pending['target_tile']}")
                for i, action in enumerate(pending["actions"], 1):
                    partner = " ".join(str(t) for t in action.get("partner", ()))
                    print(f"{i}: {action['type']} {partner}")
                choice = input("반응 번호 / 0: 패스 / q: 종료: ").strip().lower()
                if choice == "q":
                    return
                if not choice.isdigit() or not 0 <= int(choice) <= len(pending["actions"]):
                    print("유효한 번호를 입력하세요.")
                    continue
                index = int(choice) - 1
                selected = {"type": "pass"} if index < 0 else {
                    "type": pending["actions"][index]["type"], "index": index}
                session.handle_action({"action": "reaction", "choice": selected})
                print(session.last_message)
                continue

            human = game.players[0]
            print(f"손패: {human.hand} | 남은 산: {game.wall.remaining()}")
            for i, tile in enumerate(human.hand.concealed_tiles):
                print(f"{i}:{tile}", end=" ")
            print()
            if game.pending_meld_discard == 0:
                print("치/퐁 직후입니다. 패를 뽑지 않고 한 장을 버리세요.")
            actions = game.get_turn_actions(0, session.current_drawn_tile)
            if actions["can_tsumo"]:
                print("t: 쯔모 화료 가능")
            for i, (kind, tile) in enumerate(actions["kans"]):
                print(f"k {i}: {kind} {tile}")
            parts = input("행동 입력: ").strip().lower().split()
            if not parts:
                continue
            if parts == ["q"]:
                return
            if parts == ["t"]:
                request = {"action": "tsumo"}
            elif len(parts) == 2 and parts[0] == "k" and parts[1].isdigit():
                request = {"action": "kan", "kan_index": int(parts[1])}
            elif len(parts) == 2 and parts[0] == "r" and parts[1].isdigit():
                request = {"action": "discard", "index": int(parts[1]), "riichi": True}
            elif len(parts) == 1 and parts[0].isdigit():
                request = {"action": "discard", "index": int(parts[0])}
            else:
                print("유효한 행동을 입력하세요.")
                continue
            session.handle_action(request)
            print(session.last_message)
    except (EOFError, KeyboardInterrupt):
        print("\n대국을 종료합니다.")
        return
    state = session.build_state()
    print("대국 종료:", session.game.winner.name if session.game.winner else "유국")
    if state["winning_hand"]:
        print("화료패형:", " ".join(t["name"] for t in state["winning_hand"]))
        print("성립 역:", ", ".join(y["name"] for y in state["winning_yaku"]))


def run_gui():
    """모던 웹 GUI 모드 실행"""
    from gui_server import start_server
    return start_server()


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if "--cli" in args:
            run_cli()
        else:
            run_gui()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        import traceback
        from pathlib import Path
        details = traceback.format_exc()
        log_path = Path(__file__).resolve().with_name("mazak-error.log")
        print("게임을 시작하지 못했습니다. 오류 내용을 확인해 주세요.")
        print(details)
        try:
            log_path.write_text(details, encoding="utf-8")
            print(f"오류 기록: {log_path}")
        except OSError:
            pass
        # 더블클릭 실행에서 오류 메시지를 읽기도 전에 창이 사라지지 않게 한다.
        if sys.stdin is not None and sys.stdin.isatty():
            try:
                input("Enter 키를 누르면 종료합니다...")
            except (EOFError, KeyboardInterrupt):
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
