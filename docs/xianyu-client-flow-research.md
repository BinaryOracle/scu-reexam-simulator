# 闲鱼客户端下单流程可行性

截至 2026-11-24，项目当前只有可配置的联动小铺 HTTPS 外链，没有闲鱼订单创建、支付或订单状态同步实现。下面的测试是离线协议模拟，不代表项目已接入闲鱼，也不会登录账号、调用真实接口或产生订单。

闲鱼官方合作方服务端文档描述的是已获准的服务商/小程序接入：服务端需部署在聚石塔；授权通过淘宝开放平台 OAuth 2.0；订单创建使用 TOP API `alibaba.idle.isv.goosefish.order.create`。创建虚拟商品订单要提供闲鱼侧确认的 `item_id`、业务标识 `x_global_biz_code`、分为“分”的价格、`virtual_item_order=true` 及虚拟商品编码。创建订单只返回订单号，不表示已经支付。

支付步骤使用客户端 API `Goosefish.tradePay`，随后服务端应调用 `alibaba.idle.isv.order.query` 确认状态；官方文档将 `order_status=2` 定义为已付款，后续还会有订单状态消息。普通网站打开一个闲鱼网页链接，并不能直接调用闲鱼小程序的客户端支付 API。第三方 `xianyu-mcp-server` README 声明其通过逆向分析 Web 接口、未经闲鱼授权，并警告可能违反平台规则和导致账号限制，因此没有把它作为商业订单链路或测试依赖。

运行离线模拟：

```sh
python3 tests/test_xianyu_client_flow_simulation.py
```

测试覆盖虚拟订单必需字段、创建订单与支付确认的区别、普通网页无法调用客户端支付 API，以及服务端查询的已付款状态。所有请求都由内存中的模拟对象处理。

来源：

- [闲鱼合作方-服务端接入文档](https://open.goofish.com/doc/development/dev/server.html)
- [第三方 xianyu-mcp-server README](https://github.com/litongqian/xianyu-mcp-server)（仅用于核对其自述能力与风险，不作为合规接入依据）
