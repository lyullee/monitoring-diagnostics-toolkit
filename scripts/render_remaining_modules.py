from html import escape
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'remaining_modules'
def main():
    r=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    ch=json.loads((OUT/'chiller_attribution.json').read_text(encoding='utf-8'))
    audit=json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'));assert audit['successful']
    def table(head,rows):
        return '<table><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in head)+'</tr>'+''.join(
            '<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    def pct(v):return '—' if v is None else f'{100*v:.2f}%'
    names={'heat':'열교환기','ro':'RO','column':'증류탑','steam_trap':'스팀트랩','vaporizer':'기화기 저온 한계'}
    cols=('accuracy_valid','recall_valid','false_positive_rate_valid','coverage','fault_detection_all_eligible')
    head=['모듈·설정','정확도','검출률','오경보율','판단률','전체 대상 고장 검출률']
    rows=[];common=[]
    for kind,policies in r['comparison'].items():
        for k,v in policies.items():
            if 'metrics' not in v:rows.append([names[kind]+' '+k,'실행 불가: 외부 예측값 없음','—','—','—','—']);continue
            rows.append([names[kind]+' '+k,*[pct(v['metrics'][c]) for c in cols]])
            if 'common_metrics' in v:common.append([names[kind]+' '+k,*[pct(v['common_metrics'][c]) for c in cols]])
    status=[['4','열교환기','유량별 정상 열저항·선택적 유량 과도 제외','시뮬레이션 검증'],
        ['5','RO','NDP·온도 보정 입력 계산','기존의 올바른 외부 보정과 일치'],
        ['6','냉동기','동결 모델 오경보 채널 기여','운전정책·새 독립 자료 필요'],
        ['7','기화기','정상 예측기 없는 출구 저온 한계','전열·착상 예측은 보류'],
        ['8','스팀트랩','공급 시작·재개 준비 구간','판단률 감소·시동 고장 지연 가능'],
        ['9','증류탑','정상 부하–차압 지수 학습','실제 습식 탑·범람 모델 아님'],
        ['10','보일러','관측기에 필요한 입력 조건 정리','총재고 관측기는 설비 정보 필요']]
    attribution=[]
    for stage,counts in ch['dominant_channel_counts'].items():
        total=ch['normal_counts'][stage]['FP'];oil=counts.get('oil_feed_pressure',0)
        attribution.append([stage,total,oil,pct(oil/total)])
    html='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>4~10순위 후속 개선</title>
<style>body{font:16px/1.65 system-ui;max-width:1400px;margin:30px auto;padding:20px;color:#193149}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #c6d4df;padding:9px;text-align:left}th{background:#eaf1f7}pre{white-space:pre-wrap;overflow-wrap:anywhere}.note{background:#fff2d6;padding:16px}</style>
<h1>4~10순위 후속 개선 · v0.8.0</h1><p class="note">아래 진단 비교는 지정된 물리식·경험식·경계값 시나리오의 시뮬레이션입니다. 새로운 실제 설비 정확도를 확보한 결과가 아닙니다. 100%는 해당 시험에서만의 결과입니다.</p>'''
    html+=table(['순위','모듈','완료 내용','검증·보류 조건'],status)
    html+='''<h2>시뮬레이션 비교</h2><p>정상 학습·정상 보정·정상 평가·고장 평가 시드를 분리하고 모델·정상 q99 임계값을 평가 전에 동결했습니다. 준비 구간 UNKNOWN을 정상으로 세지 않습니다. 학습 없는 한계 감시는 별도로 표시합니다.</p>'''+table(head,rows)
    html+='''<p>RO는 기존 외부 보정이 올바른 경우와 같아야 합니다. 기화기는 온도 한계 위/아래 기능 시험입니다. 스팀트랩은 시동 60초를 판단 보류해 전체 판단률과 전체 대상 고장 검출률이 90%로 낮아졌습니다. 열교환기·증류탑은 시험 정상 관계와 진단 모델 구조가 일치하므로 실제 설비에서 동일 성능을 기대하면 안 됩니다.</p>
<h2>동일 표본 비교: 전후 모두 판단한 구간</h2>'''+table(head,common)
    html+='''<h2>실제 실험 자료 재분석: 냉동기 오경보의 최대 점수 채널</h2><p>v0.6의 동결 기준·임계값을 변경하지 않고 정상 12파일을 다시 계산했습니다. 이전 정상 FP/판단 표본 수를 정확히 재현했습니다. 새 진단 성능을 주장하지 않습니다.</p>'''
    html+=table(['단계','오경보 표본','오일 공급압력 최대 표본','비중'],attribution)
    html+='''<p>점수 기여는 물리적 원인 확정이 아닙니다. 정상 운전의 오일 회로 압력 제어 상태·설정값·모드 정보와 새 평가 자료가 필요합니다. 평가 파일명을 이용해 운전모드를 만들거나 문제 채널을 제거하지 않았습니다.</p>
<h2>추가 구현에 필요한 조건</h2><p>보일러: 드럼/회로 용적·수위 체적 관계, 동기화된 압력/온도/유량, 보이드·swell/shrink 모델, 독립 총재고 검증 자료. 기화기 정상 전열: 기화기 형식·전열면·유체 압력·열원 상태와 운전 자료. 스팀트랩 분류: 정상 배출/누설의 형식별 실제 라벨 자료.</p>
<h2>검증</h2><p>비통합 시험 210개·외부 저장소 실제 객체 연동 7개 통과. CSV 독립 재집계, 자료 분리, 소스·동결 해시, 모델 불변성을 확인했습니다.</p><ul>'''
    html+=''.join('<li>'+escape(v)+'</li>' for v in r['limitations'])+'</ul>'
    html+='<p><a href="../../docs/REMAINING_MODULES.md">계산식·입력 역할·사용법·근거·재현 명령</a></p>'
    html+='<h2>파일별 시나리오 결과</h2><pre>'+escape(json.dumps(r['scenarios'],indent=2))+'</pre></html>'
    (OUT/'report.html').write_text(html,encoding='utf-8');print('Rendered',OUT/'report.html')
if __name__=='__main__':main()
