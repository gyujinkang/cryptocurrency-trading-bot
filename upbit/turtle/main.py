"""
업비트 터틀 트레이딩 봇
대상 코인: BTC, ETH
전략:
    System 1 - 20일 돌파 진입 / 10일 하향 청산
    System 2 - 55일 돌파 진입 / 20일 하향 청산
    피라미딩  - 0.5N 상승마다 유닛 추가 (최대 4유닛)
    손절      - 2N 하락 시 즉시 청산
    포지션 사이징 - 계좌의 1% 위험 / N (ATR)

실행 방법:
    # 실제 거래 (upbit.txt에 API 키 필요)
    python main.py

    # 모의투자 7일 (API 키 불필요, 기본 1000만원)
    python main.py --paper

    # 모의투자 - 초기 투자금 지정 (예: 500만원)
    python main.py --paper 5000000

    # 디버그 모드 (API 키 필요, 실제 주문 없이 신호만 확인)
    python main.py --debug
"""

import time
import datetime
import logging
import argparse
import sys

import pyupbit

import manager
import strategy
import trade
from position import load_state, save_state
from paper import PaperPortfolio

# ── 설정 ─────────────────────────────────────────────────────────────────────

TICKERS = ['KRW-BTC', 'KRW-ETH']   # 거래 대상 코인

CHECK_INTERVAL = 10                  # 가격 체크 주기 (초)
SIGNAL_REFRESH = 1800                # 신호 갱신 주기 (초, 기본 30분)
STATUS_PRINT = 60                    # 상태 출력 주기 (초)
PAPER_DURATION_DAYS = 7             # 모의투자 기간

# ── 메인 ─────────────────────────────────────────────────────────────────────

def main(paper_balance=None, debug=False):
    manager.setup_logging()
    logger = logging.getLogger(__name__)

    paper_mode = paper_balance is not None

    # ── 모드 선택 ──
    if paper_mode:
        upbit = PaperPortfolio(initial_krw=paper_balance)
        paper_end = datetime.datetime.now() + datetime.timedelta(days=PAPER_DURATION_DAYS)
        state_file = "paper_turtle_state.json"
        logger.info("=" * 60)
        logger.info("  모의투자 모드 (API 키 불필요)")
        logger.info(f"  초기 투자금: {paper_balance:,.0f} KRW")
        logger.info(f"  종료 예정:   {paper_end.strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"  대상 코인:   {TICKERS}")
        logger.info("=" * 60)
    else:
        upbit = manager.create_instance()
        state_file = "turtle_state.json"
        if debug:
            logger.info("=" * 60)
            logger.info("  DEBUG 모드: 신호만 확인, 실제 주문 없음 (API 키 필요)")
            logger.info("=" * 60)
        else:
            logger.info("=" * 60)
            logger.info("  터틀 트레이딩 봇 시작 (실거래)")
            logger.info(f"  대상 코인: {TICKERS}")
            logger.info("=" * 60)

    # ── 포지션 상태 로드 ──
    positions = load_state(TICKERS, path=state_file)

    # ── 초기 신호 계산 ──
    signals_map = {}
    for ticker in TICKERS:
        df = strategy.get_ohlcv(ticker)
        sig = strategy.get_signals(df)
        if sig:
            signals_map[ticker] = sig
            logger.info(f"[{ticker}] 신호 로드  N={sig['n']:,.0f}  S2진입={sig['s2_entry']:,.0f}")
        else:
            logger.warning(f"[{ticker}] 신호 계산 실패 (데이터 부족)")

    last_signal_time = datetime.datetime.now()
    last_status_time = datetime.datetime.now()

    logger.info("매매 루프 시작")

    while True:
        try:
            now = datetime.datetime.now()

            # ── 모의투자 7일 종료 체크 ──
            if paper_mode and now >= paper_end:
                logger.info("=" * 60)
                logger.info(f"  모의투자 {PAPER_DURATION_DAYS}일 완료!")
                logger.info("=" * 60)
                upbit.print_summary(TICKERS)
                save_state(positions, path=state_file)
                sys.exit(0)

            # ── 신호 갱신 (30분마다) ──
            elapsed = (now - last_signal_time).total_seconds()
            if elapsed >= SIGNAL_REFRESH:
                logger.info("신호 갱신 중...")
                for ticker in TICKERS:
                    try:
                        df = strategy.get_ohlcv(ticker)
                        sig = strategy.get_signals(df)
                        if sig:
                            signals_map[ticker] = sig
                    except Exception as e:
                        logger.warning(f"[{ticker}] 신호 갱신 실패: {e}")
                last_signal_time = now

            # ── 총 평가금액 계산 ──
            if paper_mode:
                total_balance = upbit.get_total_value(TICKERS)
            else:
                total_balance = trade.get_total_balance(upbit, TICKERS)

            # ── 각 코인별 매매 체크 ──
            for ticker in TICKERS:
                if ticker not in signals_map:
                    continue

                sig = signals_map[ticker]
                pos = positions[ticker]

                # 청산 먼저 체크
                trade.try_exit(upbit, ticker, pos, sig, debug=debug)

                # 진입 체크
                trade.try_entry(upbit, ticker, pos, sig, total_balance, debug=debug)

            # ── 포지션 상태 저장 ──
            save_state(positions, path=state_file)

            # ── 상태 출력 (60초마다) ──
            if (now - last_status_time).total_seconds() >= STATUS_PRINT:
                if paper_mode:
                    remaining = paper_end - now
                    days_left = remaining.days
                    hours_left = remaining.seconds // 3600
                    logger.info(f"  [모의투자] 남은 기간: {days_left}일 {hours_left}시간")
                trade.print_status(positions, signals_map, total_balance)
                last_status_time = now

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("\n봇을 종료합니다...")
            if paper_mode:
                upbit.print_summary(TICKERS)
            save_state(positions, path=state_file)
            sys.exit(0)
        except Exception as e:
            logger.error(f"메인 루프 오류: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="업비트 터틀 트레이딩 봇",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        '--paper',
        type=float,
        nargs='?',
        const=10_000_000,
        default=None,
        metavar='BALANCE',
        help=(
            "모의투자 모드 (API 키 불필요, 7일 자동 종료)\n"
            "초기 투자금 지정 가능 (기본: 10,000,000 KRW)\n"
            "예) --paper           → 1,000만원으로 시작\n"
            "    --paper 5000000   → 500만원으로 시작"
        ),
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='디버그 모드: API 키 필요, 신호만 확인하고 실제 주문은 실행하지 않음',
    )
    args = parser.parse_args()

    if args.paper is not None and args.paper < 5_000:
        parser.error("초기 투자금은 최소 5,000 KRW 이상이어야 합니다.")

    main(paper_balance=args.paper, debug=args.debug)
