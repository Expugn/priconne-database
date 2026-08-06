# 公主连结国服、台服与日服数据库自动恢复

这个项目会定时取得《超异域公主连结☆Re:Dive》国服、台服、日服最新 `master.db`，恢复可读表名和字段名，并由 GitHub Actions 自动提交结果。

## 恢复优先级

国服：

1. 从国服官方 App Store 取得 iOS 客户端版本，再匿名查询官方 CDN 地址与清单版本，不执行账号登录。
2. 只检查 iOS 官方 CDN 清单；候选版本仅包含官方响应、内置的 `202607312107` iOS 基线和手动传入的版本，不读取 Expugn、Estertion 或当前产物进行版本交叉核验。只接受实际可下载且 MD5、文件大小、SQLite 完整性均正确的版本。
3. 只使用你提供的 `rainbow_cn.json`；未覆盖部分使用仓库中已提交的国服上一版可读库，再使用缓存的上一版原库与映射迁移。

台服：

1. 优先直接使用台服 `rainbow_tw.json`。
2. 数据库更新而彩虹表尚未更新时，用缓存的台服上一版本和上一版映射迁移名称。
3. 首次运行又没有上一版缓存时，才使用上游保存的历史可读库引导恢复。

日服：

1. 优先下载 [roboninon.win 可读数据库](https://roboninon.win/db/download?compressed=true)，校验响应文件名中的版本、解压并执行 SQLite 完整性检查。
2. 外部源不可用、版本滞后或文件损坏时，用缓存的日服上一版本恢复。
3. 缓存也不存在时，使用上游最后可读日服版本引导恢复。

国服数据库直接来自官方 iOS CDN。台服和日服的版本信息及历史引导库来自 [Expugn/priconne-database](https://github.com/Expugn/priconne-database)。

## 自动更新

工作流位于 `.github/workflows/update-databases.yml`，每 6 小时检查三服，也可以在 Actions 页面手动运行。

生成文件：

- `data/master_cn_unhash.db`、`data/master_tw_unhash.db`、`data/master_jp_unhash.db`：可读 SQLite 数据库。
- `data/mapping_cn.json`、`data/mapping_tw.json`、`data/mapping_jp.json`：恢复方式和名称映射。
- `data/version_cn.json`、`data/version_tw.json`、`data/version_jp.json`：上游版本和资源哈希。
- `data/REPORT_cn.md`、`data/REPORT_tw.md`、`data/REPORT_jp.md`：恢复来源、覆盖率和完整性检查结果。

无需配置个人访问令牌；工作流使用仓库自带的 `GITHUB_TOKEN`。请在仓库设置中确认 Actions 的 Workflow permissions 为 **Read and write permissions**。

## 本地运行

需要 Python 3.11 或更高版本。日服压缩源需要 Brotli：

```powershell
python -m pip install -r requirements.txt
python scripts/priconne_unhash.py update-cn --rainbow rainbow_cn.json
python scripts/priconne_unhash.py update `
  --rainbow rainbow_tw.json
python scripts/priconne_unhash.py update-jp
```

`rainbow_cn.json` 仅用于国服，不会参与台服恢复。国服内置 `202607312107` 作为最低 iOS 清单基线；如果知道更新的官方 iOS 清单版本，可额外传入 `--display-version`。当前产物不会参与版本发现，只会作为同服上一版可读库帮助恢复名称。

如果台服还有自己的可读参考库，可以重复传入：

```powershell
python scripts/priconne_unhash.py update `
  --reference "my-tw=C:\path\redive_tw.db=95" `
  --reference "my-jp=C:\path\redive_jp.db=60"
```

参数最后的数字是参考库优先级；同区服、时间越近的库应设置得越高。

## 安全策略

程序只应用彩虹表直接命中、同服上一版本数据匹配或参考库一致支持的名称。不能可靠判断的表和字段会保留原哈希名，不会强行猜测。外部日服库必须与上游 TruthVersion 一致，所有输出都会执行 SQLite `integrity_check`。

## 致谢与说明

台服、日服抓取流程和历史数据库参考 [Expugn/priconne-database](https://github.com/Expugn/priconne-database)；国服仅访问官方 iOS 来源。本项目只用于资料研究与数据保存；游戏及数据版权归原权利人所有。
