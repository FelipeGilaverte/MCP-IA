from __future__ import annotations

import builtins
import csv
import json
import sys
from pathlib import Path

import typer

from automation_intel_mcp import agency_server, research_server, server
from automation_intel_mcp.runtime import agency_graph, budget, perplexity_client, research_graph, research_run_store, settings
from automation_intel_mcp.tools.agency_logic import build_commercial_offer, build_outreach, score_niche_locally

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(help="Automation Intel MCP CLI")


def _print_json(payload: dict) -> None:
    builtins.print(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def runserver() -> None:
    """Run the legacy combined MCP server over stdio."""
    server.main()


@app.command("runserver-research")
def runserver_research() -> None:
    """Run the research MCP server over stdio."""
    research_server.main()


@app.command("runserver-research-http")
def runserver_research_http(
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port"),
    path: str | None = typer.Option(None, "--path"),
    public_base_url: str | None = typer.Option(None, "--public-base-url"),
) -> None:
    """Run the research MCP over Streamable HTTP for remote MCP clients."""
    research_server.main_streamable_http(host=host, port=port, path=path, public_base_url=public_base_url)


@app.command("runserver-agency")
def runserver_agency() -> None:
    """Run the agency MCP server over stdio."""
    agency_server.main()


@app.command("runserver-agency-http")
def runserver_agency_http(
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port"),
    path: str | None = typer.Option(None, "--path"),
    public_base_url: str | None = typer.Option(None, "--public-base-url"),
) -> None:
    """Run the agency MCP over Streamable HTTP for remote MCP clients."""
    agency_server.main_streamable_http(host=host, port=port, path=path, public_base_url=public_base_url)


@app.command()
def research(
    question: str,
    mode: str = typer.Option("auto", "--mode"),
    max_searches: int | None = typer.Option(None, "--max-searches"),
    execution_cost_cap: float | None = typer.Option(None, "--execution-cost-cap"),
    allow_exhaustive: bool = typer.Option(False, "--allow-exhaustive"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
    save_to: Path | None = typer.Option(None, "--save-to"),
) -> None:
    """Run the evidence-first research graph from the terminal."""
    try:
        result = research_graph.invoke(
            {
                "question": question,
                "mode": mode,
                "max_searches": max_searches,
                "execution_cost_cap_usd": execution_cost_cap,
                "allow_exhaustive": allow_exhaustive,
            }
        ).get("result", {})
        text = json.dumps(result, ensure_ascii=False, indent=2)
        builtins.print(text if json_output else result.get("summary", text))
        if save_to:
            save_to.write_text(text, encoding="utf-8")
    except Exception as exc:
        _print_json({"status": "error", "error": str(exc)})
        raise typer.Exit(code=1)


@app.command("get-run")
def get_run(run_id: str) -> None:
    """Fetch a stored research payload by run_id."""
    payload = research_run_store.get(run_id)
    if payload is None:
        _print_json({"status": "error", "error": f"Unknown run_id: {run_id}"})
        raise typer.Exit(code=1)
    _print_json(payload)


@app.command("deep-search-expensive")
def deep_search_expensive(
    question: str,
    confirm_expensive: bool = typer.Option(False, "--confirm-expensive"),
) -> None:
    """Run premium Sonar Deep Research explicitly when enabled in the environment."""
    try:
        result = perplexity_client.deep_research_expensive(
            question,
            confirm_expensive=confirm_expensive,
        )
        builtins.print(result.model_dump_json(indent=2))
    except Exception as exc:
        _print_json({"status": "error", "error": str(exc)})
        raise typer.Exit(code=1)


@app.command()
def rawsearch(query: str, max_results: int | None = typer.Option(None, "--max-results")) -> None:
    """Run Search API without LLM synthesis."""
    try:
        result = perplexity_client.raw_search(query, max_results=max_results)
        _print_json(result)
    except Exception as exc:
        _print_json({"status": "error", "error": str(exc)})
        raise typer.Exit(code=1)


@app.command()
def niche(niche_text: str) -> None:
    """Score a niche locally."""
    builtins.print(score_niche_locally(niche_text).model_dump_json(indent=2))


@app.command()
def company(
    company_name: str,
    company_url: str,
    niche: str,
    external_research: bool = typer.Option(False, "--external-research"),
    external_research_mode: str = typer.Option("auto", "--external-research-mode"),
) -> None:
    """Run the agency graph against a public company site."""
    try:
        result = agency_graph.invoke(
            {
                "company_name": company_name,
                "company_url": company_url,
                "niche": niche,
                "use_external_research": external_research,
                "external_research_mode": external_research_mode,
            }
        )
        _print_json(result)
    except Exception as exc:
        _print_json({"status": "error", "error": str(exc)})
        raise typer.Exit(code=1)


@app.command("batch-company")
def batch_company(
    csv_path: Path,
    output_path: Path,
    max_cost_usd: float = typer.Option(1.0, "--max-cost-usd"),
    stop_on_error: bool = typer.Option(False, "--stop-on-error"),
    external_research: bool = typer.Option(False, "--external-research"),
    external_research_mode: str = typer.Option("auto", "--external-research-mode"),
) -> None:
    """Analyze multiple companies from CSV and stop when the execution cost cap is reached."""
    run_budget_start = budget.current_month_total()
    processed = 0
    stopped_by_budget = False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file, output_path.open("a", encoding="utf-8") as out_file:
        reader = csv.DictReader(csv_file)
        required_fields = {"company_name", "company_url", "niche"}
        if not reader.fieldnames or not required_fields.issubset(set(reader.fieldnames)):
            builtins.print("CSV must contain headers: company_name, company_url, niche")
            raise typer.Exit(code=2)

        for row_number, row in enumerate(reader, start=2):
            execution_cost = round(budget.current_month_total() - run_budget_start, 6)
            if execution_cost >= max_cost_usd:
                stopped_by_budget = True
                break

            company_name = (row.get("company_name") or "").strip()
            company_url = (row.get("company_url") or "").strip()
            niche_value = (row.get("niche") or "").strip()
            if not company_name or not company_url or not niche_value:
                result_row = {
                    "row_number": row_number,
                    "status": "error",
                    "error": "Missing required value in company_name, company_url or niche.",
                    "input": row,
                }
                out_file.write(json.dumps(result_row, ensure_ascii=False) + "\n")
                out_file.flush()
                if stop_on_error:
                    raise typer.Exit(code=1)
                continue

            try:
                result = agency_graph.invoke(
                    {
                        "company_name": company_name,
                        "company_url": company_url,
                        "niche": niche_value,
                        "use_external_research": external_research,
                        "external_research_mode": external_research_mode,
                    }
                )
                execution_cost = round(budget.current_month_total() - run_budget_start, 6)
                result_row = {
                    "row_number": row_number,
                    "status": "ok",
                    "execution_cost_usd": execution_cost,
                    "input": {
                        "company_name": company_name,
                        "company_url": company_url,
                        "niche": niche_value,
                    },
                    "result": result,
                }
                out_file.write(json.dumps(result_row, ensure_ascii=False) + "\n")
                out_file.flush()
                processed += 1
                if execution_cost >= max_cost_usd:
                    stopped_by_budget = True
                    break
            except Exception as exc:
                execution_cost = round(budget.current_month_total() - run_budget_start, 6)
                result_row = {
                    "row_number": row_number,
                    "status": "error",
                    "execution_cost_usd": execution_cost,
                    "error": str(exc),
                    "input": {
                        "company_name": company_name,
                        "company_url": company_url,
                        "niche": niche_value,
                    },
                }
                out_file.write(json.dumps(result_row, ensure_ascii=False) + "\n")
                out_file.flush()
                if stop_on_error:
                    raise typer.Exit(code=1)

    final_execution_cost = round(budget.current_month_total() - run_budget_start, 6)
    _print_json(
        {
            "csv_path": str(csv_path),
            "output_path": str(output_path),
            "processed": processed,
            "execution_cost_usd": final_execution_cost,
            "max_cost_usd": max_cost_usd,
            "stopped_by_budget": stopped_by_budget,
        }
    )


@app.command()
def offer(niche: str, pain: str, solution: str, desired_ticket: str, urgency_level: str) -> None:
    """Generate a stronger commercial offer with channel-ready variants."""
    builtins.print(
        build_commercial_offer(
            niche=niche,
            pain=pain,
            solution=solution,
            desired_ticket=desired_ticket,
            urgency_level=urgency_level,
        ).model_dump_json(indent=2)
    )


@app.command()
def outreach(company_name: str, niche: str, pain_summary: str, solution_summary: str, channel: str = "whatsapp") -> None:
    """Generate first-contact copy locally."""
    builtins.print(build_outreach(company_name, niche, pain_summary, solution_summary, channel).model_dump_json(indent=2))


@app.command()
def budget_status() -> None:
    _print_json(budget.status())


if __name__ == "__main__":
    app()
