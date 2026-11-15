from app.services.contest_scoring import submission_score


def test_accepted_submission_gets_full_problem_points():
    assert submission_score(100, 'Accepted', '') == 100


def test_partial_score_rounds_up_from_accepted_testcase_ratio():
    assert submission_score(100, 'Wrong Answer', '通过测试用例数：7 / 12') == 59


def test_partial_score_accepts_test_point_summary_and_rejects_invalid_counts():
    assert submission_score(250, 'Wrong Answer', '通过测试点数：1 / 3') == 84
    assert submission_score(100, 'Wrong Answer', '通过测试用例数：13 / 12') == 0
    assert submission_score(100, 'Wrong Answer', '暂无测试点明细（当前状态：Wrong Answer）。') == 0
