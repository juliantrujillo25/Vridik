#!/usr/bin/env python3
"""
Vridik — scripts/check_pass_ratio.py
Sprint S3: falla el job de CI si menos del 90% de los tests pasaron.

pytest no tiene un umbral de "porcentaje de tests verdes" nativo (sí tiene
cov-fail-under para cobertura, que ya se usa en S3 para el 50%/60% de
cobertura). Este script cierra ese hueco: lee el reporte JUnit XML que
genera `pytest --junitxml=...` y calcula:

    ratio = passed / (passed + failed + errored)

Los tests marcados 'skipped' (por ejemplo, los que dependen de `db` cuando
no hay TEST_DATABASE_URL) no cuentan ni a favor ni en contra del ratio —
saltarse un test no debe poder inflar artificialmente el porcentaje de éxito.

USO:
    python scripts/check_pass_ratio.py --junit-xml reports/junit.xml --threshold 0.90
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET


def calcular_ratio(junit_path: str) -> tuple[float, dict]:
    tree = ET.parse(junit_path)
    root = tree.getroot()

    # El root puede ser <testsuites> (contenedor) o <testsuite> directo,
    # según la versión de pytest.
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    total = failed = errored = skipped = 0
    for suite in suites:
        total += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0))
        errored += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))

    considerados = total - skipped
    passed = considerados - failed - errored
    ratio = (passed / considerados) if considerados > 0 else 0.0

    resumen = {
        "total": total,
        "skipped": skipped,
        "considerados": considerados,
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "ratio": ratio,
    }
    return ratio, resumen


def main() -> int:
    parser = argparse.ArgumentParser(description="Vridik — umbral de tests verdes para CI")
    parser.add_argument("--junit-xml", required=True, help="Ruta al reporte JUnit XML de pytest")
    parser.add_argument("--threshold", type=float, default=0.90, help="Umbral mínimo (0.0-1.0), default 0.90")
    args = parser.parse_args()

    try:
        ratio, resumen = calcular_ratio(args.junit_xml)
    except FileNotFoundError:
        print(f"ERROR: no se encontró el reporte JUnit en {args.junit_xml}", file=sys.stderr)
        return 1
    except ET.ParseError as exc:
        print(f"ERROR: reporte JUnit inválido ({exc})", file=sys.stderr)
        return 1

    print(
        f"Vridik CI — resultados: {resumen['passed']} passed, {resumen['failed']} failed, "
        f"{resumen['errored']} errored, {resumen['skipped']} skipped "
        f"(de {resumen['total']} totales, {resumen['considerados']} considerados) "
        f"-> ratio={ratio:.1%}"
    )

    if ratio < args.threshold:
        print(f"FALLO: ratio de tests verdes {ratio:.1%} por debajo del umbral {args.threshold:.0%}", file=sys.stderr)
        return 1

    print(f"OK: ratio de tests verdes {ratio:.1%} cumple el umbral {args.threshold:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
