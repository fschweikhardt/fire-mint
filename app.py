import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import gradio as gr
import pandas as pd
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse


@dataclass
class Inputs:
    taxable_current: float
    taxable_annual: float
    taxable_annual_increase: float
    roth_current: float
    roth_annual: float
    roth_annual_increase: float
    hsa_current: float
    hsa_annual: float
    hsa_annual_increase: float
    plan_529_current: float
    plan_529_annual: float
    start_age: int
    retire_age: int
    end_age: int
    annual_return_pct: float
    fixed_income_pct: float
    plan_529_return_pct: float
    inflation_pct: float
    real_dollars: bool
    desired_spend: float
    withdrawal_rate_pct: float


@dataclass
class ProjectionResult:
    retirement_display: pd.DataFrame
    fixed_income_display: pd.DataFrame
    education_display: pd.DataFrame
    tax_split_display: pd.DataFrame
    tax_split_markdown: str
    chart_df: pd.DataFrame
    kpi_markdown: str
    csv_path: str


def round_currency(amount: float) -> int:
    """Round to the nearest dollar for display."""
    return round(amount)


def format_currency(amount: float) -> str:
    """Format a number as currency with commas."""
    return f"{round_currency(amount):,}"


def format_growth_pct(pct: float) -> str:
    """Format growth rate for column headers."""
    if abs(pct - round(pct)) < 1e-9:
        return f"{int(round(pct))}"
    return f"{pct:g}"


def rate_slider(label: str, value: float, info: str, maximum: float = 14) -> gr.Slider:
    return gr.Slider(
        minimum=0,
        maximum=maximum,
        value=value,
        step=0.5,
        label=label,
        info=info,
    )


def _as_float(value, default: float = 0.0) -> float:
    """Coerce Gradio Number values; empty fields arrive as None."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int = 0) -> int:
    """Coerce Gradio Number values to int; empty fields arrive as None."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def deflate(amount: float, inflation: float, year_index: int, real_dollars: bool) -> float:
    if not real_dollars or inflation <= 0 or year_index <= 0:
        return amount
    return amount / ((1 + inflation) ** year_index)


def milestone_age(ages: List[int], totals: List[float], threshold: float) -> Optional[int]:
    for age, total in zip(ages, totals):
        if total >= threshold:
            return age
    return None


def build_kpi_markdown(
    inputs: Inputs,
    ages: List[int],
    totals: List[float],
    fixed_incomes: List[float],
    dollar_label: str,
) -> str:
    age_to_idx = {age: i for i, age in enumerate(ages)}
    key_ages: List[int] = []
    for age in (inputs.start_age, inputs.retire_age, 55, 60, 65, inputs.end_age):
        if age in age_to_idx and age not in key_ages:
            key_ages.append(age)
    key_ages.sort()

    rows = []
    for age in key_ages:
        idx = age_to_idx[age]
        tag = ""
        if age == inputs.retire_age:
            tag = " *(retire)*"
        elif age == inputs.start_age:
            tag = " *(start)*"
        elif age == inputs.end_age:
            tag = " *(end)*"
        rows.append(
            f"| {age}{tag} | ${format_currency(totals[idx])} | "
            f"${format_currency(fixed_incomes[idx])} |"
        )

    withdrawal = max(inputs.withdrawal_rate_pct, 0.0)
    if withdrawal > 0 and inputs.desired_spend > 0:
        required = inputs.desired_spend / (withdrawal / 100.0)
        fire_age = milestone_age(ages, totals, required)
        if fire_age is None:
            fire_line = (
                f"**FIRE target:** ${format_currency(required)} nest egg "
                f"(${format_currency(inputs.desired_spend)}/yr ÷ {format_growth_pct(withdrawal)}%) — "
                f"**not reached** by age {inputs.end_age}."
            )
        else:
            fire_line = (
                f"**FIRE target:** ${format_currency(required)} nest egg "
                f"(${format_currency(inputs.desired_spend)}/yr ÷ {format_growth_pct(withdrawal)}%) — "
                f"**hit at age {fire_age}**."
            )
    else:
        fire_line = (
            "**FIRE target:** set desired annual spend and a withdrawal rate "
            "to see when you hit financial independence."
        )

    million_age = milestone_age(ages, totals, 1_000_000)
    if million_age is None:
        million_line = f"**$1M milestone:** not reached by age {inputs.end_age}."
    else:
        million_line = f"**$1M milestone:** age **{million_age}**."

    end_total = totals[-1] if totals else 0
    end_income = fixed_incomes[-1] if fixed_incomes else 0
    retire_idx = age_to_idx.get(inputs.retire_age)
    if retire_idx is not None:
        retire_blurb = (
            f"At retire age **{inputs.retire_age}**: "
            f"**${format_currency(totals[retire_idx])}** nest egg → "
            f"**${format_currency(fixed_incomes[retire_idx])}/yr** simple yield."
        )
    else:
        retire_blurb = (
            f"Retire age **{inputs.retire_age}** is outside the projection range "
            f"({inputs.start_age}–{inputs.end_age})."
        )

    table = "\n".join(
        [
            f"| Age | Nest egg ({dollar_label}) | Simple yield @ {format_growth_pct(inputs.fixed_income_pct)}% |",
            "| ---: | ---: | ---: |",
            *rows,
        ]
    )

    return "\n".join(
        [
            "## At a glance",
            "",
            f"{retire_blurb}",
            "",
            f"By age **{inputs.end_age}**: **${format_currency(end_total)}** "
            f"({dollar_label}) → **${format_currency(end_income)}/yr** simple yield.",
            "",
            fire_line,
            "",
            million_line,
            "",
            table,
            "",
            "_Simple yield = total nest egg × fixed-income rate. "
            "Not a tax-aware paycheck, Safe Withdrawal Rate, or drawdown plan._",
        ]
    )


