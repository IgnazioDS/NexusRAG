# Capacity Model

Headroom: 30%

| tier | run_rps | read_rps | mutation_rps | run_p95_ms | run_p99_ms | max_streams | ingest_docs_min | ingest_mb_min | api_replicas | worker_replicas |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| standard | 17.5 | 160.0 | 21.54 | 1600.0 | 2160.0 | 40 | 180.0 | 14.4 | 2 | 1 |
| pro | 52.5 | 360.0 | 48.46 | 1200.0 | 1620.0 | 90 | 420.0 | 33.6 | 4 | 2 |
| enterprise | 140.0 | 720.0 | 96.92 | 900.0 | 1215.0 | 180 | 900.0 | 72.0 | 8 | 4 |

## Assumptions

- queue_model: Little's Law: lambda = concurrency / service_time
- avg_doc_size_mb: 0.08
- redis: single shard with persistence enabled
- postgres: primary + 1 read replica, pgbouncer optional
- scale_policy: autoscale when p95 > target for 3 consecutive windows; shed after saturation breach
