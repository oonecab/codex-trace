# 文档职责索引

<!-- project-governance:managed:start -->
每类事实只能有一个权威来源：

- `../TECH.md`：技术栈、架构、路径、依赖、兼容边界与技术栈变更索引。
- `../AGENTS.md`：短小的 Agent 入口和不可协商红线。
- `../.project-governance.json`：结构化项目设置与已登记命令。
- `governance/`：工作流、测试、安全、变更控制、发布和风险规范。
- `environments.md`：不含秘密的环境变量名、服务和端口清单。
- `rules/`：公式、统计口径、舍入、单位、币种、时间边界等业务/计算规则的权威文档。
- `decisions/`：受控级别下难以回退的技术与架构决策。

禁止在多个文件中手工维护同一事实。其他文档必须链接到权威来源。代码变更完成前必须评估并同步受影响文档。
<!-- project-governance:managed:end -->

## 项目文档

- [运行环境](environments.md)：启动、目录、端口和停止方式。
- [执行记录与统计](rules/records.md)：事件来源、去重、时间、摘要边界和统计口径。
- [过程整理规则](rules/process.md)：无需模型的操作识别、测试报告、图关联和过程汇总口径。
- [验证记录](verification.md)：各次变更的测试范围、实际验证结果及文档影响。
