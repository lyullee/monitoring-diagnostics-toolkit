"""Machine-readable capability list, including the limits of every label."""
from copy import deepcopy


CATALOG = {
    "heat_pump_performance": {"name_ko":"히트펌프 냉매측 성능","description":"난방 COP·등온 Carnot 효율 지표·과냉·토출 과열·회전당 냉매량 잔차. 정상 부하 기준과 별도 보정 제공. 고장 원인 분류 아님","normal_reference":True},
    "mass_balance": {"name_ko": "탱크 질량수지", "description": "재고 변화와 입출고·알려진 손실을 비교해 미설명 손실률 계산", "normal_reference": False},
    "boiler_mass_balance": {"name_ko": "보일러 질량수지", "description": "검증된 총재고와 급수·증기·블로다운으로 누설 의심 감시", "normal_reference": False},
    "heat_exchanger": {"name_ko": "열교환기 열성능", "description": "단상 대향류 열수지·LMTD·UA를 계산하고 기준 대비 성능 저하 검출", "normal_reference": True},
    "hydraulic_resistance": {"name_ko": "필터·배관 차압 저항", "description": "유량·밀도를 보정한 차압 증가로 막힘·저항 변화 감시", "normal_reference": True},
    "vaporizer": {"name_ko": "기화기 온도 잔차", "description": "외부 모델 예측 대비 출구 온도 부족·저온 한계와 선택적 엔탈피 열량 계산", "normal_reference": False},
    "ro_membrane": {"name_ko": "RO 막 투수성", "description": "순구동압·온도 보정계수로 정규화한 투수성 감소 감시", "normal_reference": True},
    "valve_tracking": {"name_ko": "밸브 추종 오차", "description": "명령과 실측 위치의 지연 보정 오차 검출. 스틱션 원인 확정 아님", "normal_reference": False},
    "column_hydraulics": {"name_ko": "증류탑 수력학", "description": "증기·액체 부하를 보정한 탑 차압 증가 감시. 플러딩·오염 원인 분리 아님", "normal_reference": True},
    "steam_trap": {"name_ko": "스팀트랩 온도·음향", "description": "증기 공급 중 저온·저음향 또는 고온·고음향 패턴 감시. 현장 임계값 필요", "normal_reference": False},
    "chiller_performance": {"name_ko": "냉동기 열성능", "description": "COP·접근온도 감시. 선택적으로 부하·냉수·냉각수 온도별 정상 전력·접근온도·유량 예측과 정상 전용 보정 제공. 고장 종류 분류 아님", "normal_reference": True},
}


def list_diagnostics():
    from .diagnostics import DIAGNOSTICS
    return [{"kind": kind, **deepcopy(CATALOG[kind]),
             "references": list(DIAGNOSTICS[kind].references),
             "qualification": "engineering_screening"} for kind in sorted(DIAGNOSTICS)]
