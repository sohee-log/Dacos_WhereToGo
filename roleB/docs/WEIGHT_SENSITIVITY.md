# 가중치 민감도 (B6-1)

> `python -m tools.weight_sensitivity --md` 로 생성. 실 Supabase 대조.
> 최근 추천 로그 **200건**을 후보 그대로 다시 채점했다.

| 가중치 안 | top5 유지율 | 1위 변경률 |
|---|---:|---:|
| `quality_down` | 83.0% | 22.0% |
| `quality_up` | 87.6% | 23.5% |
| `context_up` | 93.1% | 21.0% |
