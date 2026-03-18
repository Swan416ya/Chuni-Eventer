from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChuniCharaId:
    raw: int

    @property
    def base(self) -> int:
        return self.raw // 10

    @property
    def variant(self) -> int:
        return self.raw % 10

    @property
    def raw6(self) -> str:
        return f"{self.raw:06d}"

    @property
    def base4(self) -> str:
        return f"{self.base:04d}"

    @property
    def variant2(self) -> str:
        return f"{self.variant:02d}"

    @property
    def chara_key(self) -> str:
        # matches A001: chara2469_00
        return f"chara{self.base4}_{self.variant2}"

    def dds_filename(self, idx: int) -> str:
        if idx not in (0, 1, 2):
            raise ValueError("idx must be 0/1/2 (head/half/full)")
        return f"CHU_UI_Character_{self.base4}_{self.variant2}_{idx:02d}.dds"

