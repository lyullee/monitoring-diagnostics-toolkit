"""Execute the user's six verification stages, without treating skips as passes."""
from datetime import datetime, timezone
import hashlib
from html import escape
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from equipment_diagnostics import __version__

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"outputs"/"staged_verification"
NEW = "tests/test_six_stages.py"
STAGES = [
    ("input", "입력 검사", [( [NEW], "test_input_")],
     "10종의 단위 누락·단위 불일치·NaN과 자료 크기·중복 이름·마스크·시계·빈 식별자·잘못된 설정값",
     "구조·단위 오류는 ValueError, 결측 측정은 UNKNOWN이며 경보 없음",
     "잘못된 입력의 거부와 결측 처리 계약. 센서 교정 정확도는 확인하지 않음"),
    ("formula", "계산식 확인", [([NEW], "test_formula_")],
     "손계산 가능한 10종 예제: 손실률 0.2 kg/s, UA 3344 W/K, 기준 차압 100 Pa, 열량 800 W, 투수성 1e-11, 위치 오차 0.1, 탑 기준 차압 100 Pa, 트랩 점수 1.5, COP 2.09",
     "모든 유효 표본이 기대값과 상대오차 1e-12 이내 일치",
     "주요 계산식의 수치 일치. 현장 진단 정확도나 모든 물리 현상의 재현을 뜻하지 않음"),
    ("extreme", "극단적인 값 확인", [([NEW], "test_extreme_")],
     "10종의 1e308 수준 값 또는 물리 경계 위반, 4종의 양수→0 언더플로, 1e16 s 시계의 0.1 s 창, 점수 1과 바로 위 실수",
     "범위 밖·수치 소실은 UNKNOWN·경보 없음·JSON null, 점수 1은 경보 없음·초과는 경보",
     "선택한 경계와 부동소수점 실패의 처리. 임의의 모든 수 크기에서 정밀도를 보장하지 않음"),
    ("connection", "모듈 연결 확인", [([NEW], "test_connection_"), (["tests/test_integrations.py"], None)],
     "10종의 기준 JSON 저장·복원→분할 점수화→결과 JSON, 실제 process-monitoring·h2physics·pipeline-safety 객체 연결",
     "배치/분할 점수·마스크·경보 일치, 단위·설비·시계·출처 보존 및 충돌 거부",
     "명시된 객체·직렬화·모니터 경로의 연결. 외부 solver 전체나 rotorvibe 어댑터는 미검증"),
    ("regression", "기존 기능 재확인", [(["tests/test_diagnostics.py", "tests/test_review_additions.py",
         "tests/test_cli.py", "tests/physics/test_physics.py"], None)],
     "수정 전부터 있던 핵심 38개와 독립 물리·수치 40개를 수정 후 다시 실행",
     "기존 78개 모두 통과·생략 없음",
     "기존 시험이 다루는 동작의 유지. 시험 밖의 모든 기능이 증명되는 것은 아님"),
    ("end_to_end", "전체 계산 실행", [([NEW], "test_end_to_end_")],
     "각각 새 Python 프로세스에서 CSV·설정 입력→정상 기준 학습→10종 계산→최종 JSON. 정상·이상·전체 결측·단위 오류 4조건",
     "정상 no_alarm, 이상 suspected_anomaly, 결측 insufficient_data, 잘못된 단위 종료코드 2·출력 없음",
     "파일 입력부터 최종 결과까지의 소프트웨어 실행. 합성 신호이며 결합 플랜트 시뮬레이션·현장 실증은 아님"),
]


