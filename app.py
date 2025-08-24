import gradio as gr
import pandas as pd
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Inputs:
    hsa_annual: float
    roth_annual: float
    simple_ira_annual: float
    plan_529_annual: float
    current_savings: float
    start_age: int
    end_age: int
    annual_return_pct: float
    fixed_income_pct: float
    hsa_annual_increase: float = 0
    roth_annual_increase: float = 0


def format_currency(amount: float) -> str:
    """Format a number as currency with commas."""
    return f"{int(amount):,}"


def project(inputs: Inputs) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    start_age = max(0, inputs.start_age)
    end_age = max(start_age, inputs.end_age)

    ages: List[int] = list(range(start_age, end_age + 1))

    # Track balances for each account
    hsa_bal = 0.0
    roth_bal = 0.0
    simple_bal = 0.0
    plan_529_bal = 0.0

    # Starting current savings
    current_savings = inputs.current_savings

    retirement_rows: List[Tuple] = []
    education_rows: List[Tuple] = []
    fixed_income_rows: List[Tuple] = []

    r = inputs.annual_return_pct / 100.0
    fixed_r = inputs.fixed_income_pct / 100.0

    for idx, age in enumerate(ages):
        # Calculate this year's contributions with annual increases
        hsa_contrib = inputs.hsa_annual + (idx * inputs.hsa_annual_increase)
        roth_contrib = inputs.roth_annual + (idx * inputs.roth_annual_increase)
        simple_contrib = inputs.simple_ira_annual

        # Apply interest to existing balances and add new contributions
        hsa_bal = (hsa_bal * (1 + r)) + hsa_contrib
        roth_bal = (roth_bal * (1 + r)) + roth_contrib
        simple_bal = (simple_bal * (1 + r)) + simple_contrib

        # Total new contributions for this year
        annual_in = hsa_contrib + roth_contrib + simple_contrib

        # Apply interest to current savings
        current_savings = current_savings * (1 + r)

        # Calculate total (current savings + all account balances)
        total = current_savings + hsa_bal + roth_bal + simple_bal

        # Calculate fixed income based on total
        fixed_income = total * fixed_r

        # 529 calculations (separate from retirement)
        plan_529_contrib = inputs.plan_529_annual
        plan_529_bal = (plan_529_bal * (1 + r)) + plan_529_contrib

        # Format retirement values
        retirement_rows.append(
            (
                age,
                format_currency(current_savings), # Initial savings with interest
                format_currency(hsa_bal),        # HSA with interest
                format_currency(roth_bal),       # ROTH with interest
                format_currency(simple_bal),     # SIMPLE IRA with interest
                format_currency(annual_in),      # This year's contributions
                format_currency(total),          # Grand total
            )
        )

        # Format education values
        education_rows.append(
            (
                age,
                format_currency(plan_529_bal),   # 529 balance with interest
            )
        )

        # Format fixed income values
        fixed_income_rows.append(
            (
                age,
                format_currency(total),          # Total retirement savings
                format_currency(fixed_income),   # Annual fixed income
            )
        )

    retirement_df = pd.DataFrame(
        retirement_rows,
        columns=[
            "Age",
            f"Initial Savings @ {inputs.annual_return_pct:.0f}%",
            f"HSA Balance @ {inputs.annual_return_pct:.0f}%",
            f"ROTH Balance @ {inputs.annual_return_pct:.0f}%",
            f"SIMPLE Balance @ {inputs.annual_return_pct:.0f}%",
            "ANNUAL IN",
            "TOTAL",
        ],
    )

    education_df = pd.DataFrame(
        education_rows,
        columns=[
            "Age",
            f"529 Balance @ {inputs.annual_return_pct:.0f}%",
        ],
    )

    fixed_income_df = pd.DataFrame(
        fixed_income_rows,
        columns=[
            "Age",
            "Total Retirement Savings",
            f"Annual Fixed Income @ {inputs.fixed_income_pct:.0f}%",
        ],
    )

    return retirement_df, education_df, fixed_income_df


