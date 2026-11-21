# 经典动态规划：0-1 背包问题

## 学习目标

区分前 i 个物品和容量两维状态，理解倒序容量如何保证每个物品只用一次。

## 每件物品只有选或不选

令 dp[i][c] 为只考虑前 i 件物品、容量不超过 c 时的最大价值。若第 i 件重量为 w、价值为 v，不选得到 dp[i-1][c]；能装下时，选择它得到 dp[i-1][c-w]+v。两者取较大值。

一维压缩示例假设重量为正整数、容量非负，并允许不选任何物品：

```cpp
long long knapsack(const vector<int>& weight,
                   const vector<int>& value, int capacity) {
    vector<long long> dp(capacity + 1, 0);
    for (int i = 0; i < (int)weight.size(); ++i) {
        for (int c = capacity; c >= weight[i]; --c) {
            dp[c] = max(dp[c], dp[c - weight[i]] + value[i]);
        }
    }
    return dp[capacity];
}
```

重量与价值数组须等长。容量从大到小更新，使 `dp[c-weight[i]]` 仍是上一轮、不包含当前物品的值；从小到大可能在同一轮重复选择物品，变成另一种背包问题。

## “不超过”与“恰好装满”不能混用

这份初始化允许剩余空间，所有容量初始价值为 0。若必须恰好装满，则除容量 0 外应初始化为不可达，并在转移时检查来源有效。最优价值是 0 不代表一定能达到那个精确重量。

状态总数约 n×capacity，所以时间 O(n·capacity)，空间压缩为 O(capacity)。容量取值很大时，即使物品数少也可能不可行，需要重新评估建模。

## 动手练习

1. 对重量 [2,3]、价值 [3,4]、容量 4 手算每一轮 dp。
2. 将容量改为正序，指出哪一轮重复使用了物品。
3. 编写恰好装满版本，测试容量不可达的情况。
