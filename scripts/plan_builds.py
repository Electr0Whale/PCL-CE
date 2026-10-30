#!/usr/bin/env python3
"""扫描上游 release，算出本次要构建的版本列表（供 matrix 使用）。

环境变量：
    GH_TOKEN            GitHub token（workflow 里用 github.token）
    GITHUB_REPOSITORY   本仓库 owner/repo
    INPUT_TAG           手动指定上游 tag（可空）
    INCLUDE_PRE         是否包含 pre-release（"true"/"false"）
    FORCE               已发布过的也重建（"true"/"false"）
    UPSTREAM            上游仓库，默认 PCL-Community/PCL-CE
    MAX_PER_RUN         单次最多构建几个版本，默认 5
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

try:  # Windows runner 的默认代码页可能不是 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

API = "https://api.github.com"
UPSTREAM = os.environ.get("UPSTREAM", "PCL-Community/PCL-CE")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GH_TOKEN", "")
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "5"))
# 区域限制自 2.15.1 引入；更早的 tag 没有可移除的闸门，直接跳过
MIN_VERSION = os.environ.get("MIN_VERSION", "v2.15.1").strip()


def parse_version(tag: str) -> tuple[int, ...]:
    core = tag.lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            break
    return tuple(parts)


def version_at_least(tag: str, floor: str) -> bool:
    got, want = parse_version(tag), parse_version(floor)
    if not got or not want:
        return False
    size = max(len(got), len(want))
    got += (0,) * (size - len(got))
    want += (0,) * (size - len(want))
    return got >= want


def truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def request(path: str):
    url = path if path.startswith("http") else f"{API}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "pcl-ce-unrestricted-builder",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def paginate(path: str, pages: int = 3):
    items = []
    for page in range(1, pages + 1):
        sep = "&" if "?" in path else "?"
        try:
            batch = request(f"{path}{sep}per_page=100&page={page}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return items
            raise
        if not isinstance(batch, list):
            break
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def main() -> None:
    if not TOKEN or not REPO:
        print("::error::缺少 GH_TOKEN 或 GITHUB_REPOSITORY")
        sys.exit(1)

    input_tag = os.environ.get("INPUT_TAG", "").strip()
    include_pre = truthy("INCLUDE_PRE")
    force = truthy("FORCE")

    ours = {rel.get("tag_name") for rel in paginate(f"/repos/{REPO}/releases")}

    if input_tag:
        candidates = [{"tag_name": input_tag, "prerelease": False, "published_at": ""}]
        try:
            candidates = [request(f"/repos/{UPSTREAM}/releases/tags/{input_tag}")]
            print(f"手动指定 tag：{input_tag}（上游 release 存在）")
        except urllib.error.HTTPError:
            try:
                request(f"/repos/{UPSTREAM}/git/ref/tags/{input_tag}")
                print(f"手动指定 tag：{input_tag}（上游 tag 存在，但无 release 记录）")
            except urllib.error.HTTPError as exc:
                print(f"::error::上游不存在 tag {input_tag}（{exc.code}）")
                sys.exit(1)
    else:
        releases = paginate(f"/repos/{UPSTREAM}/releases")
        candidates = [
            rel
            for rel in releases
            if not rel.get("draft") and (include_pre or not rel.get("prerelease"))
        ]
        print(f"上游 release 共 {len(releases)} 条，符合条件 {len(candidates)} 条")

    todo = []
    below_floor = []
    for rel in sorted(candidates, key=lambda r: r.get("published_at") or "", reverse=True):
        tag = rel.get("tag_name")
        if not tag:
            continue
        if not input_tag and not version_at_least(tag, MIN_VERSION):
            below_floor.append(tag)
            continue
        if tag in ours and not force:
            continue
        todo.append({"tag": tag, "prerelease": bool(rel.get("prerelease"))})

    skipped = len(candidates) - len(todo) - len(below_floor)
    if len(todo) > MAX_PER_RUN:
        print(f"待构建 {len(todo)} 个，本次只处理最新的 {MAX_PER_RUN} 个（其余下次继续）")
        todo = todo[:MAX_PER_RUN]

    matrix = {"include": todo} if todo else {"include": []}
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"matrix={json.dumps(matrix, ensure_ascii=False)}\n")
            fh.write(f"count={len(todo)}\n")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("### 待构建版本\n\n")
            if todo:
                fh.write("| tag | pre-release |\n| --- | --- |\n")
                for item in todo:
                    fh.write(f"| `{item['tag']}` | {'是' if item['prerelease'] else '否'} |\n")
            else:
                fh.write("无新版本（已发布过的 tag 会跳过；需要重建请用 `force`）。\n")
            fh.write(
                f"\n跳过已构建：{skipped} 个；低于版本下限 `{MIN_VERSION}` 而跳过：{len(below_floor)} 个；"
                f"单次上限：{MAX_PER_RUN}\n"
            )

    print(json.dumps(matrix, ensure_ascii=False))


if __name__ == "__main__":
    main()
