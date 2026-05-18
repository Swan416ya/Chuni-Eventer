from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .acus_workspace import app_root_dir


class StageAfbToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class StageAfbResult:
    notes_field_file: str
    base_file: str


def _bundled_stage_template_paths() -> tuple[Path, Path]:
    """随 PyInstaller 打入 ``chuni_eventer_desktop/data/``（与 ``dummy.acb`` 相同）。"""
    data_dir = Path(__file__).resolve().parent / "data"
    return data_dir / "nf_dummy.afb", data_dir / "st_dummy.afb"


def _candidate_mua_paths() -> list[Path]:
    root = app_root_dir()
    out: list[Path] = [
        # 打包后的固定位置
        root / ".tools" / "PenguinTools" / "mua.exe",
        root / ".tools" / "mua" / "mua.exe",
        root / ".tools" / "muautils" / "mua.exe",
        # 源码运行固定位置
        root / "tools" / "PenguinTools" / "mua.exe",
        root / "tools" / "mua" / "mua.exe",
    ]
    # 兼容：允许高级用户用环境变量覆盖
    env = (os.environ.get("CHUNI_MUA_PATH") or "").strip()
    if env:
        out.insert(0, Path(env).expanduser())
    return out


def resolve_mua_path(cfg: object | None = None) -> Path:
    if cfg is None:
        from .acus_workspace import AcusConfig

        cfg = AcusConfig.load()
    from .external_tools import TOOL_MUA, resolve_tool_path

    p = resolve_tool_path(TOOL_MUA, cfg)  # type: ignore[arg-type]
    if p is not None:
        return p
    for p in _candidate_mua_paths():
        try:
            rp = p.resolve(strict=False)
        except OSError:
            continue
        if rp.is_file():
            return rp
    raise StageAfbToolError(
        "未找到 `mua` 可执行文件。\n"
        "请把 `mua.exe` 放到以下固定路径之一：\n"
        "1) `<项目根>/tools/PenguinTools/mua.exe`\n"
        "2) `<项目根>/.tools/PenguinTools/mua.exe`（打包后推荐）"
    )


def _candidate_templates(game_root: str | None) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    root = app_root_dir()
    pairs.append(_bundled_stage_template_paths())
    pairs.extend(
        [
            (
                root / "tools" / "PenguinTools" / "Resources" / "nf_dummy.afb",
                root / "tools" / "PenguinTools" / "Resources" / "st_dummy.afb",
            ),
            (
                root / ".tools" / "PenguinTools" / "Resources" / "nf_dummy.afb",
                root / ".tools" / "PenguinTools" / "Resources" / "st_dummy.afb",
            ),
            (
                root / "A001" / "stage" / "stage000011" / "nf_00011.afb",
                root / "A001" / "stage" / "stage000011" / "st_00011.afb",
            ),
        ]
    )
    # 2) 游戏目录内常见位置
    if game_root:
        gr = Path(game_root).expanduser()
        pairs.extend(
            [
                (
                    gr / "bin" / "option" / "A001" / "stage" / "stage000011" / "nf_00011.afb",
                    gr / "bin" / "option" / "A001" / "stage" / "stage000011" / "st_00011.afb",
                ),
                (
                    gr / "bin" / "option" / "A001" / "stage" / "stage027201" / "nf_27201.afb",
                    gr / "bin" / "option" / "A001" / "stage" / "stage027201" / "st_27201.afb",
                ),
                (
                    gr / "data" / "A001" / "stage" / "stage000011" / "nf_00011.afb",
                    gr / "data" / "A001" / "stage" / "stage000011" / "st_00011.afb",
                ),
            ]
        )
    return pairs


def resolve_stage_templates(game_root: str | None) -> tuple[Path, Path]:
    tried: list[str] = []
    for nf, st in _candidate_templates(game_root):
        tried.append(f"nf={nf} | st={st}")
        if nf.is_file() and st.is_file():
            return nf, st
    nf_b, st_b = _bundled_stage_template_paths()
    raise StageAfbToolError(
        "未找到 Stage 模板 afb（nf/st）。\n"
        "正常情况应使用程序内置模板（打包在 exe 的 data 目录）。\n"
        "亦可手动放置：\n"
        f"1) 内置：{nf_b} 与 {st_b}\n"
        "2) `<项目根>/.tools/PenguinTools/Resources/nf_dummy.afb` 与 `st_dummy.afb`\n"
        "3) `<项目根>/A001/stage/stage000011/` 或设置里 game_root 下的 stage 文件。\n\n"
        "已尝试路径：\n" + "\n".join(tried)
    )


def _run_mua_convert_stage(
    *,
    mua_path: Path,
    background_image: Path,
    st_template: Path,
    st_output: Path,
    fx_paths: list[Path] | None = None,
) -> None:
    argv = [
        str(mua_path),
        "convert_stage",
        "-b",
        str(background_image),
        "-s",
        str(st_template),
        "-d",
        str(st_output),
    ]
    for i, p in enumerate(fx_paths or [], start=1):
        if i > 4:
            break
        argv.extend([f"-f{i}", str(p)])
    popen_kw: dict = {"cwd": str(mua_path.parent)}
    if os.name == "nt":
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", **popen_kw)
    except OSError as e:
        raise StageAfbToolError(f"启动 mua 失败：{e}") from e
    if p.returncode != 0:
        raise StageAfbToolError(
            "mua convert_stage 执行失败。\n"
            f"cmd: {' '.join(argv)}\nexit: {p.returncode}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}"
        )
    if not st_output.is_file():
        raise StageAfbToolError(f"mua 返回成功但未生成输出：{st_output}")


def build_stage_afb_from_image(
    *,
    stage_dir: Path,
    stage_id: int,
    background_image: Path,
    game_root: str | None,
) -> StageAfbResult:
    mua = resolve_mua_path()
    nf_tmpl, st_tmpl = resolve_stage_templates(game_root)

    notes_name = f"nf_{stage_id:05d}.afb"
    base_name = f"st_{stage_id:05d}.afb"
    nf_out = stage_dir / notes_name
    st_out = stage_dir / base_name

    _run_mua_convert_stage(
        mua_path=mua,
        background_image=background_image,
        st_template=st_tmpl,
        st_output=st_out,
        fx_paths=None,
    )
    shutil.copy2(nf_tmpl, nf_out)
    return StageAfbResult(notes_field_file=notes_name, base_file=base_name)

