from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from geo.database import SessionLocal
from geo.models.membership import ContactSubmissionORM
from geo.services.email_service import email_service
from geo.utils.error_handler import AppException

router = APIRouter()

class ContactRequest(BaseModel):
    name: str
    email: str
    website: str
    message: Optional[str] = None

@router.post("/contact")
async def contact(contact_request: ContactRequest):
    """Handle contact form submission: persist to DB and send confirmation email"""
    # Save to database
    db = SessionLocal()
    submission_id = None
    try:
        submission = ContactSubmissionORM(
            name=contact_request.name,
            email=contact_request.email,
            website=contact_request.website,
            message=contact_request.message or "",
        )
        db.add(submission)
        db.commit()
        db.refresh(submission)
        submission_id = submission.id
    except Exception:
        db.rollback()
        raise AppException(status_code=500, message="Failed to save contact submission")
    finally:
        db.close()

    # Send consultation confirmation email to the submitter
    email_service.send_consultation_confirmation_email(
        contact_request.email,
        contact_request.name,
        contact_request.message or "",
    )

    # Notify internal sales/support inbox (failure is logged but not fatal —
    # the submission is already persisted).
    email_service.send_sales_notification_email(
        kind="contact",
        name=contact_request.name,
        email=contact_request.email,
        website=contact_request.website,
        message=contact_request.message or "",
        submission_id=submission_id,
    )

    return {"message": "Consultation request received."}
