import os
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from google.api_core.exceptions import NotFound
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field


ACTIVE_GEMINI_MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Mock enterprise data sources
# ---------------------------------------------------------------------------
# These hardcoded dictionaries simulate the internal systems an adjudication
# agent would normally query before making a payment decision.
PATIENTS_DB: Dict[str, Dict[str, Any]] = {
    "PAT001": {"status": "active", "deductible_remaining": 250.0, "copay": 30.0},
    "PAT002": {"status": "expired", "deductible_remaining": 100.0, "copay": 20.0},
    "PAT003": {"status": "active", "deductible_remaining": 0.0, "copay": 15.0},
}

CODES_DB: Dict[str, Dict[str, Any]] = {
    "99213": {
        "description": "Routine outpatient follow-up visit",
        "is_covered": True,
        "standard_cost": 120.0,
    },
    "27447": {
        "description": "Complex total knee replacement surgery",
        "is_covered": True,
        "standard_cost": 18000.0,
    },
    "EX999": {
        "description": "Experimental elective treatment",
        "is_covered": False,
        "standard_cost": 5000.0,
    },
}

PROVIDER_HISTORY_DB: Dict[str, Dict[str, Any]] = {
    "PRV100": {"claims_this_week": 12, "flag_threshold": 20},
    "PRV200": {"claims_this_week": 29, "flag_threshold": 25},
    "PRV300": {"claims_this_week": 4, "flag_threshold": 10},
}

PATIENT_HISTORY_DB: Dict[str, Dict[str, Any]] = {
    "PAT001": {"recent_claims_30d": 2, "high_cost_claims_90d": 0},
    "PAT002": {"recent_claims_30d": 1, "high_cost_claims_90d": 0},
    "PAT003": {"recent_claims_30d": 9, "high_cost_claims_90d": 3},
}


# ---------------------------------------------------------------------------
# API schemas
# ---------------------------------------------------------------------------
class ClaimRequest(BaseModel):
    claim_id: str = Field(..., description="Unique claim identifier")
    patient_id: Optional[str] = Field(default=None, description="Member identifier")
    provider_id: str = Field(..., description="Billing provider identifier")
    procedure_code: Optional[str] = Field(
        default=None, description="Procedure or CPT-style code"
    )
    billed_amount: float = Field(..., ge=0, description="Amount billed by provider")
    clinical_notes: str = Field(..., min_length=1, description="Unstructured notes")


class ClaimResponse(BaseModel):
    claim_id: str
    status: Literal[
        "PENDING_PROVIDER_INFO",
        "DENIED",
        "FLAGGED_FRAUD_RISK",
        "FLAGGED_CLINICAL_MISMATCH",
        "APPROVED",
    ]
    decision_reason: str
    payout_amount: float = Field(..., ge=0)
    patient_responsibility: float = Field(..., ge=0)
    missing_fields: List[str] = Field(default_factory=list)
    confidence_notes: Optional[str] = None


class ClinicalReviewResult(BaseModel):
    match: bool
    explanation: str
    confidence: Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Deterministic validation helpers
# ---------------------------------------------------------------------------
def detect_missing_fields(claim: ClaimRequest) -> List[str]:
    missing: List[str] = []
    if not claim.patient_id:
        missing.append("patient_id")
    if not claim.procedure_code:
        missing.append("procedure_code")
    return missing


def build_pending_response(claim: ClaimRequest, missing_fields: List[str]) -> ClaimResponse:
    return ClaimResponse(
        claim_id=claim.claim_id,
        status="PENDING_PROVIDER_INFO",
        decision_reason=f"Additional provider data required: {', '.join(missing_fields)}.",
        payout_amount=0.0,
        patient_responsibility=0.0,
        missing_fields=missing_fields,
        confidence_notes="Missing-field gate triggered before any LLM or tool calls.",
    )


