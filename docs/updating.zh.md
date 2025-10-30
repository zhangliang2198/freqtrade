# 更新指南

请选择与你的安装方式对应的更新方法。

!!! Note "关注变更"
    每次发布都会附带更新日志，记录破坏性变更或行为调整。若使用 develop 分支，请关注相关 PR，以免突发变动。

## Docker

!!! Note "旧版 master 镜像"
    我们已将发布镜像从 `master` 切换为 `stable`，请将 `freqtradeorg/freqtrade:master` 改为 `freqtradeorg/freqtrade:stable`。

```bash
docker compose pull
docker compose up -d
```

## setup 脚本安装

```bash
./setup.sh --update
```

!!! Note
    更新时请确保未激活虚拟环境。

## 原生安装

请务必同时更新依赖：

```bash
git pull
pip install -U -r requirements.txt
pip install -e .

# 更新 FreqUI
freqtrade install-ui
```

### 常见问题

更新失败通常是因为依赖缺失或第三方组件安装错误（如 TA-Lib）。请参考相应的安装排障章节获取更多帮助。
