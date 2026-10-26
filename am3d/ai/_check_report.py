"""Stable deterministic-check report entries."""

def _check(report: dict, code: str, ok: bool, summary: str, details=None):
    stable_code = str(code)[:64]
    item = {"id": stable_code, "code": stable_code,
            "status": "passed" if ok else "failed",
            "severity": "info" if ok else "error",
            "path": (details.get("path") if isinstance(details, dict)
                     and isinstance(details.get("path"), str) else None),
            "summary": str(summary)[:512],
            "details": details if details is not None else {}}
    report["checks"].append(item)
    return ok
