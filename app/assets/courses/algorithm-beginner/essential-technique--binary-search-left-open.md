# 二分搜索左闭右开写法

## 学习目标

用左闭右开区间实现 lower_bound，并区分边界位置和元素索引。

## 这里的区间是左闭右开

原文章地址含 left-open，但正文讨论的是 `[left,right)` 写法。初始化 right=n；区间为空的条件是 left==right，因此循环条件为 left<right。找第一个不小于 target 的位置，可以维持左侧全小于目标、右侧已确定不小于目标的性质。

```cpp
int lowerPosition(const vector<int>& a, int target) {
    int left = 0, right = (int)a.size();
    while (left < right) {
        int mid = left + (right - left) / 2;
        if (a[mid] < target) left = mid + 1;
        else right = mid;
    }
    return left;
}
```

返回值可能等于 n，含义是应插在数组末尾，此时不能读取 a[n]。若要判断目标是否存在，应先确认结果小于 n，再比较该位置的值。把判断改成 `a[mid] <= target` 可以得到第一个大于 target 的位置；两种位置相减可得到目标出现次数。

## 不混用两套边界

闭区间模板通常初始化 n-1，相等分支可能使用 mid-1；半开区间模板初始化 n，上界可保留 mid。把闭区间的更新和半开区间的循环条件混用，容易漏掉最后一个元素或无法终止。

两种写法都能实现 O(log n) 查找。练习时选定一种并明确不变量，随后再比较另一种，而不是把某些行当作无需理解的口诀。

## 动手练习

1. 手算 a=[2,2,4]，目标为 1、2、3、5 时的返回位置。
2. 基于两种边界位置计算重复元素的个数。
3. 在纸上并列写出闭区间与半开区间的初始化、循环条件和上界更新。
