# FOUND-003B 存储键规则

此增量关闭总体审计中的存储键边界问题；历史配置 baseline 和数据库迁移保持不变。

- org_id 与 namespace 是单段 NFC Unicode 文本，UTF-8 最多 128 字节；不得为空、包含斜杠/反斜杠、空白、控制字符、格式控制字符、孤立代理或 URI 分隔字符 `%?#`，不得为 `.`/`..`。
- object_key 是 NFC Unicode 相对路径，禁止空段、`.`/`..`、反斜杠、控制字符（Unicode Cc/Cf/Cs）和 `%?#`；每段首尾不得有空白。允许段内空格、中文和 emoji。
- 实际存储键 `namespace/org_id/object_key` UTF-8 总长度最多 1024 字节。桶名不计入此长度。对象元数据 Schema 的 maxLength 是字符数上界，UTF-8 总长度、Unicode 类别与 NFC 必须由 StoragePort 运行时进一步校验。
- 键按输入精确保存，不 trim、不 Unicode 归一化、不做 URL 解码或路径折叠；调用方必须显式修正非法键。引用只使用 canonical private URI，读/写/删采用同一验证策略。

兼容性：新增规则会拒绝旧版可接受的含控制字符、超长或非 NFC 键。这是无真实存储接入前的显式契约收紧。已有合法 ASCII/synthetic 引用保持不变；没有自动重命名、删除或搬迁对象。若后续接入历史对象，先离线审计键并建立显式迁移映射，不可静默归一化合并。

这是一套项目 StoragePort 规则；后续 S3 adapter 必须保持相同键语义，不能将 Fake 验收视为真实供应商接入验证。测试应包括写入与读取路径、租户隔离、控制字符、非 NFC、Unicode 字节长度及无写入副作用。
