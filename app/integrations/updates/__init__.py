"""GitHub release checks and verified Windows installer downloads."""
from .service import (UpdateService, Release, Asset, VerifiedInstaller, UpdateCancelled, UpdateRateLimited,
                      RELEASES_URL,
                      installation_kind, launch_installer_helper, run_installer_helper)

