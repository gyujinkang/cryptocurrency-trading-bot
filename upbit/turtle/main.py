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
    1. upbit.txt에 Access Key / Secret Key 입력
    2. python main.py
    3. 디버그 모드 (실제 주문 없이 시뮬레이션):
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

# ── 설정 ─────────────────────────────────────────────────────────────────────

TICKERS = ['KRW-BTC', 'KRW-ETH']   # 거래 대상 코인

CHECK_INTERVAL = 10                  # 가격 체크 주기 (초)
SIGNAL_REFRESH = 1800                # 신호 갱신 주기 (초, 기본 30분)
STATUS_PRINT = 60                    # 상태 출력 주기 (초)

# ── 메인 ─────────────────────────────────────────────────────────────────────

def main(debug=False):
    manager.setup_logging()
    logger = logging.getLogger(__name__)

    if debug:
        logger.info("=" * 60)
        logger.info("  DEBUG 모드: 실제 주문이 실행되지 않습니다")
        logger.info("=" * 60)
    else:
        logger.info("=" * 60)
        logger.info("  터틀 트레이딩 봇 시작")
        logger.info(f"  대상 코인: {TICKERS}")
        logger.info("=" * 60)

    # API 연결
    upbit = manager.create_instance()

    # 포지션 상태 로드 (재시작 시 이전 상태 복원)
    positions = load_state(TICKERS)

    # 초기 신호 계산
    signals_map = {}
    for ticker in TICKERS:
        df = strategy.get_ohlcv(ticker)
        sig = strategy.get_signals(df)
        if sig:
            signals_map[ticker] = sig
            logger.info(f"[{ticker}] 초기 신호 로드 완료  N={sig['n']:,.0f}")
        else:
            logger.warning(f"[{ticker}] 신호 계산 실패 (데이터 부족)")

    last_signal_time = datetime.datetime.now()
    last_status_time = datetime.datetime.now()

    logger.info("매매 루프 시작")

    while True:
        try:
            now = datetime.datetime.now()

            # ── 신호 갱신 (30분마다) ──
            if (now - last_signal_time).seconds >= SIGNAL_REFRESH:
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
            save_state(positions)

            # ── 상태 출력 (60초마다) ──
            if (now - last_status_time).seconds >= STATUS_PRINT:
                trade.print_status(positions, signals_map, total_balance)
                last_status_time = now

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("\n봇을 종료합니다...")
            save_state(positions)
            sys.exit(0)
        except Exception as e:
            logger.error(f"메인 루프 오류: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="업비트 터틀 트레이딩 봇")
    parser.add_argument(
        '--debug',
        action='store_true',
        help='디버그 모드: 실제 주문 없이 신호만 확인'
    )
    args = parser.parse_args()
    main(debug=args.debug)