def parse_cases(path):
    if not path.is_file():
        return []
    cases = []
    for c in ET.parse(path).iter("testcase"):
        failure = c.find("failure")
        if failure is None: failure = c.find("error")
        status = "failed" if failure is not None else "skipped" if c.find("skipped") is not None else "passed"
        cases.append({"id":c.attrib.get("classname", "")+"::"+c.attrib.get("name", ""),
            "status":status, "seconds":float(c.attrib.get("time",0)),
            "properties":{p.attrib["name"]:p.attrib["value"] for p in c.findall("properties/property")},
            "failure":None if failure is None else failure.attrib.get("message", "")})
    return cases


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    env = {**os.environ,"PYTHONUTF8":"1"}
    stages=[]
    for key,label,groups,inputs,expected,meaning in STAGES:
        cases=[]; commands=[]; exits=[]
        for i,(paths,selection) in enumerate(groups):
            xml = OUT/f"{key}_{i+1}.xml"; xml.unlink(missing_ok=True)
            cmd=[sys.executable,"-m","pytest",*paths,"-q","-o","addopts=",
                 "-o","junit_family=legacy","--junitxml="+str(xml)]
            if selection: cmd.extend(["-k",selection])
            run=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding="utf-8",env=env,errors="replace")
            (OUT/f"{key}_{i+1}.txt").write_text(run.stdout+run.stderr,encoding="utf-8")
            cases.extend(parse_cases(xml)); commands.append(cmd); exits.append(run.returncode)
        passed=sum(c["status"]=="passed" for c in cases)
        good=bool(cases) and passed==len(cases) and all(code==0 for code in exits)
        stages.append({"key":key,"label":label,"inputs":inputs,"expected":expected,"meaning":meaning,
            "tests":len(cases),"passed":passed,"successful":good,"commands":commands,"exit_codes":exits,"cases":cases})
        print(f"{key}: {passed}/{len(cases)}; successful={good}",flush=True)
    revisions={}
    upstream=Path(env.get("EQUIPMENT_UPSTREAM_ROOT",ROOT/".upstream"))
    for name in ("process-monitoring-toolkit","h2physics","pipeline-safety-toolkit","rotorvibe"):
        p=upstream/name
        if p.is_dir():
            r=subprocess.run(["git","rev-parse","HEAD"],cwd=p,capture_output=True,text=True)
            if r.returncode==0: revisions[name]=r.stdout.strip()
    versions={}
    for p in ("numpy","pytest","ht","fluids","CoolProp","scipy","pandas","pydantic","pint"):
        try: versions[p]=importlib.metadata.version(p)
        except importlib.metadata.PackageNotFoundError: versions[p]="unavailable"
    before=parse_cases(OUT/"before_fixes.xml")
    failed_before=[c["id"] for c in before if c["status"]=="failed"]
    final={c["id"]:c["status"] for s in stages for c in s["cases"]}
    source_files=[ROOT/"pyproject.toml",Path(__file__)]+list((ROOT/"src").rglob("*.py"))+list((ROOT/"tests").rglob("*.py"))
    result={"schema":"equipment-diagnostics.six-stages.v1","version":__version__,
        "utc":datetime.now(timezone.utc).isoformat(),"python":sys.version,"dependencies":versions,
        "upstream_revisions":revisions,"rotorvibe":"Inspected checkout only; no adapter test claimed.",
        "source_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_files)},
        "before_fixes":{"tests":len(before),"failed":failed_before,
            "now_passed":[name for name in failed_before if final.get(name)=="passed"],
            "source_evidence":"before_source.json" if (OUT/"before_source.json").is_file() else None},
        "scope":"Six software verification stages on synthetic/numerical inputs; no experimental or field diagnostic accuracy claim.",
        "tests":sum(s["tests"] for s in stages),"passed":sum(s["passed"] for s in stages),
        "unique_test_ids":len(final),"successful":all(s["successful"] for s in stages),"stages":stages}
    (OUT/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    rows="".join("<tr>"+"".join("<td>"+escape(str(v))+"</td>" for v in
        (s["label"],s["inputs"],s["expected"],f'{s["passed"]}/{s["tests"]}',s["meaning"]))+"</tr>" for s in stages)
    details=""
    for s in stages:
        details+="<h2>"+escape(s["label"])+"</h2>"
        for c in s["cases"]:
            details+="<details><summary>"+escape(c["id"]+" — "+c["status"])+"</summary><pre>"+escape(json.dumps(c,ensure_ascii=False,indent=2))+"</pre></details>"
    html=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>6단계 검증 결과</title>
<style>body{{font:16px/1.6 system-ui;max-width:1450px;margin:30px auto;padding:20px;color:#152c40}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #c7d3de;padding:12px;text-align:left;vertical-align:top}}
th{{background:#e9f0f7}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}details{{margin:8px 0}}.note{{padding:16px;background:#fff3d9}}</style>
<h1>6단계 검증 결과 — v{escape(__version__)}</h1><p>{escape(result["utc"])} · {result["passed"]}/{result["tests"]} 통과 · 중복 없는 시험 {result["unique_test_ids"]}개</p>
<p class="note">입력 거부, 계산식, 수치 경계, 모듈 연결, 회귀, 전체 실행을 구분했습니다. 입력 거부와 UNKNOWN은 해당 시험의 기대 동작입니다.
시험 통과를 현장 진단 정확도로 해석하지 않습니다. 탑 습식 운전·스팀트랩 음향 판별·밸브 관성 모델의 기존 한계는 남아 있습니다.</p>
<table><tr><th>시험 종류</th><th>실제로 넣은 입력·확인 내용</th><th>기대 결과</th><th>통과</th><th>이 시험으로 알 수 있는 범위</th></tr>{rows}</table>
<h2>보완 전·후</h2><p>보완 전 실패 {len(failed_before)}개, 동일 시험의 현재 통과 {len(result["before_fixes"]["now_passed"])}개.</p>
<pre>{escape(json.dumps(result["before_fixes"],ensure_ascii=False,indent=2))}</pre>
<h2>실행 환경</h2><pre>{escape(json.dumps(versions,indent=2))}</pre>{details}</html>'''
    (OUT/"report.html").write_text(html,encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("tests","passed","unique_test_ids","successful")}))
    return 0 if result["successful"] else 1


if __name__=="__main__":
    raise SystemExit(main())
