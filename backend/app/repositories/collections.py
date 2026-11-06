from app.models import (
    Asset,
    AssetCreate,
    AuditLog,
    AuditLogCreate,
    BrandFact,
    BrandFactCreate,
    ClaimPolicy,
    ClaimPolicyCreate,
    Finding,
    FindingCreate,
    GuidelineChunk,
    GuidelineChunkCreate,
    GuidelineDoc,
    GuidelineDocCreate,
    Organisation,
    OrganisationCreate,
    Review,
    ReviewCreate,
    Revision,
    RevisionCreate,
    Submission,
    SubmissionCreate,
    Terminology,
    TerminologyCreate,
    User,
    UserCreate,
)
from app.repositories.base import Repository

organisations = Repository[OrganisationCreate, Organisation]("organisations", Organisation, org_scoped=False)
users = Repository[UserCreate, User]("users", User)
guideline_docs = Repository[GuidelineDocCreate, GuidelineDoc]("guideline_docs", GuidelineDoc)
guideline_chunks = Repository[GuidelineChunkCreate, GuidelineChunk]("guideline_chunks", GuidelineChunk)
brand_facts = Repository[BrandFactCreate, BrandFact]("brand_facts", BrandFact)
terminology = Repository[TerminologyCreate, Terminology]("terminology", Terminology)
claim_policies = Repository[ClaimPolicyCreate, ClaimPolicy]("claim_policies", ClaimPolicy)
assets = Repository[AssetCreate, Asset]("assets", Asset)
submissions = Repository[SubmissionCreate, Submission]("submissions", Submission)
revisions = Repository[RevisionCreate, Revision]("revisions", Revision)
findings = Repository[FindingCreate, Finding]("findings", Finding)
reviews = Repository[ReviewCreate, Review]("reviews", Review)
audit_log = Repository[AuditLogCreate, AuditLog]("audit_log", AuditLog)