def write_csv(df: pd.DataFrame) -> str:
    fd, path = tempfile.mkstemp(prefix="fire-mint-", suffix=".csv")
    os.close(fd)
    df.to_csv(path, index=False)
    return path


def project(inputs: Inputs, include_tax_split_in_csv: bool = False) -> ProjectionResult:
    start_age = max(0, inputs.start_age)
    end_age = max(start_age, inputs.end_age)
    retire_age = max(0, inputs.retire_age)

    ages: List[int] = list(range(start_age, end_age + 1))

    taxable_bal = inputs.taxable_current
    roth_bal = inputs.roth_current
    hsa_bal = inputs.hsa_current
    plan_529_bal = inputs.plan_529_current

    r = inputs.annual_return_pct / 100.0
    r_529 = inputs.plan_529_return_pct / 100.0
    fixed_r = inputs.fixed_income_pct / 100.0
    inflation = inputs.inflation_pct / 100.0
    growth_label = format_growth_pct(inputs.annual_return_pct)
    plan_529_label = format_growth_pct(inputs.plan_529_return_pct)
    fixed_income_label = format_growth_pct(inputs.fixed_income_pct)
    dollar_label = "today's $" if inputs.real_dollars else "nominal $"

    ages_out: List[int] = []
    taxable_out: List[float] = []
    roth_out: List[float] = []
    hsa_out: List[float] = []
    annual_in_out: List[float] = []
    total_out: List[float] = []
    fixed_out: List[float] = []
    plan_529_out: List[float] = []

    # Contribution year index only advances while still contributing (pre-retire).
    contrib_year = 0

    for idx, age in enumerate(ages):
        contributing = age < retire_age
        if contributing:
            taxable_contrib = inputs.taxable_annual + (
                contrib_year * inputs.taxable_annual_increase
            )
            roth_contrib = inputs.roth_annual + (contrib_year * inputs.roth_annual_increase)
            hsa_contrib = inputs.hsa_annual + (contrib_year * inputs.hsa_annual_increase)
            contrib_year += 1
        else:
            taxable_contrib = 0.0
            roth_contrib = 0.0
            hsa_contrib = 0.0

        taxable_bal = (taxable_bal * (1 + r)) + taxable_contrib
        roth_bal = (roth_bal * (1 + r)) + roth_contrib
        hsa_bal = (hsa_bal * (1 + r)) + hsa_contrib

        plan_529_contrib = inputs.plan_529_annual
        plan_529_bal = (plan_529_bal * (1 + r_529)) + plan_529_contrib

        annual_in = taxable_contrib + roth_contrib + hsa_contrib
        total_nom = taxable_bal + roth_bal + hsa_bal

        taxable_d = deflate(taxable_bal, inflation, idx, inputs.real_dollars)
        roth_d = deflate(roth_bal, inflation, idx, inputs.real_dollars)
        hsa_d = deflate(hsa_bal, inflation, idx, inputs.real_dollars)
        annual_in_d = deflate(annual_in, inflation, idx, inputs.real_dollars)
        total_d = deflate(total_nom, inflation, idx, inputs.real_dollars)
        fixed_d = total_d * fixed_r
        plan_529_d = deflate(plan_529_bal, inflation, idx, inputs.real_dollars)

        ages_out.append(age)
        taxable_out.append(taxable_d)
        roth_out.append(roth_d)
        hsa_out.append(hsa_d)
        annual_in_out.append(annual_in_d)
        total_out.append(total_d)
        fixed_out.append(fixed_d)
        plan_529_out.append(plan_529_d)

    retirement_rows: List[Tuple] = []
    education_rows: List[Tuple] = []
    fixed_income_rows: List[Tuple] = []
    tax_split_rows: List[Tuple] = []
    export_rows: List[dict] = []
    chart_rows: List[dict] = []

    taxable_withdraw_col = f"Taxable withdraw @ {fixed_income_label}%"
    nontax_withdraw_col = f"Non-taxable withdraw @ {fixed_income_label}%"
    combined_withdraw_col = f"Combined withdraw @ {fixed_income_label}%"

    for i, age in enumerate(ages_out):
        taxable_display = round_currency(taxable_out[i])
        roth_display = round_currency(roth_out[i])
        hsa_display = round_currency(hsa_out[i])
        annual_display = round_currency(annual_in_out[i])
        total_display = taxable_display + roth_display + hsa_display
        fixed_display = round_currency(fixed_out[i])
        plan_529_display = round_currency(plan_529_out[i])
        nontax_balance = roth_display + hsa_display
        taxable_withdraw = round_currency(taxable_display * fixed_r)
        nontax_withdraw = round_currency(nontax_balance * fixed_r)
        combined_withdraw = taxable_withdraw + nontax_withdraw

        retirement_rows.append(
            (
                age,
                format_currency(taxable_display),
                format_currency(roth_display),
                format_currency(hsa_display),
                format_currency(annual_display),
                format_currency(total_display),
            )
        )
        education_rows.append((age, format_currency(plan_529_display)))
        fixed_income_rows.append(
            (
                age,
                format_currency(total_display),
                format_currency(fixed_display),
            )
        )
        tax_split_rows.append(
            (
                age,
                format_currency(taxable_display),
                format_currency(nontax_balance),
                format_currency(taxable_withdraw),
                format_currency(nontax_withdraw),
                format_currency(combined_withdraw),
            )
        )
        row = {
            "Age": age,
            f"Taxable Accounts @ {growth_label}% ({dollar_label})": taxable_display,
            f"ROTH IRA @ {growth_label}% ({dollar_label})": roth_display,
            f"HSA @ {growth_label}% ({dollar_label})": hsa_display,
            f"ANNUAL IN ({dollar_label})": annual_display,
            f"TOTAL ({dollar_label})": total_display,
            f"Annual Fixed Income @ {fixed_income_label}% ({dollar_label})": fixed_display,
            f"529 Balance @ {plan_529_label}% ({dollar_label})": plan_529_display,
        }
        if include_tax_split_in_csv:
            row.update(
                {
                    f"Taxable balance ({dollar_label})": taxable_display,
                    f"Non-taxable balance Roth+HSA ({dollar_label})": nontax_balance,
                    f"{taxable_withdraw_col} ({dollar_label})": taxable_withdraw,
                    f"{nontax_withdraw_col} ({dollar_label})": nontax_withdraw,
                    f"{combined_withdraw_col} ({dollar_label})": combined_withdraw,
                }
            )
        export_rows.append(row)
        for account, value in (
            ("Taxable", taxable_display),
            ("Roth IRA", roth_display),
            ("HSA", hsa_display),
            ("Total", total_display),
        ):
            chart_rows.append({"Age": age, "Account": account, "Balance": value})

    retirement_df = pd.DataFrame(
        retirement_rows,
        columns=[
            "Age",
            f"Taxable Accounts @ {growth_label}%",
            f"ROTH IRA @ {growth_label}%",
            f"HSA @ {growth_label}%",
            "ANNUAL IN",
            "TOTAL",
        ],
    )
    education_df = pd.DataFrame(
        education_rows,
        columns=["Age", f"529 Balance @ {plan_529_label}%"],
    )
    fixed_income_df = pd.DataFrame(
        fixed_income_rows,
        columns=[
            "Age",
            "Total Retirement Savings",
            f"Annual Fixed Income @ {fixed_income_label}%",
        ],
    )
    tax_split_df = pd.DataFrame(
        tax_split_rows,
        columns=[
            "Age",
            "Taxable balance",
            "Non-taxable balance (Roth + HSA)",
            taxable_withdraw_col,
            nontax_withdraw_col,
            combined_withdraw_col,
        ],
    )
    chart_df = pd.DataFrame(chart_rows)
    export_df = pd.DataFrame(export_rows)

    # Recompute display totals/fixed for KPI consistency with rounded account sums
    kpi_totals = []
    kpi_fixed = []
    for i in range(len(ages_out)):
        t = (
            round_currency(taxable_out[i])
            + round_currency(roth_out[i])
            + round_currency(hsa_out[i])
        )
        kpi_totals.append(float(t))
        kpi_fixed.append(float(round_currency(t * fixed_r)))

    kpi_markdown = build_kpi_markdown(
        inputs, ages_out, kpi_totals, kpi_fixed, dollar_label
    )

    tax_split_markdown = (
        "### Optional: taxable vs non-taxable withdraw\n\n"
        f"Same fixed-income rate (**{fixed_income_label}%**) applied separately to "
        "**Taxable** vs **Roth + HSA** balances.\n\n"
        "- **Taxable withdraw** = taxable balance × rate\n"
        "- **Non-taxable withdraw** = (Roth + HSA) × rate "
        "(qualified Roth / HSA medical-style withdrawals; simplified)\n"
        "- **Combined** may differ from the standard simple-yield column by $1 "
        "due to rounding\n\n"
        "_Optional view only — the standard Fixed Income table above is unchanged._"
    )

    return ProjectionResult(
        retirement_display=retirement_df,
        fixed_income_display=fixed_income_df,
        education_display=education_df,
        tax_split_display=tax_split_df,
        tax_split_markdown=tax_split_markdown,
        chart_df=chart_df,
        kpi_markdown=kpi_markdown,
        csv_path=write_csv(export_df),
    )


