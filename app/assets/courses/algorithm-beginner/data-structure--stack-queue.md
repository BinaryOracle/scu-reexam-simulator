# 队列实现栈以及栈实现队列

## 学习目标

通过顺序翻转理解双栈队列和队列栈，并分析摊还成本。

## 双栈实现先进先出

输入栈保存新加入元素，输出栈提供队头。只有输出栈为空时，才把输入栈全部倒入输出栈。一次翻转把最近进入的顺序反过来，使最早进入的元素位于栈顶。

```cpp
class TwoStackQueue {
    stack<int> incoming, outgoing;
    void prepare() {
        if (!outgoing.empty()) return;
        while (!incoming.empty()) {
            outgoing.push(incoming.top());
            incoming.pop();
        }
    }
public:
    void push(int value) { incoming.push(value); }
    int pop() { // 调用方须保证队列非空
        prepare();
        int value = outgoing.top(); outgoing.pop();
        return value;
    }
    bool empty() const { return incoming.empty() && outgoing.empty(); }
};
```

单次出队在倒栈时可能 O(n)，但每个元素最多经历一次输入入栈、转移和出栈，长序列操作的摊还成本为 O(1)。不能把这个结论误写成每一次出队最坏 O(1)。

## 队列实现后进先出

一种做法是在每次入队新值后，把原有元素逐个取出并放到队尾，使新值来到队头。这样出栈 O(1)，入栈 O(n)。也可以把旋转成本放到出栈阶段，但必须把操作定义保持一致。

空结构上的取值需要有明确行为：检查为空、返回可识别结果或按接口要求处理，不能读取不存在的栈顶或队头。

## 动手练习

1. 依次执行入队 1、2，出队一次，再入队 3，跟踪两栈内容。
2. 用一个队列实现 push/pop，并测试 1、2、3 的出栈顺序。
3. 用五个元素的操作序列解释最坏成本和摊还成本的区别。
