# 拓扑排序算法

## 学习目标

把依赖关系转换为有向边，生成满足先后约束的次序并检测环。

## 当前可执行的节点

拓扑序要求对每条 u→v，u 都出现在 v 之前。Kahn 算法维护尚未满足的先修数量，所有入度为 0 的节点都可先执行；处理节点后移除它的出边，让新的零入度节点进入队列。

```cpp
vector<int> topo(const vector<vector<int>>& g) {
    vector<int> indegree(g.size(), 0), order;
    for (const auto& edges : g)
        for (int v : edges) ++indegree[v];
    queue<int> q;
    for (int i = 0; i < (int)g.size(); ++i)
        if (indegree[i] == 0) q.push(i);
    while (!q.empty()) {
        int u = q.front(); q.pop(); order.push_back(u);
        for (int v : g[u]) if (--indegree[v] == 0) q.push(v);
    }
    if (order.size() != g.size()) return {};
    return order;
}
```

非空图返回空结果表示存在环；空图的空序列本来就是合法结果，若接口需要区分两者，应另带状态。重复边必须在统计和消除时采用一致策略。

DFS 可以在后序记录节点，最后反转得到拓扑序，但必须先判环或在遍历中检测路径冲突。仅反转后序而不检查环，不能证明结果符合依赖关系。

拓扑序通常不唯一。队列中若同时出现多个零入度节点，任选一个都可能合法；若题目要求字典序最小，需使用最小堆，复杂度也随之改变。

## 动手练习

1. 为两门互不依赖的先修课指向同一门后续课，列出两种合法序列。
2. 验证输出时检查每条边，而不是只比较某一个固定答案。
3. 修改为字典序最小的拓扑序，说明优先队列的作用。