def compute_tables(
    taxable_current: float,
    taxable_annual: float,
    taxable_increase_enabled: bool,
    taxable_increase_amount: float,
    roth_current: float,
    roth_annual: float,
    roth_increase_enabled: bool,
    roth_increase_amount: float,
    hsa_current: float,
    hsa_annual: float,
    hsa_increase_enabled: bool,
    hsa_increase_amount: float,
    plan_529_current: float,
    plan_529_annual: float,
    start_age: int,
    retire_age: int,
    end_age: int,
    growth_rate_pct: float,
    fixed_income_rate_pct: float,
    plan_529_growth_pct: float,
    inflation_pct: float,
    real_dollars: bool,
    desired_spend: float,
    withdrawal_rate_pct: float,
    show_tax_split: bool,
):
    show_split = _as_bool(show_tax_split, False)
    inputs = Inputs(
        taxable_current=_as_float(taxable_current),
        taxable_annual=_as_float(taxable_annual),
        taxable_annual_increase=(
            _as_float(taxable_increase_amount, 100)
            if _as_bool(taxable_increase_enabled)
            else 0.0
        ),
        roth_current=_as_float(roth_current),
        roth_annual=_as_float(roth_annual),
        roth_annual_increase=(
            _as_float(roth_increase_amount, 100) if _as_bool(roth_increase_enabled) else 0.0
        ),
        hsa_current=_as_float(hsa_current),
        hsa_annual=_as_float(hsa_annual),
        hsa_annual_increase=(
            _as_float(hsa_increase_amount, 100) if _as_bool(hsa_increase_enabled) else 0.0
        ),
        plan_529_current=_as_float(plan_529_current),
        plan_529_annual=_as_float(plan_529_annual),
        start_age=_as_int(start_age, 40),
        retire_age=_as_int(retire_age, 65),
        end_age=_as_int(end_age, 100),
        annual_return_pct=_as_float(growth_rate_pct, 7.0),
        fixed_income_pct=_as_float(fixed_income_rate_pct, 3.0),
        plan_529_return_pct=_as_float(plan_529_growth_pct, 7.0),
        inflation_pct=_as_float(inflation_pct, 2.5),
        real_dollars=_as_bool(real_dollars, True),
        desired_spend=_as_float(desired_spend, 60000),
        withdrawal_rate_pct=_as_float(withdrawal_rate_pct, 4.0),
    )
    result = project(inputs, include_tax_split_in_csv=show_split)
    return (
        result.kpi_markdown,
        result.chart_df,
        result.retirement_display,
        result.fixed_income_display,
        gr.update(value=result.tax_split_markdown, visible=show_split),
        gr.update(value=result.tax_split_display, visible=show_split),
        result.education_display,
        result.csv_path,
    )


