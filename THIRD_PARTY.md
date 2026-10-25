# Attribution

School night-check-in protocol and policy are ported from [GoodNight-UESTC](https://github.com/VerBea-x/GoodNight-UESTC), commit `15881c759a0d504f82b368b078f88902e9408357` (MIT, Copyright (c) 2026 GoodNight contributors). The root LICENSE preserves its notice.

`goodnight/goodnight/policy.py` and `school.py` adapt the upstream night-check-in
policy and protocol. Check-in uses a validated school-provided location center,
with an optional per-account picker. The unused frontend-location discovery code
and its Acorn dependency are no longer distributed.

The Docker image includes the binary from [YYB-Go-Enhanced](https://github.com/525815266/YYB-Go-Enhanced),
upstream source inspected at `8a9497397abc7bf736be462f2e293f2bc6d4d0c0`.
The default image digest is `sha256:4508ad732ad8935babe67178269923d64da404f9dbbd5fccde8b9bf3736a4513`.
Its management API is used only on the container loopback interface. Upstream's
Web UI and general protocol routes are not exposed by this application's proxy.
See the upstream repository for its distribution conditions and original sources.

The IDAS encryption compatibility helper was independently implemented from the
public school's JavaScript behavior; the downloaded CryptoJS bundle is not vendored.
