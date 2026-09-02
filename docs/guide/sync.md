# 跨设备同步（`scrinium sync`）

在不同设备的 Scrinium 实例之间同步知识库（`data/`）与工作区（`workspace/`）。论文全文（paper.md、paper.pdf、images/、notes.md）、元数据（meta.json）、标签（tags.yaml）、索引（index.db）和工作区定义（papers.json）都包含在内。

> `scrinium export` / `scrinium import` 处理的是引用格式（bibtex/ris/markdown/docx）和外部导入（Endnote/Zotero），不能用于同步知识库本身。

## 子命令

| 子命令 | 作用 |
|---|---|
| `scrinium sync push <target>` | 推送 `data/` + `workspace/` 到目标 |
| `scrinium sync pull <target>` | 从目标拉取到本地 |
| `scrinium sync status <target>` | 显示将要变更的文件（dry-run，不实际变更） |
| `scrinium sync export <file.tar.gz>` | 打包为归档文件（离线/网盘/U盘传输） |
| `scrinium sync import <file.tar.gz>` | 从归档文件导入 |

## 目标格式

- SSH：`user@host:remote/path/to/scrinium`（如 `wm2:~/scrinium`）
- 本地路径：`/path/to/other/scrinium`（同机另一实例或共享盘）

## 同步语义

- **默认 `--update`（安全）**：只复制源端更新或目标端不存在的文件，**不删除任何文件**。不会丢数据。
- **`--mirror`（镜像）**：删除目标端在源端不存在的文件。先做一次 dry-run 预览将删除的文件，要求加 `--yes` 确认后才执行。
- **`status`**：dry-run，列出将变更的文件，不实际执行。

## 排除项（默认不同步）

- `data/inbox*`（暂存区）
- `*.log`、`scholaraio.log*`、`metrics.db`、`.coverage`
- `__pycache__/`、`.DS_Store`、`trash/`、`topic_model/`

`index.db` 可以不传（目标端 `scrinium index` 可重建），传了则省去重建。

## 示例

```bash
# 笔记本推送到集群
scrinium sync push wm2:~/scrinium

# 从集群拉取
scrinium sync pull wm2:~/scrinium

# 先看会改什么
scrinium sync status wm2:~/scrinium

# 离线传输
scrinium sync export sync_backup.tar.gz
# 把 sync_backup.tar.gz 传到另一台设备后：
scrinium sync import sync_backup.tar.gz
```

## 注意

- 这是**文件级同步**：meta.json 冲突以文件 mtime 新旧为准，不做按字段合并。
- 双向编辑同一份文件时，后写方会覆盖先写方；如需双向编辑，请用 git 管理 `data/` 和 `workspace/`。
