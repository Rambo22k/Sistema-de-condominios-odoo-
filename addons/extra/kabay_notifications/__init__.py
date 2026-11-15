from . import models
from . import controllers


def post_init_hook(env):
    """Create disabled, company-scoped settings; do not backfill historical mail."""
    for company in env["res.company"].search([]):
        env["kabay.notification.settings"].sudo().create({"company_id": company.id})
