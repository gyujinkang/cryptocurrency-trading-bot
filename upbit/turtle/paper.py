"""
모의투자 (Paper Trading) 엔진

- API 키 없이 실행 가능
- 실제 시장 가격을 사용하여 가상 매수/매도 시뮬레이션
- 업비트 수수료 0.05% 반영
- 최소 주문 금액 5,000 KRW 적용
- 거래 내역 및 손익 추적
- 7일 종료 시 결과 요약 출력
"""

import datetime
import logging
import pyupbit

logger = logging.getLogger(__name__)

MIN_ORDER_KRW = 5_000    # 업비트 최소 주문 금액
FEE_RATE = 0.0005        # 업비트 수수료 0.05%


class PaperPortfolio:
    """
    가상 포트폴리오 - pyupbit.Upbit과 동일한 인터페이스 제공
    trade.py의 get_balance / buy_market_order / sell_market_order 호환
    """

    def __init__(self, initial_krw=10_000_000):
        self.initial_krw = initial_krw
        self.balances = {'KRW': float(initial_krw)}
        self.trades = []        # 전체 거래 내역

    # ── pyupbit.Upbit 호환 인터페이스 ───────────────────────────────────────

    def get_balance(self, currency):
        """잔고 조회 (KRW 또는 코인 심볼)"""
        return self.balances.get(currency, 0.0)

    def buy_market_order(self, ticker, krw_amount):
        """
        시장가 매수 시뮬레이션
        - 수수료 포함 실제 차감 금액: krw_amount * (1 + fee_rate)
        - 취득 코인 수: krw_amount / current_price  (수수료는 KRW에서 차감)
        """
        if krw_amount < MIN_ORDER_KRW:
            logger.warning(f"[PAPER] {ticker} 매수 실패: 금액 부족 ({krw_amount:,.0f} < {MIN_ORDER_KRW:,} KRW)")
            return None

        cur_price = pyupbit.get_current_price(ticker)
        if cur_price is None:
            return None

        fee = krw_amount * FEE_RATE
        total_deduct = krw_amount + fee

        if total_deduct > self.balances.get('KRW', 0):
            logger.warning(f"[PAPER] {ticker} 매수 실패: KRW 잔고 부족")
            return None

        coin = ticker.split('-')[1]
        coins_bought = krw_amount / cur_price

        self.balances['KRW'] = self.balances.get('KRW', 0) - total_deduct
        self.balances[coin] = self.balances.get(coin, 0.0) + coins_bought

        record = {
            'type': 'BUY',
            'ticker': ticker,
            'price': cur_price,
            'krw': krw_amount,
            'coins': coins_bought,
            'fee': fee,
            'time': datetime.datetime.now(),
            'krw_balance': self.balances['KRW'],
        }
        self.trades.append(record)
        logger.info(
            f"[PAPER] 매수: {ticker}  가격={cur_price:,.0f}  "
            f"투자금={krw_amount:,.0f}  수량={coins_bought:.6f}  수수료={fee:,.0f}  "
            f"KRW잔고={self.balances['KRW']:,.0f}"
        )
        return record

    def sell_market_order(self, ticker, coin_amount):
        """
        시장가 매도 시뮬레이션
        - 수령 KRW: coin_amount * current_price * (1 - fee_rate)
        """
        coin = ticker.split('-')[1]
        held = self.balances.get(coin, 0.0)

        if coin_amount > held + 1e-10:
            logger.warning(f"[PAPER] {ticker} 매도 실패: 코인 잔고 부족 ({coin_amount:.6f} > {held:.6f})")
            return None

        cur_price = pyupbit.get_current_price(ticker)
        if cur_price is None:
            return None

        gross_krw = coin_amount * cur_price
        fee = gross_krw * FEE_RATE
        net_krw = gross_krw - fee

        self.balances[coin] = max(0.0, held - coin_amount)
        self.balances['KRW'] = self.balances.get('KRW', 0.0) + net_krw

        record = {
            'type': 'SELL',
            'ticker': ticker,
            'price': cur_price,
            'krw': net_krw,
            'coins': coin_amount,
            'fee': fee,
            'time': datetime.datetime.now(),
            'krw_balance': self.balances['KRW'],
        }
        self.trades.append(record)
        logger.info(
            f"[PAPER] 매도: {ticker}  가격={cur_price:,.0f}  "
            f"수량={coin_amount:.6f}  수령={net_krw:,.0f}  수수료={fee:,.0f}  "
            f"KRW잔고={self.balances['KRW']:,.0f}"
        )
        return record

    # ── 평가금액 계산 ────────────────────────────────────────────────────────

    def get_total_value(self, tickers):
        """총 평가금액 (KRW + 보유 코인 평가금액)"""
        total = self.balances.get('KRW', 0.0)
        try:
            prices = pyupbit.get_current_price(tickers)
            if prices:
                for ticker in tickers:
                    coin = ticker.split('-')[1]
                    coins = self.balances.get(coin, 0.0)
                    if coins > 0:
                        total += coins * prices.get(ticker, 0)
        except Exception:
            pass
        return total

    # ── 결과 요약 출력 ────────────────────────────────────────────────────────

    def print_summary(self, tickers):
        """7일 모의투자 결과 요약"""
        total_value = self.get_total_value(tickers)
        pnl_krw = total_value - self.initial_krw
        pnl_pct = pnl_krw / self.initial_krw * 100
        total_fee = sum(t['fee'] for t in self.trades)

        buy_trades = [t for t in self.trades if t['type'] == 'BUY']
        sell_trades = [t for t in self.trades if t['type'] == 'SELL']

        # 코인별 거래 쌍 분석 (매수 → 매도)
        wins, losses = _calc_win_loss(self.trades)

        print("\n" + "=" * 70)
        print("  [모의투자 7일 결과 요약]")
        print("=" * 70)
        print(f"  초기 투자금:   {self.initial_krw:>15,.0f} KRW")
        print(f"  최종 평가금액: {total_value:>15,.0f} KRW")
        print(f"  순손익:        {pnl_krw:>+15,.0f} KRW  ({pnl_pct:+.2f}%)")
        print(f"  총 수수료:     {total_fee:>15,.0f} KRW")
        print("-" * 70)
        print(f"  총 매수 횟수:  {len(buy_trades):>5}회")
        print(f"  총 매도 횟수:  {len(sell_trades):>5}회")
        print(f"  이익 거래:     {wins:>5}회")
        print(f"  손실 거래:     {losses:>5}회")
        if wins + losses > 0:
            win_rate = wins / (wins + losses) * 100
            print(f"  승률:          {win_rate:>8.1f}%")
        print("-" * 70)

        # 코인별 보유 현황
        print("  [보유 현황]")
        try:
            prices = pyupbit.get_current_price(tickers)
        except Exception:
            prices = {}
        for ticker in tickers:
            coin = ticker.split('-')[1]
            coins = self.balances.get(coin, 0.0)
            cur_price = prices.get(ticker, 0) if prices else 0
            value = coins * cur_price
            if coins > 0:
                print(f"    {ticker}: {coins:.6f}개  평가금={value:,.0f} KRW")
        print(f"    KRW 잔고: {self.balances.get('KRW', 0):,.0f} KRW")

        # 최근 10개 거래 내역
        if self.trades:
            print("-" * 70)
            print("  [최근 거래 내역 (최대 10건)]")
            for t in self.trades[-10:]:
                t_type = t['type']
                t_time = t['time'].strftime('%m/%d %H:%M')
                print(
                    f"    {t_time}  {t_type:<4}  {t['ticker']}  "
                    f"가격={t['price']:>12,.0f}  수량={t['coins']:.6f}  "
                    f"금액={t['krw']:>12,.0f}"
                )
        print("=" * 70)


def _calc_win_loss(trades):
    """거래 내역에서 승/패 횟수 계산 (SELL 기준, 직전 BUY와 비교)"""
    wins = 0
    losses = 0
    buy_prices = {}  # ticker -> last buy price

    for t in trades:
        ticker = t['ticker']
        if t['type'] == 'BUY':
            buy_prices[ticker] = t['price']
        elif t['type'] == 'SELL' and ticker in buy_prices:
            if t['price'] > buy_prices[ticker]:
                wins += 1
            else:
                losses += 1
            del buy_prices[ticker]

    return wins, losses
