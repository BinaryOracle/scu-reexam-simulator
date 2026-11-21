"""Function-style cases must not be sent to a stdin-style program unchanged."""
import pytest
from app.services import coding_test_adapters as adapters

META = {'name': 'twoSum', 'params': [{'name': 'nums', 'type': 'integer[]'}, {'name': 'target', 'type': 'integer'}], 'return': {'type': 'integer[]'}}

@pytest.mark.parametrize('text', ['nums = [2, 7], target = 9', '[2,7]\n9', '{"nums":[2,7],"target":9}'])
def test_parses_named_positional_and_object_arguments(text):
    assert adapters.parse_arguments(text, META) == [[2, 7], 9]

@pytest.mark.parametrize('text', ['nums=[2,7]', 'nums=[2,7], target="9"', 'nums=[2,7], target=__import__("os")', 'nums=[2,7], target=9, x=1'])
def test_rejects_missing_wrong_type_and_executable_input(text):
    with pytest.raises(ValueError):
        adapters.parse_arguments(text, META)


def test_luogu_adapter_preserves_whitespace(monkeypatch):
    from app.services import coding_judge
    observed = []
    monkeypatch.setattr(coding_judge, 'evaluate', lambda language, source, cases: observed.extend(cases) or {'status': 'Accepted'})
    assert adapters.evaluate('luogu', 'cpp11', 'int main(){}', [{'input': '2 7\n9\n', 'output': '0 1'}])['status'] == 'Accepted'
    assert observed[0]['input'] == '2 7\n9\n'


def test_leetcode_wraps_solution_and_restores_original_case_input(monkeypatch):
    from app.services import coding_judge
    def evaluate(language, source, cases, **kwargs):
        assert 'Solution' in source and 'twoSum' in source
        assert kwargs['structured'] is True
        return {'status': 'Accepted', 'cases': [{'input': cases[0]['input'], 'expected_output': '[0,1]', 'actual_output': '[0,1]', 'status': 'Accepted'}]}
    monkeypatch.setattr(coding_judge, 'evaluate', evaluate)
    result = adapters.evaluate('leetcode', 'cpp11', 'class Solution {};', [{'input': 'nums=[2,7], target=9', 'output': '[0,1]'}], META)
    assert result['cases'][0]['input'] == 'nums=[2,7], target=9'


def test_design_questions_are_explicitly_rejected():
    with pytest.raises(ValueError, match='设计类'):
        adapters.parse_arguments('[]', {'systemdesign': True})

@pytest.mark.parametrize('language,source', [
    ('cpp11', 'class Solution {public: vector<int> twoSum(vector<int>& nums,int target){return {0,1};}};'),
    ('python3', 'class Solution:\n    def twoSum(self, nums, target): return [0,1]'),
    ('c', 'int* twoSum(int* nums,int numsSize,int target,int* returnSize){*returnSize=2;int* p=malloc(2*sizeof(int));p[0]=0;p[1]=1;return p;}'),
])
def test_generated_drivers_execute_in_real_isolated_judge(language, source):
    from app.services import coding_judge
    if not coding_judge.availability()['available']:
        pytest.skip('Docker judge image unavailable')
    cases = [{'input': 'nums=[2,7], target=9', 'output': '[0,1]'}, {'input': '[3,3]\n6', 'output': '[0, 1]'}]
    result = adapters.evaluate('leetcode', language, source, cases, META)
    assert result['status'] == 'Accepted', result
    assert result['passed_cases'] == 2


def test_json_comparison_keeps_strings_and_boolean_types():
    from app.services.coding_judge import _matches
    assert not _matches('\n__SCU_RESULT__"a b"', '"ab"', True)
    assert not _matches('\n__SCU_RESULT__true', '1', True)
    assert _matches('debug\n__SCU_RESULT__[0,1]', '[0, 1]', True)
    assert _matches('\n__SCU_RESULT__0.33333333333', '0.333333', True)

@pytest.mark.parametrize('language,source,meta,cases', [
    ('cpp11', 'class Solution {public: TreeNode* invertTree(TreeNode* root){return root;}};', {'name': 'invertTree', 'params': [{'name': 'root', 'type': 'TreeNode'}], 'return': {'type': 'TreeNode'}}, [{'input': '[1,null,2,3]', 'output': '[1,null,2,3]'}, {'input': '[]', 'output': '[]'}]),
    ('python3', 'class Solution:\n    def reverseList(self, head): return head', {'name': 'reverseList', 'params': [{'name': 'head', 'type': 'ListNode'}], 'return': {'type': 'ListNode'}}, [{'input': '[1,2,3]', 'output': '[1,2,3]'}, {'input': '[]', 'output': '[]'}]),
    ('cpp11', 'class Solution {public: vector<vector<string>> echo(vector<vector<string>>& a){return a;}};', {'name': 'echo', 'params': [{'name': 'a', 'type': 'string[][]'}], 'return': {'type': 'string[][]'}}, [{'input': '[["a b","中文","a\\nb"]]', 'output': '[["a b","中文","a\\nb"]]'}]),
    ('cpp11', 'class Solution {public: void reverseString(vector<char>& s){reverse(s.begin(),s.end());}};', {'name': 'reverseString', 'params': [{'name': 's', 'type': 'character[]'}], 'return': {'type': 'void'}}, [{'input': '["a","b"]', 'output': '["b","a"]'}]),
    ('c', 'void reverseString(char* s,int sSize){char c=s[0];s[0]=s[1];s[1]=c;}', {'name': 'reverseString', 'params': [{'name': 's', 'type': 'character[]'}], 'return': {'type': 'void'}}, [{'input': '["a","b"]', 'output': '["b","a"]'}]),
])
def test_structured_drivers_in_real_sandbox(language, source, meta, cases):
    from app.services import coding_judge
    if not coding_judge.availability()['available']:
        pytest.skip('Docker judge image unavailable')
    result = adapters.evaluate('leetcode', language, source, cases, meta)
    assert result['status'] == 'Accepted', result


def test_reuses_metadata_without_network_and_fetches_missing_signatures(monkeypatch):
    from app.services import leetcode_catalog
    calls = []
    monkeypatch.setattr(leetcode_catalog, 'problem', lambda slug: calls.append(slug) or {'source_info': {'leetcode_metadata': META}})
    assert adapters.resolve_metadata({'leetcode_metadata': META}, 'two-sum') == META
    assert calls == []
    assert adapters.resolve_metadata({}, 'two-sum') == META
    assert calls == ['two-sum']
