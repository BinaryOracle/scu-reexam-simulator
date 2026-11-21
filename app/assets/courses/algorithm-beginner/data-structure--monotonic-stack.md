# 单调栈算法模板解决三道例题

## 学习目标

维护候选元素的单调性，求下一个更大元素、距离和环形变体。

## 被淘汰的候选为什么不再需要

从右向左扫描时，栈存储右侧仍可能成为答案的候选索引。若栈顶值不大于当前值，它既更小又被当前值挡住，不可能成为更左边元素的“下一个更大值”，可以弹出。

```cpp
vector<int> nextGreater(const vector<int>& a) {
    int n = (int)a.size();
    vector<int> answer(n, -1);
    stack<int> candidates;
    for (int i = n - 1; i >= 0; --i) {
        while (!candidates.empty() && a[candidates.top()] <= a[i])
            candidates.pop();
        if (!candidates.empty()) answer[i] = a[candidates.top()];
        candidates.push(i);
    }
    return answer;
}
```

这里找严格更大，因此相等也弹出。若题目要大于等于，比较关系就必须改变。每日温度一类题需要距离，应该保存索引并返回候选索引减 i，不能仅保存值。

环形数组可扫描两遍，用 i%n 取实际索引，并只在需要的阶段写答案；空数组应先处理，避免对 0 取模。每个索引入栈、出栈至多常数次，总时间 O(n)，额外空间 O(n)。

不要把单调栈误当作排序容器：它按原位置约束排除无用候选，不能提供任意次序统计，也不保证保留所有元素。

## 动手练习

1. 手算 [2,1,2,4,3] 的候选栈与答案。
2. 修改返回值，求下一个更大元素的距离。
3. 对全相等数组检查严格与非严格比较的区别，并写环形版本。
