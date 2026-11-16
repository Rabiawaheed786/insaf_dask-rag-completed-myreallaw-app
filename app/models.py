from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    display_name: str = ""
    role: str = "user"  # user | lawyer | coordinator | admin
    language: str = "roman_urdu"  # roman_urdu | en
    timezone: str = "Asia/Karachi"
    failed_logins: int = 0
    locked_until: Optional[datetime] = None
    encrypted_gemini_key: str = Field(default="", sa_column_kwargs={"server_default": ""})
    gemini_key_updated_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class AuthSession(SQLModel, table=True):
    """Server-side session. Sirf token ka hash save hota hai, token nahi."""
    __tablename__ = "sessions"
    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: str = Field(index=True, unique=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    expires_at: datetime
    created_at: datetime = Field(default_factory=utcnow)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_id: Optional[int] = None
    action: str
    detail: str = ""  # kabhi case ka matn ya password yahan nahi
    at: datetime = Field(default_factory=utcnow)


class AIProviderSettings(SQLModel, table=True):
    """Admin-managed AI provider. Sirf ek active row (id=1); key encrypt ho kar save hoti hai."""
    __tablename__ = "ai_provider_settings"
    id: Optional[int] = Field(default=None, primary_key=True)
    provider_name: str = "gemini"  # gemini | openai | deepseek
    model_name: str = ""
    encrypted_api_key: str = ""
    updated_by: Optional[int] = None
    updated_at: datetime = Field(default_factory=utcnow)


class Case(SQLModel, table=True):
    """User ki request. Teen status alag rakhe gaye hain: saved, referral, lawyer."""
    __tablename__ = "requests"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_request_idem"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    tracking_no: str = Field(index=True, unique=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    category: str
    city: str
    province: Optional[str] = None
    statement: str  # user ka apna bayan, jaisa likha gaya
    summary: str  # user ka approve kiya hua summary
    summary_approved_at: datetime = Field(default_factory=utcnow)
    safe_time: Optional[str] = None
    contact_channel: str = "in_app"
    status: str = "saved"  # saved | closed
    referral_status: str = "not_sent"  # not_sent | delivered | failed (sirf asli acknowledgment par delivered)
    lawyer_status: str = "not_assigned"  # not_assigned | accepted (sirf asli accept par)
    ai_used: bool = False
    referral_consent: bool = Field(default=False, sa_column_kwargs={"server_default": "0"})
    child_review_status: str = Field(default="not_needed", sa_column_kwargs={"server_default": "not_needed"})  # not_needed | pending | cleared
    child_review_note: Optional[str] = None  # sirf admin ko
    child_review_by: Optional[int] = None
    idempotency_key: str
    created_at: datetime = Field(default_factory=utcnow)


class CaseEvent(SQLModel, table=True):
    __tablename__ = "request_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="requests.id", index=True)
    event_type: str
    at: datetime = Field(default_factory=utcnow)


class OfficialContact(SQLModel, table=True):
    """Fallback contacts. Har contact ka source_url aur verified_on zaroori hai."""
    __tablename__ = "official_contacts"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str
    note_roman_urdu: str = ""
    note_en: str = ""
    scope: str = "national"  # national ya province ka key
    source_url: str
    verified_on: str  # YYYY-MM-DD
    emergency: bool = Field(default=False, sa_column_kwargs={"server_default": "0"})


class Referral(SQLModel, table=True):
    """Coordinator ka darj kiya hua referral. 'delivered' sirf asli acknowledgment reference ke saath."""
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("request_id", "idempotency_key", name="uq_referral_idem"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="requests.id", index=True)
    target: str
    status: str  # attempted | delivered | failed
    ack_ref: Optional[str] = None
    failed_reason: Optional[str] = None  # sirf coordinator ko nazar aati hai
    idempotency_key: str
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class LawyerProfile(SQLModel, table=True):
    """Wakeel ki arzi. Signup akela verification nahi: access sirf verified par."""
    __tablename__ = "lawyer_profiles"
    __table_args__ = (UniqueConstraint("bar_council", "licence_no", name="uq_licence"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)
    bar_council: str
    licence_no: str
    city: str
    verification_status: str = "pending"  # pending | verified | rejected | suspended
    identity_checked: bool = False
    registration_checked: bool = False
    source_note: Optional[str] = None  # admin ne kahan se verify kiya (sirf admin ko nazar aata hai)
    decision_reason: Optional[str] = None  # sirf admin ko
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class Assignment(SQLModel, table=True):
    """Request ka wakeel ko offer. Access sirf status 'accepted' par."""
    __tablename__ = "assignments"
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="requests.id", index=True)
    lawyer_profile_id: int = Field(foreign_key="lawyer_profiles.id", index=True)
    status: str = "offered"  # offered | accepted | declined | expired | revoked
    offered_by: int = Field(foreign_key="users.id")
    offered_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    responded_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoke_reason: Optional[str] = None


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("request_id", "sender_id", "idempotency_key", name="uq_msg_idem"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="requests.id", index=True)
    sender_id: int = Field(foreign_key="users.id")
    sender_role: str  # user | lawyer
    body: str
    idempotency_key: str
    created_at: datetime = Field(default_factory=utcnow)


class Attachment(SQLModel, table=True):
    """Private file. Disk par sirf random stored_name; asli name sirf yahan (saaf kiya hua)."""
    __tablename__ = "attachments"
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="requests.id", index=True)
    uploader_id: int = Field(foreign_key="users.id")
    uploader_role: str
    display_name: str
    stored_name: str = Field(unique=True)
    mime: str
    size: int
    sha256: str
    created_at: datetime = Field(default_factory=utcnow)
    deleted_at: Optional[datetime] = None


