"""
터틀 트레이딩 매수/매도 실행 모듈

진입 로직:
    - S1 (System 1): 현재가 > 20일 최고가 && 직전 S1 거래가 승리였을 때
    - S2 (System 2): 현재가 > 55일 최고가 (항상 진입)
    - 피라미딩: 보유 중 현재가 > 마지막 진입가 + 0.5N (최대 4유닛)

청산 로직:
    - 손절: 현재가 < 포지션 손절가 (2N 하락)
    - S1 청산: S1으로 진입 시 현재가 < 10일 최저가
    - S2 청산: S2로 진입 시 현재가 < 20일 최저가
"""

import time
import logging
import pyupbit
from strategy import get_unit_size_krw
from position import save_state

logger = logging.getLogger(__name__)

MIN_ORDER_KRW = 5_500       # 업비트 최소 주문 금액 (5,000 KRW + 여유)
SLEEP_AFTER_ORDER = 0.3     # 주문 후 대기 (API rate limit)


# ── 잔고 조회 ─────────────────────────────────────────────────────────────────

def get_krw_balance(upbit):
    try:
        return upbit.get_balance("KRW") or 0.0
    except Exception as e:
        logger.warning(f"KRW 잔고 조회 실패: {e}")
        return 0.0


def get_coin_balance(upbit, ticker):
    """KRW-BTC -> BTC 잔고"""
    try:
        coin = ticker.split('-')[1]
        return upbit.get_balance(coin) or 0.0
    except Exception as e:
        logger.warning(f"{ticker} 잔고 조회 실패: {e}")
        return 0.0


def get_total_balance(upbit, tickers):
    """총 평가금액 (KRW + 모든 코인 평가금액)"""
    try:
        total = get_krw_balance(upbit)
        prices = pyupbit.get_current_price(tickers)
        for ticker in tickers:
            coins = get_coin_balance(upbit, ticker)
            if coins > 0 and prices and ticker in prices:
                total += coins * prices[ticker]
        return total
    except Exception as e:
        logger.warning(f"총 잔고 조회 실패: {e}")
        return 0.0


# ── 진입 ─────────────────────────────────────────────────────────────────────

def try_entry(upbit, ticker, position, signals, total_balance, debug=False):
    """
    진입 시도 (최초 진입 + 피라미딩)
    """
    cur_price = pyupbit.get_current_price(ticker)
    if cur_price is None:
        return

    n = signals['n']
    if n <= 0:
        return

    # ── 첫 진입 ──
    if not position.is_holding:
        system = _check_entry_signal(position, signals, cur_price)
        if system is None:
            return

        krw_balance = get_krw_balance(upbit)
        unit_krw = get_unit_size_krw(total_balance, n, cur_price)
        unit_krw = min(unit_krw, krw_balance * 0.995)  # 잔고 초과 방지

        if unit_krw < MIN_ORDER_KRW:
            logger.info(f"[{ticker}] 진입 금액 부족 ({unit_krw:,.0f} KRW)")
            return

        _execute_buy(upbit, ticker, position, cur_price, unit_krw, n, system, debug)

    # ── 피라미딩 ──
    elif position.can_add_unit():
        next_price = position.get_next_pyramid_price(n)
        if cur_price <= next_price:
            return

        krw_balance = get_krw_balance(upbit)
        unit_krw = get_unit_size_krw(total_balance, n, cur_price)
        unit_krw = min(unit_krw, krw_balance * 0.995)

        if unit_krw < MIN_ORDER_KRW:
            return

        _execute_buy(upbit, ticker, position, cur_price, unit_krw, n, 'pyramid', debug)


def _check_entry_signal(position, signals, cur_price):
    """
    진입 시스템 결정
    - S2가 우선 (더 강한 신호)
    - S1은 직전 거래가 손실이면 건너뜀
    Returns: 's1' | 's2' | None
    """
    if cur_price > signals['s2_entry']:
        return 's2'
    if cur_price > signals['s1_entry'] and not position.last_s1_was_loser:
        return 's1'
    return None


