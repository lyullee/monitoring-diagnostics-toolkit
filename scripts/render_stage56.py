"""Stage5 adoption versus stage6 experimental tradeoff, clearly separated."""
import hashlib,json
from pathlib import Path
from render_filter_heatpump_improvement import table,pct

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/stage56_ensemble'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    r=read(OUT/'results.json');a=read(OUT/'independent_audit.json');s=read(OUT/'training_model_selection.json');e=read(OUT/'event_comparison.json')
    assert a['successful'] and a['results_sha256']==hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest()
    body='<h1>5~6번 후속 개선 · v'+r['version']+'</h1><p>히트펌프 상관 잔차 경로는 개발 프로파일에 채택했습니다. 필터는 새 후보를 구현했지만 기본값은 유지했습니다. 학습·보정·평가 분리를 유지했으며 아래 성능은 모두 재사용 평가입니다.</p>'
    rows=[]
    for key,label in [('before','v0.12'),('after','상관 잔차+CUSUM')]:
        m=r['heatpump']['comparison'][key];rows.append([label,*[pct(m['metrics'][n]) for n in ['accuracy_valid','recall_valid','false_positive_rate_valid','coverage']],pct(m['by_category']['EF']['recall_valid'])])
    body+='<h2>5 히트펌프 · 채택한 추가 경로</h2>'+table(['설정','정확도','전체 검출률','오경보율','판단률','EF 검출률'],rows)
    body+='<p>정상490표본에서 오경보0건입니다. EF10.1은26.99→49.08%로 여전히 절반가량 놓칩니다. 전체 EF96.17%를 미세 고장 해결로 해석하지 않습니다.</p>'
    ev=e['heatpump'];body+=table(['관측 지표','이전','새 경로'],[['연속 경보 구간',ev['before']['alarm_segments'],ev['after_candidate']['alarm_segments']],['양성 관측 구간 검출',f"{ev['before']['detected_positive_windows']}/{ev['before']['positive_windows']}",f"{ev['after_candidate']['detected_positive_windows']}/{ev['after_candidate']['positive_windows']}"],['첫 유효 양성부터 최대 지연(초)',ev['before']['delay_max_s'],ev['after_candidate']['delay_max_s']]])
    body+='<p>관측 구간은 알려진 실험 조건이며 실제 독립 고장 시작 사건이 아닙니다. 정상 두 실험의 시간 분할·시동180초 제외를 유지했습니다.</p>'
    rows=[]
    for scope,title in [('original_test','원래 Test'),('reused_suffix','기존 후반')]:
        for key,label in [('before','기본 유지'),('after','새 결합 후보 · 미채택')]:
            m=r['filter']['evaluations'][scope]['comparison'][key];rows.append([title,label,*[pct(m[n]) for n in ['accuracy_valid','recall_valid','false_positive_rate_valid','coverage']]])
    body+='<h2>6 필터 · 기본값 유지와 새 후보 비교</h2>'+table(['자료','설정','정확도','검출률','오경보율','판단률'],rows)
    body+='<p>Test 검출률은 올랐지만 오경보도 증가했고, 후반 오경보는 줄었지만 검출률이 감소했습니다. 두 자료에서 검출률·오경보를 함께 개선하지 못해 기본값을 교체하지 않았습니다. 분진 공급 조건·재료 종류 입력이 필요하며 목표는30초 내 교체 한계 위험입니다.</p>'
    body+='<h2>모델 선택 · 학습 내부 시험 단위 검증만 사용</h2>'+table(['후보','부분 AUC(FPR≤5%) 평균'],[[name,f"{v['mean_partial_auc_fpr05']:.5f}"] for name,v in s['candidates'].items()])
    body+='<p>선택: '+s['selected']+'. 학습29시험 내부 GroupKFold3을 사용하고, 별도 보정10시험으로 한계를 계산했습니다. Test와 기존 후반 자료를 모델 선택·임계값 계산에 넣지 않았습니다. 설계는 이전 재사용 분석의 영향을 받았으므로 독립 블라인드 검증은 아닙니다.</p>'
    body+='<p>부스팅·수명 회귀·경보 유지 정책도 구현·검증했고 앞선 후보의 결과와 소스를 보존했습니다. 기본 필터 기준은v0.12이며 히스테리시스는 활성화하지 않았습니다.</p>'
    body+='<h2>검증 범위</h2><p>회귀시험249개·연동7개 통과. 독립 감사에서30개 내부 ROC 곡선 적분,5775행의 잔차 거리·EWMA·CUSUM 재계산, 원본 정답·분할·기존 예측·해시를 확인했습니다. 새 독립 고장 성능은null로 남겼습니다. 기존의 새 R290195관측은 물리 지표 계산 확인, RO36398행은 품질 검사 근거로만 유지합니다.</p><p><a href="results.json">수치</a> · <a href="adoption.json">채택 여부·기본 기준</a> · <a href="independent_audit.json">감사</a> · <a href="training_model_selection.json">학습 내부 모델 선택</a> · <a href="event_comparison.json">관측 구간·지연</a></p>'
    page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>5~6번 개선 검증</title><style>body{font-family:system-ui,sans-serif;max-width:1400px;margin:32px auto;padding:0 24px;color:#172638;background:#fafbfd;line-height:1.65}h1{font-size:28px}h2{margin-top:32px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{padding:10px;border:1px solid #c9d3df;text-align:left}th{background:#eaf1f8}a{color:#1260ac}</style><body>'+body+'</body></html>'
    (OUT/'report.html').write_text(page,encoding='utf-8');print(OUT/'report.html')
if __name__=='__main__':main()
