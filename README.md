# PCL-CE 无区域限制构建

跟踪上游 [`PCL-Community/PCL-CE`](https://github.com/PCL-Community/PCL-CE) 的 release，
自动拉取同版本源码、移除中国大陆区域限制、编译出 exe 并发布到本仓库的 Releases。

本仓库默认分支只放自动化脚本，上游代码不落地、不修改上游任何内容。

## 工作方式

```
cron（每 2 小时）
   └─ plan:  拉上游 release 列表 → 对比本仓库已有 release → 得出待构建 tag（单次上限 5 个）
        └─ build:  git clone --depth 1 --branch <tag> 上游源码
                   python scripts/strip_region_gate.py upstream   # 唯一改动
                   dotnet publish -c Release -p:Platform=x64|ARM64 --no-self-contained
                   gh release create <tag> ...                    # 以同名 tag 发布
```

手动触发：Actions → 「无区域限制构建」→ Run workflow，可填：

| 输入 | 作用 |
| --- | --- |
| `tag` | 指定上游 tag（留空 = 自动扫描） |
| `include_prerelease` | 是否处理 pre-release |
| `force` | 已发布过的 tag 也重建（产物覆盖上传） |

## 移除的是哪个限制

上游自 **2.15.1** 起（提交 `8cd9d37` / `1a76531`）新增区域判定：

- `PCL.Core/App/Region/RegionPolicy.cs`：读取 `GetUserDefaultGeoName`、注册表 `DeviceRegion`（GeoID 45）、
  时区、`zh-CN` 区域/首选语言，判定 `Mainland / Other / Unknown`；
  且 `IsRestricted => Mainland or Unknown`（判不出来也算受限，fail-closed）。
- `Plain Craft Launcher 2/Modules/Minecraft/RestrictedFeaturePolicy.cs`：**唯一出口**，
  被 15 处下载 / 安装 / 补全 / 启动前检查调用。

因此最小改动只有一处：

```diff
- internal static RegionAssessment Assess() => RegionPolicy.Evaluate(RegionPolicy.ReadWindowsSignals());
+ internal static RegionAssessment Assess() => new(RegionClassification.Other, "region-policy-disabled");
```

`IsRestricted` / `Check()` / `ThrowIfRestricted()` 全部以它为准，改一处即全部放行，
且不再弹 `Region.Feature.Restricted` 提示、不再写 `[RegionPolicy] 已阻止功能` 日志。

`scripts/strip_region_gate.py` 还做两件事：

1. **兜底**：若上游重构掉 `RestrictedFeaturePolicy`，改为在 `RegionPolicy.Evaluate` 开头插入早返回。
2. **审计**：全树扫描是否出现新的 `RegionPolicy.Evaluate(` / `RegionClassification.Mainland` 调用点，
   一旦上游把闸门搬到别处，构建会直接失败而不是悄悄产出一个仍然受限的 exe。

构建完还会做一次**产物自检**：在 exe 里查找 UTF-16 标记 `region-policy-disabled`，
查不到就判定补丁未生效并失败。

## 构建密钥（重要）

上游把密钥**编译期**写进 `EnvironmentInterop.SecretDictionary`：只有构建时存在
`PCL_WRITE_SECRET` 环境变量，source generator 才会把 `PCL_*` 变量嵌进程序。
Release 构建里 `Secrets.GetSecret(..., readEnvDebugOnly: true)` **不读**运行时环境变量，
所以缺什么只能重新编译，不能靠设置环境变量补救。

缺 `PCL_MS_CLIENT_ID` 的典型表现（启动即失败）：

```
System.InvalidOperationException: Microsoft OAuth client id is not configured.
  at PCL.Core.Minecraft.Profile.Authentication.MicrosoftProvider..ctor()
```

在仓库 Settings → Secrets and variables → Actions 配置（均可选，缺了只是对应功能不可用）：

| Secret | 作用 | 缺失后果 |
| --- | --- | --- |
| `PCL_MS_CLIENT_ID` | 微软 OAuth 公共客户端 ID | 正版验证不可用（本仓库已配置） |
| `PCL_CURSEFORGE_API_KEY` | CurseForge API Key | CurseForge 源下载 403 |
| `PCL_SENTRY_DSN` | 遥测 | 无影响 |
| `PCL_NAID_CLIENT_ID` / `PCL_NAID_CLIENT_SECRET` | Natayark 账号 | 该登录方式不可用 |
| `PCL_LINK_SERVER_ROOT` / `PCL_LOBBY_DEFAULT_SECRET` | 联机大厅 | 联机大厅不可用 |

`PCL_MS_CLIENT_ID` 是公共客户端 ID（不是密钥，设备码流程不需要 client secret）。
想用自己的：Azure Portal → 应用注册 → 账户类型选「个人 Microsoft 账户」→
身份验证里开启「允许公共客户端流」→ scope 用 `XboxLive.signin offline_access`，
拿到 Application (client) ID 后替换同名 secret 即可。

## 产物

每个 release 附带：

- `PCL2_CE_<tag>_x64_unrestricted.exe`
- `PCL2_CE_<tag>_ARM64_unrestricted.exe`
- `SHA256SUMS.txt`

与官方发布同规格：单文件、`--no-self-contained`（需要 .NET 10 Desktop Runtime）。
程序会在 exe 同级创建 `PCL` 数据目录，不会覆盖 `%APPDATA%\PCLCE` 的既有配置。

## 本地复现

```bash
git clone --depth 1 --branch v2.15.1 https://github.com/PCL-Community/PCL-CE.git upstream
python scripts/strip_region_gate.py upstream
dotnet publish "upstream/Plain Craft Launcher 2/Plain Craft Launcher 2.csproj" \
  -c Release -p:Platform=x64 -p:DeleteExistingFiles=true -o out/x64 --no-self-contained
```

## 维护

- 上游改了判定结构 → `strip_region_gate.py` 的 `audit()` 会让构建失败，按报错调整补丁位置即可。
- 只想补历史版本 → 用 `tag` 输入逐个触发，或调大 `MAX_PER_RUN`（默认 5，只处理 `MIN_VERSION` 及之后的版本）。
- GitHub 会在仓库 60 天无活动后暂停定时工作流：到 Actions 页面点一次 "Enable workflow"，
  或手动跑一次即可恢复。
- 上游代码版权归原作者，见上游 [LICENSE](https://github.com/PCL-Community/PCL-CE/blob/dev/LICENSE)。
