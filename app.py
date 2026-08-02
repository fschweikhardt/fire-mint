import os
from pathlib import Path

import gradio as gr
import pandas as pd
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Inputs:
    taxable_current: float
    taxable_annual: float
    roth_current: float
    roth_annual: float
    hsa_current: float
    hsa_annual: float
    plan_529_annual: float
    start_age: int
    end_age: int
    annual_return_pct: float
    fixed_income_pct: float
    plan_529_return_pct: float
    taxable_annual_increase: float = 0
    roth_annual_increase: float = 0
    hsa_annual_increase: float = 0


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


def rate_slider(label: str, value: float, info: str) -> gr.Slider:
    return gr.Slider(
        minimum=0,
        maximum=14,
        value=value,
        step=0.5,
        label=label,
        info=info,
    )


def project(inputs: Inputs) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    start_age = max(0, inputs.start_age)
    end_age = max(start_age, inputs.end_age)

    ages: List[int] = list(range(start_age, end_age + 1))

    taxable_bal = inputs.taxable_current
    roth_bal = inputs.roth_current
    hsa_bal = inputs.hsa_current
    plan_529_bal = 0.0

    retirement_rows: List[Tuple] = []
    education_rows: List[Tuple] = []
    fixed_income_rows: List[Tuple] = []

    r = inputs.annual_return_pct / 100.0
    r_529 = inputs.plan_529_return_pct / 100.0
    fixed_r = inputs.fixed_income_pct / 100.0
    growth_label = format_growth_pct(inputs.annual_return_pct)
    plan_529_label = format_growth_pct(inputs.plan_529_return_pct)
    fixed_income_label = format_growth_pct(inputs.fixed_income_pct)

    for idx, age in enumerate(ages):
        taxable_contrib = inputs.taxable_annual + (idx * inputs.taxable_annual_increase)
        roth_contrib = inputs.roth_annual + (idx * inputs.roth_annual_increase)
        hsa_contrib = inputs.hsa_annual + (idx * inputs.hsa_annual_increase)

        taxable_bal = (taxable_bal * (1 + r)) + taxable_contrib
        roth_bal = (roth_bal * (1 + r)) + roth_contrib
        hsa_bal = (hsa_bal * (1 + r)) + hsa_contrib

        annual_in = taxable_contrib + roth_contrib + hsa_contrib

        taxable_display = round_currency(taxable_bal)
        roth_display = round_currency(roth_bal)
        hsa_display = round_currency(hsa_bal)
        total_display = taxable_display + roth_display + hsa_display
        fixed_income_display = round_currency(total_display * fixed_r)

        plan_529_contrib = inputs.plan_529_annual
        plan_529_bal = (plan_529_bal * (1 + r_529)) + plan_529_contrib

        retirement_rows.append(
            (
                age,
                format_currency(taxable_display),
                format_currency(roth_display),
                format_currency(hsa_display),
                format_currency(annual_in),
                format_currency(total_display),
            )
        )

        education_rows.append(
            (
                age,
                format_currency(plan_529_bal),
            )
        )

        fixed_income_rows.append(
            (
                age,
                format_currency(total_display),
                format_currency(fixed_income_display),
            )
        )

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
        columns=[
            "Age",
            f"529 Balance @ {plan_529_label}%",
        ],
    )

    fixed_income_df = pd.DataFrame(
        fixed_income_rows,
        columns=[
            "Age",
            "Total Retirement Savings",
            f"Annual Fixed Income @ {fixed_income_label}%",
        ],
    )

    return retirement_df, education_df, fixed_income_df


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


