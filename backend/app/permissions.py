"""Single source of truth for RBAC: permission name -> allowed roles."""

SCI, ANA, SEN, ADM = "scientist", "lab_analyst", "senior_analyst", "admin"
ROLES = (SCI, ANA, SEN, ADM)
_USER = (SCI, ANA, SEN)  # everyone except admin

PERMISSIONS: dict[str, tuple[str, ...]] = {
    "self.view": ROLES,
    "knowledge.use": _USER,          # chat, SOP search/view, troubleshooting
    "inventory.view": _USER,
    "requests.create": _USER,
    "external.optin": _USER,
    "calculators.use": _USER,
    "gaps.request_sop": _USER,
    "inventory.manage": (ANA,),      # issue/return/adjust/dispose/add lots/approve/reject
    "sop.manage": (SEN,),            # upload/publish/retire
    "gaps.view": (SEN,),
    "gaps.link": (SEN,),
    "audit.view": (SEN, ADM),
    "users.manage": (ADM,),
}


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)
