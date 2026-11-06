"""Show both reused cohorts, the rejected candidates and missing new-data tests."""
import hashlib
import json
from pathlib import Path
from render_filter_heatpump_improvement import table,pct

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/filter_heatpump_operating_points'

def main():
    r=json.loads((OUT/'results.json').read_text(encoding='utf-8'));a=json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'))
    assert a['successful'] and a['results_sha256']==hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest()
    body='<h1>필터·히트펌프 후속 개선 · v'+r['version']+'</h1><p>기존 Test와 지난번 후반 자료는 모두 재사용 평가입니다. 학습·보정·평가 분할은 유지했지만, 네 설정을 개발하며 평가 결과를 확인했습니다. 새 독립 검증으로 해석하지 않습니다.</p>'
    rows=[]
    for scope,title in [('reused_original_test','필터 원래 Test'),('reused_uncensored_suffix','필터 기존 후반 자료')]:
        for k,label in [('before','v0.10'),('after','중간 경보 설정')]:
            m=r['filter']['evaluations'][scope]['comparison'][k]
            rows.append([title,label,*[pct(m[x]) for x in ['accuracy_valid','recall_valid','false_positive_rate_valid','coverage']],f"{m['TP']:,}/{m['FN']:,}/{m['FP']:,}/{m['TN']:,}"])
    for k,label in [('before','v0.10'),('after','증발기 관련 감시 추가')]:
        m=r['heatpump']['comparison'][k]['metrics'];rows.append(['히트펌프 전체 고장',label,*[pct(m[x]) for x in ['accuracy_valid','recall_valid','false_positive_rate_valid','coverage']],f"{m['TP']:,}/{m['FN']:,}/{m['FP']:,}/{m['TN']:,}"])
    body+='<h2>최종 비교 · 모두 재사용</h2>'+table(['대상','설정','정확도','검출률','오경보율','대상 판단률','TP/FN/FP/TN'],rows)
    body+='<p>필터는 현재 막힘이 아닌 RUL≤30초 미래 교체 위험입니다. 최종 개선에는 추가로 관측 분진 공급 조건·재료 종류가 필요합니다. 판단 행은 전후 동일하며 원시 행 기준 판단률은 원래 Test 87.46%, 후반 시험 전체 31.87%, 히트펌프 90.16%입니다.</p>'
    body+='<p>필터 검출률은 초기 저항 모형의82.45%까지 회복하지 못했습니다. 후반 오경보21.58%도 여전히 높습니다.</p>'
    body+='<h2>히트펌프 고장별 검출률</h2>'+table(['고장','v0.10','최종'],[[c,pct(r['heatpump']['comparison']['before']['by_category'][c]['recall_valid']),pct(r['heatpump']['comparison']['after']['by_category'][c]['recall_valid'])] for c in ['EF','CVL','LL','OC']])
    body+='<p>EF는 증발기 물 유량 감소 모사입니다. 정상 오경보0건은 같은 정상 두 실험의 평가490표본에 한정됩니다. 약21.70%의 EF 표본은 아직 놓칩니다.</p>'
    candidates=[]
    for directory,title in [('filter_heatpump_refinement','차압·유량만 / 첫 후보'),('filter_heatpump_refinement_final','조건 입력 / 엄격 경보'),('filter_heatpump_balanced','조건 입력 / 검출 우선'),('filter_heatpump_operating_points','조건 입력 / 중간 경보')]:
        x=json.loads((ROOT/'outputs'/directory/'results.json').read_text(encoding='utf-8'))
        f=x['filter']['evaluations'];t=f['reused_original_test']['comparison']['after'];s=f['reused_uncensored_suffix']['comparison']['after'];h=x['heatpump']['comparison']['after']
        candidates.append([title,pct(t['recall_valid']),pct(t['false_positive_rate_valid']),pct(s['recall_valid']),pct(s['false_positive_rate_valid']),pct(h['by_category']['EF']['recall_valid']),pct(h['metrics']['false_positive_rate_valid'])])
    body+='<h2>개발 중 확인한 모든 후보</h2>'+table(['후보','필터 Test 검출률','Test 오경보','후반 검출률','후반 오경보','HP EF 검출률','HP 정상 오경보'],candidates)
    body+='<p>첫 히트펌프 후보는 오경보49.59%로 채택하지 않았습니다. 필터 검출 우선 설정은 Test 검출률78.48%지만 후반 오경보49.56%로 악화했습니다. 중간 설정은 두 필터 구간에서 이전 모델 대비 검출률 상승·오경보 감소를 함께 보였습니다. 선택 과정까지 포함해 재사용 개발 결과로 기록합니다.</p>'
    body+='<h2>새 데이터 검증 · 수치 없음</h2>'+table(['항목','상태'],[['새 필터 시험의30초/600Pa 위험 성능','호환 새 원본 미확보. 정확도·검출률·오경보율 null.'],['새 히트펌프 물 유량 감소 시험','호환 새 원본 미확보. 정확도·검출률·오경보율 null.'],['현재 필터 막힘 진단 정확도','독립적인 현재 막힘 시작 정답이 없어 평가 불가.']])
    body+='<p>원래 학습·보정 시험 ID와 정상 시간 분할·중간 제외 구간을 유지했습니다. 추가 입력의 기준값도 학습 자료에서만 계산했습니다. 원본 정답·기존 예측 재현·분할·해시·혼동행렬·앞선 후보 코드 스냅샷 독립 감사 통과.</p><p><a href="results.json">최종 결과</a> · <a href="independent_audit.json">독립 감사</a> · <a href="protocol.json">프로토콜·개발 이력</a></p>'
    page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>필터·히트펌프 검출 개선</title><style>body{font-family:system-ui,sans-serif;max-width:1400px;margin:32px auto;padding:0 24px;line-height:1.65;color:#172638;background:#fafbfd}h1{font-size:28px}h2{margin-top:32px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}th,td{padding:10px;border:1px solid #c9d3df;text-align:left}th{background:#eaf1f8}a{color:#1260ac}</style><body>'+body+'</body></html>'
    (OUT/'report.html').write_text(page,encoding='utf-8');print(OUT/'report.html')
if __name__=='__main__':main()
