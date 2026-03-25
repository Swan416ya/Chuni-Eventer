"""
CHUNITHM ALL.Net 导出存档（JSON）的读写与收藏品相关补丁。

示例文件：example/chusan_*_exported.json
顶层为 dict，核心字段见 load_save 的说明。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

# 账号「企鹅」类道具：userItemList 中 itemKind=5，isValid=true，stock 为数量
PENGUIN_ITEM_KIND = 5
PENGUIN_ITEM_IDS: tuple[int, ...] = (8000, 8010, 8020, 8030)
PENGUIN_ITEM_NAMES: dict[int, str] = {
    8000: "金企鹅",
    8010: "小企鹅",
    8020: "企鹅之魂",
    8030: "彩色企鹅",
}


def load_save(path: str | Path) -> dict[str, Any]:
    """
    读取导出存档。典型顶层键：
    - gameId: 如 \"SDHD\"
    - userData: 账号概要（等级、点数、当前装备的称号/名牌/角色/头像部件等）
    - userItemList: 持有物列表 {itemKind, itemId, stock, isValid}
    - userCharacterList: 角色持有与养成
    - userMusicDetailList: 乐曲游玩数据（含 isLock 等）
    - userMapList: 地图/区域进度
    - userGeneralDataList: 少量 KV（如 favorite_music）
    - userActivityList / userChargeList / … 其它活动与内购相关
    """
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def save_save(path: str | Path, data: dict[str, Any], *, indent: int | None = None) -> None:
    """写回 JSON。indent=None 时与游戏导出一致为单行。"""
    p = Path(path)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")


def find_items(
    data: dict[str, Any], *, item_kind: int, item_id: int
) -> list[dict[str, Any]]:
    """返回 userItemList 中所有匹配 (itemKind, itemId) 的 dict 引用（可原地改）。"""
    items = data.get("userItemList") or []
    return [x for x in items if x.get("itemKind") == item_kind and x.get("itemId") == item_id]


def ensure_item(
    data: dict[str, Any],
    *,
    item_kind: int,
    item_id: int,
    stock: int = 1,
    is_valid: bool = True,
    dedupe_identical: bool = True,
) -> bool:
    """
    确保 userItemList 中存在该物品；不存在则追加。
    若 dedupe_identical 且已存在完全相同的一条，则不重复添加。

    注意：部分 kind（如样本中 itemKind=3）对同一 itemId 可能出现两条相同记录，
    是否为服务端惯例尚不明确，修改前请自行对照原档。
    """
    lst = data.setdefault("userItemList", [])
    row = {"itemKind": item_kind, "itemId": item_id, "stock": stock, "isValid": is_valid}
    if dedupe_identical:
        for x in lst:
            if (
                x.get("itemKind") == item_kind
                and x.get("itemId") == item_id
                and x.get("stock") == stock
                and x.get("isValid") == is_valid
            ):
                return False
    lst.append(row)
    return True


def remove_items(data: dict[str, Any], *, item_kind: int, item_id: int) -> int:
    """删除所有匹配 (itemKind, itemId) 的项，返回删除条数。"""
    lst = data.get("userItemList") or []
    before = len(lst)
    data["userItemList"] = [
        x for x in lst if not (x.get("itemKind") == item_kind and x.get("itemId") == item_id)
    ]
    return before - len(data["userItemList"])


def sum_item_stock(data: dict[str, Any], *, item_kind: int, item_id: int) -> int:
    """同一 (itemKind, itemId) 多条目时库存求和（与部分存档重复行兼容）。"""
    return sum(int(x.get("stock") or 0) for x in find_items(data, item_kind=item_kind, item_id=item_id))


def set_item_stock_normalized(
    data: dict[str, Any], *, item_kind: int, item_id: int, stock: int, is_valid: bool = True
) -> None:
    """合并为单条记录：stock<=0 时删除该物品；否则仅保留一条且 stock 为设定值。"""
    remove_items(data, item_kind=item_kind, item_id=item_id)
    if int(stock) > 0:
        ensure_item(
            data,
            item_kind=item_kind,
            item_id=item_id,
            stock=int(stock),
            is_valid=is_valid,
            dedupe_identical=False,
        )


def replace_user_item_row(
    data: dict[str, Any],
    *,
    item_kind: int,
    item_id: int,
    stock: int,
    is_valid: bool = True,
) -> None:
    """删除同键所有行后追加一条（stock 可为 0，与导出档一致）。"""
    remove_items(data, item_kind=item_kind, item_id=item_id)
    lst = data.setdefault("userItemList", [])
    lst.append(
        {
            "itemKind": int(item_kind),
            "itemId": int(item_id),
            "stock": max(0, int(stock)),
            "isValid": bool(is_valid),
        }
    )


def set_penguin_stocks(data: dict[str, Any], stocks: dict[int, int]) -> None:
    """写入四种企鹅（itemKind=5，isValid=true）。"""
    for pid in PENGUIN_ITEM_IDS:
        replace_user_item_row(
            data,
            item_kind=PENGUIN_ITEM_KIND,
            item_id=pid,
            stock=int(stocks.get(pid, 0)),
            is_valid=True,
        )


def set_equipped_nameplate(data: dict[str, Any], nameplate_id: int) -> None:
    """设置当前名牌 ID（userData.nameplateId）；不自动写入 userItemList。"""
    ud = data.setdefault("userData", {})
    ud["nameplateId"] = int(nameplate_id)


def set_equipped_trophies(
    data: dict[str, Any], main_id: int, sub1_id: int = -1, sub2_id: int = -1
) -> None:
    """设置称号槽（userData.trophyId / trophyIdSub1 / trophyIdSub2）。"""
    ud = data.setdefault("userData", {})
    ud["trophyId"] = int(main_id)
    ud["trophyIdSub1"] = int(sub1_id)
    ud["trophyIdSub2"] = int(sub2_id)


def clone_save(data: dict[str, Any]) -> dict[str, Any]:
    """深拷贝，避免误改原对象。"""
    return deepcopy(data)
