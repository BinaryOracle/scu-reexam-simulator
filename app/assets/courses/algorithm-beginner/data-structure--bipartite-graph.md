# 二分图判定算法

## 学习目标

用两色约束判定无向图是否为二分图，覆盖不连通分量。

## 每条边都要求两端不同色

从任意未染色节点出发，给起点一种颜色，所有邻居赋相反颜色。若已染色邻居与当前节点同色，就产生冲突。图可能不连通，因此必须对每个未染色节点启动一次搜索。

```cpp
bool bipartite(const vector<vector<int>>& g) {
    vector<int> color(g.size(), -1);
    for (int s = 0; s < (int)g.size(); ++s) {
        if (color[s] != -1) continue;
        queue<int> q; q.push(s); color[s] = 0;
        while (!q.empty()) {
            int u = q.front(); q.pop();
            for (int v : g[u]) {
                if (color[v] == color[u]) return false;
                if (color[v] == -1) {
                    color[v] = 1 - color[u]; q.push(v);
                }
            }
        }
    }
    return true;
}
```

无向图邻接表应登记两个方向，节点编号合法。自环直接冲突，奇数长度环不能完成两色划分，偶数环可以。孤立节点没有边约束，不会导致失败。

DFS 也能完成同样检查，但深链图应考虑递归栈限制。每个节点染色一次、每条邻接边检查常数次，总时间 O(V+E)，颜色和队列额外空间 O(V)。这里判断的是能否分为两组，并不计算二分图最大匹配或最小覆盖，这些是其他问题。

## 动手练习

1. 给三角形和四边形分别染色，找出冲突位置。
2. 构造一个含孤立节点与两个连通分量的图测试示例。
3. 说明为什么只从节点 0 搜索可能漏掉不合法的另一分量。
