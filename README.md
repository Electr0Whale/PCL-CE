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
- 只想补历史版本 → 用 `tag` 输入逐个触发，或调大 `MAX_PER_RUN`。
- 上游代码版权归原作者，见上游 [LICENSE](https://github.com/PCL-Community/PCL-CE/blob/dev/LICENSE)。
