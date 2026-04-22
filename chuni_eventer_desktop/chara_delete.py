from __future__ import annotations

import shutil
from pathlib import Path

from .acus_scan import CharaItem
from .chuni_formats import ChuniCharaId
from .dds_preview import remove_cached_pngs_for_dds_basenames


def delete_chara_from_acus(acus_root: Path, item: CharaItem) -> None:
    """
    删除 ACUS 内该角色条目：移除 chara/charaXXXXXX/ 与 ddsImage/ddsImageXXXXXX/。
    路径必须位于 acus_root 下且符合标准命名。
    """
    ar = acus_root.resolve()
    chara_dir = item.xml_path.parent.resolve()
    try:
        chara_dir.relative_to(ar)
    except ValueError as e:
        raise ValueError(f"角色目录不在 ACUS 内：{chara_dir}") from e

    cid = int(item.name.id)
    cid_fmt = ChuniCharaId(cid)
    expected = f"chara{cid_fmt.raw6}"
    if chara_dir.name != expected:
        raise ValueError(
            f"角色文件夹名与 ID 不一致（拒绝删除）：目录={chara_dir.name!r}，期望={expected!r}"
        )

    dds_dir = ar / "ddsImage" / f"ddsImage{cid_fmt.raw6}"
    dds_cache_keys: set[str] = {
        cid_fmt.dds_filename(0),
        cid_fmt.dds_filename(1),
        cid_fmt.dds_filename(2),
    }
    if dds_dir.is_dir():
        # Also purge preview cache entries generated from this chara's DDS files.
        # dds_to_pixmap caches as "<dds filename>.png" under .cache/dds_preview.
        for dds in dds_dir.glob("*.dds"):
            dds_cache_keys.add(dds.name)

    if chara_dir.is_dir():
        shutil.rmtree(chara_dir)
    if dds_dir.is_dir():
        shutil.rmtree(dds_dir)
    remove_cached_pngs_for_dds_basenames(sorted(dds_cache_keys))
