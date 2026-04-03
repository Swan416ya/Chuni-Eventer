from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .acus_scan import CharaItem, MusicItem, scan_charas, scan_dds_images, scan_music, scan_nameplates, scan_stages, scan_trophies
from .acus_workspace import app_cache_dir
from .dds_convert import convert_dds_to_png


INDEX_VERSION = 3
INDEX_FILENAME = "game_data_index.json"


def _safe_int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except Exception:
        return None


def _relative_under(base: Path, target: Path) -> str:
    try:
        return str(target.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(target)


def enumerate_game_data_roots(game_root: Path) -> list[Path]:
    """
    扫描 CHUNITHM 安装目录下所有含 ``music/`` 的数据包根路径。

    包含：
    - 传统 ``A001`` / ``Option/A001`` / 根目录即数据包
    - ``data/a000/opt`` 下各子目录（以及 ``opt`` 本身若含 music）
    - ``bin/option`` 下以 ``A`` 开头的目录（如 A001、A002）
    """
    roots: list[Path] = []
    try:
        root = game_root.expanduser().resolve()
    except OSError:
        return []
    if not root.is_dir():
        return []

    for c in (root / "A001", root / "Option" / "A001", root):
        try:
            if c.is_dir() and (c / "music").is_dir():
                roots.append(c.resolve())
        except OSError:
            continue

    for data_name in ("data", "Data"):
        for a_name in ("a000", "A000"):
            opt_base = root / data_name / a_name / "opt"
            try:
                if not opt_base.is_dir():
                    continue
                if (opt_base / "music").is_dir():
                    roots.append(opt_base.resolve())
                for child in sorted(opt_base.iterdir()):
                    if not child.is_dir():
                        continue
                    try:
                        if (child / "music").is_dir():
                            roots.append(child.resolve())
                    except OSError:
                        continue
            except OSError:
                continue

    for bin_name in ("bin", "Bin"):
        bo = root / bin_name / "option"
        try:
            if not bo.is_dir():
                continue
            for child in sorted(bo.iterdir()):
                if not child.is_dir():
                    continue
                if not child.name.upper().startswith("A"):
                    continue
                try:
                    if (child / "music").is_dir():
                        roots.append(child.resolve())
                except OSError:
                    continue
        except OSError:
            continue

    # 无 music/ 但含 chara / reward / releaseTag 的扩展包（如 bin/option/ACUS、AKAO）
    for bin_name in ("bin", "Bin"):
        bo = root / bin_name / "option"
        try:
            if not bo.is_dir():
                continue
            for child in sorted(bo.iterdir()):
                if not child.is_dir():
                    continue
                try:
                    if (child / "music").is_dir():
                        continue
                except OSError:
                    continue
                has_pack = False
                for sub in ("chara", "reward", "releaseTag"):
                    try:
                        if (child / sub).is_dir():
                            has_pack = True
                            break
                    except OSError:
                        continue
                if not has_pack:
                    continue
                try:
                    roots.append(child.resolve())
                except OSError:
                    continue
        except OSError:
            continue

    seen: set[Path] = set()
    out: list[Path] = []
    for r in roots:
        try:
            rr = r.resolve()
        except OSError:
            continue
        if rr not in seen:
            seen.add(rr)
            out.append(rr)
    return out


def resolve_a001_root(game_root: Path) -> Path | None:
    """兼容旧逻辑：返回第一个可用的数据包根（用于单根场景）。"""
    roots = enumerate_game_data_roots(game_root)
    return roots[0] if roots else None


def _scan_dds_map_pairs(data_root: Path) -> list[tuple[int, str]]:
    seen: set[int] = set()
    out: list[tuple[int, str]] = []
    paths: set[Path] = set()
    for pat in ("ddsMap/**/DDSMap.xml", "ddsMap/**/DdsMap.xml"):
        try:
            for p in data_root.glob(pat):
                paths.add(p)
        except OSError:
            continue
    for p in sorted(paths):
        try:
            r = ET.parse(p).getroot()
            did = _safe_int(r.findtext("name/id") or "")
            dstr = (r.findtext("name/str") or "").strip()
            if did is None or did in seen:
                continue
            seen.add(did)
            out.append((did, dstr or f"DdsMap{did}"))
        except Exception:
            continue
    return sorted(out, key=lambda x: x[0])


def _enumerate_ddsmap_preview_roots(game_root: Path) -> list[Path]:
    """
    预览缓存专用 roots：
    - data/A000/opt 及其所有子目录
    - bin/option 下所有子目录（A001/A010/...）
    """
    roots: list[Path] = []
    for data_name in ("data", "Data"):
        for a_name in ("a000", "A000"):
            opt_base = game_root / data_name / a_name / "opt"
            if not opt_base.is_dir():
                continue
            roots.append(opt_base)
            try:
                for c in sorted(opt_base.iterdir()):
                    if c.is_dir():
                        roots.append(c)
            except OSError:
                pass
    for bin_name in ("bin", "Bin"):
        bo = game_root / bin_name / "option"
        if not bo.is_dir():
            continue
        try:
            for c in sorted(bo.iterdir()):
                if c.is_dir():
                    roots.append(c)
        except OSError:
            pass

    out: list[Path] = []
    seen: set[Path] = set()
    for r in roots:
        try:
            rr = r.resolve()
        except OSError:
            continue
        if rr in seen:
            continue
        seen.add(rr)
        out.append(rr)
    return out


def prewarm_game_dds_preview_pngs(
    *,
    game_root: Path,
    compressonatorcli_path: Path | None = None,
) -> tuple[int, int]:
    """
    把游戏资源 ddsMap 下所有 dds 预生成到 `.cache/dds_preview/*.png`。
    返回 (success_count, total_count)。
    """
    cache = app_cache_dir() / "dds_preview"
    cache.mkdir(parents=True, exist_ok=True)
    roots = _enumerate_ddsmap_preview_roots(game_root)
    dds_files: list[Path] = []
    for r in roots:
        droot = r / "ddsMap"
        if not droot.is_dir():
            continue
        try:
            for p in droot.glob("**/*.dds"):
                dds_files.append(p)
        except OSError:
            continue

    uniq = sorted({p.resolve() for p in dds_files})
    ok = 0
    for p in uniq:
        try:
            out_png = cache / f"{p.name}.png"
            if not out_png.exists():
                convert_dds_to_png(
                    tool_path=compressonatorcli_path,
                    input_dds=p,
                    output_png=out_png,
                )
            ok += 1
        except Exception:
            continue
    return ok, len(uniq)


def _music_item_to_catalog_row(m: MusicItem, source: str) -> dict[str, Any]:
    return {
        "id": m.name.id,
        "title": (m.name.str or "").strip() or f"Music{m.name.id}",
        "artist": (m.artist.str if m.artist else "") or "",
        "genres": [g for g in m.genres if g],
        "release_date": (m.release_date or "").strip(),
        "release_tag_id": m.release_tag.id if m.release_tag else None,
        "release_tag_str": (m.release_tag.str if m.release_tag else "") or "",
        "source": source,
    }


def merge_music_catalog_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一乐曲 ID 出现在多个包时合并流派与来源标注。"""
    by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        iid = int(row["id"])
        if iid not in by_id:
            by_id[iid] = {
                **row,
                "genres": list(row.get("genres") or []),
            }
        else:
            g = set(by_id[iid]["genres"]) | set(row.get("genres") or [])
            by_id[iid]["genres"] = sorted(g)
            s0 = str(by_id[iid].get("source") or "")
            s1 = str(row.get("source") or "")
            if s1 and s1 not in s0:
                by_id[iid]["source"] = s0 + ("; " if s0 else "") + s1
    return sorted(by_id.values(), key=lambda x: int(x["id"]))


def scan_game_music_catalog(game_root: Path) -> list[dict[str, Any]]:
    """从游戏根目录下所有数据包读取乐曲信息（供浏览窗口与索引）。"""
    try:
        gr = game_root.expanduser().resolve()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for pack in enumerate_game_data_roots(gr):
        src = _relative_under(gr, pack)
        try:
            for m in scan_music(pack):
                rows.append(_music_item_to_catalog_row(m, src))
        except Exception:
            continue
    return merge_music_catalog_rows(rows)


def _aggregate_stages_dds_from_roots(roots: list[Path]) -> tuple[list[tuple[int, str]], list[tuple[int, str]], list[tuple[int, str]]]:
    """合并多个根下的 stage / ddsImage / ddsMap（按 id 去重，后者覆盖前者）。"""
    stage_m: dict[int, str] = {}
    dds_i_m: dict[int, str] = {}
    dds_m_m: dict[int, str] = {}
    for r in roots:
        for s in scan_stages(r):
            stage_m[s.name.id] = (s.name.str or "").strip() or f"Stage{s.name.id}"
        for d in scan_dds_images(r):
            dds_i_m[d.name.id] = (d.name.str or "").strip() or f"DDSImage{d.name.id}"
        for did, dstr in _scan_dds_map_pairs(r):
            dds_m_m[did] = dstr
    return (
        sorted(stage_m.items(), key=lambda x: x[0]),
        sorted(dds_i_m.items(), key=lambda x: x[0]),
        sorted(dds_m_m.items(), key=lambda x: x[0]),
    )


def _aggregate_chara_np_trophy_from_roots(
    roots: list[Path],
) -> tuple[list[tuple[int, str]], list[tuple[int, str]], list[tuple[int, str]]]:
    """合并多个根下的 chara / namePlate / trophy（按 id 去重，后者覆盖前者）。"""
    chara_m: dict[int, str] = {}
    np_m: dict[int, str] = {}
    tr_m: dict[int, str] = {}
    for r in roots:
        for c in scan_charas(r):
            chara_m[c.name.id] = (c.name.str or "").strip() or f"Chara{c.name.id}"
        for n in scan_nameplates(r):
            np_m[n.name.id] = (n.name.str or "").strip() or f"NamePlate{n.name.id}"
        for t in scan_trophies(r):
            tr_m[t.name.id] = (t.name.str or "").strip() or f"Trophy{t.name.id}"
    return (
        sorted(chara_m.items(), key=lambda x: x[0]),
        sorted(np_m.items(), key=lambda x: x[0]),
        sorted(tr_m.items(), key=lambda x: x[0]),
    )


def _pairs_acus_music(acus_root: Path) -> list[tuple[int, str]]:
    return [
        (m.name.id, (m.name.str or "").strip() or f"Music{m.name.id}")
        for m in scan_music(acus_root)
    ]


def _pairs_acus_stage(acus_root: Path) -> list[tuple[int, str]]:
    return [
        (s.name.id, (s.name.str or "").strip() or f"Stage{s.name.id}")
        for s in scan_stages(acus_root)
    ]


def _pairs_acus_dds_image(acus_root: Path) -> list[tuple[int, str]]:
    return [
        (d.name.id, (d.name.str or "").strip() or f"DDSImage{d.name.id}")
        for d in scan_dds_images(acus_root)
    ]


def _pairs_acus_dds_map(acus_root: Path) -> list[tuple[int, str]]:
    return _scan_dds_map_pairs(acus_root)


def _pairs_acus_chara(acus_root: Path) -> list[tuple[int, str]]:
    return [
        (c.name.id, (c.name.str or "").strip() or f"Chara{c.name.id}")
        for c in scan_charas(acus_root)
    ]


def _pairs_acus_nameplate(acus_root: Path) -> list[tuple[int, str]]:
    return [
        (n.name.id, (n.name.str or "").strip() or f"NamePlate{n.name.id}")
        for n in scan_nameplates(acus_root)
    ]


def _pairs_acus_trophy(acus_root: Path) -> list[tuple[int, str]]:
    return [
        (t.name.id, (t.name.str or "").strip() or f"Trophy{t.name.id}")
        for t in scan_trophies(acus_root)
    ]


def _merge_pairs(
    game_pairs: list[tuple[int, str]] | None,
    acus_pairs: list[tuple[int, str]],
) -> list[tuple[int, str]]:
    merged: dict[int, str] = {}
    if game_pairs:
        for i, s in game_pairs:
            merged[i] = s
    for i, s in acus_pairs:
        merged[i] = s
    return sorted(merged.items(), key=lambda x: x[0])


@dataclass
class GameDataIndex:
    game_root: str
    roots_scanned: list[str]
    a001_root: str
    indexed_at: str
    music: list[tuple[int, str]]
    music_catalog: list[dict[str, Any]]
    stage: list[tuple[int, str]]
    dds_image: list[tuple[int, str]]
    dds_map: list[tuple[int, str]]
    chara: list[tuple[int, str]]
    nameplate: list[tuple[int, str]]
    trophy: list[tuple[int, str]]

    def to_json(self) -> dict[str, Any]:
        return {
            "version": INDEX_VERSION,
            "game_root": self.game_root,
            "roots_scanned": self.roots_scanned,
            "a001_root": self.a001_root,
            "indexed_at": self.indexed_at,
            "music": [{"id": a, "str": b} for a, b in self.music],
            "music_catalog": self.music_catalog,
            "stage": [{"id": a, "str": b} for a, b in self.stage],
            "dds_image": [{"id": a, "str": b} for a, b in self.dds_image],
            "dds_map": [{"id": a, "str": b} for a, b in self.dds_map],
            "chara": [{"id": a, "str": b} for a, b in self.chara],
            "nameplate": [{"id": a, "str": b} for a, b in self.nameplate],
            "trophy": [{"id": a, "str": b} for a, b in self.trophy],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> GameDataIndex | None:
        ver = int(data.get("version", 0))

        def read_pairs(key: str) -> list[tuple[int, str]]:
            raw = data.get(key) or []
            out: list[tuple[int, str]] = []
            for it in raw:
                if not isinstance(it, dict):
                    continue
                i = _safe_int(str(it.get("id", "")))
                if i is None:
                    continue
                s = str(it.get("str", "") or "").strip() or f"id{i}"
                out.append((i, s))
            return sorted(out, key=lambda x: x[0])

        gr = str(data.get("game_root", "") or "")
        if not gr:
            return None

        roots_scanned = [str(x) for x in (data.get("roots_scanned") or []) if x]
        a1 = str(data.get("a001_root", "") or "")
        ts = str(data.get("indexed_at", "") or "")

        music = read_pairs("music")
        catalog_raw = data.get("music_catalog")
        music_catalog: list[dict[str, Any]] = []
        if isinstance(catalog_raw, list):
            for it in catalog_raw:
                if isinstance(it, dict) and it.get("id") is not None:
                    music_catalog.append(dict(it))

        if ver < 2:
            if not a1 and roots_scanned:
                a1 = roots_scanned[0]
            elif not a1:
                a1 = gr
            if not music_catalog and music:
                music_catalog = [
                    {
                        "id": mid,
                        "title": mstr,
                        "artist": "",
                        "genres": [],
                        "release_date": "",
                        "release_tag_id": None,
                        "release_tag_str": "",
                        "source": a1,
                    }
                    for mid, mstr in music
                ]

        if not roots_scanned and a1:
            roots_scanned = [a1]

        return cls(
            game_root=gr,
            roots_scanned=roots_scanned,
            a001_root=a1 or (roots_scanned[0] if roots_scanned else gr),
            indexed_at=ts,
            music=music,
            music_catalog=music_catalog,
            stage=read_pairs("stage"),
            dds_image=read_pairs("dds_image"),
            dds_map=read_pairs("dds_map"),
            chara=read_pairs("chara"),
            nameplate=read_pairs("nameplate"),
            trophy=read_pairs("trophy"),
        )


def index_cache_path() -> Path:
    return app_cache_dir() / INDEX_FILENAME


def load_cached_game_index(expected_game_root: str | None = None) -> GameDataIndex | None:
    p = index_cache_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    idx = GameDataIndex.from_json(data)
    if idx is None:
        return None
    if expected_game_root and Path(idx.game_root).resolve() != Path(expected_game_root).resolve():
        return None
    return idx


def build_game_data_index(*, game_root: Path) -> GameDataIndex:
    gr = game_root.resolve()
    roots = enumerate_game_data_roots(gr)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    roots_rel = [_relative_under(gr, p) for p in roots]

    catalog_rows: list[dict[str, Any]] = []
    for pack in roots:
        src = _relative_under(gr, pack)
        try:
            for m in scan_music(pack):
                catalog_rows.append(_music_item_to_catalog_row(m, src))
        except Exception:
            continue
    merged_catalog = merge_music_catalog_rows(catalog_rows)
    music_pairs = [(int(r["id"]), str(r["title"])) for r in merged_catalog]

    stage_t, dds_i_t, dds_m_t = _aggregate_stages_dds_from_roots(roots)
    chara_t, np_t, tr_t = _aggregate_chara_np_trophy_from_roots(roots)

    primary = roots_rel[0] if roots_rel else str(gr)
    return GameDataIndex(
        game_root=str(gr),
        roots_scanned=roots_rel,
        a001_root=primary,
        indexed_at=now,
        music=sorted(music_pairs, key=lambda x: x[0]),
        music_catalog=merged_catalog,
        stage=stage_t,
        dds_image=dds_i_t,
        dds_map=dds_m_t,
        chara=chara_t,
        nameplate=np_t,
        trophy=tr_t,
    )


def save_game_data_index(idx: GameDataIndex) -> None:
    p = index_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(idx.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")


def rebuild_and_save_game_index(
    game_root: Path,
    compressonatorcli_path: Path | None = None,
) -> tuple[GameDataIndex | None, str]:
    root = game_root.expanduser().resolve()
    roots = enumerate_game_data_roots(root)
    if not roots:
        return None, (
            "未找到任何游戏数据目录。\n"
            "已尝试：data/a000/opt 下各包、bin/option/A*、以及 A001 等。\n"
            "请确认「游戏根目录」指向安装根（例如含 data 与 bin 的文件夹）。"
        )
    idx = build_game_data_index(game_root=root)
    save_game_data_index(idx)
    # 索引阶段顺便预生成游戏资源 ddsMap 预览 PNG
    prewarm_game_dds_preview_pngs(
        game_root=root,
        compressonatorcli_path=compressonatorcli_path,
    )
    return idx, ""


def merged_music_pairs(acus_root: Path, idx: GameDataIndex | None) -> list[tuple[int, str]]:
    acus = _pairs_acus_music(acus_root)
    game = idx.music if idx else None
    return _merge_pairs(game, acus)


def merged_stage_pairs(acus_root: Path, idx: GameDataIndex | None) -> list[tuple[int, str]]:
    acus = _pairs_acus_stage(acus_root)
    game = idx.stage if idx else None
    return _merge_pairs(game, acus)


def merged_dds_map_pairs(acus_root: Path, idx: GameDataIndex | None) -> list[tuple[int, str]]:
    acus = _pairs_acus_dds_map(acus_root)
    game = idx.dds_map if idx else None
    return _merge_pairs(game, acus)


def merged_dds_image_pairs(acus_root: Path, idx: GameDataIndex | None) -> list[tuple[int, str]]:
    acus = _pairs_acus_dds_image(acus_root)
    game = idx.dds_image if idx else None
    return _merge_pairs(game, acus)


def merged_chara_pairs(acus_root: Path, idx: GameDataIndex | None) -> list[tuple[int, str]]:
    acus = _pairs_acus_chara(acus_root)
    game = idx.chara if idx else None
    return _merge_pairs(game, acus)


def merged_nameplate_pairs(acus_root: Path, idx: GameDataIndex | None) -> list[tuple[int, str]]:
    acus = _pairs_acus_nameplate(acus_root)
    game = idx.nameplate if idx else None
    return _merge_pairs(game, acus)


def merged_trophy_pairs(acus_root: Path, idx: GameDataIndex | None) -> list[tuple[int, str]]:
    acus = _pairs_acus_trophy(acus_root)
    game = idx.trophy if idx else None
    return _merge_pairs(game, acus)


def merged_chara_items(acus_root: Path, idx: GameDataIndex | None) -> list[CharaItem]:
    """
    合并各数据包中的 Chara.xml（同 id 后者覆盖；工作区 ACUS 始终最后扫描以覆盖自定义）。
    """
    roots: list[Path] = []
    if idx:
        try:
            gr = Path(idx.game_root).resolve()
        except OSError:
            gr = None
        if gr is not None:
            for rel in idx.roots_scanned:
                try:
                    p = (gr / rel).resolve()
                    if p.is_dir():
                        roots.append(p)
                except OSError:
                    continue
    a001 = acus_root.parent / "A001"
    if a001.is_dir():
        try:
            a1r = a001.resolve()
            if a1r not in {r.resolve() for r in roots}:
                roots.append(a1r)
        except OSError:
            pass
    try:
        acusr = acus_root.resolve()
    except OSError:
        acusr = None
    if acusr is not None:
        roots = [p for p in roots if p.resolve() != acusr]
    roots.append(acus_root)

    by_id: dict[int, CharaItem] = {}
    for r in roots:
        for c in scan_charas(r):
            by_id[c.name.id] = c
    return sorted(by_id.values(), key=lambda x: x.name.id)
