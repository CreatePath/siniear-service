import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import DomainError


@dataclass(frozen=True)
class District:
    code: str
    province: str
    name: str
    neighbors: tuple[str, ...]

    @property
    def full_name(self):
        return self.name if self.name == self.province else f"{self.province} {self.name}"


# 주소기반산업지원서비스 2026-07 시군구 경계. 산출 기준은 서비스 README 참조.
with Path(__file__).with_name("districts.csv").open(encoding="utf-8") as source:
    rows = csv.reader(source)
    next(rows)
    DISTRICTS = {
        code: District(code, province, name, tuple(neighbors))
        for code, province, name, *neighbors in rows
    }

PROVINCE_SHORT = {
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "경기도": "경기",
    "강원특별자치도": "강원",
    "충청북도": "충북",
    "충청남도": "충남",
    "전북특별자치도": "전북",
    "전남광주통합특별시": "전남광주",
    "경상북도": "경북",
    "경상남도": "경남",
    "제주특별자치도": "제주",
}


def district_aliases(district):
    parts = district.name.split()
    names = {parts[-1], "".join(parts)}
    if len(parts[-1]) >= 3 and parts[-1].endswith(("구", "시", "군")):
        names.add(parts[-1][:-1])
    if len(parts) == 2:
        names.add(parts[0].removesuffix("시") + parts[1])
    if district.name == district.province:
        names.add(PROVINCE_SHORT[district.province])
    short = PROVINCE_SHORT[district.province]
    provinces = {district.province, short, short + district.province[-1]}
    if district.province == "전남광주통합특별시":
        provinces.update(
            {"광주", "광주시", "광주광역시"}
            if district.name.endswith("구")
            else {"전남", "전라남도"}
        )
    aliases = {prefix + name for prefix in provinces | {""} for name in names}
    # A broad place name is also a lookup. Multiple matching districts require clarification.
    if len(parts) == 2:
        aliases.update(prefix + parts[0] for prefix in provinces | {""})
    return aliases | provinces


ALIASES = defaultdict(list)
for district in DISTRICTS.values():
    for alias in district_aliases(district):
        ALIASES[alias].append(district)


def district_code(code):
    if len(code) in (8, 10) and code.isascii() and code.isdigit() and code[:5] in DISTRICTS:
        return code[:5]
    return code


def resolve_search(profile_code, keyword):
    center = district_code(profile_code)
    home = DISTRICTS.get(center)
    words = (keyword or "").split()
    # Prefer the longest qualified place name, e.g. '경기도 성남시 분당구' over '분당구'.
    matches = (
        (len(alias), start, end, ALIASES[alias])
        for start in range(len(words))
        for end in range(start + 1, min(start + 3, len(words)) + 1)
        if (alias := "".join(words[start:end])) in ALIASES
    )
    match = max(matches, key=lambda item: item[0], default=None)
    if match:
        _, start, end, candidates = match
        if len(candidates) > 1 and home:
            candidates = [d for d in candidates if d.province == home.province] or candidates
        if len(candidates) != 1:
            raise DomainError(422, "AMBIGUOUS_REGION", "시도와 시군구 이름을 함께 입력해 주세요.")
        center = candidates[0].code
        del words[start:end]
    district = DISTRICTS.get(center)
    if district is None:
        raise DomainError(
            422,
            "SEARCH_REGION_REQUIRED",
            "활동 지역을 확인하거나 검색할 시군구 이름을 입력해 주세요.",
        )
    return [center, *district.neighbors], words
