#!/usr/bin/env python3
"""PCL-CE 区域限制移除器（最小改动）。

对上游指定 tag 的源码树做且仅做一件事：让 ``RestrictedFeaturePolicy`` 恒定判定为「不受限」。

为什么一处就够：2.15.1 起所有下载 / 安装 / 补全 / 启动前检查入口（15 处）都经过
``PCL.RestrictedFeaturePolicy`` 的 ``IsRestricted`` / ``Check`` / ``ThrowIfRestricted``，
而这三者全部以 ``Assess()`` 的返回值 ``RegionAssessment.IsRestricted`` 为准。
把 ``Assess()`` 改成恒定返回 ``Other``，全部入口同时放行，且不触发提示、不写拦截日志。

用法：
    python scripts/strip_region_gate.py <源码根目录>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:  # Windows runner 的默认代码页可能不是 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 老环境没有 reconfigure 时忽略
    pass

POLICY = Path("Plain Craft Launcher 2/Modules/Minecraft/RestrictedFeaturePolicy.cs")
REGION = Path("PCL.Core/App/Region/RegionPolicy.cs")
TEST = Path("PCL.Core.Test/RegionPolicyTest.cs")

MARKER = "region-policy-disabled"
PATCHED_ASSESS = (
    "internal static RegionAssessment Assess() => "
    'new(RegionClassification.Other, "region-policy-disabled");'
)

ASSESS_RE = re.compile(
    r"internal\s+static\s+RegionAssessment\s+Assess\s*\(\s*\)\s*=>\s*[^;]+;", re.S
)
EVALUATE_RE = re.compile(
    r"(public\s+static\s+RegionAssessment\s+Evaluate\s*\(\s*RegionSignals\s+\w+\s*\)\s*\r?\n\s*\{)",
    re.S,
)


def fail(message: str) -> None:
    print(f"::error::{message}")
    sys.exit(1)


def patch_policy(root: Path) -> bool:
    """首选路径：改 RestrictedFeaturePolicy.Assess()。"""
    path = root / POLICY
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8-sig")
    if MARKER in text:
        print(f"[skip] {POLICY} 已是无限制版本")
        return True
    patched, count = ASSESS_RE.subn(PATCHED_ASSESS, text)
    if count != 1:
        print(f"[warn] {POLICY} 中 Assess() 匹配 {count} 处，放弃该路径")
        return False
    path.write_text(patched, encoding="utf-8")
    print(f"[ok] 已改写 {POLICY} 的 Assess()（1 行）")
    return True


def patch_region(root: Path) -> bool:
    """兜底路径：上游若重构掉 RestrictedFeaturePolicy，则在 RegionPolicy.Evaluate 开头直接返回。"""
    path = root / REGION
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8-sig")
    if MARKER in text:
        print(f"[skip] {REGION} 已包含补丁标记")
        return True
    patched, count = EVALUATE_RE.subn(
        lambda m: m.group(1)
        + '\n        return new(RegionClassification.Other, "region-policy-disabled"); // [PATCH] 移除区域限制',
        text,
    )
    if count != 1:
        print(f"[warn] {REGION} 中 Evaluate() 匹配 {count} 处，放弃该路径")
        return False
    path.write_text(patched, encoding="utf-8")
    print(f"[ok] 已在 {REGION} 的 Evaluate() 开头插入早返回")
    return True


def audit(root: Path) -> None:
    """确认没有绕过上面两处的新增区域闸门。"""
    suspects: list[str] = []
    for cs in root.rglob("*.cs"):
        rel = cs.relative_to(root)
        if rel in (POLICY, REGION, TEST):
            continue
        try:
            text = cs.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        if "RegionPolicy.Evaluate(" in text or "RegionClassification.Mainland" in text:
            suspects.append(str(rel))
    if suspects:
        fail("发现未知的区域闸门调用点，需要人工确认：" + ", ".join(suspects))

    patched_files = [p for p in (POLICY, REGION) if (root / p).is_file() and MARKER in (root / p).read_text(encoding="utf-8-sig", errors="ignore")]
    if not patched_files:
        fail("补丁未落到任何文件，上游结构可能已变化")
    print("[ok] 审计通过：区域判定只剩已打补丁的入口，未发现其它闸门")


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: strip_region_gate.py <源码根目录>")
    root = Path(sys.argv[1]).resolve()
    if not (root / "PCL.Core").is_dir():
        fail(f"{root} 不像 PCL-CE 源码根目录")

    if patch_policy(root):
        pass
    elif patch_region(root):
        print("[warn] 走了兜底路径（RegionPolicy.Evaluate），上游结构已变化，请复核")
    else:
        fail("未找到可打补丁的位置：RestrictedFeaturePolicy.cs / RegionPolicy.cs 都不匹配")

    audit(root)

    diff = (root / POLICY)
    if diff.is_file():
        for line in diff.read_text(encoding="utf-8-sig").splitlines():
            if MARKER in line:
                print(f"[final] {line.strip()}")


if __name__ == "__main__":
    main()
