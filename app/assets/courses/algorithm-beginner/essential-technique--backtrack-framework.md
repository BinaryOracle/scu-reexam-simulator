# 回溯算法解题套路框架

## 学习目标

用路径、候选集和结束条件描述选择树，掌握选择与撤销的对称性。

## 一个分支如何恢复

回溯是在选择树上深度优先搜索。路径记录已经选择的内容，候选集描述还能选择什么，结束条件决定何时收集结果。分支结束后恢复共享状态，让下一分支从相同的起点出发。

下面为互不相同的整数生成全排列：

```cpp
void search(const vector<int>& a, vector<int>& path,
            vector<bool>& used, vector<vector<int>>& result) {
    if (path.size() == a.size()) {
        result.push_back(path);
        return;
    }
    for (int i = 0; i < (int)a.size(); ++i) {
        if (used[i]) continue;
        used[i] = true;
        path.push_back(a[i]);
        search(a, path, used, result);
        path.pop_back();
        used[i] = false;
    }
}
```

调用时使用空 path、长度为 n 且全 false 的 used。若输入包含重复值，还需要排序和同层去重等额外规则，不能仅依靠下标访问标记消除相同排列。

剪枝发生在确定某个分支不可能产生合法答案时，而不是凭直觉跳过“不太可能”的路径。完整生成 n 个不同元素的排列，本身就要输出 n! 个结果，计入复制路径后时间达到 O(n·n!)；不要期待通过普通缓存把所有输出变成多项式规模。

## 动手练习

1. 跟踪 a=[1,2,3] 的前两个结果，记录 used 与 path。
2. 去掉一处撤销操作，解释后续结果为什么出错。
3. 将结束条件改成选择恰好 k 个元素，思考排列与组合如何避免重复。
