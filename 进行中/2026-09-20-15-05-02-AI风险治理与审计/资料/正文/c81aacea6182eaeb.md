# 【智能体安全治理｜专栏第0期·启航篇】AI时代的数字宪法：我们该如何约束自主行动的AI智能体

[TunerT\_TQ](https://juejin.cn/user/639258619294300/posts)

2026-08-24

23

阅读7分钟


专栏：


智能体安全治理


关注

## 【智能体安全治理｜专栏第0期·启航篇】AI时代的数字宪法：我们该如何约束自主行动的AI智能体

> **作者**: AI治理研究组
> **原创声明**: 本文为原创技术博客，基于一线智能体工程实践总结编写。
> 文末附有相关学术研究的延伸阅读参考。

🕒 写作说明：当前AI智能体技术处于快速迭代周期，治理思路具备长期参考价值；落地实施时需要结合业务场景、监管政策持续调整方案。本文观点仅作架构研讨参考，不构成标准化落地规范。

## 一、从一次真实实验故障说起

此前我们在搭建一套实验性AI智能体项目，Agent具备读取邮件、数据库检索、调用办公套件的自主工具调用能力。

一次测试中观察到意外行为：

1. 用户发起请求："帮我查一下昨天的销售数据"
2. Agent检索数据库成功获取目标数据
3. 主动整理数据生成邮件，自动抄送全部联系人进行群发

关键问题： **用户从未提出发送邮件的需求。**
倘若该逻辑上线生产环境，直接引发敏感业务数据外泄风险。Agent本身不存在主观恶意，根源在于智能体拥有过高自主决策权，缺少边界约束。

这个案例抛出根本性命题：
当程序不再被动执行固定代码指令，可以自主规划、自主决策、主动执行一系列动作时，我们依靠什么机制约束它的行为？
这也是「智能体安全治理」议题诞生的核心背景。

## 二、从传统软件安全，迈向智能体全新安全范式

### 传统软件的安全约束模型

传统软件执行链路高度确定：

```css

css
 代码解读
复制代码

用户输入 → [输入验证] → [业务逻辑] → [权限检查] → 结果输出
```

整条执行路径预先编码，具备强确定性。校验拦截逻辑清晰：输入非法直接拒绝、权限不足直接报错，执行链路可完整预测。

### AI智能体带来的全新安全挑战

智能体运行链路具备动态自主特性：

```css

css
 代码解读
复制代码

用户意图 → [LLM意图理解] → [自主规划] → [工具选择] → [执行] → 链式调用更多工具
                         ↑                    ↑
                   不可预测中间步骤      支持持续扩展工具调用
```

相比传统软件，产生两大本质变化：

1. **规划与执行相互分离**
传统程序路径静态固化；同一用户请求，智能体在不同时机可能生成完全不同执行方案。
2. **工具自主调度**
智能体依靠自身判断挑选工具、调整调用顺序，每一次工具调用都可能跨越安全边界。

### 直观类比：从轨道列车到自动驾驶汽车

|  | 传统软件 | AI 智能体 |
| :-- | :-- | :-- |
| 类比 | 轨道列车 | 自动驾驶汽车 |
| 运行路径 | 固定轨道 | 实时动态规划 |
| 自主自由度 | 极低 | 极高 |
| 安全防护思路 | 守住入口即可 | 全程持续感知、决策、动态管控 |
| 约束生效时机 | 入口单点校验 | 全链路持续管控 |

这个类比清晰说明治理思路的转变：
**智能体治理不能只做上线前一次性安检，而是贯穿运行全生命周期的制动系统、安全防线。**

传统软件安全

入口集中校验

智能体安全治理

事前能力约束

运行过程监控

动态权限调整

事后审计复盘

## 三、智能体治理必须回答的五大核心问题

结合大量工程落地实践，一套完备的智能体治理体系，必须系统性解决下面五个基础问题。

### 问题1：能力边界在哪里？

明确智能体允许执行、禁止执行的动作清单。这不仅是技术配置，更是顶层策略定义。
✅ 实践方案：能力沙箱 \+ 显式能力声明。智能体启动阶段声明所需权限，系统按需最小化授予，禁止隐式扩容能力。

### 问题2：最终决策权归属谁？

当智能体存在多种可行执行方案，由谁做出最终选择：智能体自主决策、人工审批、分级授权管控？
✅ 实践方案：权责分离架构——感知信息 ≠ 制定规划 ≠ 执行操作，三层权责相互隔离。

### 问题3：信任如何建立与动态撤销？

智能体可信度不是静态标签，单次异常行为就应当触发信任重评估。
✅ 实践方案：动态信任分值机制。行为合规稳定提升信任等级；检测异常行为下调信任、同步收缩操作权限。

### 问题4：决策链路如何完整审计？

风险事件发生后，能够完整回溯：当时触发了什么决策、依据哪些信息、每一步动作由谁/什么组件发起。
✅ 实践方案：链式不可篡改审计日志，所有决策、校验行为留存完整证据链，支持事故复盘与合规审查。

### 问题5：如何持续满足合规要求？

面对《生成式人工智能服务管理暂行办法》、欧盟AI法案等监管规范，如何在系统架构层面原生满足透明度、可追溯、风险管控要求。
✅ 实践方案：合规策略引擎，将法规约束转化为系统可自动执行的管控规则。

## 四、治理不是枷锁，而是安全的运行跑道

这是落地过程中最重要的实践结论：

> **完善的治理不是限制智能体能力，而是为智能体搭建安全跑道，让它能够在可控范围内充分发挥能力。**

没有治理约束的智能体，等同于一台缺少刹车、制动系统的赛车，业务侧不敢投入生产；
配套完整治理体系的智能体，如同搭载全套安全防护系统的车辆，可以安全稳定承载复杂业务场景。

这条核心理念，将会贯穿本专栏全部内容。

## 五、专栏完整路线图

本专栏将从架构、权限、攻防、合规多个维度，系统性拆解智能体安全治理体系：

| 方向 | 期数 | 核心内容简介 |
| :-- | :-: | :-- |
| 🏛️ **多层防御架构** | 第1期 | 4C分层防御框架，依靠多层隔离避免单点防御失效 |
| ⚖️ **分权决策模式** | 第2期 | 感知、规划、执行三权分立架构设计 |
| 🔄 **动态权限管理** | 第3期 | 信任等级联动权限；风险出现自动收缩权限 |
| 🧬 **能力演进治理** | 第4期 | AI模型能力持续增强，治理策略如何同步迭代 |
| 🔐 **信任链安全** | 第5期 | 智能体容易被诱导轻信外部信息，如何加固信任边界 |
| 🌐 **合规工程实现** | 第6期 | 监管条文转化为可自动执行的系统策略 |
| 🤖 **定义驱动的治理** | 第7期 | 先明确安全基线标准，再搭建评估体系 |
| 🛡️ **攻防全景图** | 第8期 | 梳理智能体完整攻击面与防御手段 |
| 🔮 **治理的未来** | 第9期 | 面向下一代智能体的「数字宪法」构想与探索 |

> 📢 专栏第1期已更新： **4C框架完整解读：面向智能体AI安全四层防御体系**，搭建智能体纵深防御底层架构。

## 六、延伸阅读

专栏探讨的治理方向，与学术界多项前沿研究方向重合，感兴趣可以检索以下论文深入学习：

> - "4C Framework for Agentic AI Security" — 探讨多层防御架构
> - "Bounding Decision Authority" — 探讨决策权限分域
> - "Reconstructive Authority" — 探讨动态权限控制
> - "Authority Inversion in LLM Systems" — 探讨信任链漏洞

以上论文均可在arXiv检索标题获取原文。

* * *

> **版权声明**: 本文为原创技术文章。
> 欢迎规范转载，请完整标注文章出处。

标签：

[Agent](https://juejin.cn/tag/Agent) [安全](https://juejin.cn/tag/%E5%AE%89%E5%85%A8)

话题：

[每日精选文章](https://juejin.cn/theme/detail/7275231252674773028?contentType=1)

本文收录于以下专栏

![cover](https://p9-juejin-sign.byteimg.com/tos-cn-i-k3u1fbpfcp/95414745836549ce9143753e2a30facd~tplv-k3u1fbpfcp-jj-mark-v1:0:0:0:0:5o6Y6YeR5oqA5pyv56S-5Yy6IEAgVHVuZXJUX1RR:q75.awebp?rk3s=f64ab15b&x-expires=1790494403&x-signature=%2BS2jOcFtQYIQo20d%2Bl6Garfq3Fs%3D)

智能体安全治理


专栏目录


当前AI智能体技术处于快速迭代周期，治理思路具备长期参考价值；落地实施时需要结合业务场景、监管政策持续调整方案。本文观点仅作架构研讨参考，不构成标准化落地规范。


0 订阅

·

8 篇文章

订阅

下一篇

【智能体安全治理｜专栏第2期】三权分立决策模式：感知-规划-执行分离，让AI不能既当裁判又当运动员


评论 0

![avatar](https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/58aaf1326ac763d8a1054056f3b7f2ef.svg)

0/ 1000

标点符号、链接等不计算在有效字数内


Ctrl + Enter


发送


登录 / 注册即可发布评论！

暂无评论数据

![](https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/c12d6646efb2245fa4e88f0e1a9565b7.svg)点赞

![](https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/336af4d1fafabcca3b770c8ad7a50781.svg)评论

![](https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/3d482c7a948bac826e155953b2a28a9e.svg)
收藏


加个关注，精彩更新不错过~

![avatar](https://p3-passport.byteacctimg.com/img/user-avatar/180567139812898ed39a74b8442506ba~40x40.awebp)

关注


为你推荐

[【智能体安全治理｜专栏第4期】能力演进治理：AI能力持续增强时，治理体系如何同步跟上](https://juejin.cn/post/7678324732161081394 "【智能体安全治理｜专栏第4期】能力演进治理：AI能力持续增强时，治理体系如何同步跟上")

[【智能体安全治理｜专栏第4期】能力演进治理：AI能力持续增强时，治理体系如何同步跟上 🕒 写作说明：能力演进治理是智能体安全体系的长期命题，具备长期工程参考价值；落地实施时需要结合模型迭代节奏](https://juejin.cn/post/7678324732161081394)

- [TunerT\_TQ](https://juejin.cn/user/639258619294300)

- 24天前


- 25
- 点赞

- 评论


[架构](https://juejin.cn/tag/%E6%9E%B6%E6%9E%84 "架构") [安全](https://juejin.cn/tag/%E5%AE%89%E5%85%A8 "安全") [Agent](https://juejin.cn/tag/Agent "Agent")

[【智能体安全治理｜专栏第6期】合规工程轻量化思考｜把EU AI Act法律文本变成可落地的系统合规能力](https://juejin.cn/post/7678596150201303086 "【智能体安全治理｜专栏第6期】合规工程轻量化思考｜把EU AI Act法律文本变成可落地的系统合规能力")

[【智能体安全治理｜专栏第6期】合规工程轻量化思考｜把EU AI Act法律文本变成可落地的系统合规能力 摘要：AI监管落地的最大工程难题，不是规则复杂，而是法律自然语言无法直接映射为机器可执行逻辑。](https://juejin.cn/post/7678596150201303086)

- [TunerT\_TQ](https://juejin.cn/user/639258619294300)

- 23天前


- 27
- 点赞

- 评论


[架构](https://juejin.cn/tag/%E6%9E%B6%E6%9E%84 "架构") [Agent](https://juejin.cn/tag/Agent "Agent") [安全](https://juejin.cn/tag/%E5%AE%89%E5%85%A8 "安全")

[智能体安全治理｜专栏第7期】：先定义“安全”再评估——面向AI系统可运营的定义驱动治理框架](https://juejin.cn/post/7678700660859797514 "智能体安全治理｜专栏第7期】：先定义“安全”再评估——面向AI系统可运营的定义驱动治理框架")

[【智能体安全治理｜专栏第7期】：先定义“安全”再评估——面向AI系统可运营的定义驱动治理框架 前言 当前大量团队在AI系统安全评审中普遍陷入一类共性困境：所有人都在讨论系统安不安全，却没有人提前对齐：](https://juejin.cn/post/7678700660859797514)

- [TunerT\_TQ](https://juejin.cn/user/639258619294300)

- 23天前


- 30
- 点赞

- 评论


[架构](https://juejin.cn/tag/%E6%9E%B6%E6%9E%84 "架构")

![智能体安全治理｜专栏第7期】：先定义“安全”再评估——面向AI系统可运营的定义驱动治理框架](https://p6-xtjj-sign.byteimg.com/tos-cn-i-73owjymdk6/e8478af0ed1840dfb80f3177004fbed5~tplv-73owjymdk6-jj-mark-v1:0:0:0:0:5o6Y6YeR5oqA5pyv56S-5Yy6IEAgVHVuZXJUX1RR:q75.awebp?rk3s=f64ab15b&x-expires=1790494405&x-signature=PCc6vx7V39BpYX8iBsYKVXRCCtY%3D)

[2026年智能体AI核心指南报告：白皮书、落地路线图｜附180+份报告PDF、数据、可视化模板汇总下载](https://juejin.cn/post/7612218579228622884 "2026年智能体AI核心指南报告：白皮书、落地路线图｜附180+份报告PDF、数据、可视化模板汇总下载")

[原文链接：https://tecdat.cn/?p=45087 原文出处：拓端抖音号@拓端teclat 上个月，一位做企业架构师的朋友发来一串灵魂拷问： 他的困惑，也是今天很多企业管理者和技术决策者的](https://juejin.cn/post/7612218579228622884)

- [拓端tecdat](https://juejin.cn/user/3466130564317400)

- 6月前


- 444
- 点赞

- 评论


[算法](https://juejin.cn/tag/%E7%AE%97%E6%B3%95 "算法")

[【智能体安全治理｜专栏第2期】三权分立决策模式：感知-规划-执行分离，让AI不能既当裁判又当运动员](https://juejin.cn/post/7677505167910551579 "【智能体安全治理｜专栏第2期】三权分立决策模式：感知-规划-执行分离，让AI不能既当裁判又当运动员")

[【智能体安全治理｜专栏第2期】三权分立决策模式：感知-规划-执行分离，让AI不能既当裁判又当运动员 🕒 写作说明：三域分离是智能体决策治理的通用架构思想，具备长期工程参考价值；落地实施时需要结合业务风](https://juejin.cn/post/7677505167910551579)

- [TunerT\_TQ](https://juejin.cn/user/639258619294300)

- 26天前


- 71
- 点赞

- 评论


[架构](https://juejin.cn/tag/%E6%9E%B6%E6%9E%84 "架构")

[【深度】OpenClaw 爆火背后的安全陷阱：某知名车企“养龙虾”爆雷，企业如何构建 AI Agent 安全治理体系？](https://juejin.cn/post/7616696042243915786 "【深度】OpenClaw 爆火背后的安全陷阱：某知名车企“养龙虾”爆雷，企业如何构建 AI Agent 安全治理体系？")

[针对近期某知名车企因 OpenClaw“养龙虾”（AI Agent）引发的内部安全事件，本文深度解析 AI 智能体在信息侦察、员工无意识投喂及权限失控方面的三大致命风险。](https://juejin.cn/post/7616696042243915786)

- [瑞华智策](https://juejin.cn/user/2561223760288764)

- 6月前


- 245
- 点赞

- 评论


[人工智能](https://juejin.cn/tag/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD "人工智能")

![【深度】OpenClaw 爆火背后的安全陷阱：某知名车企“养龙虾”爆雷，企业如何构建 AI Agent 安全治理体系？](https://p6-xtjj-sign.byteimg.com/tos-cn-i-73owjymdk6/e15dd8fe9fc44eda84470d1a42374e71~tplv-73owjymdk6-jj-mark-v1:0:0:0:0:5o6Y6YeR5oqA5pyv56S-5Yy6IEAg55Ge5Y2O5pm6562W:q75.awebp?rk3s=f64ab15b&x-expires=1790494405&x-signature=bLiuRfbHQMo5DgwTGdrcJcE4fZU%3D)

[大模型安全与智能体对抗实战：从提示词风险到执行级安全控制的全景架构](https://juejin.cn/post/7674778908173221915 "大模型安全与智能体对抗实战：从提示词风险到执行级安全控制的全景架构")

[大模型安全与智能体对抗实战：从提示词风险到执行级安全控制的全景架构 内容与合规声明 本文讨论的威胁模型、案例和代码仅用于： 获得明确授权的安全测试； 企业内部防御体系建设； 隔离实验环境中的安全研究；](https://juejin.cn/post/7674778908173221915)

- [TunerT\_TQ](https://juejin.cn/user/639258619294300)

- 1月前


- 33
- 点赞

- 评论


[GitHub](https://juejin.cn/tag/GitHub "GitHub") [安全](https://juejin.cn/tag/%E5%AE%89%E5%85%A8 "安全") [Agent](https://juejin.cn/tag/Agent "Agent")

![大模型安全与智能体对抗实战：从提示词风险到执行级安全控制的全景架构](https://p6-xtjj-sign.byteimg.com/tos-cn-i-73owjymdk6/3af1e60581eb424d89e9252159814ec1~tplv-73owjymdk6-jj-mark-v1:0:0:0:0:5o6Y6YeR5oqA5pyv56S-5Yy6IEAgVHVuZXJUX1RR:q75.awebp?rk3s=f64ab15b&x-expires=1790494405&x-signature=dRo3V8LtPbzrgV%2BluEYDwrLdlbQ%3D)

[【大模型安全实战】Agentic Cloud Decoys：面向自主智能体入侵的云端欺骗式防御实践（第2期）](https://juejin.cn/post/7675288419880140851 "【大模型安全实战】Agentic Cloud Decoys：面向自主智能体入侵的云端欺骗式防御实践（第2期）")

[【大模型安全实战】Agentic Cloud Decoys：面向自主智能体入侵的云端欺骗式防御实践（第2期） 摘要 传统云安全强调身份认证、权限控制、漏洞修复和边界阻断。这些措施非常重要](https://juejin.cn/post/7675288419880140851)

- [TunerT\_TQ](https://juejin.cn/user/639258619294300)

- 1月前


- 80
- 点赞

- 评论


[GitHub](https://juejin.cn/tag/GitHub "GitHub") [Agent](https://juejin.cn/tag/Agent "Agent") [安全](https://juejin.cn/tag/%E5%AE%89%E5%85%A8 "安全")

![【大模型安全实战】Agentic Cloud Decoys：面向自主智能体入侵的云端欺骗式防御实践（第2期）](https://p6-xtjj-sign.byteimg.com/tos-cn-i-73owjymdk6/22c664b7b9eb4048becf59190ae2ebe7~tplv-73owjymdk6-jj-mark-v1:0:0:0:0:5o6Y6YeR5oqA5pyv56S-5Yy6IEAgVHVuZXJUX1RR:q75.awebp?rk3s=f64ab15b&x-expires=1790494405&x-signature=cAOtx0GH1RLt0iX2DPVf7nx2U8E%3D)

[【智能体安全治理｜专栏第3期】动态权限管理：信任分级驱动，让AI权限不再非黑即白](https://juejin.cn/post/7678260548069654578 "【智能体安全治理｜专栏第3期】动态权限管理：信任分级驱动，让AI权限不再非黑即白")

[【智能体安全治理｜专栏第3期】动态权限管理：信任分级驱动，让AI权限不再非黑即白 🕒 写作说明：动态信任分级是智能体权限治理的通用架构思想，具备长期工程参考价值；落地实施时需要结合业务风险等级](https://juejin.cn/post/7678260548069654578)

- [TunerT\_TQ](https://juejin.cn/user/639258619294300)

- 24天前


- 22
- 点赞

- 评论


[架构](https://juejin.cn/tag/%E6%9E%B6%E6%9E%84 "架构") [Agent](https://juejin.cn/tag/Agent "Agent") [安全](https://juejin.cn/tag/%E5%AE%89%E5%85%A8 "安全")

[📌《从Prompt工程到AI思维：开发者新技能树全解析》](https://juejin.cn/post/7491590443739955238 "📌《从Prompt工程到AI思维：开发者新技能树全解析》")

[—— 当开发者开始“说人话”：Prompt工程为何成为新基建？ 🔥 开发者现状：代码之外的新战场 传统开发者的核心技能是“写代码”，但AI时代下，开发者需要学会“用自然语言对话”来驾驭大模型。 Pro](https://juejin.cn/post/7491590443739955238)

- [Homi](https://juejin.cn/user/2969152984455367)

- 1年前


- 561
- 1

- 评论


[人工智能](https://juejin.cn/tag/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD "人工智能")

[企业智能体工程体系v1.1｜ 企业智能体工程卷 · 第0期·企业公民——Agent 是同事，不是工具](https://juejin.cn/post/7680024375573119014 "企业智能体工程体系v1.1｜ 企业智能体工程卷 · 第0期·企业公民——Agent 是同事，不是工具")

[#企业智能体工程体系v1.1｜ 企业智能体工程卷 · 第0期 企业公民——Agent 是同事，不是工具 📌 本文档声明 性质：本文为企业智能体工程化设计参考框架的第0期，提供架构思路与治理协议的概念](https://juejin.cn/post/7680024375573119014)

- [TunerT\_TQ](https://juejin.cn/user/639258619294300)

- 19天前


- 69
- 点赞

- 评论


[架构](https://juejin.cn/tag/%E6%9E%B6%E6%9E%84 "架构") [安全](https://juejin.cn/tag/%E5%AE%89%E5%85%A8 "安全") [Agent](https://juejin.cn/tag/Agent "Agent")

![企业智能体工程体系v1.1｜ 企业智能体工程卷 · 第0期·企业公民——Agent 是同事，不是工具](https://p6-xtjj-sign.byteimg.com/tos-cn-i-73owjymdk6/8740fe1f2063453caebf72aecdcb681c~tplv-73owjymdk6-jj-mark-v1:0:0:0:0:5o6Y6YeR5oqA5pyv56S-5Yy6IEAgVHVuZXJUX1RR:q75.awebp?rk3s=f64ab15b&x-expires=1790494405&x-signature=w8Z8%2FwimTKaroPJbCDNF4WrBNRs%3D)

[2025年AI智能体时代重塑企业未来报告：政务金融落地、技术架构与商业化\|附180+份报告PDF、数据、可视化模板汇总下载](https://juejin.cn/post/7602188264114847759 "2025年AI智能体时代重塑企业未来报告：政务金融落地、技术架构与商业化|附180+份报告PDF、数据、可视化模板汇总下载")

[原文链接：https://tecdat.cn/?p=44931 原文出处：拓端抖音号@拓端tecdat AI大模型技术的成熟迭代、行业对效率提升的迫切需求与政策层面的持续赋能，正推动智能体从实验室概念](https://juejin.cn/post/7602188264114847759)

- [拓端tecdat](https://juejin.cn/user/3466130564317400)

- 7月前


- 410
- 点赞

- 评论


[面试](https://juejin.cn/tag/%E9%9D%A2%E8%AF%95 "面试")

[智能体来了:告别打工人？AI智能体正在成为“数字合伙人”](https://juejin.cn/post/7566131671172087817 "智能体来了:告别打工人？AI智能体正在成为“数字合伙人”")

[一.你的“数字合伙人”已上线！ 革命性升级：告别“你问我答”！智能体不再是被动工具，而是能主动思考、规划行动的战略级伙伴。 国家定下KPI：政策明确，到2027年，智能体应用普及率将超70% ，一个“](https://juejin.cn/post/7566131671172087817)

- [人间百乐](https://juejin.cn/user/2728369022312298)

- 10月前


- 139
- 点赞

- 评论


[架构](https://juejin.cn/tag/%E6%9E%B6%E6%9E%84 "架构")

[第12章-多智能体与超级智能：碳硅融合-对齐与未来社会 《智能的历史：过去与未来——AI智能体改变社会》](https://juejin.cn/post/7684463933702488074 "第12章-多智能体与超级智能：碳硅融合-对齐与未来社会 《智能的历史：过去与未来——AI智能体改变社会》")

[第12章-多智能体与超级智能：碳硅融合-对齐与未来社会《智能的历史：过去与未来——AI智能体改变社会》 —— Powered By AI Genius Institute & 光剑AI Gitcode](https://juejin.cn/post/7684463933702488074)

- [AI天才研究院](https://juejin.cn/user/3043051577548312)

- 8天前


- 32
- 点赞

- 评论


[人工智能](https://juejin.cn/tag/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD "人工智能")

![第12章-多智能体与超级智能：碳硅融合-对齐与未来社会 《智能的历史：过去与未来——AI智能体改变社会》](https://p6-xtjj-sign.byteimg.com/tos-cn-i-73owjymdk6/b15cd2e77d1f40f2b97cb58abdbe1b24~tplv-73owjymdk6-jj-mark-v1:0:0:0:0:5o6Y6YeR5oqA5pyv56S-5Yy6IEAgQUnlpKnmiY3noJTnqbbpmaI=:q75.awebp?rk3s=f64ab15b&x-expires=1790494405&x-signature=dRKp2MXlQJRKnom%2FrIBCc7elP6Y%3D)

[走向自治智能时代：【Harness&Hermes】多智能体开发特训营 ，把握行业未来走向](https://juejin.cn/post/7650045387877859362 "走向自治智能时代：【Harness&Hermes】多智能体开发特训营 ，把握行业未来走向")

[走向自治智能时代：Harness & Hermes 多智能体开发，把握行业未来走向 引言：从“被动响应”到“自主进化”的范式跃迁 2026年，人工智能的演进核心正经历一场深刻的变革。我们正跨越单纯追求](https://juejin.cn/post/7650045387877859362)

- [用户57848156184](https://juejin.cn/user/4038968808848330)

- 3月前


- 57
- 点赞

- 评论


[Agent](https://juejin.cn/tag/Agent "Agent")

收藏成功！

已添加到「」， 点击更改

- 微信
![](https://juejin.cn/post/7677461694123393033)微信扫码分享

- 新浪微博
- QQ

![image](https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/img/cartoon.31472f0.png)

AI代码助手上线啦

选中代码，体验AI替你一键快速解读代码

立即体验

APP内打开

- ![下载掘金APP](https://p1-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/2ad212d53ccd44569d10317171664bae~tplv-k3u1fbpfcp-jj:90:0:0:0:q75.avis)下载APP










下载APP
- ![微信扫一扫](https://p9-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/9f4933cc8fdb411cba89904f14a3ec0a~tplv-k3u1fbpfcp-jj:90:0:0:0:q75.avis)微信扫一扫










微信公众号
- [新浪微博](https://weibo.com/xitucircle)

![](https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/img/MaskGroup.13dfc4f.png)选择你感兴趣的技术方向

后端


前端


Android


iOS


人工智能


开发工具


代码人生


阅读


跳过

上一步

至少选择1个分类


![](https://lf-web-assets.juejin.cn/obj/juejin-web/xitu_juejin_web/8867e249c23a7c0ea596c139befc04d7.svg)

温馨提示

当前操作失败，如有疑问，可点击申诉

前往申诉我知道了

沉浸阅读


确定屏蔽该用户

屏蔽后，对方将不能关注你、与你产生任何互动，无法查看你的主页