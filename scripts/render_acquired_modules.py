"""Render fixed measured evaluations without changing references or thresholds."""
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'acquired_modules_validation'


def pct(value):
    return '평가 불가' if value is None else f'{100*value:.2f}%'


def table(headers, rows):
    cell = lambda x: html.escape(str(x))
    return '<div class="scroll"><table><thead><tr>' + ''.join(
        f'<th>{cell(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{cell(v)}</td>' for v in row) + '</tr>' for row in rows
    ) + '</tbody></table></div>'


def main():
    result = json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    audit = json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful']
    assert audit['results_sha256'] == hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest()
    modules = result['modules']
    rows = []
    for key, title in [('filter', '필터 · 30초 내 교체 한계 위험'), ('heatpump', '히트펌프 · 실험 주입 고장')]:
        for policy, label in [('before', '기존'), ('after', '보완')]:
            m = modules[key]['comparison'][policy]['metrics']
            rows.append([title, label, *[pct(m[k]) for k in (
                'accuracy_valid', 'recall_valid', 'false_positive_rate_valid', 'coverage', 'coverage_all_rows')],
                f"{m['valid']:,} / {m['eligible']:,} / {m['total']:,}"])
    body = '<h1>실측 자료 적용·검증 · v' + html.escape(result['version']) + '</h1>'
    body += '<p>필터 → RO → 히트펌프 순서로 적용. 학습·보정·평가를 분리하고, 평가 전 기준과 한계를 고정했습니다. 시뮬레이션 결과를 합산하지 않았습니다.</p>'
    body += '<h2>정답을 정의할 수 있는 평가</h2><p>필터는 공급자 RUL≤30초라는 미래 위험 대리 목표입니다. 현재 막힘 진단 정답은 없습니다. 히트펌프는 단일 프로토타입의 실험 주입 고장입니다. 두 목표의 수치를 서로 우열 비교하면 안 됩니다.</p>'
    body += table(['목표', '설정', '정확도', '검출률', '오경보율', '대상 판단률', '원시 행 판단률', '판단 / 대상 / 원시 행'], rows)
    body += '<p>정확도·검출률·오경보율은 판단 가능한 표본 기준입니다. 판단률은 사전에 제외한 시동 등을 뺀 대상 기준이며, 원시 행 판단률도 함께 표시했습니다. 필터는 개선이 없고 위험 경보가 많습니다.</p>'
    body += '<h2>RO · 고장 정답 없음, 엄격한 압력 품질 검사 실패</h2><p>정상 학습 전 행에서 농축 압력이 공급 압력보다 높아 엄격한 모델은 학습 불가입니다. 아래는 공급압만 사용하고 막 용기 손실과 투과측 게이지 압력을 0으로 가정한 미검증 근사입니다. 정식 진단 성능으로 채택하지 않습니다.</p>'
    ro_rows = []
    for policy, label in [('before', '삼투압·온도 보정 전'), ('after', '보정 후')]:
        m = modules['ro']['comparison'][policy]
        ro_rows.append([label, '평가 불가', '평가 불가', '평가 불가', pct(m['coverage']),
                        pct(m['observed_alarm_fraction']), f"{m['valid']:,}/{m['total']:,}",
                        f"{m['permeability_relative_std']:.3f}"])
    body += table(['미검증 근사', '정확도', '검출률', '오경보율', '계산 판단률', '관측 경보 비율', '판단/행', '투수성 상대 표준편차'], ro_rows)
    body += '<p>경보 0%는 오경보율 0%가 아닙니다. 동적 압력 명령을 고장 정답으로 쓰지 않았습니다. 보정 후 판단률과 지표 안정성 모두 악화했습니다. 센서 위치·교정·압력 기준 확인이 우선입니다.</p>'
    body += '<h2>히트펌프 · 고장별 검출률</h2>'
    names = {'EF': '증발기 물 유량 감소', 'CVL': '압축기 밸브 누설 모사', 'LL': '액관 제한', 'OC': '냉매 과충전'}
    comp = modules['heatpump']['comparison']
    body += table(['고장', '기존', '부하 보정'], [[name, pct(comp['before']['by_category'][k]['recall_valid']),
                 pct(comp['after']['by_category'][k]['recall_valid'])] for k, name in names.items()])
    body += '<p>정상 평가 490표본에서 두 설정 모두 오경보 0건입니다. 같은 정상 2회 시험의 시간 분할이므로 독립 반복시험·새 설비 성능은 확인하지 못했습니다. 유량 감소 고장 검출률 6.71%는 주요 미해결 문제입니다. 알려진 실험 경계에서 시동 180초 제외, 30초 지속 경보를 사용했습니다.</p>'
    body += '<h2>분리·재현 기록</h2>'
    body += table(['자료', '학습', '보정', '평가'], [
        ['필터', 'Train 별도 40시험 초기 10~20초', 'Train 별도 10시험 초기 10~20초', 'Test 50시험, 초기 10초 제외'],
        ['RO', '조건별 0~40%', '50~70%', '80~100% + 동적 27파일'],
        ['히트펌프', 'NF10/NF12의 0~40%', '50~70%', '80~100% + 고장 8시트']])
    body += '<p>RO·히트펌프 정상 시계열의 40~50%, 70~80%는 비웠습니다. 고장 코드·강도·RUL은 평가 정답과 실험 경계 확인에만 사용하고 진단 특징에 넣지 않았습니다. 필터 유량은 원 단위가 불명확하여 무차원 비로 연결했습니다. 히트펌프의 별도 과열도 로거를 행 번호로 합치지 않았습니다.</p>'
    body += '<p>독립 감사: 원본 정답 대조, 분할 행 중복 검사, 코드·원본·정상 기준 해시 확인, 행별 CSV에서 혼동행렬 재집계 통과.</p><p><a href="results.json">전체 수치 JSON</a> · <a href="independent_audit.json">독립 감사</a> · <a href="protocol.json">고정 프로토콜</a></p>'
    output = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>실측 자료 진단 검증</title><style>body{font-family:system-ui,sans-serif;max-width:1400px;margin:32px auto;padding:0 24px;color:#172638;background:#fafbfd;line-height:1.65}h1{font-size:28px}h2{margin-top:36px}p{max-width:1100px}.scroll{overflow:auto}table{border-collapse:collapse;background:white;width:100%;font-size:14px}th,td{border:1px solid #c9d3df;padding:10px;text-align:left}th{background:#eaf1f8}a{color:#1260ac}</style><body>' + body + '</body></html>'
    (OUT/'report.html').write_text(output, encoding='utf-8')
    print(OUT/'report.html')


if __name__ == '__main__':
    main()
