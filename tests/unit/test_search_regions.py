import pytest

from app.core.errors import DomainError
from app.modules.search.regions import DISTRICTS, resolve_search


def test_catalog_covers_each_district_and_its_three_neighbors():
    for district in DISTRICTS.values():
        codes, words = resolve_search("unknown", district.full_name)
        assert codes == [district.code, *district.neighbors]
        assert len(set(codes)) == 4
        assert set(codes) <= DISTRICTS.keys()
        assert words == []


@pytest.mark.parametrize(
    ("keyword", "center", "terms"),
    [
        ("운동 서울시 동작구", "11590", ["운동"]),
        ("부산시 중구", "26110", []),
        ("경기도 성남시 분당구 탁구", "41135", ["탁구"]),
        ("영등포구", "11560", []),
        ("산책", "11110", ["산책"]),
    ],
)
def test_search_region_spellings(keyword, center, terms):
    codes, words = resolve_search("1111010100", keyword)
    assert codes[0] == center
    assert words == terms


def test_city_with_multiple_districts_requires_more_specific_place():
    with pytest.raises(DomainError, match="시군구"):
        resolve_search("11110", "수원시 산책")
