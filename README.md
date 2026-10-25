# GoodNight UESTC

> 为什么之前的项目都失效了？
>
> 因为伟大的腾讯。这个签到目前需求一个由腾讯服务器签发的token用于识别是否是小程序签到。之前的项目都仅仅使用WebUI接口，很显然会被拒绝。
>
> 本项目使用[YYB-Go-Enhanced](https://github.com/525815266/YYB-Go-Enhanced)运行一个轻量级微信登陆状态管理系统，用于请求`wx.login()`接口。
>
> 并且使用`httpx`复刻了UESTC的登陆过程，因此无需`playwright`等无头浏览器模拟。因此将docker镜像压制在几百MB级。

电子科技大学晚安签到控制台，集成学校 IDAS 登录及
[YYB-Go-Enhanced](https://github.com/525815266/YYB-Go-Enhanced) 微信后端。

[English](README.en.md) · [应用 HTTP API](docs/api.md) · [登录包 API 与 CAS 流程](login/docs/api.md)

登录、短信验证、CAS 换票和签到均使用 `httpx`，不再运行 Playwright 或 Chromium。Nginx 在后端健康检查通过后启动。

## 快速开始

普通用户只需要 Docker Compose。`compose.yaml` 使用已发布的 GHCR 镜像，
无需 Node.js 或源码构建。在 `compose.yaml` 所在目录执行：

```sh
docker compose pull
docker compose up -d
```

打开 [http://localhost:8000](http://localhost:8000)。`goodnight-data` 数据卷保存
学校会话、可选密码、加密密钥、签到提交记录和微信凭据；备份时保留整个数据卷。
默认端口仅监听本机。远程使用时请通过可信网络或带身份验证的反向代理访问；
此应用是单管理员控制台。

更新时再次执行上述命令。可在 `.env` 中设置 `GOODNIGHT_IMAGE` 来固定已发布版本，
或使用 Docker Hub 镜像，例如 `GOODNIGHT_IMAGE=starstreammm/goodnight-uestc-docker:latest`。
`GOODNIGHT_PORT` 可修改本机端口（默认 `8000`）。用户配置默认关闭学校 HTTP 原始日志。

### 本地构建与测试环境

开发者还需要 Node.js 24 和 npm。**前端必须在宿主机构建**，Docker 仅复制已有产物。
通过显式加载 `compose.local.yaml` 构建 `goodnight-uestc-docker:local`，并默认开启
HTTP 原始日志；普通用户启动时不会自动加载此文件。

```sh
npm --prefix app ci
npm --prefix app run build
GOODNIGHT_PORT=8002 docker compose -p goodnight-local -f compose.yaml -f compose.local.yaml up -d --build
```

打开 [http://localhost:8002](http://localhost:8002)。`goodnight-local` 项目使用独立数据卷，
后续本地命令也应使用相同项目名及两个 `-f` 参数。若要用本地源码更新现有部署，
省略 `-p goodnight-local` 和端口覆盖，即可保留原 Compose 项目及其数据卷。

### 镜像发布

GitHub Actions 在 `app/` 中构建前端，再向 Docker Hub 和 GHCR 发布
`linux/amd64`、`linux/arm64` 镜像。推送 `main` 时发布 `main` 和 `latest`；
Git 标签发布同名镜像标签，不含 `-` 的标签还会更新 `latest`。
`v0.2.0-rc.1` 等预发布标签不会更新 `latest`。SemVer 标签还生成去掉前导 `v` 的版本别名，
每次构建也生成 `sha-` 标签。仓库需配置 Docker Hub 的 `DOCKER_USERNAME`、
`DOCKER_PASSWORD` secrets；GHCR 使用 `GITHUB_TOKEN`。GHCR 包需设为公开才能匿名拉取。
工作流只发布镜像，不创建 GitHub Release。

镜像从固定摘要的上游多架构镜像复制 YYB 二进制，来源见 Dockerfile 的
`YYB_IMAGE`。YYB 只监听容器内的 **127.0.0.1:8001**，不映射端口、不提供反向代理，
用户无法访问其 Web UI。应用自动生成私有管理凭据并在内部认证，用户无需接触
YYB 的登录页、令牌或账号编号。更新上游时，可核对兼容性后用
`docker build --build-arg YYB_IMAGE=... .` 指定新镜像。

## 账号操作

1. 输入学号和学校密码；别名可留空，默认使用学校返回的真实姓名。
2. 按学校要求完成短信二次认证。
3. 使用微信扫描二维码并在手机上确认。
4. 在最终确认窗口核对学校用户信息、签到时间和位置范围，选择位置后点击“确认并保存”。取消不会保存新账号。
5. 每个账号提供 **详情、设置、立即运行、更多** 四个按钮。

详情显示学校用户信息、签到安排和位置、学校会话的本地到期时间，以及 YYB 报告的微信凭据到期时间。
微信凭据可能自动续期，因此此时间不等于最终必须重新扫码的时间。设置可以修改
别名、选择学校允许的签到位置、删除已保存密码。更多包含重新登录和删除账号。
删除账号时也会删除关联微信记录；若其他学校账号仍引用该微信，则保留共享记录。

**更多 → 使用新浏览器指纹重新登录** 会使用新指纹和全新 Cookie，重新完成学校与
微信登录。点击 **确认并保存** 后才会替换原有指纹和会话。
尚未确认保存的账号，每次重新发起登录都会使用新指纹，包括“添加账号”失败后的重试。

密码仅在用户开启开关后加密保存在本地。未开启时，会话最多使用七天，验证会话
不会延长此期限，到期后必须重新输入密码。学校也可能提前撤销会话。已保存密码时
可以自动重新登录，但短信验证和验证码仍需要用户参与。短信码、微信一次性 code
和签到 ticket 不持久化。密钥与密文均位于数据卷中，请保护整个数据卷。

## 签到流程

在七天本地租期内，先通过 `/api/isLoginFailure` 验证上次的 jzsz 会话；有效时直接
复用且不延长租期，超时或响应格式异常时停止续期。确认失效后，由 `uestc-login`
尝试通过 CAS 换取新会话，再按
用户选择使用已保存密码续期。后台定期读取学校用户信息、允许位置范围、生效时间
和今日签到记录。每日计划采用学校返回的时间范围，尚未获取时使用备用配置。
保留最后五分钟作为提交余量；服务重启后，只要仍在截止时间前就可以补执行。
提交前会再次确认学校允许时间及今日记录。

学校请求沿用手动脚本中的 Safari 请求头和 Cookie 名称过滤规则，每次发送前等待
2.3 秒，网络请求总超时为 30 秒。CAS 保留 `https://jzsz.uestc.edu.cn/#/hall/home`
服务地址，新会话先检查登录状态，再验证小程序用户信息。

需要签到时，为 `wxaa78bf2905f01cee` 获取新的 `wx.login` code，用同一个 jzsz
会话调用 `/platform-app/api/auth/checkin-ticket`，再将凭证放入
`X-Checkin-Ticket`。提交包含 GCJ-02 定位字段，沿用项目现有的学校位置中心坐标。

持久化提交记录防止网络结果不明时重复 POST；只有学校签到记录确认后才显示成功。
“立即运行”也遵守学校时间和防重复规则。结果持续待确认时，应查看学校官方记录。

## Python 开发和测试

使用已有的 jzsz `SESSION` 手动查询 Goodnight，在仓库根目录运行：

```sh
uv run --project goodnight python goodnight/manual_test.py
```

在隐藏输入提示中粘贴 cookie 值或 `SESSION=value`，也可通过 `--session VALUE`
传入。脚本只发送三个查询请求，输出 JSON：`location` 为允许位置列表，`status`
为今日记录及解析状态，`schedule` 为学校生效时间和当前签到窗口（上海时区，包含
提前五分钟截止规则），不会提交签到。每项包含 `ok` 和数据或错误；任一查询失败
退出码为 1，否则为 0。这里的学校时间表不包含应用本地随机选定的执行时间。

两个 Python 项目分别使用 uv，不共用虚拟环境或锁文件：

```sh
(cd login && uv sync --frozen && uv run pytest)
(cd goodnight && uv sync --frozen && uv run pytest)
npm --prefix app run typecheck
npm --prefix app run build
```

在仓库根目录运行：
`uv run --project goodnight uvicorn goodnight.main:app --host 127.0.0.1 --port 8000`。
完整本地登录还需要通过 `goodnight.yyb_process` 启动私有 YYB 二进制，并使用相同
的 `DATA_DIR`；Docker 会自动完成。

测试使用虚构账号和离线接口。真实学校登录、短信发送、微信确认和签到仍需使用
实际账号验证，本次测试没有提交真实账号或执行真实签到，也未把抓包凭据写入代码。
旧版本数据库及签到提交记录会保留；旧账号缺少新租期和微信绑定，需要重新连接。

密码加密分析见 [login/docs/password-encryption.md](login/docs/password-encryption.md)。

## 目录与依赖

- `login/`：独立的 `uestc-login` Python 包，拥有自己的 `pyproject.toml`、
  `uv.lock`、`.venv` 和测试。包含密码登录、浏览器标识、短信二次认证、加密保存、
  七天会话租期，以及 `uestc_login/skill/` 服务适配器；jzsz 返回 `SESSION` 字符串。
- `goodnight/`：独立 uv 项目，通过本地路径依赖 `../login`。包含应用 API、
  账号存储、学校接口、微信适配器和定时任务。
- `app/`：React 界面及独立 npm 依赖。中文浏览器默认中文，其他语言默认英文；
  顶部语言开关的选择保存在浏览器中。