# ---------------------------------------------------------------------------
# Native LangChain tools
# ---------------------------------------------------------------------------
@tool
def check_policy_and_coverage(patient_id: str, procedure_code: str) -> Dict[str, Any]:
    """Look up patient eligibility and procedure coverage details from mock policy databases."""
    patient = PATIENTS_DB.get(patient_id)
    procedure = CODES_DB.get(procedure_code)

    if not patient:
        return {
            "patient_found": False,
            "procedure_found": bool(procedure),
            "eligible": False,
            "covered": False,
            "decision_hint": "DENIED",
            "reason": f"Patient '{patient_id}' was not found in eligibility records.",
        }

    if not procedure:
        return {
            "patient_found": True,
            "procedure_found": False,
            "eligible": patient["status"] == "active",
            "covered": False,
            "decision_hint": "DENIED",
            "reason": f"Procedure code '{procedure_code}' was not found in policy records.",
            "patient_status": patient["status"],
            "deductible_remaining": patient["deductible_remaining"],
            "copay": patient["copay"],
        }

    eligible = patient["status"] == "active"
    covered = bool(procedure["is_covered"])

    if not eligible:
        decision_hint = "DENIED"
        reason = f"Patient '{patient_id}' coverage is expired."
    elif not covered:
        decision_hint = "DENIED"
        reason = f"Procedure code '{procedure_code}' is not covered."
    else:
        decision_hint = "CONTINUE"
        reason = "Patient is active and the billed procedure is covered."

    return {
        "patient_found": True,
        "procedure_found": True,
        "eligible": eligible,
        "covered": covered,
        "decision_hint": decision_hint,
        "reason": reason,
        "patient_status": patient["status"],
        "deductible_remaining": patient["deductible_remaining"],
        "copay": patient["copay"],
        "procedure_description": procedure["description"],
        "standard_cost": procedure["standard_cost"],
    }


@tool
def check_fraud_anomalies(patient_id: str, provider_id: str) -> Dict[str, Any]:
    """Look up provider and patient utilization patterns to detect simple anomaly or fraud risk."""
    provider = PROVIDER_HISTORY_DB.get(
        provider_id,
        {"claims_this_week": 0, "flag_threshold": 999},
    )
    patient_history = PATIENT_HISTORY_DB.get(
        patient_id,
        {"recent_claims_30d": 0, "high_cost_claims_90d": 0},
    )

    provider_spike = provider["claims_this_week"] > provider["flag_threshold"]
    patient_spike = patient_history["recent_claims_30d"] >= 8
    flagged = provider_spike or patient_spike

    if provider_spike:
        reason = (
            f"Provider '{provider_id}' exceeded expected volume with "
            f"{provider['claims_this_week']} claims this week versus threshold "
            f"{provider['flag_threshold']}."
        )
    elif patient_spike:
        reason = (
            f"Patient '{patient_id}' has unusually high recent utilization with "
            f"{patient_history['recent_claims_30d']} claims in the last 30 days."
        )
    else:
        reason = "No fraud or anomaly thresholds were triggered."

    return {
        "flagged": flagged,
        "decision_hint": "FLAGGED_FRAUD_RISK" if flagged else "CONTINUE",
        "reason": reason,
        "claims_this_week": provider["claims_this_week"],
        "flag_threshold": provider["flag_threshold"],
        "recent_claims_30d": patient_history["recent_claims_30d"],
        "high_cost_claims_90d": patient_history["high_cost_claims_90d"],
    }


@tool
def evaluate_clinical_notes(
    procedure_description: str, clinical_notes: str
) -> Dict[str, Any]:
    """Use Gemini to compare clinical notes against the intended procedure description."""
    reviewer = get_clinical_reviewer()
    result = reviewer.invoke(
        [
            (
                "system",
                "You are a clinical coding reviewer. Compare the clinical notes to the "
                "procedure description. Mark match=false when the notes clearly do not "
                "justify the billed procedure, such as routine care billed as major surgery.",
            ),
            (
                "human",
                "Procedure description: "
                f"{procedure_description}\n\nClinical notes:\n{clinical_notes}",
            ),
        ]
    )
    return result.model_dump()


TOOLS = [
    check_policy_and_coverage,
    check_fraud_anomalies,
    evaluate_clinical_notes,
]