class FollowupSettings(SQLModel, table=True):
    """User ki follow-up pasand. Default: sirf important updates (koi reminder nahi)."""
    __tablename__ = "followup_settings"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)
    pref: str = "important_only"  # daily | weekly | important_only | off
    safe_time: str = "09:00"  # user ke apne waqt mein
    channel: str = "in_app"  # abhi sirf in_app


class Notification(SQLModel, table=True):
    """In-app notification. Text save nahi hota: sirf kism aur ginti; zaban ke hisaab se baad mein banta hai."""
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "kind", "period_key", name="uq_notif_period"),
                      UniqueConstraint("kind", "event_id", name="uq_notif_event"))
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    kind: str  # status_update | daily_reminder | weekly_summary | slot_booked | slot_released
    request_id: Optional[int] = Field(default=None, foreign_key="requests.id")
    event_id: Optional[int] = Field(default=None, index=True)
    period_key: Optional[str] = None
    data: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)
    read_at: Optional[datetime] = None


class AvailabilitySlot(SQLModel, table=True):
    """Wakeel ka diya hua waqt (UTC mein). Slot tabhi book hota hai jab wakeel ne khud diya ho."""
    __tablename__ = "availability_slots"
    id: Optional[int] = Field(default=None, primary_key=True)
    lawyer_profile_id: int = Field(foreign_key="lawyer_profiles.id", index=True)
    start: datetime = Field(index=True)
    end: datetime
    status: str = "open"  # open | booked | cancelled
    booked_request_id: Optional[int] = Field(default=None, foreign_key="requests.id")
    booked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class LegalDocument(SQLModel, table=True):
    """Verified qanooni PDF (sirf official source se, admin ki tasdeeq ke saath). RAG sirf isi se jawab deta hai."""
    __tablename__ = "legal_documents"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    source_url: str
    jurisdiction: str = "Pakistan"
    verified_on: str  # YYYY-MM-DD
    sha256: str = Field(unique=True)
    pages: int = 0
    ocr_pages: int = 0
    status: str = "verified"  # verified | suspended
    attested_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class LegalChunk(SQLModel, table=True):
    """Ek tukra + uska embedding (vector). kind: text (safha ka matn) | image_text (tasveer ke andar ka matn)."""
    __tablename__ = "legal_chunks"
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="legal_documents.id", index=True)
    page: int
    kind: str
    text: str
    embedding: bytes
    dim: int
    embedder: str
    created_at: datetime = Field(default_factory=utcnow)


class KnowledgeBase(SQLModel, table=True):
    """User ki apni Knowledge Base. Har row sirf apne user ki hai (user_id)."""
    __tablename__ = "knowledge_bases"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    title: str
    system_prompt: str = ""
    embed_token: str = Field(index=True, unique=True)  # widget share; sirf owner ko dikhta hai
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeChunk(SQLModel, table=True):
    """KB ka tukra. vector store row: payload mein user_id aur kb_id dono hamesha saath rehte hain."""
    __tablename__ = "knowledge_chunks"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    kb_id: int = Field(foreign_key="knowledge_bases.id", index=True)
    page: int = 1
    kind: str = "text"
    text: str
    embedding: bytes
    dim: int
    embedder: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

