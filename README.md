# Claims Adjudication Agent

An API-first medical claims adjudication system built for an AI startup take-home assignment. The project combines a `FastAPI` backend, `LangGraph` agent orchestration, explicit LangChain tool calling, and a `Streamlit` frontend for claim submission and adjudication review.

## Overview

This project simulates how a healthcare claims platform can:

- receive a claim through a REST API
- validate required structured fields before invoking an LLM
- retrieve policy, eligibility, fraud, and utilization context from mock enterprise data sources
- use an agentic workflow with native tool calling to reason over the claim
- analyze unstructured clinical notes against the billed procedure
- return a structured adjudication decision with payout and patient responsibility

## Features

- `FastAPI` backend with Swagger UI
- `Pydantic` request and response schemas
- `LangGraph` agent orchestration using `create_react_agent`
- explicit LangChain `@tool` functions for policy, fraud, and clinical review
- mock enterprise databases for:
  - patient eligibility
  - procedure coverage
  - provider claim history
  - patient utilization history
- `Streamlit` dashboard for hospital admin claim intake
- clear adjudication statuses:
  - `PENDING_PROVIDER_INFO`
  - `DENIED`
  - `FLAGGED_FRAUD_RISK`
  - `FLAGGED_CLINICAL_MISMATCH`
  - `APPROVED`

## Project Structure

```text
Claims Adjudication Agent/
├── app.py
├── frontend.py
├── requirements.txt
├── README.md
└── .gitignore
```

## Tech Stack

- Backend: `FastAPI`
- Frontend: `Streamlit`
- Agent Framework: `LangGraph`, `LangChain`
- LLM: `Google Gemini` via `langchain-google-genai`
- Validation: `Pydantic`

## Backend Architecture

The backend exposes a single POST endpoint:

```text
/process_claim
```

### Request Schema

```json
{
  "claim_id": "CLM-001",
  "patient_id": "PAT001",
  "provider_id": "PRV300",
  "procedure_code": "99213",
  "billed_amount": 175.0,
  "clinical_notes": "Patient seen for routine follow-up visit. Symptoms are stable."
}
```

### Response Schema

```json
{
  "claim_id": "CLM-001",
  "status": "APPROVED",
  "decision_reason": "Claim passed policy, fraud, and clinical validation.",
  "payout_amount": 0.0,
  "patient_responsibility": 0.0,
  "missing_fields": [],
  "confidence_notes": "Tool-assisted decision based on policy, fraud, and clinical review."
}
```

## Agentic Workflow

The application is intentionally structured to show explicit agent design.

### 1. Deterministic Validation Gate

Before the LLM is called, the API checks for missing required claim fields such as:

- `patient_id`
- `procedure_code`

If either is missing, the system immediately returns `PENDING_PROVIDER_INFO`. This avoids wasting tokens on incomplete claims.

### 2. Native Tool Calling

The LangGraph agent is configured with explicit tools:

- `check_policy_and_coverage(patient_id, procedure_code)`
- `check_fraud_anomalies(patient_id, provider_id)`
- `evaluate_clinical_notes(procedure_description, clinical_notes)`

The system prompt instructs the agent to always:

1. check policy and coverage
2. check fraud and anomaly signals
3. evaluate the clinical notes if earlier checks pass
4. synthesize the tool results into a final `ClaimResponse`

### 3. Final Adjudication Logic

The agent returns one of the following decisions:

- `DENIED` for expired coverage, uncovered procedures, or invalid patient/procedure records
- `FLAGGED_FRAUD_RISK` when provider or patient activity looks suspicious
- `FLAGGED_CLINICAL_MISMATCH` when notes do not support the billed procedure
- `APPROVED` when all checks pass

For approved claims, the payout is calculated using:

```text
deductible_applied = min(deductible_remaining, max(billed_amount - copay, 0))
payout_amount = max(billed_amount - copay - deductible_applied, 0)
patient_responsibility = copay + deductible_applied
```

## Mock Data Sources

The backend uses hardcoded dictionaries to simulate enterprise systems:

- `PATIENTS_DB`
- `CODES_DB`
- `PROVIDER_HISTORY_DB`
- `PATIENT_HISTORY_DB`

These are intentionally lightweight to keep the assignment self-contained while still reflecting realistic claims-adjudication context retrieval.

## Frontend Dashboard

The `Streamlit` app provides a hospital admin dashboard where users can:

- enter claim information in a structured form
- submit the claim to the FastAPI backend
- view adjudication outcomes using colored status cards
- inspect payout and patient responsibility metrics
- expand confidence notes for additional model reasoning context

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/TanujaNair03/Claims_Adjucation_Agent.git
cd Claims_Adjucation_Agent
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set your Gemini API key

```bash
export GOOGLE_API_KEY="your_api_key_here"
```

## Running the Project

You need two terminals.

### Terminal 1: Run the FastAPI backend

```bash
uvicorn app:app --reload
```

The API will be available at:

- [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Terminal 2: Run the Streamlit frontend

```bash
streamlit run frontend.py
```

The dashboard will open in your browser automatically.

## Example Test Cases

### Approved claim

```json
{
  "claim_id": "CLM-001",
  "patient_id": "PAT001",
  "provider_id": "PRV300",
  "procedure_code": "99213",
  "billed_amount": 175.0,
  "clinical_notes": "Patient seen for routine follow-up visit. Symptoms are stable."
}
```

### Fraud risk

```json
{
  "claim_id": "CLM-002",
  "patient_id": "PAT001",
  "provider_id": "PRV200",
  "procedure_code": "99213",
  "billed_amount": 175.0,
  "clinical_notes": "Routine office visit for stable symptoms."
}
```

### Missing provider information

```json
{
  "claim_id": "CLM-003",
  "patient_id": "",
  "provider_id": "PRV300",
  "procedure_code": "",
  "billed_amount": 175.0,
  "clinical_notes": "Routine follow-up."
}
```

## Notes on Gemini API Usage

This project is implemented using `langchain-google-genai` with Gemini. Live execution depends on the quota available to the configured Google AI Studio project.

If you encounter quota or model-availability errors such as:

- `429 quota exceeded`
- `model not found`

the backend architecture is still valid, but the external Gemini API project may need a different key, project, or quota configuration.

## Why This Design

This implementation is intentionally built to highlight:

- explicit separation between deterministic validation and LLM reasoning
- clear tool boundaries for enterprise context retrieval
- an API-first service contract with typed request and response models
- a customer-facing frontend that demonstrates the workflow end-to-end

## Author

Tanuja Nair
