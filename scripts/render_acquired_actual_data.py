from html import escape
import hashlib
import json
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'actual_data_acquisition'
def main():
    r=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
    a=json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'))
    assert a['successful'] and hashlib.sha256((OUT/'inventory.json').read_bytes()).hexdigest()==a['inventory_sha256']
    rows=[]
    for d in r['datasets']:
        qty={'filter_hse':'100시험 기록 / 78,834행','ro_nrel':'28 CSV / 203,643행','coil_frost':'8시트 / 463관측행',
            'tank_three':'25센서 파일 / 3개 접두 기록군','heatpump_propane':'10데이터 시트 / 주 계측 8,363행'}[d['id']]
        use={'filter_hse':'차압 모듈 최우선 후보. 유량 절대단위·검열 처리 확인 필요',
            'ro_nrel':'정상 보정·동적 응답 후보. 오염 고장 정답 없음',
            'coil_frost':'습공기·착상 모델 확장 필요. 기존 건식 단상 UA에 직접 적용 불가',
            'tank_three':'누설 시점·액위 모델 후보. 유량계 정확도 한계',
            'heatpump_propane':'다른 기계의 실제 고장. 냉매측 어댑터·독립 시각 정렬 필요'}[d['id']]
        link='<a href="'+escape(d['source'],quote=True)+'">'+escape(d['title'])+'</a>'
        rows.append([link,escape(qty),escape(use),escape(d['license'])])
    html='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>실제 관측 데이터 추가 확보</title>
<style>body{font:16px/1.65 system-ui;max-width:1400px;margin:30px auto;padding:20px;color:#193149}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #c6d4df;padding:9px;text-align:left}th{background:#eaf1f7}pre{white-space:pre-wrap;overflow-wrap:anywhere}.note{background:#fff2d6;padding:16px}</style>
<h1>실제 관측 데이터 5종 추가 확보</h1><p>2026-11-05 · 핵심 배포 원본 8파일, 19,090,736바이트. 읽기용 CSV 사본 83개. 기존 DAMADICS·RP1043 수집분과 별개입니다.</p>
<p class="note">자료 확보·형식·센서 호환성 점검 결과입니다. 아직 진단 모델의 학습·보정·평가나 정확도 계산을 하지 않았습니다. 정상 운전 자료를 고장 정답으로 바꾸거나 빠진 센서값을 임의 생성하지 않았습니다.</p>
<table><tr><th>실제 자료·출처</th><th>확보량</th><th>적용 판단</th><th>제작자 라이선스</th></tr>'''
    html+=''.join('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    html+='<h2>파일 위치</h2><p>research_support/public_data/acquisition_20261105/ 에 배포 원본과 tables/ 사본을 보관합니다. CSV 원본은 바이트 단위 동일 복사이며, Excel 편의용 사본은 원본과 구분합니다.</p>'
    html+='<h2>다음 적용 순서</h2><p>필터 열화 → RO 정상 보정/동적 응답 → 히트펌프 냉매측 어댑터 → 탱크 계측 검토 → 습식 코일 확장.</p>'
    html+='<h2>품질·호환성 확인</h2><ul><li>필터 Train/Test의 시험 ID는 각각 1부터 시작하므로 출처 분할과 ID를 함께 사용합니다. RUL은 입력으로 쓰지 않습니다.</li><li>탱크 Strict OOXML은 직접 XML로 읽고 원본을 고치지 않았습니다. 전압·펄스를 교정 없이 Pa·kg/s로 바꾸지 않았습니다.</li><li>습식 코일의 착상 형성률을 브라인 질량유량으로 매핑하지 않았습니다. Excel 시각과 단위 행 불일치도 기록했습니다.</li><li>히트펌프 주 측정과 과열도는 서로 다른 시각 열이므로 별도 CSV로 내보냈습니다. 행 번호로 결합하지 않았습니다.</li><li>원본·사본 SHA256, 압축파일 CRC, 제작자 제공 체크섬, CSV 행 수와 시험 수를 확인했습니다.</li></ul>'
    html+='<p><a href="../../docs/ACTUAL_DATA_ACQUISITION.md">상세 센서·단위·라벨·제약·재현 방법</a> · <a href="inventory.json">파일·열·결측값 목록</a> · <a href="download_manifest.json">다운로드 최종 목록</a> · <a href="independent_audit.json">독립 감사</a></p>'
    for d in r['datasets']:
        html+='<h2>'+escape(d['title'])+'</h2><ul>'+''.join('<li>'+escape(v)+'</li>' for v in d['limitations'])+'</ul>'
    html+='</html>';(OUT/'report.html').write_text(html,encoding='utf-8')
    files=[OUT/'report.html',OUT/'inventory.json',OUT/'download_manifest.json',OUT/'independent_audit.json',
        ROOT/'docs'/'ACTUAL_DATA_ACQUISITION.md',ROOT/'scripts'/'acquire_actual_datasets.py',
        ROOT/'scripts'/'inspect_acquired_actual_data.py',ROOT/'scripts'/'audit_acquired_actual_data.py',Path(__file__)]
    bundle=OUT/'data_catalog_and_tools.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,p.relative_to(ROOT).as_posix())
    (OUT/'bundle_manifest.json').write_text(json.dumps(dict(bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        raw_observations_included=False,files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}),indent=2),encoding='utf-8')
    print('Created report and metadata/tools bundle; raw observations remain in workspace.')
if __name__=='__main__':main()
