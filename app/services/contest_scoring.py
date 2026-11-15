"""Score contest submissions from accepted test-case counts."""
import re

_TESTCASE_SUMMARY = re.compile(r"通过测试(?:用例|点)数\s*[:：]\s*(\d+)\s*/\s*(\d+)")


def submission_score(points: int, status: str, detail: str) -> int:
    """Return full or ceiling-rounded proportional points for one submission."""
    if status == "Accepted":
        return points
    match = _TESTCASE_SUMMARY.search(detail)
    if not match:
        return 0
    passed, total = map(int, match.groups())
    if total < 1 or passed > total:
        return 0
    return (points * passed + total - 1) // total
