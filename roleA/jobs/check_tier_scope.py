import pandas as pd

df = pd.read_csv(
    "roleA/data/yongsan_poi_final.csv",
    encoding="utf-8-sig",
)

T1_DONGS = [
    "이태원1동",
    "이태원2동",
    "한남동",
    "한강로동",
    "후암동",
]

T2_DONGS = [
    "이촌1동",
    "남영동",
    "청파동",
    "원효로1동",
]

df["tier_scope"] = 3
df.loc[df["dong"].isin(T2_DONGS), "tier_scope"] = 2
df.loc[df["dong"].isin(T1_DONGS), "tier_scope"] = 1

print("=== tier 후보 규모 ===")
print(df["tier_scope"].value_counts().sort_index())

print("\n=== T1 행정동별 ===")
print(df[df["tier_scope"] == 1]["dong"].value_counts().to_string())

print("\n=== T1 카테고리별 ===")
print(df[df["tier_scope"] == 1]["category_l1"].value_counts().to_string())
