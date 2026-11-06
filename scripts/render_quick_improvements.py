"""Render measured/simulated results without merging evidence types."""
from html import escape
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'/'quick_improvements'

def main():
    plant=json.loads((OUT/'valve_results.json').read_text(encoding='utf-8'))
    physics=json.loads((OUT/'physics_results.json').read_text(encoding='utf-8'))
    audit=json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful']
    cols=('accuracy_valid','recall_valid','false_positive_rate_valid','coverage','coverage_all_rows')
    heads=['설정/시나리오','정확도','검출률','오경보율','대상 중 판단률','원본 전체 판단률']
    def pct(x): return '—' if x is None else f'{100*x:.3f}%'
    def table(rows,headers=heads):
        return '<table><tr>'+''.join('<th>'+escape(v)+'</th>' for v in headers)+'</tr>'+''.join(
            '<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    measured=[]; common=[]; simulations=[]
    for key,v in plant['comparison'].items():
        measured.append([key,*[pct(v['metrics'][c]) for c in cols]])
        common.append([key,*[pct(v['common_metrics'][c]) for c in cols]])
    for s in physics['scenarios']:
        for key,v in s['policies'].items(): simulations.append([s['scenario']+' '+key,*[pct(v['metrics'][c]) for c in cols]])
    priority=[['1','밸브','정상 1차 응답','구현·실제 자료 재평가'],['2','필터·배관','점성·관성 혼합 모델','구현·독립 시뮬레이션'],
        ['3','탱크','계측 오차 한계','구현·독립 시뮬레이션'],['4','열교환기','유량별 정상 UA','후속'],
        ['5','RO','장치별 NDP·온도 보정 연결','후속'],['6','냉동기','정상 모드/채널별 보정','후속'],
        ['7','기화기','정상 전열 예측기','자료·모델 필요'],['8','스팀트랩','형식/운전상태별 모델','라벨 자료 필요'],
        ['9','증류탑','내부 기액 부하·양상 모델','설비 정보 필요'],['10','보일러','총재고 관측기','열역학·계측 필요']]
    events=[]
    for e in plant['events']:
        events.append([e['policy'],e['asset'],e['date'],e['start'],e['end'],e['detected'],e['delay_s']])
    body='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>빠른 개선 우선순위와 검증</title>
<style>body{font:16px/1.65 system-ui;max-width:1400px;margin:30px auto;padding:20px;color:#193149}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #c6d4df;padding:9px;text-align:left}th{background:#eaf1f7}pre{white-space:pre-wrap;overflow-wrap:anywhere}.note{background:#fff2d6;padding:16px}</style>
<h1>빠른 개선 우선순위와 상위 3개 보완</h1><p>v0.7.0 · 추가 계측·모델·자료 부담에 따른 개선 순서입니다. 현장 정확도 순위가 아닙니다.</p>'''
    body+=table(priority,['순위','모듈','개선 내용','상태'])
    body+='''<p class="note">밸브 동특성 추가는 정상 관성 반례를 해결했지만 실제 자료에서는 검출률과 오경보가 함께 증가했습니다. 탱크 오차 한계는 오경보를 줄이는 대신 작은 누설을 놓칠 수 있습니다. 새 옵션을 기존 경보 설정에 자동 적용하지 않습니다.</p>
<h2>실제 공장: 밸브</h2><p>정상 학습 10/29, 정상 보정 11/01, 평가 11/08·09·17·20·21·22. 기존 두 밸브·6건 f16을 유지했습니다. 모든 모델·임계값은 평가 전에 동결했습니다. 이전에 본 평가 자료를 재사용한 개발 비교입니다.</p>'''+table(measured)
    body+='<h2>밸브 두 설정이 모두 판단한 동일 표본</h2>'+table(common)
    body+='<h2>밸브 고장 사건별 검출·최초 지연</h2>'+table(events,['설정','밸브','날짜','시작 초','종료 초','검출','지연 초'])
    body+='''<h2>독립 물리식 시뮬레이션: 차압·탱크</h2><p>차압은 외부 Ergun 함수로 생성하고 학습·보정·평가 시드를 분리했습니다. 탱크는 해석적 질량 보존과 명시한 절대 계측 오차를 사용했습니다. 이 수치는 실제 설비의 정확도나 오경보율이 아닙니다. 표본별 결과이며 사건 전체를 검출로 바꾸지 않았습니다.</p>'''+table(simulations)
    body+='<h2>선택된 밸브 설정</h2><pre>'+escape(json.dumps(plant['selected'],indent=2))+'</pre>'
    body+='<h2>검증·제한</h2><p>비통합 시험 194개, 기존 외부 객체 연동 시험 7개 통과. CSV 독립 집계·기존 밸브 혼동행렬 재현·자료 분리·동결 파일 및 소스 해시 확인.</p><ul>'
    body+=''.join('<li>'+escape(v)+'</li>' for v in [*plant['limitations'],*physics['limitations']])+'</ul>'
    body+='<p><a href="../../docs/QUICK_IMPROVEMENTS.md">계산식·입력·사용법·상세 설명</a></p></html>'
    (OUT/'report.html').write_text(body,encoding='utf-8')
    print('Rendered',OUT/'report.html')

if __name__=='__main__': main()
