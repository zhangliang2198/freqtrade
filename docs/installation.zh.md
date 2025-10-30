# 安装

本页面解释如何为运行机器人准备你的环境。

freqtrade 文档描述了安装 freqtrade 的各种方法

* [Docker 镜像](docker_quickstart.md)（单独的页面）
* [脚本安装](#脚本安装)
* [手动安装](#手动安装)
* [使用 Conda 安装](#使用-conda-安装)

请考虑使用预构建的 [docker 镜像](docker_quickstart.md)快速开始，同时评估 freqtrade 的工作方式。

------

## 信息

对于 Windows 安装，请使用 [Windows 安装指南](windows_installation.md)。

安装和运行 Freqtrade 的最简单方法是克隆机器人的 Github 仓库，然后运行 `./setup.sh` 脚本（如果你的平台支持）。

!!! Note "版本考虑"
    克隆仓库时，默认工作分支的名称是 `develop`。该分支包含所有最新功能（由于自动化测试，可以认为是相对稳定的）。
    `stable` 分支包含上一个版本的代码（通常每月发布一次，基于大约一周前的 `develop` 分支快照，以防止打包错误，因此可能更稳定）。

!!! Note
    假定可用 [uv](https://docs.astral.sh/uv/) 或 Python3.11 或更高版本以及相应的 `pip`。如果不是这种情况，安装脚本将警告你并停止。还需要 `git` 来克隆 Freqtrade 仓库。
    此外，为了成功完成安装，必须提供 python 头文件（`python<yourversion>-dev` / `python<yourversion>-devel`）。

!!! Warning "保持时钟最新"
    运行机器人的系统时钟必须准确，足够频繁地与 NTP 服务器同步，以避免与交易所通信时出现问题。

------

## 要求

这些要求适用于[脚本安装](#脚本安装)和[手动安装](#手动安装)。

!!! Note "ARM64 系统"
    如果你运行的是 ARM64 系统（如 MacOS M1 或 Oracle VM），请使用 [docker](docker_quickstart.md) 运行 freqtrade。
    虽然通过一些手动努力可以进行原生安装，但目前不支持。

### 安装指南

* [Python >= 3.11](http://docs.python-guide.org/en/latest/starting/installation/)
* [pip](https://pip.pypa.io/en/stable/installing/)
* [git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
* [virtualenv](https://virtualenv.pypa.io/en/stable/installation.html)（推荐）

### 安装代码

我们收集了 Ubuntu、MacOS 和 Windows 的安装说明。这些是指南，你在其他发行版上的成功可能会有所不同。
首先列出特定于操作系统的步骤，下面的通用部分对所有系统都是必需的。

!!! Note
    假定可用 Python3.11 或更高版本以及相应的 pip。

=== "Debian/Ubuntu"
    #### 安装必要的依赖

    ```bash
    # 更新仓库
    sudo apt-get update

    # 安装包
    sudo apt install -y python3-pip python3-venv python3-dev python3-pandas git curl
    ```

=== "MacOS"
    #### 安装必要的依赖

    如果你还没有安装 [Homebrew](https://brew.sh/)，请先安装。

    ```bash
    # 安装包
    brew install gettext libomp
    ```
    !!! Note
        假设你的系统上已安装 brew，`setup.sh` 脚本将为你安装这些依赖。

=== "RaspberryPi/Raspbian"
    以下假定使用最新的 [Raspbian Buster lite 镜像](https://www.raspberrypi.org/downloads/raspbian/)。
    该镜像预装了 python3.11，使得 freqtrade 的启动和运行变得容易。

    使用 Raspbian Buster lite 镜像在 Raspberry Pi 3 上测试，应用了所有更新。


    ```bash
    sudo apt-get install python3-venv libatlas-base-dev cmake curl libffi-dev
    # 使用 piwheels.org 加速安装
    sudo echo "[global]\nextra-index-url=https://www.piwheels.org/simple" > tee /etc/pip.conf

    git clone https://github.com/freqtrade/freqtrade.git
    cd freqtrade

    bash setup.sh -i
    ```

    !!! Note "安装持续时间"
        根据你的网速和树莓派版本，安装可能需要几个小时才能完成。
        因此，我们建议按照 [Docker 快速入门文档](docker_quickstart.md)使用预构建的 docker 镜像用于树莓派。

    !!! Note
        上述操作不会安装 hyperopt 依赖。要安装这些，请使用 `python3 -m pip install -e .[hyperopt]`。
        我们不建议在树莓派上运行 hyperopt，因为这是一个非常消耗资源的操作，应该在强大的机器上完成。

------

## Freqtrade 仓库

Freqtrade 是一个开源加密货币交易机器人，其代码托管在 `github.com` 上

```bash
# 下载 freqtrade 仓库的 `develop` 分支
git clone https://github.com/freqtrade/freqtrade.git

# 进入下载的目录
cd freqtrade

# 你的选择 (1)：新手用户
git checkout stable

# 你的选择 (2)：高级用户
git checkout develop
```

(1) 此命令将克隆的仓库切换到使用 `stable` 分支。如果你希望保持在 (2) `develop` 分支上，则不需要此命令。

你稍后可以随时使用 `git checkout stable`/`git checkout develop` 命令在分支之间切换。

??? Note "从 pypi 安装"
    安装 Freqtrade 的另一种方法是从 [pypi](https://pypi.org/project/freqtrade/) 安装。缺点是此方法需要事先正确安装 ta-lib，因此目前不是推荐的安装 Freqtrade 的方法。

    ``` bash
    pip install freqtrade
    ```

------

## 脚本安装

安装 Freqtrade 的第一种方法是使用提供的 Linux/MacOS `./setup.sh` 脚本，该脚本安装所有依赖并帮助你配置机器人。

确保你满足[要求](#要求)并已下载 [Freqtrade 仓库](#freqtrade-仓库)。

### 使用 /setup.sh -install（Linux/MacOS）

如果你使用 Debian、Ubuntu 或 MacOS，freqtrade 提供了安装 freqtrade 的脚本。

```bash
# --install，从头开始安装 freqtrade
./setup.sh -i
```

### 激活你的虚拟环境

每次打开新终端时，你必须运行 `source .venv/bin/activate` 来激活你的虚拟环境。

```bash
# 激活虚拟环境
source ./.venv/bin/activate
```

[你现在已准备好](#你已准备好)运行机器人。

### /setup.sh 脚本的其他选项

你还可以使用 `./script.sh` 更新、配置和重置机器人的代码库

```bash
# --update，执行 git pull 以更新。
./setup.sh -u
# --reset，硬重置你的 develop/stable 分支。
./setup.sh -r
```

```
** --install **

使用此选项，脚本将安装机器人和大多数依赖：
你需要事先安装 git 和 python3.11+ 才能正常工作。

* 必需的软件，如：`ta-lib`
* 在 `.venv/` 下设置你的 virtualenv

此选项是安装任务和 `--reset` 的组合

** --update **

此选项将拉取当前分支的最新版本并更新你的 virtualenv。定期使用此选项运行脚本以更新你的机器人。

** --reset **

此选项将硬重置你的分支（仅当你在 `stable` 或 `develop` 上时）并重新创建你的 virtualenv。
```

-----

## 手动安装

确保你满足[要求](#要求)并已下载 [Freqtrade 仓库](#freqtrade-仓库)。

### 设置 Python 虚拟环境（virtualenv）

你将在分离的 `虚拟环境` 中运行 freqtrade

```bash
# 在目录 /freqtrade/.venv 中创建 virtualenv
python3 -m venv .venv

# 运行 virtualenv
source .venv/bin/activate
```

### 安装 python 依赖

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
# 安装 freqtrade
python3 -m pip install -e .
```

[你现在已准备好](#你已准备好)运行机器人。

### （可选）安装后任务

!!! Note
    如果你在服务器上运行机器人，你应该考虑使用 [Docker](docker_quickstart.md) 或终端多路复用器，如 `screen` 或 [`tmux`](https://en.wikipedia.org/wiki/Tmux)，以避免机器人在注销时停止。

在带有软件套件 `systemd` 的 Linux 上，作为可选的安装后任务，你可能希望将机器人设置为作为 `systemd 服务`运行，或将其配置为将日志消息发送到 `syslog`/`rsyslog` 或 `journald` 守护进程。有关详细信息，请参阅[高级日志记录](advanced-setup.md#高级日志记录)。

------

## 使用 Conda 安装

Freqtrade 也可以使用 Miniconda 或 Anaconda 安装。我们建议使用 Miniconda，因为它的安装占用空间更小。Conda 将自动准备和管理 Freqtrade 程序的广泛库依赖。

### 什么是 Conda？

Conda 是一个用于多种编程语言的包、依赖和环境管理器：[conda 文档](https://docs.conda.io/projects/conda/en/latest/index.html)

### 使用 conda 安装

#### 安装 Conda

[在 linux 上安装](https://conda.io/projects/conda/en/latest/user-guide/install/linux.html#install-linux-silent)

[在 windows 上安装](https://conda.io/projects/conda/en/latest/user-guide/install/windows.html)

回答所有问题。安装后，必须关闭并重新打开终端。

#### Freqtrade 下载

下载并安装 freqtrade。

```bash
# 下载 freqtrade
git clone https://github.com/freqtrade/freqtrade.git

# 进入下载的目录 'freqtrade'
cd freqtrade
```

#### Freqtrade 安装：Conda 环境

```bash
conda create --name freqtrade python=3.12
```

!!! Note "创建 Conda 环境"
    conda 命令 `create -n` 会自动为选定的库安装所有嵌套依赖，安装命令的一般结构是：

    ```bash
    # 选择你自己的包
    conda env create -n [环境名称] [python 版本] [包]
    ```

#### 进入/退出 freqtrade 环境

要检查可用环境，请输入

```bash
conda env list
```

进入已安装的环境

```bash
# 进入 conda 环境
conda activate freqtrade

# 退出 conda 环境 - 现在不要这样做
conda deactivate
```

使用 pip 安装最后的 python 依赖

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
```

[你现在已准备好](#你已准备好)运行机器人。

### 重要快捷方式

```bash
# 列出已安装的 conda 环境
conda env list

# 激活 base 环境
conda activate

# 激活 freqtrade 环境
conda activate freqtrade

# 停用任何 conda 环境
conda deactivate
```

### 有关 anaconda 的更多信息

!!! Info "新的大型包"
    在创建时填充了选定包的新 Conda 环境可能比将大型、重型库或应用程序安装到先前设置的环境中花费的时间更少。

!!! Warning "在 conda 中使用 pip install"
    conda 的文档说不应该在 conda 中使用 pip，因为可能会出现内部问题。
    但是，它们很少见。[Anaconda 博客文章](https://www.anaconda.com/blog/using-pip-in-a-conda-environment)

    尽管如此，这就是为什么首选 `conda-forge` 频道：

    * 有更多库可用（减少对 `pip` 的需求）
    * `conda-forge` 与 `pip` 配合得更好
    * 库更新

祝交易愉快！

-----

## 你已准备好

你已经走到这一步，所以你已经成功安装了 freqtrade。

### 初始化配置

```bash
# 步骤 1 - 初始化用户文件夹
freqtrade create-userdir --userdir user_data

# 步骤 2 - 创建新的配置文件
freqtrade new-config --config user_data/config.json
```

你已准备好运行，阅读[机器人配置](configuration.md)，记住从 `dry_run: True` 开始并验证一切正常。

要了解如何设置配置，请参阅[机器人配置](configuration.md)文档页面。

### 启动机器人

```bash
freqtrade trade --config user_data/config.json --strategy SampleStrategy
```

!!! Warning
    你应该阅读其余的文档，回测你要使用的策略，并在使用真实资金之前使用模拟运行。

-----

## 故障排除

### 常见问题："command not found"

如果你使用了 (1)`脚本` 或 (2)`手动` 安装，你需要在虚拟环境中运行机器人。如果你收到如下错误，请确保 venv 处于活动状态。

```bash
# 如果：
bash: freqtrade: command not found

# 那么激活你的虚拟环境
source ./.venv/bin/activate
```

### MacOS 安装错误

较新版本的 MacOS 可能会安装失败，出现类似 `error: command 'g++' failed with exit status 1` 的错误。

此错误需要显式安装 SDK 头文件，这些头文件在此版本的 MacOS 中默认不安装。
对于 MacOS 10.14，可以使用以下命令完成。

```bash
open /Library/Developer/CommandLineTools/Packages/macOS_SDK_headers_for_macOS_10.14.pkg
```

如果此文件不存在，那么你可能使用的是不同版本的 MacOS，因此你可能需要咨询互联网以获取具体的解决方案细节。