def compute_tables(
    hsa_annual: float,
    roth_annual: float,
    simple_ira_annual: float,
    plan_529_annual: float,
    current_savings: float,
    start_age: int,
    end_age: int,
    return_choice: str,
    fixed_income_choice: str,
    hsa_increase_enabled: bool,
    roth_increase_enabled: bool,
):
    pct_map = {"3%": 3.0, "5%": 5.0, "7%": 7.0}
    growth_pct = pct_map.get(return_choice, 7.0)
    income_pct = pct_map.get(fixed_income_choice, 3.0)

    inputs = Inputs(
        hsa_annual=hsa_annual,
        roth_annual=roth_annual,
        simple_ira_annual=simple_ira_annual,
        plan_529_annual=plan_529_annual,
        current_savings=current_savings,
        start_age=start_age,
        end_age=end_age,
        annual_return_pct=growth_pct,
        fixed_income_pct=income_pct,
        hsa_annual_increase=100 if hsa_increase_enabled else 0,
        roth_annual_increase=100 if roth_increase_enabled else 0,
    )
    return project(inputs)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Retirement Projection") as demo:
        gr.Markdown("""
        # Retirement & Education Planning
        
        Enter your contribution amounts and see how your savings grow over time.
        """)

        # Input section
        with gr.Row():
            # Left column - HSA and ROTH with increase checkboxes
            with gr.Column():
                with gr.Group():
                    hsa_annual = gr.Number(label="HSA Annual Contribution", value=8500, precision=0)
                    hsa_increase_enabled = gr.Checkbox(
                        label="Add $100/yr to HSA",
                        value=False,
                        info="Increase HSA contribution by $100 each year",
                    )

                with gr.Group():
                    roth_annual = gr.Number(label="ROTH IRA Annual", value=14000, precision=0)
                    roth_increase_enabled = gr.Checkbox(
                        label="Add $100/yr to ROTH",
                        value=False,
                        info="Increase ROTH contribution by $100 each year",
                    )

            # Middle column - other inputs
            with gr.Column():
                simple_ira_annual = gr.Number(label="SIMPLE IRA Annual", value=14000, precision=0)
                current_savings = gr.Number(
                    label="Initial Savings",
                    value=0,
                    precision=0,
                    info="Your existing savings that will grow with interest",
                )

            # Right column - age and growth rate
            with gr.Column():
                start_age = gr.Number(label="Start Age", value=40, precision=0)
                end_age = gr.Number(label="End Age", value=100, precision=0)
                return_choice = gr.Radio(
                    ["3%", "5%", "7%"],
                    value="7%",
                    label="Growth Rate",
                    info="Annual growth rate for all accounts",
                    interactive=True,
                )

        # Retirement table
        gr.Markdown("""
        ### FIRE-MINT - Retirement Savings

        The retirement table shows how your savings grow each year:
        - **Age**: The year you'll be this age
        - **Initial Savings**: Your starting savings growing with interest
        - **Account Balances**: Growth of contributions with interest for each account
        - **ANNUAL IN**: Total new money added this year
        - **TOTAL**: Sum of account balances plus initial savings

        Note: Account balances show only the growth of your contributions.
        The TOTAL includes both these balances and your initial savings with interest.
        """)
        
        retirement_df = gr.Dataframe(
            wrap=True,
            height=400,
            label="Retirement Projection",
        )

        # Fixed Income section right after retirement table
        gr.Markdown("""
        ### Fixed Income Potential

        Shows potential annual fixed income based on your total retirement savings:
        - **Total Retirement Savings**: Combined value of all retirement accounts
        - **Annual Fixed Income**: Potential annual income at selected rate
        """)

        # Fixed income rate selector
        fixed_income_choice = gr.Radio(
            ["3%", "5%", "7%"],
            value="3%",
            label="Fixed Income Rate",
            info="Annual fixed income/dividend rate",
            interactive=True,
        )

        fixed_income_df = gr.Dataframe(
            wrap=True,
            height=300,
            label="Fixed Income Projection",
        )

        # Education section
        gr.Markdown("### Education Savings (529 Plan)")
        
        # 529 input above its table
        plan_529_annual = gr.Number(
            label="529 Annual Contribution",
            value=0,
            precision=0,
            info="Annual contribution to 529 education savings plan",
        )
        
        education_df = gr.Dataframe(
            wrap=True,
            height=300,
            label="529 Plan Projection",
        )

        # All inputs that trigger table updates
        inputs = [
            hsa_annual,
            roth_annual,
            simple_ira_annual,
            plan_529_annual,
            current_savings,
            start_age,
            end_age,
            return_choice,
            fixed_income_choice,
            hsa_increase_enabled,
            roth_increase_enabled,
        ]

        # Update tables on load and any input change
        demo.load(compute_tables, inputs=inputs, outputs=[retirement_df, education_df, fixed_income_df])
        for comp in inputs:
            comp.change(compute_tables, inputs=inputs, outputs=[retirement_df, education_df, fixed_income_df])

    return demo


def main():
    app = build_ui()
    app.queue().launch(server_name="0.0.0.0", server_port=7860, share=True)

if __name__ == "__main__":
    import hupper
    reloader = hupper.start_reloader("app.main")
    main()
