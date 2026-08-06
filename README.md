# 公主连结国服、台服与日服数据库自动恢复

这个项目会定时取得《超异域公主连结☆Re:Dive》国服、台服、日服最新 `master.db`，恢复可读表名和字段名，并由 GitHub Actions 自动提交结果。

## 恢复优先级

国服：

1. 从国服官方 App Store 取得 iOS 客户端版本，只检查官方 iOS CDN，不登录账号或读取第三方数据库仓库。
2. 优先使用 `rainbow_cn.json`；数据库更新而彩虹表尚未更新时，用缓存或仓库中的国服上一版本迁移名称。

台服：

1. 直接检查 `img-pc.so-net.tw` 官方 iOS CDN，发现并下载最新台服数据库。
2. 优先使用台服 `rainbow_tw.json` 恢复名称。
3. 数据库更新而彩虹表尚未更新时，用缓存或仓库中的台服上一版本迁移名称。

日服：

1. 从日服官方 iOS CDN 主动发现最新版本，下载官方 CDB 并校验 MD5 与文件大小。
2. 官方 CDB 仍是加密格式，因此使用 [roboninon.win 可读数据库](https://roboninon.win/db/download?compressed=true) 提供同版本的可读反哈希结果；只有版本与官方 iOS 清单一致才会接受。
3. roboninon 不可用、版本滞后或文件损坏时，保留上一版可读日服数据库，等待下次重试。

国服和台服数据库直接来自各自官方 iOS CDN；日服数据库来自 roboninon.win，并由日服官方 iOS CDN 验证版本。项目不读取其他数据库仓库。

## 自动更新

工作流位于 `.github/workflows/update-databases.yml`，每 6 小时检查三服，也可以在 Actions 页面手动运行。

生成文件：

- `data/master_cn_unhash.db`、`data/master_tw_unhash.db`、`data/master_jp_unhash.db`：可读 SQLite 数据库。
- `data/version_cn.json`、`data/version_tw.json`、`data/version_jp.json`：版本和资源哈希。

名称映射和恢复报告只保存在 GitHub Actions 的 `.cache` 内部状态中，不提交到仓库。映射用于把上一版已确认名称迁移到新哈希，并记录彩虹表命中结果；数据库使用者不需要下载它。

## 历史数据库与下载 API

每次出现新版本时，Action 会按照“区服、版本号、UTC 日期”把可读数据库归档到 GitHub Releases，并更新 `data/history.json`。历史大文件不会反复塞进 Git 提交记录，适合长期保存和考古。

仓库包含一个无需额外依赖的 Vercel Python API。将仓库连接到 Vercel 后可使用：

- `/api/databases`：列出三服最新版和全部历史版本。
- `/api/databases?region=cn`：只查看指定区服，可选 `cn`、`tw`、`jp`。
- `/api/databases?region=cn&version=202607312107`：查找指定版本。
- `/api/databases?region=cn&download=1`：重定向下载最新版数据库。

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
  --reference "my-tw=C:\path\redive_tw.db=95"
```

参数最后的数字是参考库优先级；同区服、时间越近的库应设置得越高。

## 安全策略

程序只应用彩虹表直接命中、同服上一版本数据匹配或参考库一致支持的名称。不能可靠判断的表和字段会保留原哈希名，不会强行猜测。外部日服库的版本必须在日服官方 iOS CDN 中真实存在，所有输出都会执行 SQLite `integrity_check`。

## 致谢与说明

本项目只用于资料研究与数据保存；游戏及数据版权归原权利人所有。
