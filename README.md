# Claims Adjudication Agent

An enterprise-grade medical claims adjudication engine built for the Alchemyst AI technical assessment. This system features a `FastAPI` backend, `LangGraph` agent orchestration with native tool-calling, and a `Streamlit` dashboard for real-time claim processing and clinical validation.

## Live Demo & Links

- Live Dashboard: `[PASTE_YOUR_STREAMLIT_URL_HERE]`
- API Documentation: [https://claims-adjucation-agent.onrender.com/docs](https://claims-adjucation-agent.onrender.com/docs)
- Backend Status: `Live` on Render

---

## Architecture Overview

This project demonstrates a production-style AI agentic workflow designed for the healthcare sector:

1. **Deterministic Gate**: Validates structured data before invoking the LLM to optimize token usage and prevent reasoning on incomplete claims.
2. **Contextual Retrieval**: An agentic loop retrieves data from mock enterprise databases covering policy, fraud, and utilization history.
3. **Semantic Clinical Review**: Uses `Gemini 2.5 Flash` to compare unstructured clinical notes against billed procedure descriptions and detect possible upcoding or clinical mismatches.
4. **Automated Adjudication**: Calculates final payouts and patient responsibility in `INR` based on policy and eligibility context.

---

## Tech Stack

- Backend: `FastAPI` (Python)
- Agent Framework: `LangGraph` and `LangChain`
- LLM: Google Gemini via `langchain-google-genai`
- Frontend: `Streamlit`
- Deployment: Render (Backend) and Streamlit Community Cloud (Frontend)

---

## Data Schema

### Request Schema

Endpoint: `POST /process_claim`

| Field | Type | Description |
| :--- | :--- | :--- |
| `claim_id` | `string` | Unique identifier for the claim transaction. |
| `patient_id` | `string` | Used to verify eligibility and deductible status, for example `PAT001`. |
| `provider_id` | `string` | Used for provider-level anomaly and fraud detection, for example `PRV100`. |
| `procedure_code` | `string` | CPT-style billed code, for example `99213` for a routine office visit. |
| `billed_amount` | `float` | Total amount charged by the hospital in `INR`. |
| `clinical_notes` | `text` | Unstructured medical narrative used for clinical verification. |

### Response Schema

| Field | Type | Description |
| :--- | :--- | :--- |
| `claim_id` | `string` | Echoes the incoming claim identifier for downstream reconciliation. |
| `status` | `enum` | `APPROVED`, `DENIED`, `PENDING_PROVIDER_INFO`, `FLAGGED_FRAUD_RISK`, or `FLAGGED_CLINICAL_MISMATCH`. |
| `decision_reason` | `string` | Concise explanation of the final adjudication logic. |
| `payout_amount` | `float` | Amount payable by the insurer in `INR`. |
| `patient_responsibility` | `float` | Amount owed by the patient after co-pay and deductible, in `INR`. |
| `missing_fields` | `list[string]` | Lists any required structured fields missing from the request. |
| `confidence_notes` | `string` | Traceability notes summarizing the evidence and agent reasoning path. |

### Status Definitions

- `PENDING_PROVIDER_INFO`: Required structured claim fields were missing.
- `DENIED`: Eligibility or policy rules failed.
- `FLAGGED_FRAUD_RISK`: Fraud or anomaly signals require human review.
- `FLAGGED_CLINICAL_MISMATCH`: Clinical notes do not support the billed procedure.
- `APPROVED`: All checks passed and payout was calculated.

---

## Agentic Logic & Tools

The LangGraph agent uses three explicit tools to arrive at a decision:

- `check_policy_and_coverage`: Verifies whether the patient is active and whether the billed code is covered under the plan.
- `check_fraud_anomalies`: Flags providers exceeding weekly claim thresholds or patients with suspicious utilization spikes.
- `evaluate_clinical_notes`: Performs a semantic comparison between the procedure description and the clinical notes.

Example:

If a claim describes a routine checkup but the billed procedure corresponds to a much higher-acuity treatment, the agent flags the claim as `FLAGGED_CLINICAL_MISMATCH` for human review.

### Adjudication Flow

1. The API validates missing `patient_id` and `procedure_code` fields before any model call.
2. The agent is prompted to always use the policy and fraud tools before making a decision.
3. If structured checks pass, the agent calls the clinical-review tool backed by Gemini.
4. The agent returns a structured `ClaimResponse`.

### Financial Logic

All monetary values are treated as `INR`.

```text
deductible_applied = min(deductible_remaining, max(billed_amount - copay, 0))
payout_amount = max(billed_amount - copay - deductible_applied, 0)
patient_responsibility = copay + deductible_applied
```

---

## Deployment & Resilience

### Cloud Infrastructure

- Backend: Deployed on `Render` as a Python web service with dynamic port binding and environment variable support.
- Frontend: Deployed on `Streamlit Community Cloud`, connected to the backend through a `BACKEND_API_URL` secret.

### Error Handling & Reliability

- Fast failure on Gemini model and quota errors to avoid long hanging requests during demos.
- Optional API key passthrough from the frontend sidebar using the `X-Gemini-API-Key` header.
- Deterministic missing-field validation before the agent runs, which reduces unnecessary LLM calls.

Note:

The current implementation is optimized to fail quickly on Gemini quota or model-access issues rather than retrying aggressively.

---

## Frontend Dashboard

The Streamlit app provides a hospital admin workflow for:

- submitting claims through a structured form
- viewing adjudication outcomes with status-specific message boxes
- reviewing `payout_amount` and `patient_responsibility` in `INR`
- inspecting `confidence_notes`
- optionally supplying a custom Gemini API key from the sidebar if the default key is rate-limited

---

## Local Development

1. Clone and install:
   ```bash
   git clone https://github.com/TanujaNair03/Claims_Adjucation_Agent.git
   cd Claims_Adjucation_Agent
   pip install -r requirements.txt
   ```
2. Set environment variables:
   ```bash
   export GOOGLE_API_KEY="your_key_here"
   ```
3. Run backend:
   ```bash
   uvicorn app:app --reload
   ```
4. Run frontend:
   ```bash
   streamlit run frontend.py
   ```

For local frontend testing, the Streamlit app defaults to:

```text
http://127.0.0.1:8000/process_claim
```

If deployed, set `BACKEND_API_URL` in Streamlit secrets.

---

## Example Request

```json
{
  "claim_id": "CLM-001",
  "patient_id": "PAT001",
  "provider_id": "PRV300",
  "procedure_code": "99213",
  "billed_amount": 1750.0,
  "clinical_notes": "Patient seen for routine follow-up visit. Symptoms are stable, medication reviewed, and no acute distress noted."
}
```

---

## Author

Tanuja Nair

Submitted for the Alchemyst AI Technical Assessment (March 2026)
