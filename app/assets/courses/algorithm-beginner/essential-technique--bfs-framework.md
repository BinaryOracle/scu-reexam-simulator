# BFS 算法解题套路框架

## 学习目标

在无权图上按层寻找最少步数，并在入队时标记已访问状态。

## 层次与距离

BFS 从起点出发，先访问距离为 1 的状态，再访问距离为 2 的状态。这个最短路结论要求每条边成本相同；带不同权重的最短路径不能直接用普通 FIFO 队列代替其他最短路算法。

```cpp
vector<int> distances(const vector<vector<int>>& graph, int start) {
    vector<int> dist(graph.size(), -1);
    queue<int> pending;
    dist[start] = 0;
    pending.push(start);
    while (!pending.empty()) {
        int u = pending.front(); pending.pop();
        for (int v : graph[u]) {
            if (dist[v] != -1) continue;
            dist[v] = dist[u] + 1;
            pending.push(v);
        }
    }
    return dist;
}
```

要求起点和邻居编号合法。距离 -1 同时表示尚未发现，第一次入队便写入距离，防止多个父状态把同一节点重复加入。邻接表图的复杂度为 O(V+E)，队列和距离数组占 O(V)。

密码锁和滑动拼图可看作隐式图：节点是完整局面，边是一种合法操作。要明确状态编码、生成邻居和去重规则，不能只标记某个坐标而忽略影响后续行动的状态。双向 BFS 可在可逆状态图中缩小探索范围，但仍需检查相遇条件和两边的访问记录。

## 动手练习

1. 在带环的小图上手算所有节点距离。
2. 比较入队时标记与出队时标记对重复入队的影响。
3. 定义一个三位密码锁的状态和邻居，解释为何不能只记录最后改变的数字。
