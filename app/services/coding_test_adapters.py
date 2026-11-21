"""Adapt stdin programs and LeetCode function cases to the isolated sample runner."""
import json
import math
import re

IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
DECODER = json.JSONDecoder()
SCALARS = {'integer', 'long', 'double', 'boolean', 'string', 'character'}


class UnsupportedCase(ValueError):
    """A platform-supported signature needs a driver not yet available locally."""


def metadata(value):
    """Validate the public function signature before generating any driver source."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise ValueError('力扣函数签名无效，请重新导入题目') from error
    if isinstance(value, dict) and (value.get('systemdesign') or value.get('classname')):
        raise UnsupportedCase('设计类题目暂不支持本地函数测试，请使用平台提交评测')
    if not isinstance(value, dict):
        raise ValueError('缺少力扣函数签名，请重新导入题目后运行')
    params = value.get('params')
    if (not IDENTIFIER.fullmatch(str(value.get('name', ''))) or not isinstance(params, list)
            or len(params) > 30 or not isinstance(value.get('return'), dict)):
        raise ValueError('缺少力扣函数签名，请重新导入题目后运行')
    names = []
    for param in params:
        if not isinstance(param, dict) or not IDENTIFIER.fullmatch(str(param.get('name', ''))):
            raise ValueError('力扣函数参数信息无效')
        names.append(param['name'])
        type_name(param.get('type'))
    if len(set(names)) != len(names):
        raise ValueError('力扣函数参数名称重复')
    type_name(value['return'].get('type'), allow_void=True)
    if value['return']['type'] == 'void' and not params:
        raise UnsupportedCase('无参数且无返回值的函数暂不支持本地结果比较，请提交平台评测')
    return value


def type_name(value, *, allow_void=False):
    if not isinstance(value, str):
        raise ValueError('力扣参数类型信息无效')
    base = value.removesuffix('[][]').removesuffix('[]')
    if value in ('ListNode', 'TreeNode') or base in SCALARS and value in (base, base+'[]', base+'[][]'):
        return value
    if allow_void and value == 'void':
        return value
    raise UnsupportedCase(f'本地测试暂不支持类型 {value}，请使用平台提交评测')


def _typed(value, kind):
    if kind in ('ListNode', 'TreeNode'):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f'{kind} 请使用 JSON 数组，空节点使用 null')
        return [None if item is None and kind == 'TreeNode' else _typed(item, 'integer') for item in value]
    if kind.endswith('[]'):
        if not isinstance(value, list):
            raise ValueError(f'{kind} 参数必须是 JSON 数组')
        return [_typed(item, kind[:-2]) for item in value]
    valid = {'integer': type(value) is int and -2**31 <= value < 2**31,
             'long': type(value) is int and -2**63 <= value < 2**63,
             'double': type(value) in (int, float) and abs(value) <= 1.7976931348623157e308 and math.isfinite(value),
             'boolean': type(value) is bool, 'string': isinstance(value, str),
             'character': isinstance(value, str) and len(value) == 1 and ord(value) < 128}
    if not valid.get(kind):
        raise ValueError(f'参数应为 {kind}，请检查 JSON 值的类型与范围')
    return value


def parse_arguments(text, meta):
    """Accept ordered JSON values, named assignments, or a parameter-name JSON object."""
    meta = metadata(meta)
    params = meta['params']
    text = text.strip()
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError):
        obj = None
    if isinstance(obj, dict):
        if set(obj) != {p['name'] for p in params}:
            raise ValueError('JSON 对象的参数名必须与题目函数签名完全一致')
        values = [obj[p['name']] for p in params]
    else:
        named, ordered, pos, mode = {}, [], 0, None
        try:
            while pos < len(text):
                match = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*', text[pos:])
                current = 'named' if match else 'ordered'
                if mode and mode != current:
                    raise ValueError('请勿混用带参数名与不带参数名的格式')
                mode = current
                if match:
                    name = match[1]
                    if name in named:
                        raise ValueError('参数名重复')
                    pos += match.end()
                value, pos = DECODER.raw_decode(text, pos)
                if match:
                    named[name] = value
                else:
                    ordered.append(value)
                if pos < len(text) and text[pos] not in ' ,\r\n\t':
                    raise ValueError('参数之间请使用换行或逗号分隔')
                pos = len(text) - len(text[pos:].lstrip(' ,\r\n\t'))
        except (ValueError, RecursionError) as error:
            raise ValueError('用例格式无效：使用 JSON 参数值，例如 nums = [2,7], target = 9；字符串用双引号') from error
        if mode == 'named':
            if set(named) != {p['name'] for p in params}:
                raise ValueError('参数名称或数量不匹配，请按函数签名填写全部参数')
            values = [named[p['name']] for p in params]
        else:
            values = ordered
    if len(values) != len(params):
        raise ValueError(f'本题需要 {len(params)} 个参数，每个参数单独一行；数组整体作为一个参数')
    return [_typed(value, param['type']) for value, param in zip(values, params)]


def validate_cases(cases, meta):
    """Validate authored LeetCode examples without executing or evaluating expressions."""
    meta = metadata(meta)
    for index, case in enumerate(cases):
        try:
            parse_arguments(case['input'], meta)
            if not case['output'].strip():
                raise ValueError('请填写 JSON 格式的期望输出')
            if case['output'].strip():
                _typed(json.loads(case['output']), meta['return']['type'] if meta['return']['type'] != 'void' else meta['params'][0]['type'])
        except (ValueError, RecursionError) as error:
            raise ValueError(f'用例 {index + 1}：{error}') from error
    return meta


PYTHON_NODES = '''
class ListNode:
    def __init__(self, val=0, next=None): self.val, self.next = val, next
class TreeNode:
    def __init__(self, val=0, left=None, right=None): self.val, self.left, self.right = val, left, right

def _scu_arg(value, kind):
    if kind == 'ListNode':
        head = ListNode(); tail = head
        for item in value: tail.next = ListNode(item); tail = tail.next
        return head.next
    if kind == 'TreeNode':
        if not value or value[0] is None: return None
        root = TreeNode(value[0]); queue = collections.deque([root]); items = iter(value[1:])
        while queue:
            node = queue.popleft()
            for side in ('left', 'right'):
                try: item = next(items)
                except StopIteration: return root
                if item is not None:
                    child = TreeNode(item); setattr(node, side, child); queue.append(child)
        return root
    return value

def _scu_out(value):
    if isinstance(value, ListNode):
        values = []
        while value is not None: values.append(value.val); value = value.next
        return values
    if isinstance(value, TreeNode):
        values = []; queue = collections.deque([value])
        while queue:
            node = queue.popleft(); values.append(None if node is None else node.val)
            if node is not None: queue.extend((node.left, node.right))
        while values and values[-1] is None: values.pop()
        return values
    return value
'''

CPP_SUPPORT = r'''
#include <bits/stdc++.h>
using namespace std;
struct ListNode { int val; ListNode *next; ListNode(int x=0, ListNode* n=nullptr): val(x),next(n){} };
struct TreeNode { int val; TreeNode *left,*right; TreeNode(int x=0,TreeNode* l=nullptr,TreeNode* r=nullptr):val(x),left(l),right(r){} };
ListNode* scu_list(vector<int> a){ListNode h; auto p=&h; for(int x:a){p->next=new ListNode(x);p=p->next;} return h.next;}
TreeNode* scu_tree(vector<pair<bool,int>> a){if(a.empty()||!a[0].first)return nullptr; auto r=new TreeNode(a[0].second);queue<TreeNode*> q;q.push(r);size_t i=1;while(!q.empty()&&i<a.size()){auto p=q.front();q.pop();for(auto slot:{&p->left,&p->right}){if(i>=a.size())break;if(a[i].first){*slot=new TreeNode(a[i].second);q.push(*slot);}++i;}}return r;}
void scu_json(const string& s){cout<<'"';for(unsigned char c:s){switch(c){case '"':cout<<"\\\"";break;case '\\':cout<<"\\\\";break;case '\n':cout<<"\\n";break;case '\r':cout<<"\\r";break;case '\t':cout<<"\\t";break;default:if(c<32){const char* h="0123456789abcdef";cout<<"\\u00"<<h[c>>4]<<h[c&15];}else cout<<c;}}cout<<'"';}
void scu_json(char c){scu_json(string(1,c));}
void scu_json(bool x){cout<<(x?"true":"false");}
template<class T> typename enable_if<is_arithmetic<T>::value>::type scu_json(T x){cout<<setprecision(17)<<x;}
template<class T> void scu_json(const vector<T>& a){cout<<'[';for(size_t i=0;i<a.size();i++){if(i)cout<<',';scu_json(static_cast<T>(a[i]));}cout<<']';}
void scu_json(ListNode* p){cout<<'[';bool first=true;while(p){if(!first)cout<<',';first=false;cout<<p->val;p=p->next;}cout<<']';}
void scu_json(TreeNode* r){vector<pair<bool,int>> a;queue<TreeNode*> q;if(r)q.push(r);while(!q.empty()){auto p=q.front();q.pop();a.push_back({p!=nullptr,p?p->val:0});if(p){q.push(p->left);q.push(p->right);}}while(!a.empty()&&!a.back().first)a.pop_back();cout<<'[';for(size_t i=0;i<a.size();i++){if(i)cout<<',';if(a[i].first)cout<<a[i].second;else cout<<"null";}cout<<']';}
'''


def _cpp_type(kind):
    if kind.endswith('[]'):
        return 'vector<' + _cpp_type(kind[:-2]) + '>'
    return {'integer': 'int', 'long': 'long long', 'double': 'double', 'boolean': 'bool',
            'string': 'string', 'character': 'char', 'ListNode': 'ListNode*', 'TreeNode': 'TreeNode*'}[kind]


def _cpp_literal(value, kind):
    if kind == 'TreeNode':
        return 'scu_tree({' + ','.join('{false,0}' if x is None else '{true,'+str(x)+'}' for x in value) + '})'
    if kind == 'ListNode':
        return 'scu_list({' + ','.join(map(str, value)) + '})'
    if kind.endswith('[]'):
        return '{' + ','.join(_cpp_literal(x, kind[:-2]) for x in value) + '}'
    if kind == 'character':
        return 'static_cast<char>(' + str(ord(value)) + ')'
    if kind == 'string':
        # Byte escapes avoid C++ interpreting JSON's Unicode surrogate pairs or control escapes.
        data = value.encode('utf-8')
        return 'string("' + ''.join('\\%03o' % x for x in data) + '",' + str(len(data)) + ')'
    if kind == 'long':
        return '(-9223372036854775807LL-1)' if value == -2**63 else str(value)+'LL'
    return json.dumps(value)


def driver(language, source, arguments, meta):
    """Build a source file; it is compiled/executed exclusively inside the existing sandbox."""
    meta = metadata(meta)
    if meta['return']['type'] == 'void' and not meta['params']:
        raise ValueError('无返回值且无参数的题目无法比较本地结果')
    if language == 'python3':
        prelude = 'from typing import *\nfrom collections import *\nfrom heapq import *\nimport json, sys, collections, math, itertools, functools, bisect, heapq\n'
        payload = json.dumps(arguments, ensure_ascii=True)
        types = json.dumps([p['type'] for p in meta['params']])
        call = f"_scu_result = Solution().{meta['name']}(*_scu_args)\n"
        if meta['return']['type'] == 'void':
            call += '_scu_result = _scu_args[0]\n'
        if meta['return']['type'] in ('ListNode', 'TreeNode'):
            call += 'if _scu_result is None: _scu_result = []\n'
        return prelude + PYTHON_NODES + '\n' + source + '\n' + (
            f"_scu_cases = json.loads({payload!r})\n_scu_values = _scu_cases[int(sys.stdin.read())]\n"
            f"_scu_args = [_scu_arg(v,t) for v,t in zip(_scu_values, {types})]\n" + call
            + "print('\\n__SCU_RESULT__' + json.dumps(_scu_out(_scu_result), ensure_ascii=True, allow_nan=False))\n")
    if language == 'c':
        return _c_driver(source, arguments, meta)
    if language != 'cpp11':
        raise ValueError('本地力扣测试支持 C++11、C 和 Python 3')
    blocks = []
    for index, values in enumerate(arguments):
        declarations = '\n'.join(f"{_cpp_type(p['type'])} scu_a{i} = {_cpp_literal(v, p['type'])};" for i, (p, v) in enumerate(zip(meta['params'], values)))
        call = f"Solution().{meta['name']}(" + ','.join(f'scu_a{i}' for i in range(len(values))) + ')'
        result = call + '; auto scu_result = scu_a0;' if meta['return']['type'] == 'void' else 'auto scu_result = '+call+';'
        blocks.append(f'case {index}: {{{declarations}\n{result}\ncout<<"\\n__SCU_RESULT__";scu_json(scu_result);return 0;}}')
    return CPP_SUPPORT + '\n' + source + '\nint main(){int scu_case;cin>>scu_case;switch(scu_case){' + '\n'.join(blocks) + '}return 1;}'


def evaluate(platform, language, source, cases, meta=None):
    """Dispatch by question source; local runs never create submissions or reward records."""
    from app.services import coding_judge
    if platform in ('luogu', 'samples'):
        return coding_judge.evaluate(language, source, cases)
    if platform != 'leetcode':
        raise ValueError('不支持此题目的本地评测格式')
    meta = validate_cases(cases, meta)
    args = [parse_arguments(case['input'], meta) for case in cases]
    adapted = [{'input': str(i), 'output': case['output']} for i, case in enumerate(cases)]
    result = coding_judge.evaluate(language, driver(language, source, args, meta), adapted, structured=True)
    for item, original in zip(result.get('cases', []), cases):
        item['input'] = original['input']
    return result


def _c_driver(source, arguments, meta):
    """Use LeetCode C pointer/size conventions for scalars and one-dimensional arrays."""
    kinds = [p['type'] for p in meta['params']] + [meta['return']['type']]
    if any(k in ('ListNode', 'TreeNode', 'string[]') or k.endswith('[][]') for k in kinds):
        raise UnsupportedCase('此题的 C 指针结构尚不支持本地测试，请选择 C++11/Python 3 或提交平台评测')
    scalar = {'integer': 'int', 'long': 'long long', 'double': 'double', 'boolean': 'bool', 'character': 'char', 'string': 'char*'}
    blocks = []
    for index, values in enumerate(arguments):
        declarations, args = [], []
        for i, (param, value) in enumerate(zip(meta['params'], values)):
            kind = param['type']; name = f'scu_a{i}'
            if kind.endswith('[]'):
                base = kind[:-2]
                declarations.append(f"{scalar[base]} {name}[] = {{" + ','.join(str(ord(v)) if base == 'character' else _cpp_literal(v, base) for v in value) + ('' if value else '0') + '};')
                args.extend([name, str(len(value))])
            elif kind == 'string':
                data = value.encode('utf-8')
                declarations.append(f'char {name}[]="' + ''.join('\\%03o' % x for x in data) + '";')
                args.append(name)
            else:
                literal = str(ord(value)) if kind == 'character' else _cpp_literal(value, kind)
                declarations.append(f'{scalar[kind]} {name}={literal};')
                args.append(name)
        ret = meta['return']['type']
        if ret.endswith('[]'):
            declarations.append('int scu_size=0;'); args.append('&scu_size')
        call = meta['name'] + '(' + ','.join(args) + ')'
        result_kind = meta['params'][0]['type'] if ret == 'void' else ret
        if ret == 'void':
            declarations.append(call+';')
            result = 'scu_a0'; length = str(len(values[0])) if isinstance(values[0], list) else '0'
        else:
            ctype = scalar[ret[:-2]]+'*' if ret.endswith('[]') else scalar[ret]
            declarations.append(f'{ctype} scu_result={call};')
            result = 'scu_result'; length = 'scu_size'
        if result_kind.endswith('[]'):
            output = f'printf("[");for(int i=0;i<{length};i++){{if(i)printf(",");' + _c_output(result+'[i]', result_kind[:-2]) + '}printf("]");'
        else:
            output = _c_output(result, result_kind)
        blocks.append(f'case {index}: {{' + '\n'.join(declarations) + '\nprintf("\\n__SCU_RESULT__");' + output + 'return 0;}')
    return r'''
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <math.h>
void scu_string(const char* s){putchar('"');for(;*s;s++){unsigned char c=*s;if(c=='"'||c=='\\'){putchar('\\');putchar(c);}else if(c<32)printf("\\u%04x",c);else putchar(c);}putchar('"');}
''' + source + '\nint main(){int scu_case;if(scanf("%d",&scu_case)!=1)return 1;switch(scu_case){' + '\n'.join(blocks) + '}return 1;}'


def _c_output(value, kind):
    if kind == 'string':
        return f'scu_string({value});'
    if kind == 'character':
        return f'{{char scu_char[]={{ {value},0 }};scu_string(scu_char);}}'
    if kind == 'boolean':
        return f'printf("%s",{value}?"true":"false");'
    fmt = {'integer': '%d', 'long': '%lld', 'double': '%.17g'}[kind]
    return f'printf("{fmt}",{value});'


def resolve_metadata(source_info, slug):
    """Older imported questions fetch their missing signature from LeetCode China on first run."""
    value = source_info.get('leetcode_metadata')
    if not value:
        from app.services.leetcode_catalog import problem
        value = problem(slug)['source_info'].get('leetcode_metadata')
    return metadata(value)
