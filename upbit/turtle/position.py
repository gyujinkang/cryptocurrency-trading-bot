"""
터틀 트레이딩 포지션 관리
- 유닛별 진입가, 보유 코인 수량, 손절가, 진입 시스템 추적
- 피라미딩: 최대 4 유닛, 0.5N 간격으로 추가 진입
- 손절: 최신 유닛 기준 2N 하락
- 상태를 JSON 파일로 저장/복원 (재시작 대비)
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

MAX_UNITS = 4
STATE_FILE = "turtle_state.json"


class Unit:
    """개별 진입 유닛"""

    def __init__(self, entry_price, coins, stop_loss, system):
        self.entry_price = entry_price  # 진입가 (KRW)
        self.coins = coins              # 보유 코인 수량
        self.stop_loss = stop_loss      # 손절가 (entry_price - 2N)
        self.system = system            # 진입 시스템: 's1', 's2', 'pyramid'

    def to_dict(self):
        return {
            'entry_price': self.entry_price,
            'coins': self.coins,
            'stop_loss': self.stop_loss,
            'system': self.system,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d['entry_price'], d['coins'], d['stop_loss'], d['system'])


class Position:
    """티커별 포지션 상태"""

    def __init__(self, ticker):
        self.ticker = ticker
        self.units = []                     # List[Unit]
        self.last_s1_was_loser = False      # 직전 S1 거래 손실 여부 (S1 필터)

    # ── 조회 ────────────────────────────────────────────────────────────────

    @property
    def is_holding(self):
        return len(self.units) > 0

    @property
    def num_units(self):
        return len(self.units)

    @property
    def total_coins(self):
        return sum(u.coins for u in self.units)

    @property
    def stop_loss(self):
        """전체 포지션 손절가 = 가장 낮은 유닛 손절가"""
        if not self.units:
            return 0.0
        return min(u.stop_loss for u in self.units)

    @property
    def avg_entry_price(self):
        """평균 진입가"""
        if not self.units:
            return 0.0
        total_krw = sum(u.entry_price * u.coins for u in self.units)
        return total_krw / self.total_coins

    def can_add_unit(self):
        return self.num_units < MAX_UNITS

    def get_next_pyramid_price(self, n):
        """피라미딩 진입가 = 마지막 유닛 진입가 + 0.5N"""
        if not self.units:
            return None
        return self.units[-1].entry_price + 0.5 * n

    # ── 변경 ────────────────────────────────────────────────────────────────

    def add_unit(self, entry_price, coins, n, system):
        """유닛 추가 (손절가 = entry_price - 2N)"""
        stop_loss = entry_price - 2 * n
        unit = Unit(entry_price, coins, stop_loss, system)
        self.units.append(unit)
        logger.info(
            f"[{self.ticker}] 유닛 추가 #{self.num_units} ({system}): "
            f"진입가={entry_price:,.0f}  손절가={stop_loss:,.0f}  수량={coins:.6f}"
        )

    def clear(self, was_loser=False):
        """포지션 청산 후 초기화"""
        self.units.clear()
        if was_loser:
            self.last_s1_was_loser = True
        else:
            self.last_s1_was_loser = False

    # ── 직렬화 ──────────────────────────────────────────────────────────────

    def to_dict(self):
        return {
            'ticker': self.ticker,
            'units': [u.to_dict() for u in self.units],
            'last_s1_was_loser': self.last_s1_was_loser,
        }

    @classmethod
    def from_dict(cls, d):
        pos = cls(d['ticker'])
        pos.units = [Unit.from_dict(u) for u in d.get('units', [])]
        pos.last_s1_was_loser = d.get('last_s1_was_loser', False)
        return pos

    def __repr__(self):
        return (
            f"Position({self.ticker}, units={self.num_units}, "
            f"coins={self.total_coins:.6f}, stop={self.stop_loss:,.0f})"
        )


# ── 상태 저장/로드 ───────────────────────────────────────────────────────────

def save_state(positions, path=STATE_FILE):
    """포지션 상태를 JSON 파일로 저장"""
    try:
        data = {ticker: pos.to_dict() for ticker, pos in positions.items()}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"상태 저장 실패: {e}")


def load_state(tickers, path=STATE_FILE):
    """JSON 파일에서 포지션 상태 복원"""
    positions = {ticker: Position(ticker) for ticker in tickers}

    if not os.path.exists(path):
        return positions

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for ticker in tickers:
            if ticker in data:
                positions[ticker] = Position.from_dict(data[ticker])
                logger.info(f"[{ticker}] 이전 포지션 복원: {positions[ticker]}")
    except Exception as e:
        logger.warning(f"상태 복원 실패 (새로 시작): {e}")

    return positions
