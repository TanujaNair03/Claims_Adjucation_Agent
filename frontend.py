import os

import requests
import streamlit as st


backend_base_url = st.secrets.get("BACKEND_API_URL", os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000"))
API_URL = f"{backend_base_url.rstrip('/')}/process_claim"


st.set_page_config(
    page_title="Hospital Claim Adjudication Portal",
    layout="wide",
)


def render_status_box(status: str, decision_reason: str) -> None:
    if status == "APPROVED":
        st.success(f"{status}: {decision_reason}")
    elif status == "FLAGGED_FRAUD_RISK":
        st.error(f"{status}: {decision_reason}")
    elif status == "FLAGGED_CLINICAL_MISMATCH":
        st.warning(f"{status}: {decision_reason}")
    elif status == "PENDING_PROVIDER_INFO":
        st.info(f"{status}: {decision_reason}")
    else:
        st.error(f"{status}: {decision_reason}")


st.title("Hospital Claim Adjudication Portal")
st.caption("Submit medical claims and review AI-assisted adjudication outcomes in real time.")


with st.container():
    st.subheader("Claim Intake")
    with st.form("claim_submission_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            claim_id = st.text_input("Claim ID", value="CLM-001")
            patient_id = st.text_input("Patient ID", value="PAT001")
            provider_id = st.text_input("Provider ID", value="PRV300")
        with col2:
            procedure_code = st.text_input("Procedure Code", value="99213")
            billed_amount = st.number_input(
                "Billed Amount",
                min_value=0.0,
                value=175.0,
                step=25.0,
                format="%.2f",
            )

        clinical_notes = st.text_area(
            "Clinical Notes",
            value=(
                "Patient seen for routine follow-up visit. Symptoms are stable, "
                "medication reviewed, and no acute distress noted."
            ),
            height=180,
        )

        submitted = st.form_submit_button("Submit Claim for Adjudication", use_container_width=True)


if submitted:
    payload = {
        "claim_id": claim_id,
        "patient_id": patient_id,
        "provider_id": provider_id,
        "procedure_code": procedure_code,
        "billed_amount": billed_amount,
        "clinical_notes": clinical_notes,
    }

    try:
        with st.spinner("Processing claim through the adjudication agent..."):
            response = requests.post(API_URL, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()

        st.divider()
        st.subheader("Adjudication Result")
        render_status_box(result.get("status", "UNKNOWN"), result.get("decision_reason", "No reason returned."))

        metrics_col1, metrics_col2 = st.columns(2)
        with metrics_col1:
            st.metric(
                label="Payout Amount",
                value=f"${result.get('payout_amount', 0.0):,.2f}",
            )
        with metrics_col2:
            st.metric(
                label="Patient Responsibility",
                value=f"${result.get('patient_responsibility', 0.0):,.2f}",
            )

        missing_fields = result.get("missing_fields") or []
        if missing_fields:
            st.info("Missing fields: " + ", ".join(missing_fields))

        with st.expander("AI Confidence Notes", expanded=False):
            st.write(result.get("confidence_notes") or "No confidence notes returned.")

        with st.expander("Raw API Response", expanded=False):
            st.json(result)

    except requests.exceptions.ConnectionError:
        st.error(
            "Could not connect to the FastAPI backend at "
            f"`{API_URL}`. Please make sure your server is running with `uvicorn app:app --reload`."
        )
    except requests.exceptions.Timeout:
        st.error("The request timed out while waiting for the adjudication service to respond.")
    except requests.exceptions.HTTPError as exc:
        error_detail = "The backend returned an error."
        try:
            error_payload = exc.response.json()
            error_detail = error_payload.get("detail", error_detail)
        except Exception:
            pass
        st.error(f"Backend error: {error_detail}")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
