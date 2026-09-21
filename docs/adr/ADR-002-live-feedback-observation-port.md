# ADR-002：Live Feedback 通过注入的 Observation Port 写入

状态：Accepted；日期：2026-09-21；任务：FEEDBACK-LIVE-001（实现准备，真实验收仍待完成）。

Live Feedback 将平台窗口转换为四类 Observation。Analytics 已拥有 Observation
校验、去重、版本、审计和事件；反馈模块不应再实现另一套存储规则。

`LiveFeedbackService` 必须接收 `ObservationPort`，只调用其公开命令
`record_observation`。调用方在组合入口注入 Analytics 的 `ObservationService`。
领域模块不导入 Analytics、adapter、infra 或 app；架构检查规则保持不变。

每个窗口使用四个稳定子命令幂等键。若写入中断，窗口成功记录尚未产生；使用原键
重试时，已写入观察由 Analytics 复用，其余继续写入。该协议是可恢复的逐条写入，
不声称四条观察具备跨模块事务原子性。整体完成后才生成窗口审计记录。

账号证据必须绑定租户和连接；证据摘要参与命令摘要。测试使用 synthetic fixture，
平台接入层将来必须提供经过官方授权及健康校验的证据，不能将请求方自报的
`status=verified` 当作真实授权。真实环境仍受 EXT-ACCOUNT-001 门槛约束。

验证：`tests/unit/feedback/test_live_feedback_service.py` 使用实际 ObservationService，
覆盖中途失败后恢复，确认最终只有四条观察及八条既有 Analytics 事件；契约测试
检查四类结果都符合 Observation Schema。移除 Port 注入调用即可回退该准备性接入，
不涉及现有业务表迁移。
