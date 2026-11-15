from . import models
from . import controllers


def post_init_hook(env):
    """Create the Kabay portal team and workflow stages per company."""
    # The upstream Helpdesk module assigns its manager group to every internal
    # user through base.default_user_group. Remove only that implication; Kabay
    # groups below receive their needed role explicitly.
    default_group = env.ref("base.default_user_group", raise_if_not_found=False)
    manager_group = env.ref("helpdesk.group_helpdesk_manager", raise_if_not_found=False)
    if default_group and manager_group and manager_group in default_group.implied_ids:
        default_group.write({"implied_ids": [(3, manager_group.id)]})

    for company in env["res.company"].search([]):
        company._kabay_ensure_helpdesk_team()
