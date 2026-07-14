"""Lead-category registry.

Importing this package triggers registration of every built-in detector, so
downstream code can simply do:

    from mls_bot.leadgen import REGISTRY, print_leads
    leads = REGISTRY["INHERITANCE_MULTI"](rows, {"jurisdiction": "BLACKSBURG"})
    print_leads("INHERITANCE_MULTI", leads)
"""

from .base import Lead, REGISTRY, print_leads, register, write_leads_csv  # noqa: F401

# Import modules to trigger @register side-effects.
from . import (  # noqa: F401,E402
    inheritance,
    tenure_sweet_spot,
    concentration,
    student_rental_llc,
    empty_lots,
    subdivision_report,
    home_inventory,
    dc_suitability,
)
