"""Render development reuse and previously unused observations separately."""
import hashlib
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/filter_heatpump_improvement'
def pct(v):return '평가 불가' if v is None else f'{v*100:.2f}%'
def table(head,rows):
    esc=lambda v:html.escape(str(v))
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'

def main():
    r=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    a=json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'))
    assert a['successful'] and a['results_sha256']==hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest()
    body='<h1>필터·히트펌프 개선 검증 · '+html.escape(r['version'])+'</h1><p>기존 평가 자료 재사용과 이전 미사용 관측을 분리했습니다. 학습·보정·평가를 유지했고, 평가 수치를 확인한 뒤 매개변수를 재조정하지 않았습니다.</p>'
    headers=['대상','설정','정확도','검출률','오경보율','판단률','TP / FN / FP / TN']
    def values(title,k,m):return [title,k,*[pct(m[x]) for x in ['accuracy_valid','recall_valid','false_positive_rate_valid','coverage']],f"{m['TP']:,} / {m['FN']:,} / {m['FP']:,} / {m['TN']:,}"]
    body+='<h2>기존 평가 자료 재사용</h2>'
    rows=[]
    for k,label in [('before','기존'),('after','개선')]:
        rows.append(values('필터 · 30초 위험',label,r['filter']['evaluations']['reused_test']['comparison'][k]))
        rows.append(values('히트펌프 · 전체 고장',label,r['heatpump']['comparison'][k]['metrics']))
    body+=table(headers,rows)
    body+='<p>필터 오경보를 낮추면서 검출률도 떨어졌습니다. 새로운 지도학습 모형에는 별도 시험의 완전 수명 자료를 추가했으므로, 알고리즘만 바꾼 비교가 아닙니다. 정확도는 클래스 불균형의 영향을 받습니다.</p>'
    body+='<h2>히트펌프 · 고장별 검출률 (재사용)</h2>'
    body+=table(['고장','기존','개선'],[[c,pct(r['heatpump']['comparison']['before']['by_category'][c]['recall_valid']),pct(r['heatpump']['comparison']['after']['by_category'][c]['recall_valid'])] for c in ['EF','CVL','LL','OC']])
    body+='<p>EF는 증발기 물 유량 감소 모사입니다. 정상 오경보 0건은 같은 정상 두 실험의 끝부분 490표본에 한정됩니다. 독립적인 현장 성능은 확인되지 않았습니다.</p>'
    body+='<h2>필터 · 이전 미사용 후반 관측</h2><p>10개 기존 Train 시험체의 CSV 검열 시점 뒤 MAT 원본 관측 3,206행만 집계했습니다. 새 모형의 학습·보정 시험체와는 겹치지 않습니다. 기존 기준은 과거에 이 시험체의 초기 보정 자료를 봤으므로 새 설비·새 코퍼스 검증으로 부르지 않습니다.</p>'
    body+=table(headers,[values('필터 · 미사용 후반',label,r['filter']['evaluations']['unused_suffix_known_specimens']['comparison'][k]) for k,label in [('before','기존'),('after','개선')]])
    body+='<p>이 구간은 수명 말기 표본으로 구성돼 기존 Test와 분포가 다릅니다. 개선 후에도 오경보율 38.14%가 남습니다. 첫 성공 실행 뒤 수치에 맞춰 다시 보정하지 않았습니다.</p>'
    body+='<h2>새 독립 데이터에서 평가하지 못한 항목</h2>'+table(['항목','상태','이유'],[
        ['히트펌프 EF 정확도·검출률·오경보율','평가 불가','새로운 호환 물 유량 감소 시험 미확보. NIST 냉방 자료 다운로드는 HTTP403. 냉매 충전량 실험은 EF 정답이 없음.'],
        ['필터 현재 막힘 진단 정확도','평가 불가','평가 정답은 미래 600Pa 교체 한계까지 시간이며 독립적인 현재 막힘 시작 정답이 아님.'],
        ['새 설비에서 필터 전이 성능','미검증','미사용 후반 자료도 기존 시험체에서 측정됨.']])
    body+='<h2>재현 기록</h2><p>필터: 완전 수명 MAT 29시험 학습, 별도 10시험 보정, 10시험 미사용 후반 평가. 원시 시간 역전이 있는 28번 시험 전체 제외. 기존 Test 50시험은 재사용 평가 전용입니다. 히트펌프: 기존 NF10/NF12 시간 분리와 중간 제외 구간을 유지했습니다.</p><p>판단률은 사전 평가 대상 기준입니다. 기존 원시 행 기준 판단률은 필터 87.46%, 히트펌프 90.16%입니다. 후반 자료 판단률은 후반 평가 대상 100%이며, 해당 10시험 전체 원시 행 대비 31.87%입니다.</p><p>독립 원본 정답 대조·혼동행렬 집계·분할 중복·기준 불변성·해시 확인 통과. <a href="results.json">전체 결과</a> · <a href="independent_audit.json">감사</a> · <a href="protocol.json">프로토콜</a></p>'
    page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>필터·히트펌프 개선 검증</title><style>body{font-family:system-ui,sans-serif;max-width:1300px;margin:32px auto;padding:0 24px;background:#fafbfd;color:#172638;line-height:1.65}h1{font-size:28px}h2{margin-top:32px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{padding:10px;border:1px solid #c9d3df;text-align:left}th{background:#eaf1f8}a{color:#1260ac}</style><body>'+body+'</body></html>'
    (OUT/'report.html').write_text(page,encoding='utf-8');print(OUT/'report.html')
if __name__=='__main__':main()
