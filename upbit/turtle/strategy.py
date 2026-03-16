"""
터틀 트레이딩 전략 (Turtle Trading Strategy)
- System 1: 20일 돌파 진입 / 10일 하향 청산
- System 2: 55일 돌파 진입 / 20일 하향 청산
- N: 20일 지수이동평균 ATR (True Range)
- 포지션 사이징: 계좌의 1% 위험 / N
"""

import pyupbit
import pandas as pd


def get_ohlcv(ticker, count=200):
    """일봉 OHLCV 데이터 조회"""
    return pyupbit.get_ohlcv(ticker, interval="day", count=count)


def get_atr(df, period=20):
    """
    N (ATR) 계산 - 20일 지수가중 평균 True Range
    True Range = max(high, prev_close) - min(low, prev_close)
    """
    df = df.copy()
    df['prev_close'] = df['close'].shift(1)
    df['tr'] = (
        df[['high', 'prev_close']].max(axis=1) -
        df[['low', 'prev_close']].min(axis=1)
    )
    atr = df['tr'].ewm(span=period, adjust=False).mean()
    return atr.iloc[-1]


def get_donchian_high(df, period):
    """최근 N일 최고가 (현재 봉 제외) - 돈치안 채널 상단"""
    return df['high'].iloc[-(period + 1):-1].max()


def get_donchian_low(df, period):
    """최근 N일 최저가 (현재 봉 제외) - 돈치안 채널 하단"""
    return df['low'].iloc[-(period + 1):-1].min()


def get_signals(df):
    """
    터틀 트레이딩 신호 계산

    Returns:
        dict:
            n        - ATR (변동성 단위, KRW)
            s1_entry - System 1 진입가 (20일 최고가)
            s1_exit  - System 1 청산가 (10일 최저가)
            s2_entry - System 2 진입가 (55일 최고가)
            s2_exit  - System 2 청산가 (20일 최저가)
    """
    if df is None or len(df) < 60:
        return None

    n = get_atr(df, period=20)

    return {
        'n': n,
        's1_entry': get_donchian_high(df, 20),
        's1_exit':  get_donchian_low(df, 10),
        's2_entry': get_donchian_high(df, 55),
        's2_exit':  get_donchian_low(df, 20),
    }


def get_unit_size_krw(total_balance, n, current_price, risk_pct=0.01):
    """
    1 유닛의 KRW 투자금액 계산

    원리:
        unit_coins = (total_balance * risk_pct) / N
        unit_krw   = unit_coins * current_price

    예시:
        잔고=10,000,000 KRW, N=500,000, BTC=50,000,000
        unit_coins = 100,000 / 500,000 = 0.2 BTC
        unit_krw   = 0.2 * 50,000,000 = 10,000,000 KRW
    """
    if n <= 0 or current_price <= 0:
        return 0
    unit_coins = (total_balance * risk_pct) / n
    return unit_coins * current_price


if __name__ == "__main__":
    for ticker in ["KRW-BTC", "KRW-ETH"]:
        df = get_ohlcv(ticker)
        sig = get_signals(df)
        cur = pyupbit.get_current_price(ticker)
        print(f"\n[{ticker}]")
        print(f"  현재가:     {cur:,.0f} KRW")
        print(f"  N (ATR):    {sig['n']:,.0f} KRW")
        print(f"  S1 진입가:  {sig['s1_entry']:,.0f}  (20일 최고가)")
        print(f"  S1 청산가:  {sig['s1_exit']:,.0f}  (10일 최저가)")
        print(f"  S2 진입가:  {sig['s2_entry']:,.0f}  (55일 최고가)")
        print(f"  S2 청산가:  {sig['s2_exit']:,.0f}  (20일 최저가)")
        unit_krw = get_unit_size_krw(10_000_000, sig['n'], cur)
        print(f"  유닛 크기:  {unit_krw:,.0f} KRW  (잔고 1000만 기준)")
