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


def ranked_rows(db, contest):
    """Use the contest rule and in-time submissions for both displayed and rewarded ranks."""
    problems = list(db.execute('SELECT id,points FROM problems WHERE contest_id=? ORDER BY id', (contest['id'],)))
    users = list(db.execute('''SELECT DISTINCT users.id,users.username FROM submissions
        JOIN users ON users.id=submissions.user_id JOIN problems ON problems.id=submissions.problem_id
        WHERE problems.contest_id=? AND users.is_admin=0
        AND submissions.created>=? AND submissions.created<=?''',
        (contest['id'], contest['starts'], contest['ends'])))
    rows = []
    for candidate in users:
        per_problem = []
        score = accepted = attempts = 0
        first_accept = None
        for problem in problems:
            submissions = list(db.execute('''SELECT status,created,detail FROM submissions
                WHERE user_id=? AND problem_id=? AND created>=? AND created<=? ORDER BY id''',
                (candidate['id'], problem['id'], contest['starts'], contest['ends'])))
            accepted_rows = [row for row in submissions if row['status'] == 'Accepted']
            solved = bool(accepted_rows)
            scored_submissions = [(submission_score(problem['points'], row['status'], row['detail']), row)
                                  for row in submissions]
            problem_score, best_submission = max(scored_submissions, key=lambda item: item[0], default=(0, None))
            testcase_match = re.search(r'通过测试(?:用例|点)数\s*[:：]\s*(\d+)\s*/\s*(\d+)', best_submission['detail']) if best_submission else None
            attempts += len(submissions)
            accepted += int(solved)
            score += problem_score
            if solved:
                solved_at = accepted_rows[0]['created']
                first_accept = solved_at if first_accept is None else min(first_accept, solved_at)
            per_problem.append({'problem_id': problem['id'], 'attempts': len(submissions),
                'accepted': len(accepted_rows), 'solved': solved, 'score': problem_score,
                'passed_cases': int(testcase_match.group(1)) if testcase_match else 0,
                'total_cases': int(testcase_match.group(2)) if testcase_match else 0})
        rows.append({'user_id': candidate['id'], 'username': candidate['username'], 'score': score,
            'accepted_count': accepted, 'attempt_count': attempts, 'first_accepted_at': first_accept,
            'problems': per_problem})
    if contest['ranking_rule'] == 'acm':
        rows.sort(key=lambda item: (-item['accepted_count'], item['attempt_count'], item['first_accepted_at'] or float('inf'), item['username'].casefold()))
    else:
        rows.sort(key=lambda item: (-item['score'], -item['accepted_count'], item['attempt_count'], item['first_accepted_at'] or float('inf'), item['username'].casefold()))
    for rank, row in enumerate(rows, 1): row['rank'] = rank
    return rows
