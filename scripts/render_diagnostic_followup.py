"""Human-readable sequential analysis, reused performance and fresh-data limits."""
import hashlib
import json
from pathlib import Path
from render_filter_heatpump_improvement import table,pct

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/diagnostic_followup';ANALYSIS=ROOT/'outputs/diagnostic_gap_analysis'
def read(p):return json.loads(p.read_text(encoding='utf-8'))

def main():
    r=read(OUT/'results.json');audit=read(OUT/'independent_audit.json');events=read(OUT/'event_comparison.json');strata=read(OUT/'stratified_comparison.json')
    new=read(ANALYSIS/'new_independent_physical_validation.json');ro=read(ANALYSIS/'ro_new_quality.json')
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest()
    body='<h1>순차 분석·후속 개선 · v'+r['version']+'</h1><p>1~4 분석 뒤5~6 후보를 구현했습니다. 학습·보정·평가 분할은 유지했지만 모델 설계에 기존 평가 분석을 활용했습니다. 성능 수치는 재사용 평가이며 새 블라인드 검증이 아닙니다.</p>'
    body+='<h2>단계별 완료 내용</h2>'+table(['단계','확인·수행한 내용','결정'],[
        ['1 경보 구간 평가','발생 구간·음성 경보 조각·양성 관측 구간·지연을 집계','표본 검출률과 관측 구간 검출을 따로 표시'],
        ['2 히트펌프 미검출','약한 EF에서 문턱을 잠깐 넘고 내려와30초 연속 조건을 충족하지 못함','정상 자료로 보정한 누적 증거 경로 추가'],
        ['3 필터 조건','A2 미검출, A3 및 교체 시점 근처 오경보 집중','재료별 보정·분진 부하 지표 후보 비교'],
        ['4 RO 품질','설명·공정도·기존 관측·이전 미사용36398행 확인','압력 순서 문제 미해결, 엄격한 모델 제한 유지'],
        ['5 히트펌프 개선','EWMA20초+CUSUM, 부하별 정상 학습·별도 보정','기존 경보와 OR 결합'],
        ['6 필터 개선','후보 두 개와 학습 범위·트리 예측 차이 표시','성능 후보 미채택, 기존 결정 유지·정보 출력 추가']])
    rows=[]
    for key,label in [('before','v0.11'),('after','v0.12')]:
        m=r['heatpump']['comparison'][key]['metrics'];rows.append(['히트펌프 전체',label,*[pct(m[x]) for x in ['accuracy_valid','recall_valid','false_positive_rate_valid','coverage']]])
    for scope,title in [('original_test','필터 원래 Test'),('reused_suffix','필터 기존 후반')]:
        for key,label in [('before','v0.11'),('after','v0.12')]:
            m=r['filter']['evaluations'][scope]['comparison'][key];rows.append([title,label,*[pct(m[x]) for x in ['accuracy_valid','recall_valid','false_positive_rate_valid','coverage']]])
    body+='<h2>최종 채택 성능 · 재사용 평가</h2>'+table(['대상','설정','정확도','검출률','오경보율','대상 판단률'],rows)
    ef0=r['heatpump']['comparison']['before']['by_category']['EF']['recall_valid'];ef1=r['heatpump']['comparison']['after']['by_category']['EF']['recall_valid']
    body+='<p><strong>증발기 물 유량 감소 검출률 '+pct(ef0)+' → '+pct(ef1)+'</strong>. 정상490표본의 오경보는0건 유지했습니다. 유효 정상 관측 약81.67분이며 장기 현장 성능으로 환산하지 않습니다. 필터는 현재 막힘이 아닌30초 내600Pa 교체 한계 위험 평가입니다.</p>'
    rows=[]
    for name,label in [('heatpump','히트펌프'),('filter_original_test','필터 Test'),('filter_reused_suffix','필터 후반')]:
        old,new_event=events[name]['before'],events[name]['after']
        rows.append([label,f"{old['alarm_segments']} → {new_event['alarm_segments']}",f"{old['negative_alarm_fragments']} → {new_event['negative_alarm_fragments']}",
            f"{old['detected_positive_windows']}/{old['positive_windows']} → {new_event['detected_positive_windows']}/{new_event['positive_windows']}",
            f"{old['delay_median_s']:g}/{old['delay_max_s']:g} → {new_event['delay_median_s']:g}/{new_event['delay_max_s']:g}"])
    body+='<h2>경보 구간·지연</h2>'+table(['대상','연속 경보 구간','음성 경보 조각','검출한 양성 관측 구간','지연 중앙값/최대(초)'],rows)
    body+='<p>35개는 알려진 실험 조건의 양성 관측 구간이며 독립적인 실제 고장 시작 사건이 아닙니다. 지연은 시동 제외 후 첫 유효 양성부터 계산했습니다. 양성이 이미 시작된 구간의 좌측 검열을 따로 기록했습니다. 필터 음성은RUL>30초이며 완전 정상이라는 뜻이 아닙니다.</p>'
    rows=[]
    for name,label in [('analysis_driven_improvement','재료별 보정'),('analysis_driven_dose','분진 부하 지표')]:
        candidate=read(ROOT/'outputs'/name/'results.json')['filter']['evaluations'];t=candidate['original_test']['comparison']['after'];s=candidate['reused_suffix']['comparison']['after']
        rows.append([label,pct(t['recall_valid']),pct(t['false_positive_rate_valid']),pct(s['recall_valid']),pct(s['false_positive_rate_valid']),'미채택'])
    body+='<h2>필터 개선 후보를 채택하지 않은 이유</h2>'+table(['후보','Test 검출률','Test 오경보','후반 검출률','후반 오경보','결정'],rows)
    body+='<p>기존 기준을 안정적으로 넘지 못해 결정은 유지했습니다. tree_vote_std와 학습 특징 범위를 추가했습니다. 이는 보정된 고장 확률이나 신뢰구간이 아닙니다. 범위 경고 때문에 표본을 제외하지 않았습니다.</p>'
    body+=table(['자료','학습 범위 경고 비율'],[[label,pct(strata[name]['support_warning_fraction'])] for name,label in [('filter_original_test','원래 Test'),('filter_reused_suffix','후반 관측')]])
    body+='<h2>새로 확보한 실측 자료 · 진단 정확도와 구분</h2>'+table(['자료','확보·확인 결과','평가 한계'],[
        ['독립 R290 수액기 히트펌프',f"{new['sessions']}세션 / {new['rows']}개 평균 관측, COP·과냉도 계산 일치 확인",'충전량 시험. EF 정답·명목 열수요·시간 이력이 없어 고장 정확도 미평가. 학습·보정·선택에 사용하지 않음.'],
        ['RO 이전 미사용 파형 실험',f"{sum(x['rows'] for x in ro['files']):,}행, 압력 순서 검사 통과{sum(x['pressure_order_ok'] for x in ro['files'])}행",'같은 장치의 새 관측. 시뮬레이션 파형을 사용한 실제 실험. 고장 정답 없음.']])
    body+='<p>새 히트펌프 자료는 제공 파생 값과의 단위·산술 일치만 확인했습니다. 같은 센서 값에서 유도된 지표이므로 독립 센서 정확도 검증이 아닙니다. 전기적Hz를 기계적 회전수로 바꾸거나 평균 행에 가짜 시간 축을 만들지 않았습니다. 새 자료의 고장 정확도·검출률·오경보율은null입니다.</p>'
    body+='<p>RO 설명과 공정도에서도 압력 오프셋·고도·기준압 보정값은 확정하지 못했습니다. 열 이름을 바꾸거나 압력을 임의로 더하지 않고 현재 제한을 유지했습니다.</p>'
    body+='<h2>검증·재현</h2><p>회귀시험240개와 외부 저장소 연동7개 통과. 독립 감사는 원본 정답·분할·혼동행렬·기존 정책 일치·후보 소스 스냅샷·경보 구간·지연을 확인하고 EWMA/CUSUM 유효5775행을 재계산했습니다.</p><p><a href="results.json">최종 결과</a> · <a href="independent_audit.json">독립 감사</a> · <a href="event_comparison.json">경보 구간·좌측 검열</a> · <a href="stratified_comparison.json">조건별 분석</a> · <a href="../diagnostic_gap_analysis/new_independent_physical_validation.json">새 독립 자료 계산 확인</a> · <a href="../diagnostic_gap_analysis/ro_new_quality.json">새 RO 품질 검사</a></p>'
    page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>설비 진단 후속 분석</title><style>body{font-family:system-ui,sans-serif;max-width:1400px;margin:32px auto;padding:0 24px;color:#172638;background:#fafbfd;line-height:1.65}h1{font-size:28px}h2{margin-top:32px}.scroll{overflow:auto}table{border-collapse:collapse;background:white;width:100%;font-size:14px}td,th{border:1px solid #c9d3df;padding:10px;text-align:left}th{background:#eaf1f8}a{color:#1260ac}</style><body>'+body+'</body></html>'
    (OUT/'report.html').write_text(page,encoding='utf-8');print(OUT/'report.html')
if __name__=='__main__':main()