def _execute_buy(upbit, ticker, position, cur_price, unit_krw, n, system, debug):
    """시장가 매수 실행 및 포지션 업데이트"""
    if debug:
        estimated_coins = unit_krw / cur_price
        logger.info(
            f"[DEBUG][{ticker}] 매수 ({system}): {cur_price:,.0f} KRW "
            f"투자금={unit_krw:,.0f} 수량≈{estimated_coins:.6f}"
        )
        position.add_unit(cur_price, estimated_coins, n, system)
        return

    try:
        result = upbit.buy_market_order(ticker, unit_krw)
        time.sleep(SLEEP_AFTER_ORDER)

        if result:
            # 실제 체결된 수량을 잔고에서 확인
            actual_coins = get_coin_balance(upbit, ticker) - sum(u.coins for u in position.units)
            coins = actual_coins if actual_coins > 0 else unit_krw / cur_price
            position.add_unit(cur_price, coins, n, system)
            logger.info(
                f"[{ticker}] 매수 완료 ({system}): {cur_price:,.0f} KRW "
                f"투자금={unit_krw:,.0f} 수량={coins:.6f}"
            )
        else:
            logger.warning(f"[{ticker}] 매수 실패 (result=None)")
    except Exception as e:
        logger.error(f"[{ticker}] 매수 오류: {e}")


# ── 청산 ─────────────────────────────────────────────────────────────────────

def try_exit(upbit, ticker, position, signals, debug=False):
    """
    청산 시도 (손절 또는 채널 하향 돌파)
    """
    if not position.is_holding:
        return

    cur_price = pyupbit.get_current_price(ticker)
    if cur_price is None:
        return

    reason = _check_exit_signal(position, signals, cur_price)
    if reason is None:
        return

    # 실제 보유 수량 확인
    actual_coins = get_coin_balance(upbit, ticker)
    coins_to_sell = min(position.total_coins, actual_coins)

    if coins_to_sell <= 0:
        position.clear()
        return

    if debug:
        was_loser = cur_price < position.avg_entry_price
        logger.info(
            f"[DEBUG][{ticker}] 매도 ({reason}): {cur_price:,.0f} KRW "
            f"수량={coins_to_sell:.6f} 손익={'손실' if was_loser else '이익'}"
        )
        position.clear(was_loser=was_loser)
        return

    try:
        result = upbit.sell_market_order(ticker, coins_to_sell)
        time.sleep(SLEEP_AFTER_ORDER)

        was_loser = cur_price < position.avg_entry_price
        if result:
            logger.info(
                f"[{ticker}] 매도 완료 ({reason}): {cur_price:,.0f} KRW "
                f"수량={coins_to_sell:.6f} 손익={'손실' if was_loser else '이익'}"
            )
        else:
            logger.warning(f"[{ticker}] 매도 실패 (result=None)")

        position.clear(was_loser=was_loser)
    except Exception as e:
        logger.error(f"[{ticker}] 매도 오류: {e}")


def _check_exit_signal(position, signals, cur_price):
    """
    청산 조건 확인
    Returns: 'stop_loss' | 's1_exit' | 's2_exit' | None
    """
    # 손절
    if cur_price < position.stop_loss:
        return 'stop_loss'

    # 진입 시스템에 따른 청산 채널
    systems = {u.system for u in position.units}
    if 's1' in systems and cur_price < signals['s1_exit']:
        return 's1_exit'
    if ('s2' in systems or 'pyramid' in systems) and cur_price < signals['s2_exit']:
        return 's2_exit'

    return None


# ── 상태 출력 ─────────────────────────────────────────────────────────────────

def print_status(positions, signals_map, total_balance):
    """현재 포지션 상태 콘솔 출력"""
    print("=" * 70)
    print(f"  총 평가금액: {total_balance:>15,.0f} KRW")
    print("-" * 70)

    for ticker, pos in positions.items():
        sig = signals_map.get(ticker)
        cur_price = pyupbit.get_current_price(ticker)

        if cur_price is None or sig is None:
            continue

        n = sig['n']
        status = "보유" if pos.is_holding else "미보유"
        pnl = ""
        if pos.is_holding:
            gain_pct = (cur_price - pos.avg_entry_price) / pos.avg_entry_price * 100
            pnl = f"  수익률: {gain_pct:+.2f}%"

        print(f"  [{ticker}]  현재가: {cur_price:>12,.0f}  N: {n:>10,.0f}  상태: {status}{pnl}")
        print(f"    S1 진입: {sig['s1_entry']:>12,.0f}  S1 청산: {sig['s1_exit']:>12,.0f}")
        print(f"    S2 진입: {sig['s2_entry']:>12,.0f}  S2 청산: {sig['s2_exit']:>12,.0f}")

        if pos.is_holding:
            print(f"    유닛: {pos.num_units}/{4}  "
                  f"평균진입가: {pos.avg_entry_price:,.0f}  "
                  f"손절가: {pos.stop_loss:,.0f}  "
                  f"수량: {pos.total_coins:.6f}")
    print("=" * 70)
