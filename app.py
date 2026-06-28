"""Streamlit dashboard for Postdoc Scout Agent."""

import pandas as pd
import streamlit as st

from postdoc_scout.dashboard_utils import (
    available_downloads,
    build_queries_for_dashboard,
    candidate_score_rows,
    ecosystem_unit_rows,
    map_institution_for_dashboard,
    queries_by_source,
    report_markdown_options,
    resolve_dashboard_output_dir,
    run_dashboard_pipeline,
    safe_load_markdown,
    score_breakdown_rows,
    score_mock_candidates_for_dashboard,
)

st.set_page_config(
    page_title="Postdoc Scout Agent",
    page_icon="🔎",
    layout="wide",
)

st.title("Postdoc Scout Agent")
st.caption(
    "Evidence-based postdoctoral supervisor discovery for translational digital medicine "
    "and clinical AI."
)
st.warning("All results are preliminary and require human verification before outreach.")

with st.sidebar:
    st.header("Controls")
    institution = st.text_input("Institution", value="Harvard University")
    country = st.selectbox("Country", options=["us"], index=0)
    mode = st.selectbox("Mode", options=["broad", "narrow"], index=0)
    output_dir_text = st.text_input("Output directory", value="outputs/dashboard_demo")
    output_dir = resolve_dashboard_output_dir(output_dir_text)
    pipeline_mode = st.radio(
        "Pipeline mode",
        options=[
            "Dry run",
            "Use existing outputs",
            "Full pipeline (API-dependent)",
        ],
        index=0,
    )
    limit_queries = st.number_input("Query limit", min_value=1, max_value=250, value=50)
    limit_per_source = st.number_input("Limit per source", min_value=0, max_value=100, value=10)
    allow_full_pipeline = False
    if pipeline_mode == "Full pipeline (API-dependent)":
        st.warning(
            "Full pipeline mode may call OpenAlex, PubMed, NIH RePORTER, or Semantic "
            "Scholar. Use dry run for a demo-safe workflow."
        )
        allow_full_pipeline = st.checkbox("I understand this may call external APIs.")

    map_clicked = st.button("Map institution", use_container_width=True)
    query_clicked = st.button("Build discovery queries", use_container_width=True)
    dry_pipeline_clicked = st.button("Run dry pipeline", use_container_width=True)
    load_existing_clicked = st.button("Load existing report", use_container_width=True)
    full_pipeline_clicked = st.button(
        "Run selected pipeline mode",
        disabled=pipeline_mode != "Full pipeline (API-dependent)" or not allow_full_pipeline,
        use_container_width=True,
    )

if map_clicked:
    st.session_state["ecosystem"] = map_institution_for_dashboard(
        institution=institution,
        mode=mode,
        country=country,
    )

if query_clicked:
    st.session_state["query_bundle"] = build_queries_for_dashboard(
        institution=institution,
        mode=mode,
        country=country,
        limit=int(limit_queries),
    )

if dry_pipeline_clicked:
    with st.spinner("Running dry pipeline without external API calls..."):
        st.session_state["pipeline_report"] = run_dashboard_pipeline(
            institution=institution,
            mode=mode,
            country=country,
            output_dir=output_dir,
            dry_run=True,
            resume=True,
            limit_queries=int(limit_queries),
            limit_per_source=int(limit_per_source),
        )
    st.success(f"Dry pipeline completed. Reports written to `{output_dir}`.")

if full_pipeline_clicked:
    with st.spinner("Running full pipeline. This may call external APIs..."):
        st.session_state["pipeline_report"] = run_dashboard_pipeline(
            institution=institution,
            mode=mode,
            country=country,
            output_dir=output_dir,
            dry_run=False,
            resume=True,
            limit_queries=int(limit_queries),
            limit_per_source=int(limit_per_source),
        )
    st.success(f"Full pipeline completed. Reports written to `{output_dir}`.")

tabs = st.tabs(
    [
        "Ecosystem",
        "Discovery Queries",
        "Mock Scoring",
        "Existing Outputs",
        "Exports",
    ]
)

with tabs[0]:
    st.subheader("Institution Ecosystem")
    st.info(
        "Seed-map relationships are curated scouting hints and require verification before "
        "being treated as formal affiliations."
    )
    ecosystem = st.session_state.get("ecosystem")
    if ecosystem is None and "pipeline_report" in st.session_state:
        ecosystem_path = output_dir / "ecosystem.json"
        if ecosystem_path.exists():
            from postdoc_scout.models import InstitutionEcosystem

            ecosystem = InstitutionEcosystem.model_validate_json(
                ecosystem_path.read_text(encoding="utf-8")
            )
    if ecosystem is None:
        st.write("Use **Map institution** or **Run dry pipeline** to populate this view.")
    else:
        rows = ecosystem_unit_rows(ecosystem)
        st.metric("Mapped units", len(rows))
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with tabs[1]:
    st.subheader("Discovery Queries")
    query_bundle = st.session_state.get("query_bundle")
    if query_bundle is None and "pipeline_report" in st.session_state:
        query_path = output_dir / "discovery_queries.json"
        if query_path.exists():
            from postdoc_scout.models import QueryBundle

            query_bundle = QueryBundle.model_validate_json(
                query_path.read_text(encoding="utf-8")
            )
    if query_bundle is None:
        st.write("Use **Build discovery queries** or **Run dry pipeline** to populate this view.")
    else:
        grouped_queries = queries_by_source(query_bundle)
        st.metric("Generated queries", len(query_bundle.queries))
        for source, rows in grouped_queries.items():
            with st.expander(source, expanded=source in {"pubmed", "openalex"}):
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("Candidate Scoring Demo")
    st.caption("Mock candidates only. No external APIs are called.")
    ranked = score_mock_candidates_for_dashboard()
    score_rows = candidate_score_rows(ranked)
    st.dataframe(pd.DataFrame(score_rows), use_container_width=True, hide_index=True)
    candidate_names = [row["candidate name"] for row in score_rows]
    selected_candidate = st.selectbox("Score breakdown", options=candidate_names)
    breakdown_rows = score_breakdown_rows(ranked, selected_candidate)
    st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("Existing Output Viewer")
    reports = report_markdown_options(output_dir)
    if load_existing_clicked:
        st.session_state["existing_reports"] = reports
    reports = st.session_state.get("existing_reports", reports)
    if not reports:
        st.write(f"No Markdown reports found in `{output_dir}` yet.")
    else:
        label = st.selectbox("Report", options=list(reports))
        st.markdown(safe_load_markdown(reports[label]))

with tabs[4]:
    st.subheader("Export Files")
    downloads = available_downloads(output_dir)
    if not downloads:
        st.write(f"No export files found in `{output_dir}` yet.")
    for path in downloads:
        mime = "text/csv" if path.suffix == ".csv" else "text/plain"
        if path.suffix == ".json":
            mime = "application/json"
        st.download_button(
            label=f"Download {path.name}",
            data=path.read_bytes(),
            file_name=path.name,
            mime=mime,
        )

with st.expander("Dashboard safety notes", expanded=False):
    st.markdown(
        """
        - The dashboard does not call external APIs on page load.
        - Dry-run mode maps institutions and builds discovery queries only.
        - Full pipeline mode is explicitly marked as API-dependent.
        - No website scraping or LLM summarization is performed.
        - All candidate outputs require human verification before outreach.
        """
    )
