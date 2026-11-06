"""Run independent physical checks and emit auditable JSON, JUnit and HTML evidence."""
from datetime import datetime, timezone
import hashlib
from html import escape
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from equipment_diagnostics import __version__

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"outputs"/"physics_verification"
SCOPE = {
    "mass_balance": ("탱크 질량수지", "해석해·수렴성", "총 질량 측정, 선형 유량·구간 내 일정 미지 손실 가정"),
    "boiler_mass_balance": ("보일러 질량수지", "해석해", "증기·물 총 재고량이 입력됨; 드럼 수위 추정은 검증 범위 밖"),
    "heat_exchanger": ("열교환기", "독립 ε–NTU 모델", "정상상태·일정 비열·향류, 단상; 다른 배치의 LMTD 보정계수 미구현"),
    "hydraulic_resistance": ("필터·배관", "Darcy–Weisbach 및 유동 극한", "일정 점도, 유동 영역별 지수 지정; 전이유동 미검증"),
    "vaporizer": ("기화기", "CoolProp 포화 물성", "잠열·엔탈피 기준 불변성; 외부 온도 예측모델·건도 추정 미검증"),
    "ro_membrane": ("RO 막", "용해–확산 모델", "양의 순구동압, TCF=A_ref/A(T); 염 제거율 미구현"),
    "valve_tracking": ("밸브", "순수 지연 해석해 / 제한 확인", "1차 관성 정상 응답도 오경보 가능; 스틱션 식별 아님"),
    "column_hydraulics": ("탑 압력손실", "부분: 단상 유동 극한", "습식 상관식·액체 지수·플러딩 판별은 물리 검증 미완료"),
    "steam_trap": ("스팀트랩", "부분: 열응답·규칙 논리", "음향–고장 구성식 없음; 시동 제외·현장 임계값 보정 필요"),
    "chiller_performance": ("냉동기", "CoolProp 압축 냉동사이클", "정상상태 수측 일정 비열; Carnot 제한은 등온 가정 명시 시만 선택 적용"),
}


def classify(name):
    if "inventory" in name:
        return "boiler_mass_balance" if "BoilerBalance" in name else "mass_balance"
    for keyword, kind in (("heat_exchanger", "heat_exchanger"), ("hydraulic", "hydraulic_resistance"),
                          ("vaporizer", "vaporizer"), ("_ro_", "ro_membrane"),
                          ("valve", "valve_tracking"), ("column", "column_hydraulics"),
                          ("steam_trap", "steam_trap"), ("chiller", "chiller_performance")):
        if keyword in name:
            return kind
    raise ValueError("Unclassified physics test: "+name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/"tests.xml").unlink(missing_ok=True)
    command = [sys.executable, "-m", "pytest", "-m", "physics", "tests/physics", "-q",
               "--junitxml="+str(OUT/"tests.xml"), "-o", "junit_family=legacy"]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (OUT/"pytest.txt").write_text(run.stdout+run.stderr, encoding="utf-8")
    cases = []
    if (OUT/"tests.xml").exists():
        for item in ET.parse(OUT/"tests.xml").iter("testcase"):
            name = item.attrib["name"]
            status = ("failed" if item.find("failure") is not None or item.find("error") is not None
                      else "skipped" if item.find("skipped") is not None else "passed")
            cases.append({"name": name, "module": classify(name), "status": status,
                          "properties": {p.attrib["name"]: p.attrib["value"]
                                         for p in item.findall("properties/property")}})
    modules = []
    for kind, (label, method, limit) in SCOPE.items():
        selected = [c for c in cases if c["module"] == kind]
        modules.append({"kind": kind, "label": label, "method": method, "limit": limit,
            "tests": len(selected), "passed": sum(c["status"] == "passed" for c in selected),
            "complete": bool(selected) and all(c["status"] == "passed" for c in selected)})
    result = {"schema": "equipment-diagnostics.physics-verification.v1",
        "utc": datetime.now(timezone.utc).isoformat(), "version": __version__, "python": sys.version,
        "libraries": {p: importlib.metadata.version(p) for p in ("numpy", "pytest", "ht", "fluids", "CoolProp")},
        "scope": "Computational verification of declared models, not experimental or field validation. Passing counterexample tests documents model limitations.",
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for base in (ROOT/"src", ROOT/"tests"/"physics") for p in sorted(base.rglob("*.py"))},
        "passed": sum(c["status"] == "passed" for c in cases), "tests": len(cases),
        "successful": run.returncode == 0 and all(m["complete"] for m in modules),
        "modules": modules, "cases": cases}
    (OUT/"results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = "".join("<tr>"+"".join("<td>"+escape(str(v))+"</td>" for v in
        (m["label"], m["method"], f'{m["passed"]}/{m["tests"]}', m["limit"]))+"</tr>" for m in modules)
    details = "".join("<details><summary>"+escape(c["name"]+" — "+c["status"])+"</summary><pre>"+
        escape(json.dumps(c["properties"], ensure_ascii=False, indent=2))+"</pre></details>" for c in cases)
    html = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>설비 진단 물리 검증</title>
<style>body{{font:16px/1.65 system-ui;max-width:1250px;margin:40px auto;padding:20px;color:#1b2935}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border:1px solid #cad4df;text-align:left}}
th{{background:#eaf1f8}}details{{margin:12px 0}}pre{{white-space:pre-wrap}}.note{{background:#fff2d5;padding:18px}}</style>
<h1>설비 진단 모듈 물리·수치 검증</h1><p>{escape(result["utc"])} · {result["passed"]}/{result["tests"]} tests passed</p>
<p class="note">이 결과는 명시한 물리 모델과 구현의 일치 검증입니다. 현장·실험 데이터에 의한 진단 정확도 검증은 수행하지 않았습니다.
탑은 단상 극한만, 스팀트랩은 열응답과 규칙 논리만 확인했습니다. 정상 시동·정상 밸브 관성의 오경보 반례도 포함하며, 테스트 통과가 해당 한계의 해소를 뜻하지 않습니다.</p>
<table><tr><th>모듈</th><th>비교 기준</th><th>통과</th><th>적용 범위 / 남은 검증</th></tr>{rows}</table>
<h2>기준 자료</h2><p><a href="https://ht.readthedocs.io/en/latest/ht.hx.html#ht.hx.effectiveness_from_NTU">ht ε–NTU</a> ·
<a href="https://fluids.readthedocs.io/fluids.friction.html">fluids 마찰계수</a> ·
<a href="https://coolprop.org/coolprop/HighLevelAPI.html">CoolProp 물성 API</a> ·
<a href="https://watertap.readthedocs.io/en/stable/technical_reference/unit_models/reverse_osmosis_0D.html">WaterTAP RO 기준식</a> ·
<a href="https://www.tlv.com/en-ae/steam-info/steam-theory/trap-considerations/steam-trap-test">TLV 스팀트랩 시험</a></p>
<p>ht·fluids·CoolProp은 실제 계산에 사용했습니다. WaterTAP은 문서 기준식만 참고했으며 solver는 실행하지 않았습니다.
스팀트랩 상용 알고리즘의 정확도를 재현한 결과가 아닙니다.</p>
<h2>환경</h2><pre>{escape(json.dumps(result["libraries"], indent=2))}</pre>
<h2>개별 검증 결과 및 수치 오차</h2>{details}</html>'''
    (OUT/"report.html").write_text(html, encoding="utf-8")
    print(run.stdout)
    print(json.dumps({k: result[k] for k in ("passed", "tests", "successful")}, indent=2))
    return 0 if result["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
