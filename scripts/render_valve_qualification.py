from html import escape
import hashlib
import json
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'qualification'
def main():
    r=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    p=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    audit=json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest()
    def table(head,rows):
        return '<table><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in head)+'</tr>'+''.join(
            '<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    def pct(x):return '미산출' if x is None else f'{x*100:.6f}%'
    def metric_table(cohort):
        return table(['정책','정확도','검출률','오경보율','판단률','FP','TP','FN'],[
            [key,*[pct(m[k]) for k in ('accuracy_valid','recall_valid','false_positive_rate_valid','coverage')],m['FP'],m['TP'],m['FN']]
            for key,m in r['comparison'][cohort].items()])
    checks=[]
    for key,d in r['decisions'].items():
        checks.append([key,'통과' if d['passes_project_monitoring_gates'] else '미통과',d['new_background_alarm_episodes'],
            f"{d['normal_alarm_episodes_per_24h']:.4f}",', '.join(k for k,v in d['checks'].items() if not v) or '없음'])
    file_rows=[]
    for f in r['files']:
        a=f['policies']['baseline'];b=f['policies']['sustained']
        file_rows.append([f['cohort'],f['date'],f['asset'],pct(a['metrics']['false_positive_rate_valid']),
            pct(b['metrics']['false_positive_rate_valid']),a['normal_alarm_episodes'],b['normal_alarm_episodes']])
    events=[[e['policy'],e['asset'],e['date'],e['start'],e['end'],e['detected'],e['delay_s']] for e in r['events']]
    html='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>밸브 지속 추종 감시 검증</title>
<style>body{font:16px/1.65 system-ui;max-width:1400px;margin:30px auto;padding:20px;color:#193149}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #c6d4df;padding:9px;text-align:left}th{background:#eaf1f7}pre{white-space:pre-wrap;overflow-wrap:anywhere}.note{background:#fff2d6;padding:16px}</style>
<h1>밸브 지속 추종 불량 감시: 실제 자료 기준 통과</h1><p>정상 학습·보정된 지연/오차 한계를 유지하고 경보 지속시간만 3→10초로 변경했습니다. 새 날짜 자료를 읽기 전에 정책·합격 기준을 동결했고 이후 조정하지 않았습니다.</p>
<p class="note">사용 범위는 DAMADICS A1/A3의 지속적인 명령–위치 추종 편차 감시입니다. 새 정상 배경은 17일×2개 밸브이지만 고장 6건은 과거 개발 자료 재생입니다. 새 독립 고장 시험은 0건이며 다른 현장에 대한 검증이나 외부 인증을 주장하지 않습니다.</p>
<h2>프로젝트 감시 기준</h2>'''
    html+=table(['정책','종합 판정','새 배경 경보 구간 수','유효 정상 24시간당 경보 구간','미통과 항목'],checks)
    html+='<h2>새 실제 정상 배경: 2,937,600행</h2><p>알려진 비대상 고장 구간을 제외한 유효 관측은 약 815.55시간입니다. 문서상 인위적 대상 고장이 없는 배경이며 정비 인증 정상은 아닙니다. 대상 고장이 없어 새 자료의 검출률은 미산출입니다.</p>'+metric_table('new_background')
    html+='<h2>기존 고장 자료 재생</h2><p>고장 사건 6건은 양쪽 모두 검출했습니다. 지연은 7~11초→14~18초, 고장 표본 검출률은 91.16→85.16%입니다. 경보 횟수를 줄이는 대가로 짧은 이상과 고장 초반 표본의 검출이 감소합니다.</p>'+metric_table('historical_replay')
    html+='<h2>고정 합격 기준과 설정</h2><pre>'+escape(json.dumps({'gates':p['gates'],'configurations':p['configurations']},indent=2))+'</pre>'
    html+='<h2>고장 사건별 검출·지연</h2>'+table(['정책','밸브','날짜','시작 초','끝 초','검출','지연 초'],events)
    html+='<h2>전체 날짜·밸브별 결과</h2>'+table(['구분','날짜','밸브','기존 오경보율','개선 오경보율','기존 경보 구간','개선 경보 구간'],file_rows)
    html+='<h2>실행·검증 자료</h2><p>configs/의 두 JSON은 지정 밸브의 0~1 정규화 명령·위치를 입력하는 실행 설정입니다. 독립 CSV 재집계와 두 프로파일의 합성 CSV→별도 CLI→JSON 연결 시험을 통과했습니다.</p><p><a href="../../docs/VALVE_MONITOR_QUALIFICATION.md">범위·사용법·새 자료 조사·한계</a> · <a href="configs/A1_persistent_tracking.json">A1 설정</a> · <a href="configs/A3_persistent_tracking.json">A3 설정</a></p><ul>'
    html+=''.join('<li>'+escape(v)+'</li>' for v in r['limitations'])+'</ul></html>'
    (OUT/'report.html').write_text(html,encoding='utf-8')
    bundle=OUT/'valve_monitor_profiles.zip'
    sources=[OUT/'report.html',OUT/'results.json',OUT/'frozen_protocol.json',OUT/'independent_audit.json',
        *sorted((OUT/'configs').glob('*.json')),OUT/'smoke'/'results.json',ROOT/'docs'/'VALVE_MONITOR_QUALIFICATION.md',
        ROOT/'scripts'/'qualify_valve_monitor.py',ROOT/'scripts'/'audit_valve_qualification.py',Path(__file__)]
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
        for source in sources:z.write(source,source.relative_to(ROOT).as_posix())
    manifest={'schema':'equipment-diagnostics.valve-monitor-profile-bundle.v1','engine_version':r['version'],
        'bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),'sources':{str(s.relative_to(ROOT)):hashlib.sha256(s.read_bytes()).hexdigest() for s in sources},
        'project_monitoring_gates_passed':r['decisions']['sustained']['passes_project_monitoring_gates'],
        'new_independent_positive_tests':0,'scope':'Persistent command-position tracking; observed DAMADICS A1/A3 scope, not new-site qualification.'}
    (OUT/'bundle_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Rendered report and profile bundle',bundle)
if __name__=='__main__':main()
