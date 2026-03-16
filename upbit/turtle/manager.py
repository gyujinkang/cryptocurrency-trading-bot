"""
업비트 API 인스턴스 생성 및 유틸리티
"""

import pyupbit
import logging

logger = logging.getLogger(__name__)


def create_instance(key_file="upbit.txt"):
    """
    upbit.txt에서 API 키를 읽어 pyupbit.Upbit 인스턴스 생성
    upbit.txt 형식:
        첫 번째 줄: Access Key
        두 번째 줄: Secret Key
    """
    try:
        with open(key_file, 'r') as f:
            lines = f.readlines()
        access_key = lines[0].strip()
        secret_key = lines[1].strip()
        inst = pyupbit.Upbit(access_key, secret_key)
        logger.info("업비트 API 연결 성공")
        return inst
    except FileNotFoundError:
        raise FileNotFoundError(
            f"API 키 파일을 찾을 수 없습니다: {key_file}\n"
            "upbit.txt 파일에 Access Key와 Secret Key를 입력하세요."
        )
    except IndexError:
        raise ValueError(
            "upbit.txt 형식 오류: 첫 번째 줄에 Access Key, 두 번째 줄에 Secret Key"
        )


def setup_logging(log_file="turtle_trading.log"):
    """로그 설정: 콘솔 + 파일"""
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding='utf-8'),
        ]
    )