# ---------------------------------------------------------------------------
# Model / agent construction
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """
You are a claims adjudication agent processing a medical claim.

You must follow this workflow:
1. Receive the claim details.
2. ALWAYS call `check_policy_and_coverage` first.
3. ALWAYS call `check_fraud_anomalies` next.
4. If policy/coverage is valid and fraud is not flagged, call `evaluate_clinical_notes`
   using the procedure description returned by the policy tool.
5. Synthesize the tool responses into the final claim decision.

Decision rules:
- If the API pre-check already says fields are missing, you will never be called.
- If policy/coverage says the patient is ineligible, the patient is missing, the
  procedure code is missing from records, or the procedure is not covered, return `DENIED`.
- If fraud/anomaly checks are flagged, return `FLAGGED_FRAUD_RISK`.
- If clinical note review says match=false, return `FLAGGED_CLINICAL_MISMATCH`.
- Otherwise return `APPROVED`.

Financial rules:
- For `APPROVED`, calculate:
  deductible_applied = min(deductible_remaining, max(billed_amount - copay, 0))
  payout_amount = max(billed_amount - copay - deductible_applied, 0)
  patient_responsibility = copay + deductible_applied
- For `DENIED`, set payout_amount to 0 and patient_responsibility to billed_amount.
- For `FLAGGED_FRAUD_RISK` and `FLAGGED_CLINICAL_MISMATCH`, set payout_amount to 0
  and patient_responsibility to 0 pending human review.

Return the final answer strictly as JSON matching the ClaimResponse schema.
Do not skip tools. Do not answer from prior knowledge. Use only tool evidence.
""".strip()


RESPONSE_FORMAT_INSTRUCTIONS = """
Return only the final ClaimResponse object.
Populate:
- claim_id from the input claim
- status with one of the allowed enum values
- decision_reason with the clearest single-sentence explanation
- payout_amount as a non-negative number
- patient_responsibility as a non-negative number
- missing_fields as an empty list here because missing fields are handled before the agent runs
- confidence_notes with a brief note on the tool evidence used
""".strip()


@lru_cache(maxsize=1)
def get_gemini_model() -> ChatGoogleGenerativeAI:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set.")
    return ChatGoogleGenerativeAI(
        model=ACTIVE_GEMINI_MODEL,
        google_api_key=api_key,
        temperature=0,
        max_retries=0,
    )


@lru_cache(maxsize=1)
def get_clinical_reviewer():
    return get_gemini_model().with_structured_output(ClinicalReviewResult)


@lru_cache(maxsize=1)
def get_claim_agent():
    # This prebuilt LangGraph agent uses native tool calling under the hood.
    # We also attach a structured response schema so the final output is a
    # validated ClaimResponse instead of free-form text.
    return create_react_agent(
        model=get_gemini_model(),
        tools=TOOLS,
        prompt=SYSTEM_PROMPT,
        response_format=(RESPONSE_FORMAT_INSTRUCTIONS, ClaimResponse),
    )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Claims Adjudication Agent",
    description=(
        "API-first FastAPI backend using LangGraph native tool calling to process "
        "medical claims with policy checks, fraud checks, and clinical note analysis."
    ),
    version="2.0.0",
)


@app.get("/")
def read_root() -> Dict[str, str]:
    return {
        "message": "Claims Adjudication Agent is running. Use POST /process_claim to adjudicate claims."
    }


@app.post("/process_claim", response_model=ClaimResponse)
def process_claim(claim_request: ClaimRequest) -> ClaimResponse:
    # Best practice: keep this validation deterministic and outside the LLM so
    # we avoid wasting tokens on requests that cannot be adjudicated yet.
    missing_fields = detect_missing_fields(claim_request)
    if missing_fields:
        return build_pending_response(claim_request, missing_fields)

    try:
        agent = get_claim_agent()
        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Adjudicate this medical claim.\n\n"
                            f"claim_id: {claim_request.claim_id}\n"
                            f"patient_id: {claim_request.patient_id}\n"
                            f"provider_id: {claim_request.provider_id}\n"
                            f"procedure_code: {claim_request.procedure_code}\n"
                            f"billed_amount: {claim_request.billed_amount}\n"
                            f"clinical_notes: {claim_request.clinical_notes}\n"
                        ),
                    }
                ]
            }
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except NotFound as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Gemini model '{ACTIVE_GEMINI_MODEL}' was not found or is not enabled for this API key."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Claim adjudication agent failed: {exc}",
        ) from exc

    structured = result.get("structured_response")
    if isinstance(structured, ClaimResponse):
        return structured
    if isinstance(structured, dict):
        return ClaimResponse.model_validate(structured)

    raise HTTPException(
        status_code=500,
        detail="Agent completed without producing a valid ClaimResponse.",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=True,
    )
