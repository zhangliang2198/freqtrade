# Windows 安装指南

我们**强烈**建议 Windows 用户优先选择 [Docker](docker_quickstart.md) 方案——整体流程更简单、流畅且更安全。

若无法使用 Docker，可尝试 Windows Subsystem for Linux（WSL），通常可以直接套用 Ubuntu 的安装步骤。

若以上方法都不可行，请按以下步骤在原生 Windows 环境中安装。以下所有说明假定已安装可用的 Python 3.11 及以上版本。

## 克隆仓库

首先克隆项目仓库：

```powershell
git clone https://github.com/freqtrade/freqtrade.git
```

接下来可选择自动脚本安装（推荐）或手动安装。

## 自动安装

### 运行安装脚本

脚本会通过几个问答确认需要安装的组件：

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass
cd freqtrade
. .\setup.ps1
```

## 手动安装

!!! Note "请使用 64 位 Python"
    请确保使用 64 位 Windows 和 64 位 Python。32 位 Python 已不再支持，并且会因内存限制导致回测或 Hyperopt 失败。

!!! Hint
    使用 [Anaconda](https://www.anaconda.com/distribution/) 可以显著简化 Windows 上的环境配置。详见文档的 [Conda 安装章节](installation.md#installation-with-conda)。

### 常见安装错误

```bash
error: Microsoft Visual C++ 14.0 is required. Get it with "Microsoft Visual C++ Build Tools": http://landinghub.visualstudio.com/visual-cpp-build-tools
```

部分需要编译的第三方包没有预编译轮子，因此必须安装 C/C++ 编译器。可从 [Visual Studio 官网](https://visualstudio.microsoft.com/visual-cpp-build-tools/) 下载“Desktop development with C++”工具集，按默认选项安装。由于该依赖较大，如有可能请优先考虑 WSL2 或 [docker compose](docker_quickstart.md)。

![Windows 安装](assets/windows_install.png)
