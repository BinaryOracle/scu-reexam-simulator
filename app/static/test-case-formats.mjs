/** Platform-owned examples shared by authoring and practice case editors. */
export function testCaseFormat(platform, metadata) {
  if (platform !== 'leetcode') return {
    label: '标准输入 / 输出',
    hint: '洛谷格式：填写完整程序从标准输入读取的数据；换行和空格按题目要求填写。期望输出为程序打印的文本。',
    input: '2 7\n9', output: '0 1',
  };
  let signature = metadata;
  if (typeof signature === 'string') {
    try { signature = JSON.parse(signature); } catch { signature = null; }
  }
  const params = Array.isArray(signature?.params) ? signature.params : [];
  return {
    label: 'LeetCode 函数参数 / JSON 返回值',
    hint: '力扣格式：按函数参数顺序，每行填写一个 JSON 值；也支持参数名赋值（nums = [2,7], target = 9）。字符串用双引号，布尔值用 true/false，空节点用 null。期望输出填写 JSON 返回值；无返回值函数填写修改后的第一个参数。' +
      (params.length ? ` 本题参数：${params.map(p => `${p.name}: ${p.type}`).join('；')}。` : '') +
      ' 本地按 JSON 结构比较，列表顺序需一致；平台特殊判题规则以正式提交为准。',
    input: params.length ? params.map(p => `${p.name} = ${example(p.type)}`).join('\n') : 'nums = [2,7]\ntarget = 9',
    output: '[0,1]',
  };
}

function example(type) {
  if (type === 'TreeNode') return '[1,null,2]';
  if (type === 'ListNode') return '[1,2,3]';
  if (type?.endsWith('[]')) return `[${example(type.slice(0, -2))}]`;
  return ({ integer: '1', long: '1', double: '1.5', boolean: 'true', string: '"text"', character: '"a"' })[type] || 'null';
}
