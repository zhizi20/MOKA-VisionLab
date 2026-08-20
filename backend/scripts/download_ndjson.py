"""把 Ultralytics Platform 的 .ndjson 下载成本地 YOLO 数据集。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ndjson_import import class_name_list, parse_ndjson  # noqa: E402


def _download(url: str, dest: Path, retries: int = 3):
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url,
                timeout=90,
                stream=True,
                headers={"User-Agent": "MOKA-VisionLab/0.1"},
            )
            resp.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
            if tmp.stat().st_size < 32:
                tmp.unlink(missing_ok=True)
                raise RuntimeError("下载文件过小")
            tmp.replace(dest)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
            time.sleep(min(2 * attempt, 6))
    raise RuntimeError(str(last))


def _write_label(path: Path, boxes: list):
    lines = []
    for box in boxes:
        if not isinstance(box, (list, tuple)) or len(box) < 5:
            continue
        cls, cx, cy, w, h = box[:5]
        lines.append(f"{int(cls)} {float(cx):.6f} {float(cy):.6f} {float(w):.6f} {float(h):.6f}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="下载 Ultralytics NDJSON 数据集到本地")
    parser.add_argument("ndjson", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="输出目录，默认与 ndjson 同名文件夹")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    ndjson = args.ndjson.expanduser().resolve()
    if not ndjson.is_file():
        raise SystemExit(f"找不到文件：{ndjson}")
    out = (args.out or (ndjson.parent / ndjson.stem)).expanduser().resolve()
    meta, images = parse_ndjson(ndjson)
    names = class_name_list(meta)
    for split in ("train", "val", "test"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    total = len(images)
    done = 0
    failed = 0
    started = time.time()
    print(f"数据集：{meta.get('name') or ndjson.stem}")
    print(f"类别：{names}")
    print(f"图片：{total} 张 → {out}")

    def one(rec: dict):
        name = Path(rec.get("file") or "image.jpg").name
        split = (rec.get("split") or "train").lower()
        if split not in {"train", "val", "test"}:
            split = "train"
        dest = out / "images" / split / name
        if not dest.exists():
            url = rec.get("url") or ""
            if not url:
                raise RuntimeError(f"{name} 缺少下载地址")
            _download(url, dest)
        boxes = ((rec.get("annotations") or {}).get("boxes")) or []
        if boxes:
            _write_label(out / "labels" / split / f"{dest.stem}.txt", boxes)
        return name

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(one, rec) for rec in images]
        for fut in as_completed(futures):
            done += 1
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"失败：{exc}")
            if done % 20 == 0 or done == total:
                elapsed = max(time.time() - started, 1)
                speed = done / elapsed
                print(f"进度 {done}/{total}  失败 {failed}  {speed:.1f} 张/秒")

    has_test = any((out / "images" / "test").iterdir())
    names_txt = ", ".join(repr(n) for n in names)
    yaml = (
        f"path: {out.as_posix()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
    )
    if has_test:
        yaml += "test: images/test\n"
    yaml += f"nc: {len(names)}\nnames: [{names_txt}]\n"
    (out / "data.yaml").write_text(yaml, encoding="utf-8")
    meta_path = out / "dataset.json"
    meta_path.write_text(json.dumps({
        "name": meta.get("name"),
        "class_names": names,
        "source": str(ndjson),
        "total": total,
        "failed": failed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：{out}")
    print(f"成功 {total - failed}  失败 {failed}")
    print(f"data.yaml：{out / 'data.yaml'}")


if __name__ == "__main__":
    main()
