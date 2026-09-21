# Foundation 数据库初始化

`alembic upgrade head` 仅执行 Python revision，不会自动执行之前接受的 SQL 基线。全新数据库使用统一入口：

```powershell
python scripts/bootstrap_foundation_db.py --database-url "sqlite:///local-foundation.db"
```

目标必须显式指定；上例会在当前目录创建本地测试数据库，不应在生产环境照搬。运行前确认目标并备份已有数据，使用独占维护窗口，不允许两个初始化进程同时执行。

入口顺序：固定白名单中的 12 个历史 SQL 文件（16 条幂等建表/索引语句），然后在同一连接执行 Alembic `upgrade head`。不改写历史迁移，不插入业务种子，不删除表或数据。环境变量中的 DATABASE_URL 不会替换显式连接。

当前验证范围：临时 SQLite 空库初始化、重复运行、保留已有数据、队列表和索引存在、Alembic 版本一致。PostgreSQL 需要安装合适驱动并在隔离测试实例另行验证；未宣称生产可用。

限制：`IF NOT EXISTS` 不是已有表结构校验器。旧环境若存在同名但结构不同的表，应先比较结构并编写审查过的增量迁移，不可依靠本入口自动修复。初始化不创建真实账号，也不启动 Worker。失败后检查数据库实际状态；SQLite DDL 的回滚行为依驱动而异，不宣称跨方言全程原子回滚。
