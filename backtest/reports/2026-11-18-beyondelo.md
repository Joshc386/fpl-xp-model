# Outside-source Elo check: 2026-11-18

Ratings from beyondELO (https://beyondelo.com), CC BY 4.0.

## Verdict

**Not a poor Elo rating**, on the pooled scored windows (199 matches). A poor rating needs either condition; both comparisons are made after rounding to 9 decimals. SE is the differences' sd (ddof 1) divided by the square root of n.

| Condition | Mean | SD | n | SE | 2 SE | Fires |
|---|---|---|---|---|---|---|
| 1. Ours minus beyondELO's, mean per match, above zero by more than 2 SE | 0.005176 | 0.095845 | 199 | 0.006794 | 0.013589 | no |

| Condition | Ours (nats) | Baseline (nats) | Ours minus baseline | Fires |
|---|---|---|---|---|
| 2. Our log-loss isn't below the baseline's | 1.032609 | 1.085887 | -0.053278 | no |

## Predictive log-loss

Nats per match, lower is better: the mean over scored matches of -ln(probability given to the actual result).

### All scored matches

| Window | Matches | Ours | beyondELO | Baseline | Ours minus beyondELO |
|---|---|---|---|---|---|
| 2025-2026 GW27-38 | 119 | 1.0398 | 1.0315 | 1.0830 | 0.0083 |
| 2026-2027 GW3-10 | 80 | 1.0220 | 1.0214 | 1.0902 | 0.0006 |
| pooled | 199 | 1.0326 | 1.0274 | 1.0859 | 0.0052 |

### Without matches involving a promoted club

No verdict of its own. The fits are the same (every fit-window match); only matches with a promoted club on either side are left out of the scoring.

| Window | Matches | Ours | beyondELO | Baseline | Ours minus beyondELO |
|---|---|---|---|---|---|
| 2025-2026 GW27-38 | 85 | 1.0323 | 1.0289 | 1.0662 | 0.0033 |
| 2026-2027 GW3-10 | 57 | 1.0514 | 1.0480 | 1.1025 | 0.0035 |
| pooled | 142 | 1.0399 | 1.0366 | 1.0808 | 0.0034 |

Promoted clubs (beyondELO's `promoted` flag):

- 2025-2026: Burnley, Leeds, Sunderland
- 2026-2027: Coventry City, Hull City, Ipswich Town

## Fitted parameters

Ordered logistic fit of the result on the before-match gap (home minus away), once per source on 2025-2026 GW1-26 (261 matches). P(away win) = F(cut away/draw - slope x gap), P(away win or draw) = F(cut draw/home - slope x gap), F logistic. The baseline has no gap.

| Source | n | Slope | Cut away/draw | Cut draw/home | Iterations | Log-likelihood |
|---|---|---|---|---|---|---|
| Ours | 261 | 0.00414101 | -0.916128 | 0.298115 | 4 | -268.4369 |
| beyondELO | 261 | 0.00426451 | -0.935457 | 0.301349 | 4 | -265.3629 |
| Baseline | 261 | 0 | -0.834559 | 0.285447 | 0 | -281.2869 |

## Ranking agreement

A diagnostic with no pass mark: Spearman's rank correlation of our `elo_before` with `beyondelo_before` over each gameweek's team-kickoffs (a double gameweek counts each kickoff; ties take their average rank).

### 2025-2026 GW27-38

Spearman: median 0.963, minimum 0.947.

| GW | Team-kickoffs | Spearman |
|---|---|---|
| 27 | 20 | 0.961 |
| 28 | 20 | 0.964 |
| 29 | 20 | 0.975 |
| 30 | 20 | 0.973 |
| 31 | 16 | 0.947 |
| 32 | 20 | 0.965 |
| 33 | 26 | 0.947 |
| 34 | 14 | 0.952 |
| 35 | 20 | 0.947 |
| 36 | 22 | 0.968 |
| 37 | 20 | 0.962 |
| 38 | 20 | 0.974 |

The 5 biggest rank disagreements at GW38 (rank 1 is the highest rating):

| Club | Match | Ours | Our rank | beyondELO | beyondELO rank | Rank gap |
|---|---|---|---|---|---|---|
| Aston Villa | 25-26-prem-manchester-city-vs-aston-villa | 1860.0 | 6 | 1985.0 | 3 | 3 |
| Chelsea | 25-26-prem-sunderland-vs-chelsea | 1842.2 | 7 | 1886.0 | 10 | 3 |
| Crystal Palace | 25-26-prem-crystal-palace-vs-arsenal | 1785.7 | 14 | 1840.0 | 16 | 2 |
| Liverpool | 25-26-prem-liverpool-vs-brentford | 1909.5 | 3 | 1945.0 | 5 | 2 |
| Bournemouth | 25-26-prem-nottingham-forest-vs-afc-bournemouth | 1861.3 | 5 | 1938.0 | 6 | 1 |

### 2026-2027 GW3-10

Spearman: median 0.977, minimum 0.974.

| GW | Team-kickoffs | Spearman |
|---|---|---|
| 3 | 20 | 0.974 |
| 4 | 20 | 0.976 |
| 5 | 20 | 0.978 |
| 6 | 20 | 0.977 |
| 7 | 20 | 0.977 |
| 8 | 20 | 0.974 |
| 9 | 20 | 0.982 |
| 10 | 20 | 0.978 |

The 5 biggest rank disagreements at GW10 (rank 1 is the highest rating):

| Club | Match | Ours | Our rank | beyondELO | beyondELO rank | Rank gap |
|---|---|---|---|---|---|---|
| Liverpool | 26-27-prem-crystal-palace-vs-liverpool | 1917.2 | 3 | 1951.0 | 5.5 | 2.5 |
| Bournemouth | 26-27-prem-ipswich-town-vs-afc-bournemouth | 1871.9 | 6 | 1955.0 | 4 | 2 |
| Coventry City | 26-27-prem-everton-vs-coventry-city | 1667.8 | 18 | 1710.0 | 20 | 2 |
| Hull City | 26-27-prem-arsenal-vs-hull-city | 1583.5 | 20 | 1759.0 | 18 | 2 |
| Spurs | 26-27-prem-leeds-united-vs-tottenham-hotspur | 1790.9 | 14 | 1868.0 | 12 | 2 |

## Match counts

A match is in a window if a fixture, our ratings or beyondELO's place it there. The run stops, with no report, if any lacks a partner.

| Window | Matches | Finished result | Our rating | beyondELO rating | Complete |
|---|---|---|---|---|---|
| fit | 261 | 261 | 261 | 261 | 261 |
| 2025-2026 GW27-38 | 119 | 119 | 119 | 119 | 119 |
| 2026-2027 GW3-10 | 80 | 80 | 80 | 80 | 80 |

## Provenance

`upstream_commit` is the local checkout that `load_as_of` read the results from.

| Item | Value |
|---|---|
| commit | 11f1a6ce363c428834f812297d3b3e1e5d79b48a |
| code_clean | yes |
| harness_clean | yes |
| model_version | 0.1.1-elo |
| upstream_commit | ac8be9caa3bce7aa6c2b73d5a33a9f5c0b2f0e41 |
| upstream_clean | yes |
| upstream_time | 2026-11-13T15:35:47Z |
| model_yaml_sha256 | 9178c1bc16fe68947253d75270a42cdfa0957e0bc3fba8a0637ac15f3f2a6a8c |
| settings_sha256 | 4819e0e77db808d00afddc4db00716ab241cfdd26fbb4d1e2bdab3be688b4aeb |
| harness_sha256 | 1dcadfb74e555eb4ac3b6cebbd5d04ee0d8e39bca2e2698924a51b7500d44710 |
| date | 2026-11-18 |
| upstream_commit in outputs/meta.csv (the publish elo_ratings.csv came from) | 648ec2114fbc7ad440782d2488ead6cc93246ff7 |
| sha256 outputs/elo_ratings.csv | 178f3cfcf77b0210cef48e589642d950d471acbf9a085039cbe4e0bdbe6e3961 |
| sha256 data/external/beyondelo/2025-2026.parquet | af29c97b8fe8099e4f1eea9c5bf7a04f37fe62828aa830ef1bc9f941588fa593 |
| sha256 data/external/beyondelo/2026-2027.parquet | 996d1e2f9c3ef2cd0af209100f52b18686d3b2194e433a3dbfc4ca8366929427 |

## Credit

Ratings from beyondELO (https://beyondelo.com), CC BY 4.0.