def account_block(title: str, current_default: float, annual_default: float, hint: str = ""):
    with gr.Group():
        gr.Markdown(f"**{title}**" + (f"  \n_{hint}_" if hint else ""))
        current = gr.Number(label="Current amount", value=current_default, precision=0)
        annual = gr.Number(label="Annual contribution", value=annual_default, precision=0)
        increase_enabled = gr.Checkbox(
            label="Increase contribution each year",
            value=False,
        )
        increase_amount = gr.Number(
            label="Annual step-up ($)",
            value=100,
            precision=0,
            info="Added to the contribution each contributing year (year 0, then +N, +2N, …)",
        )
    return current, annual, increase_enabled, increase_amount


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Fire Mint") as demo:
        gr.Markdown(
            """
# Fire Mint
### Retirement & education projection

Change any input — the summary, chart, and tables update live.
            """
        )

        with gr.Row():
            with gr.Column():
                (
                    taxable_current,
                    taxable_annual,
                    taxable_increase_enabled,
                    taxable_increase_amount,
                ) = account_block("Taxable Accounts", 0, 15000)
                (
                    roth_current,
                    roth_annual,
                    roth_increase_enabled,
                    roth_increase_amount,
                ) = account_block(
                    "ROTH IRA",
                    0,
                    7000,
                    "Soft limit hint: IRA contribution caps change yearly (often ~$7k under 50).",
                )
                (
                    hsa_current,
                    hsa_annual,
                    hsa_increase_enabled,
                    hsa_increase_amount,
                ) = account_block(
                    "HSA",
                    0,
                    4300,
                    "Soft limit hint: HSA caps change yearly (self-only vs family).",
                )

            with gr.Column():
                start_age = gr.Number(label="Start Age", value=40, precision=0)
                retire_age = gr.Number(
                    label="Retire Age",
                    value=65,
                    precision=0,
                    info="Retirement contributions stop at this age; balances keep growing",
                )
                end_age = gr.Number(label="End Age", value=100, precision=0)
                growth_rate_pct = rate_slider(
                    "Growth rate (%)",
                    7,
                    "Annual growth rate for Taxable, Roth, and HSA",
                )
                inflation_pct = rate_slider(
                    "Inflation (%)",
                    2.5,
                    "Used when showing today's dollars",
                    maximum=10,
                )
                real_dollars = gr.Checkbox(
                    label="Show today's dollars (inflation-adjusted)",
                    value=True,
                    info="Off = nominal future dollars",
                )
                desired_spend = gr.Number(
                    label="Desired annual spend (FIRE)",
                    value=60000,
                    precision=0,
                    info="Spending goal used with withdrawal rate to size the nest egg",
                )
                withdrawal_rate_pct = rate_slider(
                    "Withdrawal rate (%)",
                    4,
                    "FIRE nest egg = spend ÷ this rate (classic 4% rule)",
                    maximum=10,
                )

        kpi_md = gr.Markdown()
        chart = gr.LinePlot(
            x="Age",
            y="Balance",
            color="Account",
            title="Retirement balances over time",
            x_title="Age",
            y_title="Balance ($)",
            height=360,
        )
        csv_file = gr.File(label="Download projection CSV", interactive=False)

        with gr.Tabs():
            with gr.Tab("Retirement"):
                gr.Markdown(
                    """
Each row is one age in your projection:
- **Account columns**: End-of-year balance (growth on prior balance, then that year's contribution)
- **ANNUAL IN**: Total new retirement contributions that year (0 at/after retire age)
- **TOTAL**: Sum of the three account columns (do not add ANNUAL IN again)
                    """
                )
                retirement_df = gr.Dataframe(
                    wrap=True,
                    max_height=400,
                    label="Retirement Projection",
                )
            with gr.Tab("Income"):
                gr.Markdown(
                    """
### Fixed income potential

Potential annual income if you applied a simple yield to your total nest egg.
This is **not** a Safe Withdrawal Rate plan, tax-aware paycheck, or longevity model —
just `total × rate` for a quick sense of scale.
                    """
                )
                fixed_income_rate_pct = rate_slider(
                    "Fixed income rate (%)",
                    3,
                    "Annual yield applied to total retirement savings",
                )
                fixed_income_df = gr.Dataframe(
                    wrap=True,
                    max_height=300,
                    label="Fixed Income Projection",
                )
                show_tax_split = gr.Checkbox(
                    label="Show taxable vs non-taxable withdrawal split",
                    value=False,
                    info="Optional view: does not change the standard simple-yield table above",
                )
                tax_split_md = gr.Markdown(visible=False)
                tax_split_df = gr.Dataframe(
                    wrap=True,
                    max_height=300,
                    label="Taxable vs non-taxable withdraw",
                    visible=False,
                )
            with gr.Tab("Education"):
                gr.Markdown("### 529 plan projection")
                plan_529_current = gr.Number(
                    label="529 current balance",
                    value=0,
                    precision=0,
                )
                plan_529_annual = gr.Number(
                    label="529 annual contribution",
                    value=0,
                    precision=0,
                    info="Contributions continue through end age (separate from retirement cutoff)",
                )
                plan_529_growth_pct = rate_slider(
                    "529 growth rate (%)",
                    7,
                    "Annual growth rate for the 529 balance",
                )
                education_df = gr.Dataframe(
                    wrap=True,
                    max_height=300,
                    label="529 Plan Projection",
                )
            with gr.Tab("Assumptions"):
                gr.Markdown(
                    """
### How the math works

1. **Growth then contribution** each year: `balance = balance × (1 + r) + contribution`.
2. **Step-ups** add N dollars to the annual contribution each contributing year (0, N, 2N, …).
3. **Retire age** stops Taxable / Roth / HSA contributions; growth continues to end age.
4. **529** has its own balance, contribution, and growth rate; it is not in TOTAL.
5. **Today's dollars** divides each year's figures by `(1 + inflation)^years_from_start`.
6. **FIRE nest egg** = desired spend ÷ withdrawal rate; first age TOTAL ≥ that amount is the hit.
7. **Simple yield** on the Income tab is illustrative only — not advice.
8. **Optional tax split** (Income tab): taxable withdraw = Taxable × rate;
   non-taxable withdraw = (Roth + HSA) × rate. Off by default; standard figures stay the same.

Contribution limit hints on Roth/HSA are informational soft caps; the app does not enforce them.
                    """
                )

        inputs = [
            taxable_current,
            taxable_annual,
            taxable_increase_enabled,
            taxable_increase_amount,
            roth_current,
            roth_annual,
            roth_increase_enabled,
            roth_increase_amount,
            hsa_current,
            hsa_annual,
            hsa_increase_enabled,
            hsa_increase_amount,
            plan_529_current,
            plan_529_annual,
            start_age,
            retire_age,
            end_age,
            growth_rate_pct,
            fixed_income_rate_pct,
            plan_529_growth_pct,
            inflation_pct,
            real_dollars,
            desired_spend,
            withdrawal_rate_pct,
            show_tax_split,
        ]
        outputs = [
            kpi_md,
            chart,
            retirement_df,
            fixed_income_df,
            tax_split_md,
            tax_split_df,
            education_df,
            csv_file,
        ]

        demo.load(compute_tables, inputs=inputs, outputs=outputs)
        for comp in inputs:
            comp.change(compute_tables, inputs=inputs, outputs=outputs)

    return demo


QR_PAGE = Path(__file__).resolve().parent / "qr" / "index.html"


def register_qr_route(app: FastAPI) -> None:
    """Serve shared qr/index.html at GET /qr (copy the qr/ folder to other projects)."""

    @app.get("/qr", include_in_schema=False)
    def qr_page() -> FileResponse:
        return FileResponse(QR_PAGE, media_type="text/html; charset=utf-8")


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "7860"))

    demo = build_ui()
    demo.queue()

    api = FastAPI()
    register_qr_route(api)
    app = gr.mount_gradio_app(api, demo, path="/")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
