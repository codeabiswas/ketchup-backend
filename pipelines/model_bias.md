# Model Bias Detection

## Section 2.4: Model Bias Detection (Using Slicing Techniques)

The model-bias workflow in this repo uses synthetic planning cycles to evaluate whether some slices receive systematically worse outcomes than others.

Primary slicing dimensions:

- `city_tier x budget_tier`
- `distance_bucket x car_ratio_bucket`
- optional extra intersections including `dietary_flag`

Primary metrics:

- `json_valid`
- `options_count_ok`
- `budget_compliance`
- `distance_compliance`
- `logistics_feasible`
- `full_budget_ok`

Workflow:

1. Generate synthetic requests and score model outputs with `scripts/run_model_bias_synthetic_eval.py`.
2. Aggregate slice metrics and bootstrap intervals with `scripts/check_model_bias_slices.py`.
3. Run a Fairlearn disparity check with `scripts/check_model_bias_fairlearn.py`.

This detects coverage and constraint disparity even when the slices are not protected-class demographics.

## Section 2.5: Code to Check for Bias

Relevant files:

- `scripts/run_model_bias_synthetic_eval.py`
- `scripts/check_model_bias_slices.py`
- `scripts/check_model_bias_fairlearn.py`
- `pipelines/bias_detection.py`
- `scripts/detect_bias.py`

Example commands:

```bash
python scripts/run_model_bias_synthetic_eval.py \
  --base-url http://localhost:8080 \
  --model Qwen/Qwen3-4B-Instruct-2507 \
  --n 100 \
  --save-csv data/reports/model_bias_results.csv
```

```bash
python scripts/check_model_bias_slices.py \
  --csv data/reports/model_bias_results.csv \
  --out data/reports/model_bias_slicing_report.md
```

```bash
python scripts/check_model_bias_fairlearn.py \
  --csv data/reports/model_bias_results.csv \
  --slice city_tier,budget_tier
```

Mitigation ideas tracked by these scripts:

- budget prefiltering,
- validate-then-repair loops,
- fallback low-cost activities for sparse coverage slices.