def compute_tables(
    taxable_current: float,
    taxable_annual: float,
    taxable_increase_enabled: bool,
    roth_current: float,
    roth_annual: float,
    roth_increase_enabled: bool,
    hsa_current: float,
    hsa_annual: float,
    hsa_increase_enabled: bool,
    plan_529_annual: float,
    start_age: int,
    end_age: int,
    growth_rate_pct: float,
    fixed_income_rate_pct: float,
    plan_529_growth_pct: float,
):
    inputs = Inputs(
        taxable_current=_as_float(taxable_current),
        taxable_annual=_as_float(taxable_annual),
        roth_current=_as_float(roth_current),
        roth_annual=_as_float(roth_annual),
        hsa_current=_as_float(hsa_current),
        hsa_annual=_as_float(hsa_annual),
        plan_529_annual=_as_float(plan_529_annual),
        start_age=_as_int(start_age, 40),
        end_age=_as_int(end_age, 100),
        annual_return_pct=_as_float(growth_rate_pct, 7.0),
        fixed_income_pct=_as_float(fixed_income_rate_pct, 3.0),
        plan_529_return_pct=_as_float(plan_529_growth_pct, 7.0),
        taxable_annual_increase=100 if taxable_increase_enabled else 0,
        roth_annual_increase=100 if roth_increase_enabled else 0,
        hsa_annual_increase=100 if hsa_increase_enabled else 0,
    )
    return project(inputs)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Retirement Projection") as demo:
        gr.Markdown("""
        # Retirement & Education Planning
        
        Enter current balances and contribution amounts for each account.
        """)

        with gr.Row():
            with gr.Column():
                with gr.Group():
                    gr.Markdown("**Taxable Accounts**")
                    taxable_current = gr.Number(
                        label="Current amount",
                        value=0,
                        precision=0,
                    )
                    taxable_annual = gr.Number(
                        label="Annual contribution",
                        value=15000,
                        precision=0,
                    )
                    taxable_increase_enabled = gr.Checkbox(
                        label="Add $100/yr to annual contribution",
                        value=False,
                    )

                with gr.Group():
                    gr.Markdown("**ROTH IRA**")
                    roth_current = gr.Number(
                        label="Current amount",
                        value=0,
                        precision=0,
                    )
                    roth_annual = gr.Number(
                        label="Annual contribution",
                        value=15000,
                        precision=0,
                    )
                    roth_increase_enabled = gr.Checkbox(
                        label="Add $100/yr to annual contribution",
                        value=False,
                    )

                with gr.Group():
                    gr.Markdown("**HSA**")
                    hsa_current = gr.Number(
                        label="Current amount",
                        value=0,
                        precision=0,
                    )
                    hsa_annual = gr.Number(
                        label="Annual contribution",
                        value=8500,
                        precision=0,
                    )
                    hsa_increase_enabled = gr.Checkbox(
                        label="Add $100/yr to annual contribution",
                        value=False,
                    )

            with gr.Column():
                start_age = gr.Number(label="Start Age", value=40, precision=0)
                end_age = gr.Number(label="End Age", value=100, precision=0)
                growth_rate_pct = rate_slider(
                    "Growth rate (%)",
                    7,
                    "Annual growth rate for retirement accounts",
                )

        gr.Markdown("""
        ### FIRE-MINT - Retirement Savings

        Each row is one age in your projection:
        - **Account columns**: End-of-year balance for that account (current balance, growth, and contributions)
        - **ANNUAL IN**: Total new contributions that year
        - **TOTAL**: Sum of the three account columns (do not add ANNUAL IN again)
        """)
        
        retirement_df = gr.Dataframe(
            wrap=True,
            max_height=400,
            label="Retirement Projection",
        )

        gr.Markdown("""
        ### Fixed Income Potential

        Potential annual income from total retirement savings at the selected rate.
        """)

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

        gr.Markdown("### Education Savings (529 Plan)")
        
        plan_529_annual = gr.Number(
            label="529 Annual Contribution",
            value=0,
            precision=0,
            info="Annual contribution to 529 education savings plan",
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

        inputs = [
            taxable_current,
            taxable_annual,
            taxable_increase_enabled,
            roth_current,
            roth_annual,
            roth_increase_enabled,
            hsa_current,
            hsa_annual,
            hsa_increase_enabled,
            plan_529_annual,
            start_age,
            end_age,
            growth_rate_pct,
            fixed_income_rate_pct,
            plan_529_growth_pct,
        ]

        demo.load(compute_tables, inputs=inputs, outputs=[retirement_df, education_df, fixed_income_df])
        for comp in inputs:
            comp.change(compute_tables, inputs=inputs, outputs=[retirement_df, education_df, fixed_income_df])

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
